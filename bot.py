"""Telegram Meal Bot -- Main Entry Point

Intelligent kitchen assistant that manages ingredients, tracks expiry,
and suggests meals from diverse global cuisines using Google Gemini AI.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
import state  # shared service container
from services.database import DatabaseService
from services.gemini import GeminiService
from services.notion_client import NotionService
from services.scheduler import SchedulerService

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramConflictError

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    """Initialize services when bot starts."""
    logger.info("Starting Meal Bot...")

    if not config.BOT_TOKEN or not config.GEMINI_API_KEY:
        logger.error("Missing BOT_TOKEN or GEMINI_API_KEY. Bot cannot start.")
        return

    # CRITICAL: Delete any leftover webhook from previous deployments.
    # A stale webhook causes TelegramConflictError when we try to poll.
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Cleared any existing webhook and dropped pending updates.")
    except Exception as e:
        logger.warning("Failed to delete webhook (non-fatal): %s", e)

    # Initialize database
    db_service = DatabaseService()
    await db_service.connect()
    logger.info("Database connected.")

    # Initialize Gemini AI
    gemini_service = GeminiService()
    logger.info("Gemini AI initialized (model: %s).", config.GEMINI_MODEL)

    # Initialize Notion (optional -- failures are non-fatal)
    notion_service = NotionService()
    try:
        await notion_service.connect()
    except Exception as e:
        logger.warning("Notion init failed (non-fatal): %s", e)
    notion_status = "enabled" if notion_service.is_available else "disabled"
    logger.info("Notion integration: %s.", notion_status)

    # Initialize scheduler
    scheduler_service = SchedulerService(db=db_service, bot=bot)
    scheduler_service.start()
    logger.info("Scheduler started.")

    # Store services in the shared state module
    state.db = db_service
    state.gemini = gemini_service
    state.notion = notion_service
    state.scheduler = scheduler_service

    # Wire services into each router's module-level refs
    from routers.inventory import router as inventory_router
    from routers.suggest import router as suggest_router
    from routers.planner import router as planner_router
    from routers.notion_router import router as notion_router

    inventory_router.db = db_service
    inventory_router.gemini = gemini_service

    suggest_router.db = db_service
    suggest_router.gemini = gemini_service
    suggest_router.notion = notion_service

    planner_router.db = db_service
    planner_router.gemini = gemini_service
    planner_router.notion_svc = notion_service

    notion_router.db = db_service
    notion_router.notion_svc = notion_service

    logger.info("All services wired. Bot is ready!")


async def on_shutdown(bot: Bot):
    """Clean up services when bot stops."""
    logger.info("Shutting down Meal Bot...")
    if state.scheduler:
        state.scheduler.shutdown()
    if state.db:
        await state.db.close()
    logger.info("Cleanup complete. Goodbye!")


async def main():
    """Async entry point -- runs the bot with conflict-error recovery."""
    if not config.BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set!")
        print("Get one from @BotFather: https://t.me/BotFather")
        sys.exit(1)
    if not config.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY is not set!")
        print("Get one from: https://aistudio.google.com/apikey")
        sys.exit(1)

    dp = Dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    from routers.start import router as start_router
    from routers.inventory import router as inventory_router
    from routers.suggest import router as suggest_router
    from routers.planner import router as planner_router
    from routers.notion_router import router as notion_router

    dp.include_router(start_router)
    dp.include_router(inventory_router)
    dp.include_router(suggest_router)
    dp.include_router(planner_router)
    dp.include_router(notion_router)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )

    logger.info("Starting Telegram bot polling...")
    try:
        dp.run_polling(bot, drop_pending_updates=True)
    except TelegramConflictError:
        logger.warning(
            "TelegramConflictError: another bot instance is still running. "
            "This is normal during Render redeploy -- the old instance will "
            "stop shortly. If this persists, wait 2-3 minutes then redeploy."
        )
        # Wait for the old instance to die, then retry once
        await asyncio.sleep(5)
        try:
            dp.run_polling(bot, drop_pending_updates=True)
        except TelegramConflictError:
            logger.error(
                "TelegramConflictError persists after retry. Exiting."
            )
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical("Bot crashed: %s", e, exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
