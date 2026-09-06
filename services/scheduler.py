import logging
from datetime import date, datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.database import DatabaseService

import config

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self, db: DatabaseService, bot=None, gemini=None):
        self.db = db
        self.bot = bot
        self.gemini = gemini
        self.scheduler = AsyncIOScheduler()
        # Cache "use-up" recipe suggestions per user+day so the hourly
        # expiry check doesn't re-bill Gemini for the same alert.
        self._use_up_cache: dict = {}

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
        """Send a Telegram message about expiring ingredients.

        Premium users additionally get AI "cook this tonight" suggestions
        with a one-tap recipe button; free users get the plain list.
        """
        if not self.bot:
            return
        try:
            import services.subscriptions as subs

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

            reply_markup = None
            premium = await subs.is_premium(self.db, user_id)
            if premium and self.gemini:
                cache_key = f"{user_id}:{date.today().isoformat()}"
                dishes = self._use_up_cache.get(cache_key)
                if dishes is None:
                    expiring_names = [ing["name"] for ing in expiring]
                    try:
                        dishes = await self.gemini.use_up_recipes(
                            expiring_names, premium=True
                        )
                    except Exception as exc:
                        logger.warning("use_up_recipes failed for %s: %s", user_id, exc)
                        dishes = []
                    self._use_up_cache[cache_key] = dishes

                if dishes:
                    lines.append("\n💎 *Pro — cook one of these tonight:*")
                    for d in dishes[:2]:
                        lines.append(
                            f"• {d.get('name', '?')} — "
                            f"{str(d.get('description', ''))[:100]}"
                        )
                    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                    buttons = [
                        [InlineKeyboardButton(
                            text=f"🍳 {str(d.get('name', 'Recipe'))[:30]}",
                            callback_data=f"use_up:{str(d.get('name', ''))[:50]}",
                        )]
                        for d in dishes[:2]
                    ]
                    reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)

            from utils.formatters import escape_markdown
            text = "\n".join(lines)
            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
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
