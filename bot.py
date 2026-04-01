"""Telegram Meal Bot -- Main Entry Point

Intelligent kitchen assistant that manages ingredients, tracks expiry,
and suggests meals from diverse global cuisines using Google Gemini AI.
"""
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
import state  # shared service container
import httpx
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


def _delete_webhook_sync(token: str):
    """Synchronously delete any leftover webhook via raw HTTP call.

    This runs BEFORE dp.run_polling() to prevent TelegramConflictError.
    Telegram only allows one connection per bot: either webhook OR polling.
    If a stale webhook is set, getUpdates will conflict.
    """
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/deleteWebhook",
            json={"drop_pending_updates": True},
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            logger.info("Pre-polling: webhook deleted, pending updates dropped.")
        else:
            logger.warning("Pre-polling: deleteWebhook response: %s", data)
    except Exception as e:
        logger.warning("Pre-polling: deleteWebhook failed (non-fatal): %s", e)


async def on_startup(bot: Bot):
    """Initialize services when bot starts polling."""
    logger.info("Starting Meal Bot...")

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


def main():
    """Entry point -- sets up dispatcher and starts polling."""
    if not config.BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set!")
        print("Get one from @BotFather: https://t.me/BotFather")
        sys.exit(1)
    if not config.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY is not set!")
        print("Get one from: https://aistudio.google.com/apikey")
        sys.exit(1)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )

    # ─── CRITICAL PRE-POLLING STEPS ────────────────────────────────────
    # Step 1: Kill any leftover webhook from a previous deployment.
    # A stale webhook blocks getUpdates with TelegramConflictError.
    _delete_webhook_sync(config.BOT_TOKEN)

    # Step 2: Wait for any previous bot instance to fully shut down.
    # During Render redeploy, the old process may still hold the
    # getUpdates connection. Telegram only allows ONE polling connection.
    startup_delay = int(os.environ.get("BOT_STARTUP_DELAY", "15"))
    if startup_delay > 0:
        logger.info("Waiting %ds for any previous instance to shut down...", startup_delay)
        time.sleep(startup_delay)

    # ─── BUILD DISPATCHER ──────────────────────────────────────────────
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

    # ─── START POLLING ─────────────────────────────────────────────────
    logger.info("Starting Telegram bot polling...")
    try:
        dp.run_polling(bot, drop_pending_updates=True)
    except TelegramConflictError:
        logger.warning(
            "TelegramConflictError: another instance still running. "
            "Retrying in 10s..."
        )
        time.sleep(10)
        try:
            dp.run_polling(bot, drop_pending_updates=True)
        except TelegramConflictError:
            logger.error("TelegramConflictError persists. Exiting.")
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical("Bot crashed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
