"""Subscription router — plans, Telegram Stars payments, trials,
lifetime passes (admin grants + redeem codes)."""
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery

import config
import services.subscriptions as subs
from services.database import DatabaseService
from utils.formatters import escape_markdown_v1
from utils.keyboards import subscribe_keyboard, paywall_keyboard

logger = logging.getLogger(__name__)

router = Router()

db: DatabaseService = None  # type: ignore[assignment]

PLAN_PAYLOADS = {
    "weekly":  {"label": "Pro Weekly",  "stars": config.PRICE_WEEKLY_STARS,
                "price": "$1.99"},
    "monthly": {"label": "Pro Monthly", "stars": config.PRICE_MONTHLY_STARS,
                "price": "$4.99"},
    "yearly":  {"label": "Pro Yearly",  "stars": config.PRICE_YEARLY_STARS,
                "price": "$39.99"},
}

FREE_FEATURES = (
    "🆓 *Free plan — always available*\n\n"
    "• Unlimited pantry tracking & expiry alerts\n"
    "• /suggest — 5 AI meal ideas per day\n"
    "• /recipe — 3 full recipes per day\n"
    "• 📸 Receipt photo scanning — 3 per month\n"
    "• 🎁 7-day Pro trial for every new user\n\n"
    "💎 *Pro adds:* weekly meal plans (/plan), smart shopping lists, "
    "unlimited AI, nutrition, recipe scaling, voice notes & more."
)


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_USER_IDS


async def _db_ok(message: Message) -> bool:
    if db is None:
        await message.answer("⚠️ Database not available. Please try again later.")
        return False
    return True


# ── /subscribe & plans ──────────────────────────────────────────────────────

@router.message(F.text == "/subscribe")
async def cmd_subscribe(message: Message):
    if not await _db_ok(message):
        return
    user_id = message.from_user.id
    tier, expires = await subs.describe(db, user_id)
    text = f"💎 *Chef4Me Pro*\n\nYour plan: *{escape_markdown_v1(tier)}*"
    if expires:
        text += f"\nActive until: {expires[:10]}"
    text += "\n\nPick a plan — pay with Telegram Stars:"
    await message.answer(text, parse_mode="Markdown", reply_markup=subscribe_keyboard())


@router.message(F.text == "/pricing")
async def cmd_pricing(message: Message):
    await message.answer(
        "💎 *Chef4Me Pro*\n\n"
        "• Weekly — $1.99\n"
        "• Monthly — $4.99\n"
        "• Yearly — $39.99 (≈ $3.33/mo)\n\n"
        "Pay with Telegram Stars, right in the chat. /subscribe to choose.\n\n"
        "Free plan: pantry tracking, expiry alerts, 5 AI suggestions & 3 "
        "recipes per day, 3 photo scans per month. Every new user gets a "
        "7-day Pro trial.",
        parse_mode="Markdown",
    )


@router.callback_query(F.data == "sub_pricing")
async def cb_sub_pricing(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_text(
            "💎 *Chef4Me Pro plans*\n\n"
            "• Weekly — $1.99\n"
            "• Monthly — $4.99\n"
            "• Yearly — $39.99 (≈ $3.33/mo)\n\n"
            "Pick a plan to pay with Telegram Stars:",
            parse_mode="Markdown",
            reply_markup=subscribe_keyboard(),
        )
    except Exception:
        await callback.message.answer(
            "💎 *Chef4Me Pro plans*\n\n• Weekly — $1.99\n• Monthly — $4.99\n"
            "• Yearly — $39.99\n\n/subscribe to choose a plan.",
            parse_mode="Markdown",
        )


@router.callback_query(F.data == "sub_free")
async def cb_sub_free(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_text(FREE_FEATURES, parse_mode="Markdown")
    except Exception:
        await callback.message.answer(FREE_FEATURES, parse_mode="Markdown")


@router.callback_query(F.data.startswith("sub_plan:"))
async def cb_sub_plan(callback: CallbackQuery):
    plan = callback.data.split(":", 1)[1]
    info = PLAN_PAYLOADS.get(plan)
    if not info:
        await callback.answer("Unknown plan.")
        return
    await callback.answer()
    try:
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"Chef4Me {info['label']}",
            description=(
                f"Chef4Me Pro — {info['label']} subscription.\n"
                "Unlimited AI recipes, weekly meal plans, smart shopping "
                "lists, nutrition, voice notes, Notion sync."
            ),
            payload=f"sub:{plan}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=info["label"], amount=info["stars"])],
            start_parameter="chef4me_pro",
        )
    except Exception as exc:
        logger.exception("Failed to send Stars invoice for plan %s", plan)
        await callback.message.answer(
            "⚠️ Couldn't open the payment right now. Please try again later."
        )



@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload  # e.g. "sub:weekly"
    plan = payload.split(":", 1)[1] if payload.startswith("sub:") else ""
    if plan not in PLAN_PAYLOADS:
        await message.answer("⚠️ Unknown payment payload. Please contact support.")
        return
    user_id = message.from_user.id
    ref = message.successful_payment.telegram_payment_charge_id
    await subs.grant_plan(db, user_id, plan, provider="stars", reference=ref)
    _, expires = await subs.describe(db, user_id)
    await message.answer(
        f"🎉 Thank you! You're now on *{PLAN_PAYLOADS[plan]['label']}*.\n\n"
        f"Active until: {expires[:10] if expires else 'forever'}.\n"
        "Try /plan for your weekly meal plan!",
        parse_mode="Markdown",
    )


# ── /mypass ─────────────────────────────────────────────────────────────────

@router.message(F.text == "/mypass")
async def cmd_mypass(message: Message):
    if not await _db_ok(message):
        return
    tier, expires = await subs.describe(db, message.from_user.id)
    text = f"🎟️ *Your plan:* {escape_markdown_v1(tier)}"
    if expires:
        text += f"\n⏳ Active until: {expires[:10]}"
    if tier == "Free":
        text += "\n\n💡 Upgrade anytime with /subscribe."
    await message.answer(text, parse_mode="Markdown")


# ── Redeem codes ────────────────────────────────────────────────────────────

@router.message(F.text.startswith("/redeem"))
async def cmd_redeem(message: Message):
    if not await _db_ok(message):
        return
    code = message.text.strip().removeprefix("/redeem").strip()
    if not code:
        await message.answer(
            "Usage: `/redeem CHEF4ME-XXXXXX`", parse_mode="Markdown"
        )
        return
    plan = await subs.redeem_code(db, message.from_user.id, code)
    if plan is None:
        await message.answer(
            "❌ That code is invalid or already used.\n"
            "Check the code and try again."
        )
        return
    label = subs.PLANS[plan]["label"]
    await message.answer(
        f"🎉 Code accepted! You now have *{label}*.\n\n"
        "Enjoy the full features!",
        parse_mode="Markdown",
    )


# ── Admin: lifetime passes ──────────────────────────────────────────────────

@router.message(F.text.startswith("/grant"))
async def cmd_grant(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Admins only.")
        return
    if not await _db_ok(message):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            "Usage: `/grant <user_id> [plan]`\n"
            "Plans: lifetime (default), yearly, monthly, weekly, trial",
            parse_mode="Markdown",
        )
        return
    user_id = int(parts[1])
    plan = parts[2].lower() if len(parts) > 2 else "lifetime"
    if plan not in subs.PLANS:
        await message.answer(f"Unknown plan: {plan}.")
        return
    await subs.grant_plan(db, user_id, plan, provider="admin",
                          reference=str(message.from_user.id))
    await message.answer(
        f"✅ Granted *{subs.PLANS[plan]['label']}* to user {user_id}."
    )


@router.message(F.text.startswith("/revoke"))
async def cmd_revoke(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Admins only.")
        return
    if not await _db_ok(message):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: `/revoke <user_id>`")
        return
    await subs.revoke_plan(db, int(parts[1]))
    await message.answer("✅ Revoked access for user — back to Free.")


@router.message(F.text.startswith("/genpass"))
async def cmd_genpass(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Admins only.")
        return
    if not await _db_ok(message):
        return
    parts = message.text.split()
    n = 1
    plan = "lifetime"
    if len(parts) > 1 and parts[1].isdigit():
        n = min(int(parts[1]), 20)
    if len(parts) > 2 and parts[2].lower() in subs.PLANS:
        plan = parts[2].lower()
    codes = [subs.generate_code() for _ in range(n)]
    await db.create_redeem_codes(codes, plan, message.from_user.id)
    text = (
        f"🎟️ *{n} × {subs.PLANS[plan]['label']} pass{'es' if n != 1 else ''}:*\n\n"
        + "\n".join(f"`{c}`" for c in codes)
        + "\n\nSend a code to a friend — they redeem it with /redeem <code>."
    )
    await message.answer(text, parse_mode="Markdown")
