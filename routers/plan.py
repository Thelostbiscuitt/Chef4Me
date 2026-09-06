"""Weekly meal planner — the flagship Pro feature."""
import json
import logging
from datetime import date

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

import config
import services.subscriptions as subs
from services.database import DatabaseService
from services.gemini import GeminiService
from utils.formatters import escape_markdown_v1, truncate_text
from utils.keyboards import plan_days_keyboard, plan_nav_keyboard, paywall_keyboard

logger = logging.getLogger(__name__)

router = Router()

db: DatabaseService = None  # type: ignore[assignment]
gemini: GeminiService = None  # type: ignore[assignment]

SLOT_EMOJI = {
    "breakfast": "🍳",
    "lunch": "🥙",
    "dinner": "🍽️",
    "snack": "🍎",
}


def _fmt_num(value) -> str:
    try:
        f = float(value)
        return str(int(f)) if f.is_integer() else str(f)
    except (TypeError, ValueError):
        return str(value)


def _merge_qty(a: str, b: str) -> str:
    if not a:
        return b
    if not b or a == b:
        return a
    return f"{a} + {b}"


async def _gate_message(message: Message) -> bool:
    """Premium gate for /plan. Returns True when the user may proceed."""
    if db is not None and await subs.is_premium(db, message.from_user.id):
        return True
    if db is None:
        await message.answer("⚠️ Database not available. Please try again later.")
        return False
    await message.answer(
        await subs.paywall_text(db, message.from_user.id),
        parse_mode="Markdown",
        reply_markup=paywall_keyboard(),
    )
    return False


async def _gate_callback(callback: CallbackQuery) -> bool:
    """Premium gate for planner callbacks."""
    if db is not None and await subs.is_premium(db, callback.from_user.id):
        return True
    await callback.answer("This is a Pro feature.", show_alert=True)
    return False


def _render_day(plan: list[dict], day_idx: int) -> str:
    day = plan[day_idx]
    lines = [f"🗓️ *Day {day_idx + 1} — {day.get('day_name', '')}*", ""]
    for meal in day.get("meals", []):
        slot = str(meal.get("slot", "")).lower()
        emoji = SLOT_EMOJI.get(slot, "🍽️")
        name = escape_markdown_v1(meal.get("name", "?"))
        cuisine = str(meal.get("cuisine", "")).title()
        minutes = meal.get("cook_time_minutes", "?")
        diff = int(meal.get("difficulty", 3) or 3)
        nut = meal.get("nutrition") or {}
        cal = nut.get("calories")
        cal_str = f" | 🔥 {_fmt_num(cal)} kcal" if cal else ""
        lines.append(
            f"{emoji} *{name}* — {cuisine} | {minutes} min | "
            f"{'⭐' * diff}{cal_str}"
        )
        missing = [
            f"{ing.get('quantity', '')} {escape_markdown_v1(ing.get('name', ''))}".strip()
            for ing in meal.get("ingredients", [])
            if not ing.get("have")
        ]
        if missing:
            preview = ", ".join(missing[:4])
            if len(missing) > 4:
                preview += "…"
            lines.append(f"   🛒 Buy: {preview}")
        lines.append("")
    return "\n".join(lines)


@router.message(F.text == "/plan")
async def cmd_plan(message: Message, state: FSMContext):
    if not await _gate_message(message):
        return
    ingredients, seasonings = await db.get_ingredients_as_lists(message.from_user.id)
    if not ingredients and not seasonings:
        await message.answer(
            "Your pantry is empty — add some ingredients with /add first, "
            "then I'll plan your week around them."
        )
        return
    await state.update_data(plan_ingredients=ingredients, plan_seasonings=seasonings)
    await message.answer(
        "🗓️ *Weekly Meal Planner*\n\n"
        "I'll build you a meal plan using what you already have, minimizing "
        "extra shopping. How many days?",
        parse_mode="Markdown",
        reply_markup=plan_days_keyboard(),
    )



async def _generate_and_show(
    callback: CallbackQuery, state: FSMContext, days: int
) -> None:
    user_id = callback.from_user.id

    allowed, used, limit = await subs.check_and_consume(
        db, user_id, "plans",
        free_limit=0,
        premium_limit=config.PREMIUM_PLANS_PER_DAY,
    )
    if not allowed:
        await callback.answer(
            f"You've used all {limit} plan generations today. "
            "Try again tomorrow!",
            show_alert=True,
        )
        return

    await callback.answer()
    await callback.message.edit_text("🧠 Generating your meal plan… this takes a moment.")

    data = await state.get_data()
    ingredients = data.get("plan_ingredients", [])
    seasonings = data.get("plan_seasonings", [])
    prefs = await db.get_preferences(user_id)

    result = await gemini.generate_meal_plan(
        ingredients=ingredients,
        seasonings=seasonings,
        dietary_restrictions=prefs.get("dietary_restrictions") or None,
        allergens=prefs.get("allergens") or None,
        skill_level=prefs.get("skill_level", "beginner"),
        servings=prefs.get("serving_size", 2),
        days=days,
        premium=True,
    )
    plan = result.get("plan", [])
    if not plan:
        await callback.message.edit_text(
            "❌ I couldn't build a plan right now. Please try again in a moment."
        )
        return

    await db.save_meal_plan(
        user_id,
        start_date=date.today().isoformat(),
        days=days,
        plan_json=json.dumps(plan, ensure_ascii=False),
    )
    await state.update_data(plan=plan, plan_day=0, plan_days=len(plan))
    await callback.message.edit_text(
        truncate_text(_render_day(plan, 0)),
        parse_mode="Markdown",
        reply_markup=plan_nav_keyboard(0, len(plan)),
    )


@router.callback_query(F.data.startswith("plan_days:"))
async def cb_plan_days(callback: CallbackQuery, state: FSMContext):
    if not await _gate_callback(callback):
        return
    days = int(callback.data.split(":")[1])
    await _generate_and_show(callback, state, days)


@router.callback_query(F.data == "plan_regen")
async def cb_plan_regen(callback: CallbackQuery, state: FSMContext):
    if not await _gate_callback(callback):
        return
    data = await state.get_data()
    days = int(data.get("plan_days") or len(data.get("plan", [])) or 7)
    await _generate_and_show(callback, state, days)


@router.callback_query(F.data.startswith("plan_day:"))
async def cb_plan_day(callback: CallbackQuery, state: FSMContext):
    if not await _gate_callback(callback):
        return
    data = await state.get_data()
    plan = data.get("plan", [])
    if not plan:
        await callback.answer("No active plan. Generate one with /plan.", show_alert=True)
        return
    idx = int(callback.data.split(":")[1])
    if idx < 0 or idx >= len(plan):
        await callback.answer()
        return
    await state.update_data(plan_day=idx)
    await callback.answer()
    try:
        await callback.message.edit_text(
            truncate_text(_render_day(plan, idx)),
            parse_mode="Markdown",
            reply_markup=plan_nav_keyboard(idx, len(plan)),
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "plan_shop")
async def cb_plan_shop(callback: CallbackQuery, state: FSMContext):
    if not await _gate_callback(callback):
        return
    await callback.answer()
    data = await state.get_data()
    plan = data.get("plan", [])
    if not plan:
        await callback.message.answer("No active plan. Generate one with /plan.")
        return

    missing: dict[str, str] = {}
    for day in plan:
        for meal in day.get("meals", []):
            for ing in meal.get("ingredients", []):
                if ing.get("have"):
                    continue
                name = str(ing.get("name", "?")).strip().lower()
                qty = str(ing.get("quantity", ""))
                missing[name] = _merge_qty(missing.get(name, ""), qty)

    if not missing:
        await callback.message.edit_text(
            "🎉 Nothing to buy! Your plan only uses what you already have."
        )
        return

    items = [f"{q} {n}".strip() for n, q in missing.items()]
    organized = await gemini.organize_shopping_list(items, premium=True)
    aisles = organized.get("aisles", [])
    if not aisles:
        lines = ["🛒 *Shopping List*", ""] + [f"• {i}" for i in items]
    else:
        lines = ["🛒 *Smart Shopping List*", ""]
        for aisle in aisles:
            entries = aisle.get("items", [])
            if not entries:
                continue
            lines.append(f"*{escape_markdown_v1(aisle.get('aisle', 'Other'))}*")
            for it in entries:
                q = str(it.get("quantity", "")).strip()
                name = escape_markdown_v1(str(it.get("name", "?")))
                lines.append(f"   • {f'{q} ' if q else ''}{name}")
            lines.append("")

    try:
        await callback.message.edit_text(
            truncate_text("\n".join(lines)), parse_mode="Markdown"
        )
    except TelegramBadRequest:
        await callback.message.answer(
            truncate_text("\n".join(lines)), parse_mode="Markdown"
        )


@router.callback_query(F.data == "plan_close")
async def cb_plan_close(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(plan=None)
    try:
        await callback.message.edit_text("🗓️ Plan closed. Use /plan to make a new one.")
    except TelegramBadRequest:
        pass
