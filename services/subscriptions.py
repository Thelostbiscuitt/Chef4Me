"""Subscription tiers, trials, quotas and redeem codes.

All premium logic funnels through this module so routers only ever call:

    premium = await subscriptions.is_premium(db, user_id)
    allowed, used, limit = await subscriptions.check_and_consume(...)
"""
import secrets
import string
import logging
from datetime import datetime, timedelta, timezone

import config
from services.database import DatabaseService

logger = logging.getLogger(__name__)

# Plan definitions: days = subscription length (None = forever)
PLANS = {
    "free":     {"days": None, "label": "Free"},
    "trial":    {"days": None, "label": "Pro Trial"},
    "weekly":   {"days": 7,    "label": "Pro Weekly"},
    "monthly":  {"days": 30,   "label": "Pro Monthly"},
    "yearly":   {"days": 365,  "label": "Pro Yearly"},
    "lifetime": {"days": None, "label": "Pro Lifetime"},
}

PREMIUM_TIERS = {"trial", "weekly", "monthly", "yearly", "lifetime"}
PAID_TIERS = {"weekly", "monthly", "yearly", "lifetime"}

_CODE_ALPHABET = string.ascii_uppercase + string.digits
for _ch in "0O1I":
    _CODE_ALPHABET = _CODE_ALPHABET.replace(_ch, "")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def generate_code() -> str:
    """Generate a friendly redeem code like CHEF4ME-7K2X9Q."""
    return "CHEF4ME-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


async def get_tier(db: DatabaseService, user_id: int) -> str:
    """Resolve the effective tier: lifetime > paid > trial > free.

    Expired subscriptions are demoted to free (and marked expired in the DB).
    """
    sub = await db.get_subscription(user_id)
    if not sub:
        return "free"

    plan = sub.get("plan", "free")
    status = sub.get("status", "active")

    if plan == "lifetime" and status == "active":
        return "lifetime"

    expires = sub.get("expires_at")
    if expires:
        try:
            if datetime.fromisoformat(expires) <= _utcnow():
                if status == "active":
                    await db.upsert_subscription(
                        user_id, "free", status="expired", expires_at=None
                    )
                return "free"
        except (ValueError, TypeError):
            pass

    return plan if plan in PREMIUM_TIERS else "free"


async def is_premium(db: DatabaseService, user_id: int) -> bool:
    """Premium-equivalent (trial included) — unlocks all paid features."""
    return (await get_tier(db, user_id)) in PREMIUM_TIERS


async def start_trial(db: DatabaseService, user_id: int) -> str:
    """Give a brand-new user their free trial. Returns the resulting tier."""
    sub = await db.get_subscription(user_id)
    if sub is None:
        await db.upsert_subscription(
            user_id,
            "trial",
            expires_at=_iso(_utcnow() + timedelta(days=config.TRIAL_DAYS)),
            provider="trial",
        )
        logger.info("User %s started a %s-day trial", user_id, config.TRIAL_DAYS)
        return "trial"
    return await get_tier(db, user_id)


async def grant_plan(
    db: DatabaseService, user_id: int, plan: str,
    provider: str = "admin", reference: str = None, days: int = None,
) -> str:
    """Grant a plan (admin grant, redeem code or successful payment)."""
    if plan not in PLANS:
        plan = "free"
    if days is None:
        days = PLANS[plan]["days"]
    expires = _iso(_utcnow() + timedelta(days=days)) if days else None
    await db.upsert_subscription(
        user_id, plan, status="active",
        provider=provider, reference=reference, expires_at=expires,
    )
    logger.info("User %s granted plan=%s (provider=%s)", user_id, plan, provider)
    return plan


async def revoke_plan(db: DatabaseService, user_id: int) -> None:
    """Revoke all access — user falls back to free (no new trial)."""
    await db.upsert_subscription(
        user_id, "free", status="active", provider="admin", expires_at=None
    )


async def check_and_consume(
    db: DatabaseService, user_id: int, kind: str,
    free_limit: int, premium_limit: int = None,
) -> tuple[bool, int, int]:
    """Quota gate for one AI action.

    Premium users are unlimited unless premium_limit is set (hard cap).
    Returns (allowed, used, limit). Counters always increment.
    """
    tier = await get_tier(db, user_id)

    if tier in PREMIUM_TIERS and premium_limit is None:
        return (True, 0, 0)

    limit = premium_limit if tier in PREMIUM_TIERS else free_limit
    usage = await db.increment_usage(user_id, kind)
    used = usage.get(kind, 0)
    return (used <= limit, used, limit)


async def check_monthly(
    db: DatabaseService, user_id: int, kind: str, free_limit: int
) -> tuple[bool, int, int]:
    """Monthly quota gate (used for photo/OCR scans). Premium = unlimited."""
    tier = await get_tier(db, user_id)
    if tier in PREMIUM_TIERS:
        return (True, 0, 0)
    await db.increment_usage(user_id, kind)
    used = await db.get_usage_in_month(user_id, kind)
    return (used <= free_limit, used, free_limit)



async def redeem_code(db: DatabaseService, user_id: int, code: str) -> str | None:
    """Redeem a code for its plan. Returns the plan or None if invalid/used."""
    code = code.strip().upper()
    row = await db.get_redeem_code(code)
    if not row:
        return None
    if row.get("redeemed_by") is not None:
        return None
    expires = row.get("expires_at")
    if expires:
        try:
            if datetime.fromisoformat(expires) < _utcnow():
                return None
        except (ValueError, TypeError):
            return None
    await db.mark_code_redeemed(code, user_id)
    plan = row.get("plan", "lifetime")
    await grant_plan(db, user_id, plan, provider="code", reference=code)
    return plan


async def describe(db: DatabaseService, user_id: int) -> tuple[str, str | None]:
    """Human-readable (tier label, expiry iso) for /mypass."""
    tier = await get_tier(db, user_id)
    sub = await db.get_subscription(user_id)
    expires = sub.get("expires_at") if sub else None
    return PLANS[tier]["label"], expires


async def paywall_text(db: DatabaseService, user_id: int) -> str:
    """Message text shown when a premium-only feature is blocked."""
    from utils.formatters import escape_markdown_v1

    tier, _ = await describe(db, user_id)
    return (
        "💎 *This is a Pro feature.*\n\n"
        f"Your plan: *{escape_markdown_v1(tier)}*\n\n"
        "Upgrade for weekly meal plans, smart shopping lists, unlimited AI "
        "recipes, nutrition, voice notes and more — /subscribe"
    )
