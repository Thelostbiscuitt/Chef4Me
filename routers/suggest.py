"""Router handling /suggest and /recipe commands -- the AI-powered meal suggestion core."""
import json
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from services.database import DatabaseService
from services.gemini import GeminiService
from utils.formatters import format_meal_suggestion, format_full_recipe, truncate_text
from utils.keyboards import meal_suggestion_keyboard, recipe_action_keyboard, rating_keyboard

logger = logging.getLogger(__name__)

router = Router()

# -- Service references (injected during bot startup) --
db: DatabaseService = None  # type: ignore[assignment]
gemini: GeminiService = None  # type: ignore[assignment]
notion = None  # type: ignore[assignment]

BATCH_SIZE = 3
MAX_MESSAGE_LENGTH = 4096


# ======================================================================
#  /suggest  -- AI meal suggestions
# ======================================================================

@router.message(F.text.startswith("/suggest"))
async def cmd_suggest(message: Message, state: FSMContext):
    """Suggest meals based on user's ingredients and preferences."""
    user_id = message.from_user.id

    parts = message.text.strip().split()
    arg_cuisine = None
    arg_diet = None
    for part in parts[1:]:
        candidate = part.lower()
        known_diets = {
            "vegetarian", "vegan", "pescatarian", "halal", "kosher",
            "gluten-free", "dairy-free", "nut-free", "low-carb", "keto",
        }
        if candidate in known_diets:
            arg_diet = candidate
        else:
            arg_cuisine = candidate

    ingredients, seasonings = await db.get_ingredients_as_lists(user_id)
    if not ingredients and not seasonings:
        await message.answer(
            "Your ingredient list is empty!\n"
            "Add ingredients first with /add so I know what you're working with."
        )
        return

    prefs = await db.get_preferences(user_id)

    dietary_restrictions = list(prefs.get("dietary_restrictions") or [])
    allergens = list(prefs.get("allergens") or [])
    skill_level = prefs.get("skill_level", "beginner")
    serving_size = prefs.get("serving_size", 2)
    preferred_cuisines = list(prefs.get("preferred_cuisines") or [])

    if arg_cuisine:
        preferred_cuisines = [arg_cuisine]
    if arg_diet and arg_diet not in dietary_restrictions:
        dietary_restrictions.append(arg_diet)

    avoid_cuisines = await db.get_recent_cuisines(user_id, limit=20)
    if preferred_cuisines:
        avoid_cuisines = [
            c for c in avoid_cuisines
            if c.lower() not in [p.lower() for p in preferred_cuisines]
        ]

    thinking_msg = await message.answer(
        "Thinking... Let me find something delicious for you!"
    )

    try:
        response = await gemini.suggest_meals(
            ingredients=ingredients,
            seasonings=seasonings,
            dietary_restrictions=dietary_restrictions if dietary_restrictions else None,
            allergens=allergens if allergens else None,
            skill_level=skill_level,
            servings=serving_size,
            count=6,
            preferred_cuisines=preferred_cuisines if preferred_cuisines else None,
            avoid_cuisines=avoid_cuisines if avoid_cuisines else None,
        )
    except Exception as exc:
        logger.error("Gemini suggest_meals failed for user %s: %s", user_id, exc)
        try:
            await thinking_msg.edit_text(
                "Sorry, the AI kitchen is down right now. Please try again in a moment."
            )
        except TelegramBadRequest:
            await thinking_msg.delete()
        return

    if not response.suggestions:
        try:
            await thinking_msg.edit_text(
                "I couldn't find any meals matching your ingredients and preferences.\n"
                "Try adding more ingredients with /add or adjusting your dietary "
                "settings with /preferences."
            )
        except TelegramBadRequest:
            await message.answer(
                "I couldn't find any meals matching your ingredients and preferences.\n"
                "Try adding more ingredients with /add or adjusting your dietary "
                "settings with /preferences."
            )
        return

    suggestions_data = [s.model_dump() for s in response.suggestions]
    await state.update_data(
        suggestions=suggestions_data,
        current_offset=0,
    )

    first_batch = suggestions_data[:BATCH_SIZE]
    text = _build_suggestions_list_text(first_batch, 0)
    keyboard = meal_suggestion_keyboard(first_batch, offset=0)

    try:
        await thinking_msg.edit_text(
            truncate_text(text),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except TelegramBadRequest:
        await thinking_msg.delete()
        await message.answer(
            truncate_text(text), parse_mode="Markdown", reply_markup=keyboard
        )


# ======================================================================
#  Callback: recipe_select:{index}  -- show full suggestion detail
# ======================================================================

@router.callback_query(F.data.startswith("recipe_select:"))
async def cb_recipe_select(callback: CallbackQuery, state: FSMContext):
    """Display full details for a selected meal suggestion."""
    await callback.answer()

    data = await state.get_data()
    suggestions: list[dict] = data.get("suggestions", [])
    index = int(callback.data.split(":")[1])

    if index < 0 or index >= len(suggestions):
        await callback.message.edit_text(
            "This suggestion is no longer available."
        )
        return

    suggestion = suggestions[index]
    text = format_meal_suggestion(suggestion, index)
    keyboard = recipe_action_keyboard(recipe_idx=index)

    try:
        await callback.message.edit_text(
            truncate_text(text),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except TelegramBadRequest:
        await callback.message.delete()
        await callback.message.answer(
            truncate_text(text), parse_mode="Markdown", reply_markup=keyboard
        )


# ======================================================================
#  Callback: suggest_more  -- next batch or fresh AI call
# ======================================================================

@router.callback_query(F.data == "suggest_more")
async def cb_suggest_more(callback: CallbackQuery, state: FSMContext):
    """Show the next batch of suggestions, or generate new ones if exhausted."""
    await callback.answer("Loading more suggestions...")

    user_id = callback.from_user.id
    data = await state.get_data()
    suggestions: list[dict] = data.get("suggestions", [])
    current_offset: int = data.get("current_offset", 0)

    next_offset = current_offset + BATCH_SIZE

    if next_offset < len(suggestions):
        batch = suggestions[next_offset: next_offset + BATCH_SIZE]
        await state.update_data(current_offset=next_offset)

        text = _build_suggestions_list_text(batch, next_offset)
        keyboard = meal_suggestion_keyboard(batch, offset=next_offset)

        try:
            await callback.message.edit_text(
                truncate_text(text),
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except TelegramBadRequest:
            await callback.message.delete()
            await callback.message.answer(
                truncate_text(text), parse_mode="Markdown", reply_markup=keyboard
            )
        return

    thinking_text = "Fresh ideas coming up..."

    try:
        await callback.message.edit_text(thinking_text, parse_mode="Markdown")
    except TelegramBadRequest:
        await callback.message.answer(thinking_text)

    ingredients, seasonings = await db.get_ingredients_as_lists(user_id)
    if not ingredients and not seasonings:
        await callback.message.answer(
            "No ingredients left! Add more with /add."
        )
        return

    prefs = await db.get_preferences(user_id)
    avoid_cuisines = await db.get_recent_cuisines(user_id, limit=20)

    try:
        response = await gemini.suggest_meals(
            ingredients=ingredients,
            seasonings=seasonings,
            dietary_restrictions=prefs.get("dietary_restrictions") or None,
            allergens=prefs.get("allergens") or None,
            skill_level=prefs.get("skill_level", "beginner"),
            servings=prefs.get("serving_size", 2),
            count=6,
            avoid_cuisines=avoid_cuisines if avoid_cuisines else None,
        )
    except Exception as exc:
        logger.error("Gemini re-suggest failed for user %s: %s", user_id, exc)
        await callback.message.edit_text(
            "Couldn't load more suggestions. Please try /suggest again."
        )
        return

    if not response.suggestions:
        await callback.message.edit_text(
            "No more ideas right now. Try adding different ingredients with /add!"
        )
        return

    new_suggestions = [s.model_dump() for s in response.suggestions]
    combined = (suggestions + new_suggestions)[-30:]
    new_offset = len(suggestions)
    await state.update_data(suggestions=combined, current_offset=new_offset)

    batch = new_suggestions[:BATCH_SIZE]
    text = _build_suggestions_list_text(batch, new_offset)
    keyboard = meal_suggestion_keyboard(batch, offset=new_offset)

    try:
        await callback.message.edit_text(
            truncate_text(text),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except TelegramBadRequest:
        await callback.message.delete()
        await callback.message.answer(
            truncate_text(text), parse_mode="Markdown", reply_markup=keyboard
        )


# ======================================================================
#  Callback: cooked:{index}  -- mark meal as cooked
# ======================================================================

@router.callback_query(F.data.startswith("cooked:"))
async def cb_cooked(callback: CallbackQuery, state: FSMContext):
    """Record that the user cooked a suggested meal and prompt for a rating."""
    await callback.answer("Noted!")

    user_id = callback.from_user.id
    index = int(callback.data.split(":")[1])

    data = await state.get_data()
    suggestions: list[dict] = data.get("suggestions", [])

    if index < 0 or index >= len(suggestions):
        await callback.message.answer("This suggestion is no longer available.")
        return

    suggestion = suggestions[index]
    recipe_name = suggestion.get("name", "Unknown")
    cuisine = suggestion.get("cuisine", "")
    ingredient_names = [
        ing["name"]
        for ing in suggestion.get("ingredients", [])
        if ing.get("have")
    ]

    meal_id = await db.add_cooked_meal(
        user_id=user_id,
        recipe_name=recipe_name,
        cuisine=cuisine,
        ingredients_used=ingredient_names,
    )

    if ingredient_names:
        await db.consume_ingredients(user_id, ingredient_names)

    if notion and getattr(notion, "is_available", False):
        try:
            notion_db_id = None
            prefs = await db.get_preferences(user_id)
            notion_db_id = prefs.get("notion_database_id")
            await notion.sync_cooked_meal(
                user_id=user_id,
                recipe_name=recipe_name,
                cuisine=cuisine,
                database_id=notion_db_id,
            )
        except Exception as exc:
            logger.warning("Notion sync failed for cooked meal: %s", exc)

    confirm_text = (
        f"Great choice! You cooked *{recipe_name}*!\n\n"
        f"Consumed ingredients: "
        f"{', '.join(ingredient_names) or 'none recorded'}\n\n"
        "Rate your meal:"
    )
    keyboard = rating_keyboard(meal_id)

    try:
        await callback.message.edit_text(
            confirm_text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except TelegramBadRequest:
        await callback.message.delete()
        await callback.message.answer(
            confirm_text, parse_mode="Markdown", reply_markup=keyboard
        )


# ======================================================================
#  Callback: rate:{meal_id}:{rating}  -- rate a cooked meal
# ======================================================================

@router.callback_query(F.data.startswith("rate:"))
async def cb_rate(callback: CallbackQuery):
    """Rate a previously cooked meal. Auto-favourites if rating >= 4."""
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Invalid rating callback.", show_alert=True)
        return

    meal_id = int(parts[1])
    rating = int(parts[2])
    user_id = callback.from_user.id

    await db.rate_meal(user_id=user_id, meal_id=meal_id, rating=rating)

    if rating >= 4:
        await db.toggle_favorite(user_id, meal_id)

    stars = "\u2b50" * rating
    await callback.answer(f"Rated {stars}", show_alert=False)

    fav_note = "\nAutomatically added to favourites!" if rating >= 4 else ""
    text = (
        f"{stars} Thanks for rating! Your feedback helps me suggest better meals."
        f"{fav_note}\n\n"
        "Use /suggest for more ideas or /history to see past meals."
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown")
    except TelegramBadRequest:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown")


# ======================================================================
#  /recipe {name}  -- get a full detailed recipe
# ======================================================================

@router.message(F.text.startswith("/recipe"))
async def cmd_recipe(message: Message):
    """Fetch a complete, detailed recipe from Gemini."""
    user_id = message.from_user.id

    recipe_name = message.text.strip().removeprefix("/recipe").strip()
    if not recipe_name:
        await message.answer(
            "Usage: /recipe <dish name>\n\nExample: /recipe Pad Thai"
        )
        return

    ingredients, seasonings = await db.get_ingredients_as_lists(user_id)
    prefs = await db.get_preferences(user_id)

    thinking_msg = await message.answer(
        f"Looking up the recipe for *{recipe_name}*...", parse_mode="Markdown"
    )

    try:
        recipe = await gemini.get_full_recipe(
            recipe_name=recipe_name,
            ingredients=ingredients if ingredients else None,
            seasonings=seasonings if seasonings else None,
            dietary_restrictions=prefs.get("dietary_restrictions") or None,
            skill_level=prefs.get("skill_level", "beginner"),
            servings=prefs.get("serving_size", 2),
        )
    except Exception as exc:
        logger.error("Gemini get_full_recipe failed for user %s: %s", user_id, exc)
        try:
            await thinking_msg.edit_text(
                "Couldn't fetch the recipe. Please try again in a moment."
            )
        except TelegramBadRequest:
            await message.answer(
                "Couldn't fetch the recipe. Please try again in a moment."
            )
        return

    if not recipe:
        try:
            await thinking_msg.edit_text(
                f"Sorry, I couldn't find a recipe for *{recipe_name}*.\n"
                "Try a different dish name or use /suggest for ideas based "
                "on your ingredients.",
                parse_mode="Markdown",
            )
        except TelegramBadRequest:
            await message.answer(
                f"Sorry, I couldn't find a recipe for *{recipe_name}*.",
                parse_mode="Markdown",
            )
        return

    text = format_full_recipe(recipe.model_dump())
    text = truncate_text(text)

    try:
        await thinking_msg.edit_text(text, parse_mode="Markdown")
    except TelegramBadRequest:
        await thinking_msg.delete()
        plain = text.replace("*", "").replace("_", "")
        for i in range(0, len(plain), MAX_MESSAGE_LENGTH):
            chunk = plain[i:i + MAX_MESSAGE_LENGTH]
            await message.answer(chunk)


# ======================================================================
#  Callback: show_rating  -- list recent meals for rating
# ======================================================================

@router.callback_query(F.data == "show_rating")
async def cb_show_rating(callback: CallbackQuery):
    """Show recent meals so the user can pick one to rate."""
    await callback.answer()

    user_id = callback.from_user.id
    recent = await db.get_recent_meals(user_id, limit=10)

    unrated = [m for m in recent if m.get("rating") is None]

    if not unrated:
        try:
            await callback.message.edit_text(
                "All your recent meals are already rated! Thanks for "
                "the feedback.\n\nUse /suggest for more meal ideas.",
                parse_mode="Markdown",
            )
        except TelegramBadRequest:
            await callback.message.delete()
            await callback.message.answer(
                "All your recent meals are already rated! Thanks for "
                "the feedback.",
                parse_mode="Markdown",
            )
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    buttons = []
    for meal in unrated[:8]:
        name = meal.get("recipe_name", "Unknown")
        meal_id = meal["id"]
        buttons.append([InlineKeyboardButton(
            text=f"\u2b50 {name}",
            callback_data=f"rate_prompt:{meal_id}",
        )])

    buttons.append([InlineKeyboardButton(
        text="Back", callback_data="close"
    )])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    text = "Which meal would you like to rate?\n\nPick from your recent cooks:"
    try:
        await callback.message.edit_text(
            text, parse_mode="Markdown", reply_markup=keyboard
        )
    except TelegramBadRequest:
        await callback.message.delete()
        await callback.message.answer(
            text, parse_mode="Markdown", reply_markup=keyboard
        )


# ======================================================================
#  Callback: rate_prompt:{meal_id}  -- show rating stars for a meal
# ======================================================================

@router.callback_query(F.data.startswith("rate_prompt:"))
async def cb_rate_prompt(callback: CallbackQuery):
    """Show the 1-5 star rating keyboard for a specific meal."""
    await callback.answer()

    meal_id = int(callback.data.split(":")[1])
    keyboard = rating_keyboard(meal_id)

    text = "How was this meal? Tap a rating:"
    try:
        await callback.message.edit_text(
            text, parse_mode="Markdown", reply_markup=keyboard
        )
    except TelegramBadRequest:
        await callback.message.delete()
        await callback.message.answer(
            text, parse_mode="Markdown", reply_markup=keyboard
        )


# ======================================================================
#  Callback: back_to_list  -- return to the suggestions list
# ======================================================================

@router.callback_query(F.data == "back_to_list")
async def cb_back_to_list(callback: CallbackQuery, state: FSMContext):
    """Resend the meal suggestions list from FSM state."""
    await callback.answer()

    data = await state.get_data()
    suggestions: list[dict] = data.get("suggestions", [])
    current_offset: int = data.get("current_offset", 0)

    if not suggestions:
        try:
            await callback.message.edit_text(
                "No suggestions cached. Use /suggest to get fresh ideas!",
                parse_mode="Markdown",
            )
        except TelegramBadRequest:
            await callback.message.delete()
            await callback.message.answer(
                "No suggestions cached. Use /suggest to get fresh ideas!",
                parse_mode="Markdown",
            )
        return

    start = current_offset
    end = min(start + BATCH_SIZE, len(suggestions))
    batch = suggestions[start:end]

    text = _build_suggestions_list_text(batch, start)
    keyboard = meal_suggestion_keyboard(batch, offset=start)

    try:
        await callback.message.edit_text(
            truncate_text(text),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except TelegramBadRequest:
        await callback.message.delete()
        await callback.message.answer(
            truncate_text(text), parse_mode="Markdown", reply_markup=keyboard
        )


# ======================================================================
#  Helpers
# ======================================================================

def _build_suggestions_list_text(suggestions: list[dict], offset: int = 0) -> str:
    """Build a combined text preview for a batch of meal suggestions."""
    from data.cuisines import CUISINE_EMOJIS

    lines = ["Meal Suggestions\n"]
    for i, sug in enumerate(suggestions):
        idx = offset + i
        cuisine = sug.get("cuisine", "").lower()
        emoji = CUISINE_EMOJIS.get(cuisine, "")
        match_pct = sug.get("match_percentage", 0)
        match_icon = "OK" if match_pct >= 90 else ("~" if match_pct >= 70 else "!")
        diff = sug.get("difficulty", 3)
        time = sug.get("cook_time_minutes", "?")

        lines.append(
            f"{idx + 1}. {emoji} *{sug.get('name', 'Unknown')}* -- "
            f"{match_icon} {match_pct}% match | {time} min | "
            f"{'*' * diff}"
        )

        ingredients = sug.get("ingredients", [])
        have = [ing["name"] for ing in ingredients if ing.get("have")]
        missing = [ing["name"] for ing in ingredients if not ing.get("have")]
        if have or missing:
            parts = []
            if have:
                parts.append(f"{len(have)} on hand")
            if missing:
                parts.append(f"{len(missing)} needed")
            lines.append(f"   {' | '.join(parts)}")

        lines.append("")

    lines.append("Tap a meal to see full details")
    return "\n".join(lines)
