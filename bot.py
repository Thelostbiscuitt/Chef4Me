"""Telegram Meal Bot -- Main Entry Point

Intelligent kitchen assistant that manages ingredients, tracks expiry,
and suggests meals from diverse global cuisines using Google Gemini AI.

Deployment mode: webhook (via aiohttp) for conflict-free Render deploys.
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
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot) -> None:
    """Initialize services and register the webhook with Telegram."""
    logger.info("Starting Meal Bot...")

    # ── Validate required config ──────────────────────────────────────────────
    if not config.BOT_TOKEN or not config.GEMINI_API_KEY:
        logger.error("Missing BOT_TOKEN or GEMINI_API_KEY. Bot cannot start.")
        sys.exit(1)

    if not config.WEBHOOK_BASE_URL:
        logger.error(
            "WEBHOOK_BASE_URL is not set. "
            "Set it to your Render service URL, e.g. https://yourbot.onrender.com"
        )
        sys.exit(1)

    # ── Register webhook with Telegram ────────────────────────────────────────
    webhook_url = f"{config.WEBHOOK_BASE_URL.rstrip('/')}{config.WEBHOOK_PATH}"
    await bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,
        # Tells Telegram to send updates only to this secret path — provides
        # a basic layer of authentication so random HTTP traffic is ignored.
        secret_token=config.WEBHOOK_SECRET,
        allowed_updates=["message", "callback_query", "inline_query"],
    )
    logger.info("Webhook registered: %s", webhook_url)

    # ── Initialize database ───────────────────────────────────────────────────
    db_service = DatabaseService()
    await db_service.connect()
    logger.info("Database connected.")

    # ── Initialize Gemini AI ──────────────────────────────────────────────────
    gemini_service = GeminiService()
    logger.info("Gemini AI initialized (model: %s).", config.GEMINI_MODEL)

    # ── Initialize Notion (optional) ──────────────────────────────────────────
    notion_service = NotionService()
    try:
        await notion_service.connect()
    except Exception as e:
        logger.warning("Notion init failed (non-fatal): %s", e)
    notion_status = "enabled" if notion_service.is_available else "disabled"
    logger.info("Notion integration: %s.", notion_status)

    # ── Initialize scheduler ──────────────────────────────────────────────────
    scheduler_service = SchedulerService(db=db_service, bot=bot)
    scheduler_service.start()
    logger.info("Scheduler started.")

    # ── Store services in shared state ────────────────────────────────────────
    state.db = db_service
    state.gemini = gemini_service
    state.notion = notion_service
    state.scheduler = scheduler_service

    # ── Wire services into each router's module-level refs ────────────────────
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


async def on_shutdown(bot: Bot) -> None:
    """Remove the webhook and clean up services on shutdown."""
    logger.info("Shutting down Meal Bot...")

    # Delete webhook so Telegram stops sending updates while we're down.
    # This prevents a backlog of updates queuing up during the restart window.
    try:
        await bot.delete_webhook()
        logger.info("Webhook deleted.")
    except Exception as e:
        logger.warning("Failed to delete webhook during shutdown: %s", e)

    if state.scheduler:
        state.scheduler.shutdown()
    if state.db:
        await state.db.close()
    logger.info("Cleanup complete. Goodbye!")


def main() -> None:
    """Build the aiohttp application and start serving webhook requests."""
    if not config.BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set!")
        sys.exit(1)
    if not config.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY is not set!")
        sys.exit(1)
    if not config.WEBHOOK_BASE_URL:
        print("ERROR: WEBHOOK_BASE_URL is not set!")
        print("Set it to your Render service public URL, e.g. https://yourbot.onrender.com")
        sys.exit(1)

    # ── Build bot + dispatcher ────────────────────────────────────────────────
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )

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

    # ── Build aiohttp web app ─────────────────────────────────────────────────
    app = web.Application()

    # SimpleRequestHandler validates the X-Telegram-Bot-Api-Secret-Token header
    # against config.WEBHOOK_SECRET before dispatching — zero-cost auth.
    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=config.WEBHOOK_SECRET,
    )
    webhook_handler.register(app, path=config.WEBHOOK_PATH)

    # setup_application wires dp startup/shutdown into aiohttp's lifecycle.
    setup_application(app, dp, bot=bot)

    # ── Health-check endpoint ─────────────────────────────────────────────────
    # Render's health checks hit "/" — return 200 so the service stays "live".
    async def health(request: web.Request) -> web.Response:
        return web.Response(text="OK")

    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    # ── Start server ──────────────────────────────────────────────────────────
    port = config.PORT
    logger.info("Starting webhook server on port %d", port)
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
