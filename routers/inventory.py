"""Inventory router — handles /add, /add bulk, /remove, /inventory, /expiry."""
import logging
from datetime import date

from aiogram import Router, F
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

logger = logging.getLogger(__name__)

router = Router()

# ── Module-level service references ──────────────────────────────────────────
# These are set during bot initialisation (e.g. in bot.py):
#   from routers.inventory import inventory as inventory_router
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
        # Ingredient name provided directly — store and ask for quantity
        normalized = normalize_name(ingredient_input)
        await state.set_state(AddIngredientStates.waiting_for_quantity)
        await state.update_data(ingredient_name=normalized)
        await message.answer(
            f"How much *{escape_markdown_v1(normalized)}* do you have?",
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
    """Handle text input while waiting for quantity.

    This handler serves two purposes:
    1. When /add is called WITHOUT a name → the first message is treated as the
       ingredient name.  We store it and then re-prompt for the quantity.
    2. When /add is called WITH a name (or after step 1) → the message is
       parsed as the quantity.
    """
    data = await state.get_data()
    raw = message.text.strip()

    # If we already have a name, this message should be the quantity.
    if "ingredient_name" in data:
        # ── Parse quantity ────────────────────────────────────────────────────
        try:
            quantity = float(raw.replace(",", "."))
        except ValueError:
            await message.answer(
                "That doesn't look like a number. Please send a quantity "
                "(e.g. `2`, `0.5`, `250`).",
                parse_mode="Markdown",
            )
            return

        if quantity <= 0:
            await message.answer("Quantity must be greater than 0. Try again.")
            return

        await state.update_data(ingredient_quantity=quantity)
        await state.set_state(AddIngredientStates.waiting_for_unit)
        await message.answer(
            "Choose the unit:",
            reply_markup=unit_keyboard(),
        )
    else:
        # ── First message is the ingredient name ─────────────────────────────
        if not raw:
            await message.answer("Please send a valid ingredient name.")
            return

        normalized = normalize_name(raw)
        await state.update_data(ingredient_name=normalized)
        # Stay in waiting_for_quantity — next message will be the quantity.
        await message.answer(
            f"How much *{escape_markdown_v1(normalized)}* do you have?\n"
            "Send a number (e.g. `2`, `0.5`, `250`).",
            parse_mode="Markdown",
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

    expiry_date = None

    if raw not in ("skip", "-", "none", "n/a", "/"):
        # Try to parse DD/MM format
        try:
            parts = raw.replace("/", " ").replace("-", " ").replace(".", " ").split()
            if len(parts) >= 2:
                day, month = int(parts[0]), int(parts[1])
                # Infer year — prefer the next occurrence of this date
                today = date.today()
                try:
                    expiry = date(today.year, month, day)
                    if expiry < today:
                        expiry = date(today.year + 1, month, day)
                except ValueError:
                    # Invalid date (e.g. Feb 30) — keep None
                    expiry = None
                if expiry:
                    expiry_date = expiry.isoformat()
        except (ValueError, IndexError):
            await message.answer(
                "Couldn't parse that date. Use `DD/MM` format or type `skip`.",
                parse_mode="Markdown",
            )
            return

    # ── Save to DB ───────────────────────────────────────────────────────────
    if db is None:
        logger.error("DatabaseService not initialised on inventory router.")
        await message.answer("⚠️ Internal error: database not available.")
        await state.clear()
        return

    ingredient_id = await db.add_ingredient(
        user_id=message.from_user.id,
        name=data["ingredient_name"],
        quantity=data["ingredient_quantity"],
        unit=data["ingredient_unit"],
        category=data["ingredient_category"],
        expiry_date=expiry_date,
        purchase_date=date.today().isoformat(),
    )

    expiry_str = f" | Expires: {expiry_date}" if expiry_date else ""
    await message.answer(
        f"✅ *Added:* {data['ingredient_name']} "
        f"({data['ingredient_quantity']} {data['ingredient_unit']}) "
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
        "Send me a list of ingredients. You can separate them with:\n"
        "• Commas: `chicken, rice, tomatoes`\n"
        "• Newlines (each ingredient on a new line)\n\n"
        "Include quantities if you like: `2 chicken breast, 500g rice`\n\n"
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

    # Store parsed results in FSM for confirmation
    await state.update_data(bulk_parsed=parsed)

    # Build a summary
    lines = ["📋 *Parsed Ingredients:*\n"]
    for i, item in enumerate(parsed, 1):
        lines.append(
            f"{i}. {item.get('name', '?')} — "
            f"{item.get('quantity', '?')} {item.get('unit', '?')} "
            f"[{item.get('category', 'other')}]"
        )
    lines.append(f"\n✅ Total: {len(parsed)} items")
    lines.append("\nAdd all of these to your inventory?")

    from utils.keyboards import confirm_keyboard

    await processing_msg.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=confirm_keyboard("bulk_add"),
    )


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
            await message.answer("Your inventory is empty. Use /add to add ingredients!")
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
