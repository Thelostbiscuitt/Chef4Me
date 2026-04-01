import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.database import DatabaseService

import config

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self, db: DatabaseService, bot=None):
        self.db = db
        self.bot = bot
        self.scheduler = AsyncIOScheduler()

    def start(self):
        self.scheduler.add_job(
            self._check_expiry_notifications,
            IntervalTrigger(seconds=config.EXPIRY_CHECK_INTERVAL),
            id="expiry_check",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Scheduler started. Expiry check interval: %ds", config.EXPIRY_CHECK_INTERVAL)

    def shutdown(self):
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler shutdown.")

    async def _check_expiry_notifications(self):
        """Check all users for expiring ingredients and send notifications."""
        try:
            # Get all users with notifications enabled
            cursor = await self.db.db.execute(
                """SELECT u.user_id, u.first_name, p.notifications_enabled
                   FROM users u
                   JOIN user_preferences p ON u.user_id = p.user_id
                   WHERE p.notifications_enabled = 1"""
            )
            users = await cursor.fetchall()

            for user in users:
                expiring = await self.db.get_expiring_soon(
                    user["user_id"], days=config.EXPIRY_WARNING_DAYS
                )
                if expiring and self.bot:
                    await self._send_expiry_alert(user["user_id"], user["first_name"], expiring)
        except Exception as e:
            logger.error(f"Expiry notification check failed: {e}")

    async def _send_expiry_alert(self, user_id: int, first_name: str, expiring: list[dict]):
        """Send a Telegram message about expiring ingredients."""
        if not self.bot:
            return
        try:
            lines = [f"⚠️ *Expiry Alert*", f""]
            for ing in expiring:
                days_left = self._days_until(ing["expiry_date"])
                if days_left <= 0:
                    urgency = "🔴 Expires TODAY"
                elif days_left == 1:
                    urgency = "🟠 Expires TOMORROW"
                else:
                    urgency = f"🟡 Expires in {days_left} days"
                lines.append(f"• {ing['name']} ({ing['quantity']} {ing['unit']}) — {urgency}")

            lines.append(f"\n💡 Use `/suggest` to find recipes that use these ingredients!")

            from utils.formatters import escape_markdown
            text = "\n".join(lines)
            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown"
            )
            logger.info(f"Sent expiry alert to user {user_id} for {len(expiring)} items")
        except Exception as e:
            logger.error(f"Failed to send expiry alert to {user_id}: {e}")

    @staticmethod
    def _days_until(date_str: str) -> int:
        try:
            exp_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            return (exp_date - date.today()).days
        except (ValueError, TypeError):
            return 0
