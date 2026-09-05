"""Inventory router — handles /add, /add bulk, /remove, /inventory, /expiry,
and photo/OCR-based ingredient extraction."""
import io
import re
import logging
from datetime import date

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from services.database import DatabaseService
from services.gemini import GeminiService
from fsm.add_ingredient import AddIngredientStates, BulkAddStates
from utils.formatters import format_ingredient_list, escape_markdown_v1
from utils.keyboards import (
    category_keyboard,
    unit_keyboard,
    ingredient_remove_keyboard,
    expiry_keyboard,
)
from utils.normalize import normalize_name
from utils.dates import parse_expiry_input

logger = logging.getLogger(__name__)

router = Router()

# ── Module-level service references ──────────────────────────────────────────
# These are set during bot initialisation in bot.py, which imports this MODULE
# (import routers.inventory as inventory_router) and assigns module globals:
#   inventory_router.db = database_service
#   inventory_router.gemini = gemini_service
db: DatabaseService = None  # type: ignore[assignment]
gemini: GeminiService = None  # type: ignore[assignment]


# ══════════════════════════════════════════════════════════════════════════════
# /add  — single ingredient
# ══════════════════════════════════════════════════════════════════════════════

@router.message(F.text.lower().startswith("/add"))
async def cmd_add(message: Message, state: FSMContext):
    """Entry point for /add or /add bulk."""
    # Ensure user is registered
    if db:
        await db.register_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        await db.update_user_activity(message.from_user.id)

    text = message.text or ""
    parts = text.split(maxsplit=1)
    subcommand = parts[1].strip().lower() if len(parts) > 1 else ""

    if subcommand == "bulk":
        await _start_bulk_add(message, state)
        return

    # ── Single /add ──────────────────────────────────────────────────────────
    ingredient_input = parts[1].strip() if len(parts) > 1 else ""

    if ingredient_input:
        # Lists (commas/newlines) and chatty sentences go straight to the
        # AI bulk parser — one command handles both one-by-one and lists.
        lowered = ingredient_input.lower()
        looks_like_list = (
            "," in ingredient_input
            or "\n" in ingredient_input
            or len(ingredient_input.split()) >= 5
            or lowered.startswith(("i bought", "bought", "i have", "i got", "we bought", "got "))
        )
        if looks_like_list:
            await state.set_state(BulkAddStates.waiting_for_bulk_input)
            await on_bulk_input(message, state)
            return

        # Single ingredient — an inline amount like "/add 500g flour" or
        # "/add soy sauce 625ml" skips straight to the category question.
        inline = _parse_inline_amount(ingredient_input)
        if inline:
            name, amount, unit = inline
            await state.update_data(
                ingredient_name=name,
                ingredient_count=1.0,
                ingredient_quantity=amount,
                ingredient_unit=unit,
            )
            await state.set_state(AddIngredientStates.waiting_for_category)
            await message.answer(
                "Choose a category:",
                reply_markup=category_keyboard(),
            )
            return

        # Store the name and ask how many items/packages were bought
        normalized = normalize_name(ingredient_input)
        await state.set_state(AddIngredientStates.waiting_for_quantity)
        await state.update_data(ingredient_name=normalized)
        await message.answer(
            f"How many *{escape_markdown_v1(normalized)}* did you buy?\n"
            "Send a number of items (e.g. `1`, `20`, `a dozen`).",
            parse_mode="Markdown",
        )
    else:
        # No argument — ask for ingredient name
        await state.set_state(AddIngredientStates.waiting_for_quantity)
        await message.answer(
            "What ingredient would you like to add?\n"
            "Send the name (e.g. `chicken breast`).",
            parse_mode="Markdown",
        )


@router.message(AddIngredientStates.waiting_for_quantity, F.text)
async def on_quantity_input(message: Message, state: FSMContext):
    """Handle text input while waiting for the item count.

    This handler serves two purposes:
    1. When /add is called WITHOUT a name → the first message is treated as the
       ingredient name.  We store it and then re-prompt for the count.
    2. When /add is called WITH a name (or after step 1) → the message is
       parsed as the number of items/packages.
    """
    data = await state.get_data()
    raw = message.text.strip()

    if raw.startswith("/"):
        return  # commands like /cancel are handled elsewhere

    # If we already have a name, this message should be the count.
    if "ingredient_name" in data:
        count = _parse_count(raw)
        if count is None or count <= 0:
            await message.answer(
                "That doesn't look like a number of items. Please send how many "
                "you bought (e.g. `1`, `20`, `a dozen`).",
                parse_mode="Markdown",
            )
            return

        await state.update_data(ingredient_count=count)
        await state.set_state(AddIngredientStates.waiting_for_amount)
        await message.answer(
            "And how much is in *each one*?\n"
            "Send the amount with a unit (e.g. `625 ml`, `500 g`, `1 L`, "
            "`1 bottle`) — or just a number like `625` and I'll ask the unit.",
            parse_mode="Markdown",
        )
    else:
        # First message is the ingredient name.
        if not raw:
            await message.answer("Please send a valid ingredient name.")
            return

        normalized = normalize_name(raw)
        await state.update_data(ingredient_name=normalized)
        # Stay in waiting_for_quantity — next message will be the count.
        await message.answer(
            f"How many *{escape_markdown_v1(normalized)}* did you buy?\n"
            "Send a number of items (e.g. `1`, `20`, `a dozen`).",
            parse_mode="Markdown",
        )


# ── Per-item measurement received ───────────────────────────────────────────
@router.message(AddIngredientStates.waiting_for_amount, F.text)
async def on_amount_input(message: Message, state: FSMContext):
    """Parse how much is in EACH item: '625 ml', '500g', '1 bottle' — or a
    bare number like '625', in which case we ask for the unit afterwards."""
    raw = message.text.strip()

    if raw.startswith("/"):
        return  # commands like /cancel are handled elsewhere

    if raw.lower() in ("skip", "-", "none", "n/a"):
        amount, unit = 1.0, "pcs"
    else:
        result = _parse_amount(raw)
        if result is None:
            await message.answer(
                "I couldn't read that measurement. Send the amount in *each one* "
                "with a unit, e.g. `625 ml`, `500 g`, `1 L`, `1 bottle` — or just "
                "a number like `625` and I'll ask the unit.",
                parse_mode="Markdown",
            )
            return
        amount, unit = result
        if amount <= 0:
            await message.answer("The amount must be greater than 0. Try again.")
            return

    await state.update_data(ingredient_quantity=amount)

    if unit:
        await state.update_data(ingredient_unit=unit)
        await state.set_state(AddIngredientStates.waiting_for_category)
        await message.answer(
            "Choose a category:",
            reply_markup=category_keyboard(),
        )
        return

    # Amount without a unit → ask which unit via the keyboard.
    await state.set_state(AddIngredientStates.waiting_for_unit)
    await message.answer(
        "Choose the unit:",
        reply_markup=unit_keyboard(),
    )


# ── Unit selected via inline keyboard ──────────────────────────────────────
@router.callback_query(AddIngredientStates.waiting_for_unit, F.data.startswith("unit:"))
async def on_unit_select(callback: CallbackQuery, state: FSMContext):
    unit = callback.data.split(":", 1)[1]
    await state.update_data(ingredient_unit=unit)
    await state.set_state(AddIngredientStates.waiting_for_category)
    await callback.answer()

    try:
        await callback.message.edit_text(
            "Choose a category:",
            reply_markup=category_keyboard(),
        )
    except TelegramBadRequest:
        # Fallback if message is unchanged
        await callback.message.answer(
            "Choose a category:",
            reply_markup=category_keyboard(),
        )


# ── Unit typed as text (fallback to the keyboard) ───────────────────────────
@router.message(AddIngredientStates.waiting_for_unit, F.text)
async def on_unit_text(message: Message, state: FSMContext):
    """Allow typing a unit instead of tapping a button."""
    raw = message.text.strip()

    if raw.startswith("/"):
        return  # commands like /cancel are handled elsewhere

    unit = _normalize_unit(raw)
    if unit is None:
        await message.answer(
            "I don't know that unit. Send one like `ml`, `g`, `pcs` "
            "or tap a button below.",
            parse_mode="Markdown",
        )
        return

    await state.update_data(ingredient_unit=unit)
    await state.set_state(AddIngredientStates.waiting_for_category)
    await message.answer(
        "Choose a category:",
        reply_markup=category_keyboard(),
    )


# ── Category selected via inline keyboard ──────────────────────────────────
@router.callback_query(AddIngredientStates.waiting_for_category, F.data.startswith("cat:"))
async def on_category_select(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    await state.update_data(ingredient_category=category)
    await state.set_state(AddIngredientStates.waiting_for_expiry)
    await callback.answer()

    try:
        await callback.message.edit_text(
            "When does it expire?\n"
            "Send date as `DD/MM` (e.g. `25/12`) or type `skip` to skip.",
            parse_mode="Markdown",
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "When does it expire?\n"
            "Send date as `DD/MM` (e.g. `25/12`) or type `skip` to skip.",
            parse_mode="Markdown",
        )


# ── Expiry date received ───────────────────────────────────────────────────
@router.message(AddIngredientStates.waiting_for_expiry)
async def on_expiry_date(message: Message, state: FSMContext):
    """Parse expiry and save the ingredient to the database."""
    data = await state.get_data()
    raw = message.text.strip().lower()

    if raw.startswith("/"):
        return  # commands like /cancel are handled elsewhere

    expiry_date = None

    if raw not in ("skip", "-", "none", "n/a", "/"):
        # Accepts natural phrases (today/tomorrow/in 3 days/next week)
        # as well as DD/MM — see utils/dates.py.
        try:
            expiry_date = parse_expiry_input(raw)
        except ValueError:
            await message.answer(
                "Couldn't parse that. Try `DD/MM`, or phrases like "
                "`tomorrow`, `in 3 days`, `next week` — or type `skip`.",
                parse_mode="Markdown",
            )
            return

    # ── Save to DB ───────────────────────────────────────────────────────────
    if db is None:
        logger.error("DatabaseService not initialised on inventory router.")
        await message.answer("⚠️ Internal error: database not available.")
        await state.clear()
        return

    count = float(data.get("ingredient_count", 1))
    per_item = float(data.get("ingredient_quantity", 1))
    unit = data["ingredient_unit"]
    total = count * per_item

    ingredient_id = await db.add_ingredient(
        user_id=message.from_user.id,
        name=data["ingredient_name"],
        quantity=total,
        unit=unit,
        category=data["ingredient_category"],
        expiry_date=expiry_date,
        purchase_date=date.today().isoformat(),
    )

    # Show the multiplication only when it adds information.
    if count != 1 and not (unit == "pcs" and per_item == 1):
        amount_str = (
            f"{_fmt_num(count)} × {_fmt_num(per_item)} {unit} = "
            f"{_fmt_num(total)} {unit}"
        )
    else:
        amount_str = f"{_fmt_num(total)} {unit}"

    expiry_str = f" | Expires: {expiry_date}" if expiry_date else ""
    await message.answer(
        f"✅ *Added:* {data['ingredient_name']} ({amount_str}) "
        f"[{data['ingredient_category']}]{expiry_str}",
        parse_mode="Markdown",
    )
    logger.info(
        "User %s added ingredient #%s: %s",
        message.from_user.id,
        ingredient_id,
        data["ingredient_name"],
    )
    await state.clear()


# ══════════════════════════════════════════════════════════════════════════════
# /add bulk
# ══════════════════════════════════════════════════════════════════════════════

async def _start_bulk_add(message: Message, state: FSMContext):
    """Ask the user to send a list of ingredients."""
    await state.set_state(BulkAddStates.waiting_for_bulk_input)
    await message.answer(
        "📦 *Bulk Add Mode*\n\n"
        "Just tell me what you have — any format works:\n"
        "• A list: `chicken, rice, tomatoes`\n"
        "• With amounts: `2 chicken breast, 500g rice, a dozen eggs`\n"
        "• A sentence: `I bought 2kg of chicken and some milk today`\n"
        "• With expiry: `yogurt 500g expires in 3 days`\n\n"
        "I'll parse it all with AI and confirm before saving.\n"
        "Type /cancel to abort.",
        parse_mode="Markdown",
    )


@router.message(BulkAddStates.waiting_for_bulk_input)
async def on_bulk_input(message: Message, state: FSMContext):
    """Parse the bulk ingredient list using Gemini and ask for confirmation."""
    if gemini is None:
        await message.answer(
            "⚠️ AI service is not available right now. Please use /add for individual items."
        )
        await state.clear()
        return

    raw_text = message.text.strip()
    if not raw_text:
        await message.answer("Please send a non-empty list of ingredients.")
        return

    processing_msg = await message.answer("🤖 Parsing your ingredient list with AI…")

    parsed = await gemini.identify_ingredients_from_text(raw_text)

    if not parsed:
        await processing_msg.edit_text(
            "❌ Could not parse any ingredients from your text.\n"
            "Please try again with a clearer list, or use /add for individual items."
        )
        return

    _resolve_expiry_hints(parsed)
    await _present_parsed_for_confirmation(message, state, parsed, processing_msg)


# ── Bulk add confirmation ──────────────────────────────────────────────────
@router.callback_query(F.data == "confirm:bulk_add")
async def on_bulk_confirm(callback: CallbackQuery, state: FSMContext):
    """Confirm and save all bulk-parsed ingredients."""
    await callback.answer("Adding ingredients…")

    data = await state.get_data()
    parsed: list[dict] = data.get("bulk_parsed", [])

    if db is None:
        logger.error("DatabaseService not initialised on inventory router.")
        await callback.message.edit_text("⚠️ Internal error: database not available.")
        await state.clear()
        return

    added_ids = await db.add_ingredients_bulk(callback.from_user.id, parsed)

    # Build a concise confirmation
    names = [normalize_name(item.get("name", "?")) for item in parsed]
    summary = ", ".join(f"• {n}" for n in names)

    try:
        await callback.message.edit_text(
            f"✅ *Added {len(added_ids)} ingredients:*\n\n{summary}",
            parse_mode="Markdown",
        )
    except TelegramBadRequest:
        # Message too long or unchanged — send a new one
        await callback.message.answer(
            f"✅ Added {len(added_ids)} ingredients!",
            parse_mode="Markdown",
        )

    logger.info(
        "User %s bulk-added %d ingredients",
        callback.from_user.id,
        len(added_ids),
    )
    await state.clear()


# ── Cancel during any state ────────────────────────────────────────────────
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Allow typing /cancel to abort any in-progress flow."""
    await state.clear()
    await message.answer("❌ Cancelled. Your inventory is unchanged.")


@router.callback_query(F.data == "cancel")
async def on_cancel(callback: CallbackQuery, state: FSMContext):
    """Cancel the current multi-step flow."""
    await state.clear()
    await callback.answer("Cancelled.", show_alert=False)
    try:
        await callback.message.edit_text("❌ Action cancelled.")
    except TelegramBadRequest:
        await callback.message.answer("❌ Action cancelled.")


# ══════════════════════════════════════════════════════════════════════════════
# /remove
# ══════════════════════════════════════════════════════════════════════════════

@router.message(F.text.lower() == "/remove")
async def cmd_remove(message: Message):
    """Show a keyboard with all user's ingredients for removal."""
    if db is None:
        await message.answer("⚠️ Database not available.")
        return

    await db.update_user_activity(message.from_user.id)

    ingredients = await db.get_ingredients(message.from_user.id)
    if not ingredients:
        await message.answer(
            "Your inventory is empty — nothing to remove. Use /add to add ingredients!"
        )
        return

    await message.answer(
        "🗑️ *Select an ingredient to remove:*",
        parse_mode="Markdown",
        reply_markup=ingredient_remove_keyboard(ingredients),
    )


@router.callback_query(F.data.startswith("remove_ing:"))
async def on_remove_ingredient(callback: CallbackQuery):
    """Remove a selected ingredient from the database."""
    await callback.answer()

    if db is None:
        await callback.message.answer("⚠️ Database not available.")
        return

    try:
        ingredient_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.message.answer("Invalid ingredient selection.")
        return

    removed = await db.remove_ingredient(callback.from_user.id, ingredient_id)

    if removed:
        await callback.message.edit_text(
            "✅ Ingredient removed from your inventory."
        )
        logger.info(
            "User %s removed ingredient #%s",
            callback.from_user.id,
            ingredient_id,
        )
    else:
        try:
            await callback.message.edit_text(
                "⚠️ Could not find that ingredient. It may have already been removed."
            )
        except TelegramBadRequest:
            await callback.message.answer(
                "⚠️ Could not find that ingredient."
            )


# ══════════════════════════════════════════════════════════════════════════════
# /inventory
# ══════════════════════════════════════════════════════════════════════════════

@router.message(F.text.lower().startswith("/inventory"))
async def cmd_inventory(message: Message):
    """Show the user's full inventory, optionally filtered by category."""
    if db is None:
        await message.answer("⚠️ Database not available.")
        return

    await db.register_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await db.update_user_activity(message.from_user.id)

    # Parse optional category filter: /inventory proteins
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    category_filter = parts[1].strip().lower() if len(parts) > 1 else None

    # Validate category against known categories
    if category_filter:
        from data.cuisines import CATEGORIES
        if category_filter not in CATEGORIES:
            # Try a fuzzy hint
            available = ", ".join(CATEGORIES.keys())
            await message.answer(
                f"Unknown category *{escape_markdown_v1(category_filter)}*.\n"
                f"Available: {available}",
                parse_mode="Markdown",
            )
            return

    ingredients = await db.get_ingredients(
        message.from_user.id,
        category=category_filter,
    )

    if not ingredients:
        if category_filter:
            await message.answer(
                f"No ingredients found in category *{escape_markdown_v1(category_filter)}*.\n"
                f"Use /add to add some!",
                parse_mode="Markdown",
            )
        else:
            await message.answer(
                "🍳 *Your kitchen is empty — for now.*\n\n"
                "This is where everything you have on hand lives. Once it has "
                "even one ingredient, I can start suggesting meals from what "
                "you actually have — no wasted food, no last-minute shops.\n\n"
                "👉 Send /add to drop in the first thing you can see.",
                parse_mode="Markdown",
            )
        return

    reply = format_ingredient_list(ingredients)

    # Add category filter info
    if category_filter:
        from data.cuisines import CATEGORIES
        cat_label = CATEGORIES.get(category_filter, category_filter)
        reply = f"📦 *{cat_label}*\n\n" + reply

    await message.answer(reply, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
# /expiry
# ══════════════════════════════════════════════════════════════════════════════

@router.message(F.text.lower() == "/expiry")
async def cmd_expiry(message: Message):
    """Show ingredients expiring within 2 days."""
    if db is None:
        await message.answer("⚠️ Database not available.")
        return

    await db.update_user_activity(message.from_user.id)

    expiring = await db.get_expiring_soon(message.from_user.id, days=2)

    if not expiring:
        await message.answer(
            "✅ No ingredients expiring in the next 2 days. You're good!"
        )
        return

    today = date.today()
    lines = ["⏰ *Expiring Soon*\n"]

    for ing in expiring:
        try:
            exp_date = date.fromisoformat(ing["expiry_date"])
            days_left = (exp_date - today).days
            if days_left <= 0:
                urgency = "🔴 *EXPIRED*"
            elif days_left == 1:
                urgency = "🟠 *Tomorrow!*"
            else:
                urgency = f"🟡 In {days_left} days"
        except (ValueError, TypeError):
            urgency = "⚠️ Unknown date"

        lines.append(
            f"{urgency}\n"
            f"  • {ing['name']} — {ing['quantity']} {ing['unit']} "
            f"(expires: {ing['expiry_date']})"
        )
        lines.append("")

    lines.append("💡 Tap an ingredient below to find recipes that use it:")

    keyboard = expiry_keyboard(expiring)
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


# ── Expiry recipe lookup callback ──────────────────────────────────────────
@router.callback_query(F.data.startswith("expiry_recipe:"))
async def on_expiry_recipe(callback: CallbackQuery):
    """When user taps an expiring ingredient — suggest using /suggest with that ingredient."""
    await callback.answer()
    ingredient_name = callback.data.split(":", 1)[1]
    decoded_name = ingredient_name  # callback_data is already plain text

    await callback.message.answer(
        f"🍽️ *{escape_markdown_v1(decoded_name)}* is expiring soon!\n\n"
        f"Use /suggest to get recipe ideas that use ingredients from your inventory. "
        f"Consider cooking something with *{escape_markdown_v1(decoded_name)}* today!",
        parse_mode="Markdown",
    )

    try:
        await callback.message.edit_text(
            f"💡 Check your messages above for recipe suggestions using *{escape_markdown_v1(decoded_name)}*.",
            parse_mode="Markdown",
        )
    except TelegramBadRequest:
        pass  # original message may be identical or already edited


# ══════════════════════════════════════════════════════════════════════════════
# Generic close callback
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "close")
async def on_close(callback: CallbackQuery):
    """Dismiss an inline-keyboard message."""
    await callback.answer()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        try:
            await callback.message.edit_text("Closed.")
        except TelegramBadRequest:
            pass


# ── Shared helpers for AI-parsed (text bulk / photo) adds ─────────────────

def _resolve_expiry_hints(parsed: list[dict]) -> list[dict]:
    """Convert natural-language expiry hints into ISO dates (in place).
    Unparseable hints are dropped with a warning rather than failing the add."""
    for item in parsed:
        item["expiry_date"] = None
        hint = (item.pop("expiry_hint", None) or "").strip()
        if hint:
            try:
                item["expiry_date"] = parse_expiry_input(hint)
            except ValueError:
                logger.warning(
                    "Unparseable expiry hint %r for ingredient %r — ignoring.",
                    hint, item.get("name"),
                )
    return parsed


def _fmt_qty(item: dict) -> str:
    """Human-readable 'quantity unit' fragment for display."""
    qty, unit = item.get("quantity"), item.get("unit", "pcs")
    if qty is None:
        return "?"
    unit_str = "" if unit in (None, "", "unknown") else f" {unit}"
    qty_int = int(qty) if float(qty).is_integer() else qty
    return f"{qty_int}{unit_str}"


def _render_card(parsed: list[dict]) -> str:
    lines = ["📋 *Parsed Ingredients:*\n"]
    for i, item in enumerate(parsed, 1):
        expiry_suffix = f" ⏰ {item['expiry_date']}" if item.get("expiry_date") else ""
        lines.append(
            f"{i}. {escape_markdown_v1(item.get('name', '?'))} — {_fmt_qty(item)} "
            f"[{item.get('category', 'other')}]{expiry_suffix}"
        )
    lines.append(f"\n✅ Total: {len(parsed)} items")
    lines.append(
        "\n💬 Spot a mistake? Just reply with a correction "
        "(e.g. `the soy sauce is 500ml`) and I'll update the list.\n"
        "✅ Confirm to save, or ❌ to cancel."
    )
    return "\n".join(lines)


def _parse_quantity_reply(raw: str) -> tuple[float, str | None] | None:
    """Parse a quantity reply like '500', '500 ml', '2 bottles', '0.5'.
    Returns (quantity, unit_or_None) or None if unparseable."""
    raw = raw.strip().lower().replace(",", ".")
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Zµ/]{1,12})?$", raw)
    if not match:
        return None
    qty = float(match.group(1))
    unit_word = match.group(2)
    if unit_word:
        unit = _normalize_unit(unit_word) or unit_word.lower()
    else:
        unit = None
    return (qty, unit)


# ── Single-add parsing helpers ──────────────────────────────────────────────

UNIT_SYNONYMS = {
    # weight
    "g": "g", "gram": "g", "grams": "g", "gr": "g",
    "kg": "kg", "kilo": "kg", "kilos": "kg",
    "kilogram": "kg", "kilograms": "kg",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    # volume
    "ml": "ml", "mil": "ml", "milliliter": "ml", "milliliters": "ml",
    "millilitre": "ml", "millilitres": "ml",
    "l": "L", "lt": "L", "liter": "L", "liters": "L",
    "litre": "L", "litres": "L",
    "cup": "cups", "cups": "cups",
    "tbsp": "tbsp", "tbs": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    # counts / containers
    "pcs": "pcs", "pc": "pcs", "piece": "pcs", "pieces": "pcs",
    "bottle": "pcs", "bottles": "pcs",
    "can": "pcs", "cans": "pcs",
    "jar": "pcs", "jars": "pcs",
    "pack": "pcs", "packs": "pcs", "packet": "pcs", "packets": "pcs",
    "bag": "pcs", "bags": "pcs",
    "box": "pcs", "boxes": "pcs",
    "carton": "pcs", "cartons": "pcs",
    "tin": "pcs", "tins": "pcs", "tray": "pcs", "trays": "pcs",
    # produce
    "bunch": "bunches", "bunches": "bunches",
    "clove": "cloves", "cloves": "cloves",
    "pinch": "pinches", "pinches": "pinches",
    "whole": "whole",
}


def _normalize_unit(word: str) -> str | None:
    """Map a user-typed unit word to a canonical unit (g, kg, ml, L, pcs…).
    Returns None for unrecognized words."""
    return UNIT_SYNONYMS.get(word.strip().lower())


def _fmt_num(value: float) -> str:
    """Format a number without a trailing .0 (625.0 → '625')."""
    return str(int(value)) if float(value).is_integer() else str(value)


_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "half": 0.5, "couple": 2, "pair": 2,
}


def _parse_count(raw: str) -> float | None:
    """Parse a count of items: '20', '20 bottles', 'a dozen', 'half a dozen'.
    Returns the count or None if unparseable."""
    text = raw.strip().lower().replace(",", ".")
    match = re.match(r"^(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    words = text.split()
    if "dozen" in words:
        return 6.0 if "half" in words else 12.0
    for word in words:
        if word in _NUMBER_WORDS:
            return float(_NUMBER_WORDS[word])
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    return None


def _parse_amount(raw: str) -> tuple[float, str | None] | None:
    """Parse a per-item measurement: '625 ml', '500g', '1 bottle', '0.5'.
    Returns (amount, unit_or_None) or None if unparseable/unknown unit."""
    text = raw.strip().lower().replace(",", ".")
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Zµ/]{1,12})?$", text)
    if not match:
        return None
    amount = float(match.group(1))
    unit_word = match.group(2)
    if unit_word:
        unit = _normalize_unit(unit_word)
        if unit is None:
            return None  # unknown unit word — caller re-asks
    else:
        unit = None
    return (amount, unit)


_INLINE_LEAD_RE = re.compile(
    r"^(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>[a-zA-Zµ/]{1,12})\s+(?P<name>.+)$"
)
_INLINE_TRAIL_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>[a-zA-Zµ/]{1,12})$"
)


def _parse_inline_amount(raw: str) -> tuple[str, float, str] | None:
    """Parse an amount written inside the /add argument:
    '/add 500g flour' or '/add soy sauce 625ml' → (name, amount, unit)."""
    for pattern in (_INLINE_LEAD_RE, _INLINE_TRAIL_RE):
        match = pattern.match(raw.strip())
        if not match:
            continue
        unit = _normalize_unit(match.group("unit"))
        if unit is None:
            continue  # e.g. '3 cheese pizza' — not an amount
        amount = float(match.group("num").replace(",", "."))
        if amount <= 0:
            continue
        name = re.sub(r"^(of|with)\s+", "", match.group("name").strip()).strip()
        return normalize_name(name), amount, unit
    return None


async def _present_parsed_for_confirmation(
    message: Message, state: FSMContext, parsed: list[dict], processing_msg: Message
):
    """Store parsed items in FSM, ask about any unknown amounts, then show the
    shared confirmation card (which also accepts plain-English corrections)."""
    # Normalize items coming back from the model.
    clean: list[dict] = []
    for item in parsed:
        qty = item.get("quantity")
        try:
            qty = float(qty) if qty is not None else None
        except (TypeError, ValueError):
            qty = None
        if qty is not None and qty <= 0:
            qty = None
        clean.append({
            "name": str(item.get("name", "?")).strip(),
            "quantity": qty,
            "unit": str(item.get("unit") or "pcs").strip().lower(),
            "category": str(item.get("category") or "other").strip().lower(),
            "expiry_date": item.get("expiry_date"),
        })

    await state.update_data(bulk_parsed=clean)

    # Items with an unknown amount → ask the user one by one.
    queue = [i for i, item in enumerate(clean) if item["quantity"] is None]
    if queue:
        await state.update_data(qty_queue=queue)
        await state.set_state(BulkAddStates.waiting_for_quantity_fix)
        first = clean[queue[0]]
        unit_hint = first["unit"] if first["unit"] not in ("unknown", "pcs") else ""
        hint = f" (suggested unit: {unit_hint})" if unit_hint else ""
        text = (
            f"❓ How much *{escape_markdown_v1(first['name'])}* do you have?{hint}\n\n"
            "Send a number (e.g. `500`) or an amount with a unit "
            "(`500 ml`, `2 bottles`) — or `skip` to save it as 1 pcs."
        )
        if processing_msg:
            await processing_msg.edit_text(text, parse_mode="Markdown")
        else:
            await message.answer(text, parse_mode="Markdown")
        return

    await state.set_state(BulkAddStates.reviewing_parsed)
    from utils.keyboards import confirm_keyboard

    if processing_msg:
        await processing_msg.edit_text(
            _render_card(clean),
            parse_mode="Markdown",
            reply_markup=confirm_keyboard("bulk_add"),
        )
    else:
        await message.answer(
            _render_card(clean),
            parse_mode="Markdown",
            reply_markup=confirm_keyboard("bulk_add"),
        )


async def _ask_next_quantity(message: Message, state: FSMContext):
    """Prompt for the next unknown amount, or show the card when done."""
    data = await state.get_data()
    parsed: list[dict] = data["bulk_parsed"]
    queue: list[int] = data.get("qty_queue", [])

    if not queue:
        await state.set_state(BulkAddStates.reviewing_parsed)
        from utils.keyboards import confirm_keyboard

        await message.answer(
            _render_card(parsed),
            parse_mode="Markdown",
            reply_markup=confirm_keyboard("bulk_add"),
        )
        return

    item = parsed[queue[0]]
    unit_hint = item["unit"] if item["unit"] not in ("unknown", "pcs") else ""
    hint = f" (suggested unit: {unit_hint})" if unit_hint else ""
    await message.answer(
        f"❓ And how much *{escape_markdown_v1(item['name'])}*?{hint}\n"
        "(`500`, `500 ml`, `2 bottles`, or `skip`)",
        parse_mode="Markdown",
    )


@router.message(BulkAddStates.waiting_for_quantity_fix, F.text)
async def on_quantity_fix(message: Message, state: FSMContext):
    """User answered the 'how much?' question for one parsed item."""
    data = await state.get_data()
    parsed: list[dict] = data["bulk_parsed"]
    queue: list[int] = data.get("qty_queue", [])
    raw = message.text.strip()
    idx = queue[0]

    if raw.lower() in ("skip", "-", "none", "idk", "dunno"):
        parsed[idx]["quantity"] = 1
        if parsed[idx]["unit"] == "unknown":
            parsed[idx]["unit"] = "pcs"
    else:
        result = _parse_quantity_reply(raw)
        if result is None:
            await message.answer(
                "That doesn't look like an amount. Try `500`, `500 ml`, "
                "`2 bottles` — or `skip`.",
            )
            return
        qty, unit = result
        if qty <= 0:
            await message.answer("Quantity must be greater than 0. Try again.")
            return
        parsed[idx]["quantity"] = qty
        if unit:
            parsed[idx]["unit"] = unit
        elif parsed[idx]["unit"] == "unknown":
            parsed[idx]["unit"] = "pcs"

    queue = queue[1:]
    await state.update_data(bulk_parsed=parsed, qty_queue=queue)
    await _ask_next_quantity(message, state)


@router.message(BulkAddStates.reviewing_parsed, F.text)
async def on_review_correction(message: Message, state: FSMContext):
    """User replied with a plain-English correction to the parsed list."""
    if gemini is None:
        await message.answer("⚠️ AI service is not available right now.")
        return

    data = await state.get_data()
    parsed: list[dict] = data.get("bulk_parsed", [])
    correction = message.text.strip()
    if not correction:
        return

    processing_msg = await message.answer("🤖 Updating your list…")
    updated = await gemini.apply_correction(parsed, correction)
    if not updated:
        await processing_msg.edit_text(
            "❌ I couldn't apply that correction. Try rephrasing it, "
            "or ❌ cancel and start again."
        )
        return

    _resolve_expiry_hints(updated)
    await _present_parsed_for_confirmation(message, state, updated, processing_msg)


# ── Photo / OCR add ────────────────────────────────────────────────────────
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


@router.message(StateFilter(None), F.photo | F.document)
async def on_photo_upload(message: Message, state: FSMContext):
    """OCR/vision: send a receipt, shopping list, or fridge/pantry photo and
    Gemini extracts the ingredients into the same confirm-and-save flow."""
    if gemini is None:
        await message.answer(
            "⚠️ AI service is not available right now. Please use /add for individual items."
        )
        return

    if message.photo:
        # Telegram photos are always JPEG; pick the largest resolution.
        file_id = message.photo[-1].file_id
        mime_type = "image/jpeg"
    else:
        doc = message.document
        mime = (doc.mime_type or "").lower()
        if mime not in IMAGE_MIME_TYPES:
            await message.answer(
                "That file isn't an image I can read — send a JPEG, PNG, WEBP or HEIC photo."
            )
            return
        file_id = doc.file_id
        mime_type = mime

    processing_msg = await message.answer("📸 Reading your image with AI…")

    try:
        image_buffer = io.BytesIO()
        await message.bot.download(file=file_id, destination=image_buffer)
    except Exception:
        logger.exception("Failed to download photo from Telegram")
        await processing_msg.edit_text(
            "❌ Couldn't download that image. Please try sending it again."
        )
        return

    parsed = await gemini.extract_ingredients_from_image(
        image_buffer.getvalue(), mime_type
    )
    if not parsed:
        await processing_msg.edit_text(
            "❌ I couldn't find any ingredients in that image.\n"
            "Try a clearer photo, or add items by text with /add."
        )
        return

    _resolve_expiry_hints(parsed)
    await _present_parsed_for_confirmation(message, state, parsed, processing_msg)
