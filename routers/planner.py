"""Planner router -- handles /preferences, /history, /favorites, /shopping, /cook, /clear, /rate."""
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from fsm.add_ingredient import SetPreferencesStates
from fsm.set_preferences import SetPreferencesFSM
from services.database import DatabaseService
from services.gemini import GeminiService
from services.notion_client import NotionService
from utils.formatters import format_history, format_favorites, format_ingredient_list
from utils.keyboards import dietary_keyboard, cuisine_keyboard, rating_keyboard, confirm_keyboard

logger = logging.getLogger(__name__)

router = Router()

# -- Service references (set during bot startup) --
db: DatabaseService | None = None
gemini: GeminiService | None = None
notion_svc: NotionService | None = None


def init_services(database: DatabaseService, gemini_service: GeminiService,
                  notion_service: NotionService | None = None):
    """Wire service singletons into this router's module-level references."""
    global db, gemini, notion_svc
    db = database
    gemini = gemini_service
    notion_svc = notion_service


# ======================================================================
#  /preferences
# ======================================================================

@router.message(F.text == "/preferences")
async def cmd_preferences(message: Message):
    """Show current preferences and a menu to change them."""
    user_id = message.from_user.id
    prefs = await db.get_preferences(user_id)

    dietary = ", ".join(prefs.get("dietary_restrictions", [])) or "None"
    cuisines = ", ".join(prefs.get("preferred_cuisines", [])) or "None"
    skill = prefs.get("skill_level", "beginner").title()
    servings = prefs.get("serving_size", 2)
    notif = "On" if prefs.get("notifications_enabled", True) else "Off"

    text = (
        "Your Preferences\n\n"
        f"Dietary: {dietary}\n"
        f"Cuisines: {cuisines}\n"
        f"Skill Level: {skill}\n"
        f"Serving Size: {servings}\n"
        f"Notifications: {notif}"
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Dietary Restrictions", callback_data="pref:dietary")],
        [InlineKeyboardButton(text="Preferred Cuisines", callback_data="pref:cuisine")],
        [InlineKeyboardButton(text="Skill Level", callback_data="pref:skill")],
        [InlineKeyboardButton(text="Serving Size", callback_data="pref:serving")],
        [InlineKeyboardButton(text="Toggle Notifications", callback_data="pref:notifications")],
        [InlineKeyboardButton(text="Cancel", callback_data="cancel")],
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "pref:dietary")
async def pref_dietary_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    prefs = await db.get_preferences(user_id)
    current = prefs.get("dietary_restrictions", [])
    await state.set_state(SetPreferencesStates.waiting_for_dietary)
    await state.update_data(dietary_selections=current)

    text = "Select your dietary restrictions\nTap to toggle. Tap Done when finished."
    if current:
        text += f"\n\nCurrently selected: {', '.join(current)}"
    await callback.message.edit_text(
        text, reply_markup=dietary_keyboard(), parse_mode="Markdown"
    )


@router.callback_query(
    SetPreferencesStates.waiting_for_dietary,
    F.data.startswith("diet:"),
)
async def pref_dietary_toggle(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(":", 1)[1]

    if value == "done":
        data = await state.get_data()
        selections = data.get("dietary_selections", [])
        user_id = callback.from_user.id
        await db.update_preferences(user_id, dietary_restrictions=selections)
        await state.clear()
        await callback.answer()
        await callback.message.edit_text(
            f"Dietary restrictions saved: "
            f"{', '.join(selections) or 'None'}"
        )
        return

    await callback.answer()
    data = await state.get_data()
    selections: list = data.get("dietary_selections", [])

    if value in selections:
        selections.remove(value)
    else:
        selections.append(value)

    await state.update_data(dietary_selections=selections)

    text = "Select your dietary restrictions\nTap to toggle. Tap Done when finished."
    if selections:
        text += f"\n\nCurrently selected: {', '.join(selections)}"
    await callback.message.edit_text(
        text, reply_markup=dietary_keyboard(), parse_mode="Markdown"
    )


@router.callback_query(F.data == "pref:cuisine")
async def pref_cuisine_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    prefs = await db.get_preferences(user_id)
    current = prefs.get("preferred_cuisines", [])
    await state.set_state(SetPreferencesStates.waiting_for_cuisine_prefs)
    await state.update_data(cuisine_selections=current)

    text = "Select your preferred cuisines\nTap to toggle. Tap Done selecting when finished."
    if current:
        text += f"\n\nCurrently selected: {', '.join(current)}"
    await callback.message.edit_text(
        text, reply_markup=cuisine_keyboard(), parse_mode="Markdown"
    )


@router.callback_query(
    SetPreferencesStates.waiting_for_cuisine_prefs,
    F.data.startswith("cuisine_pref:"),
)
async def pref_cuisine_toggle(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(":", 1)[1]

    if value == "done":
        data = await state.get_data()
        selections = data.get("cuisine_selections", [])
        user_id = callback.from_user.id
        await db.update_preferences(user_id, preferred_cuisines=selections)
        await state.clear()
        await callback.answer()
        await callback.message.edit_text(
            f"Cuisine preferences saved: "
            f"{', '.join(s.title() for s in selections) or 'None'}"
        )
        return

    await callback.answer()
    data = await state.get_data()
    selections: list = data.get("cuisine_selections", [])

    if value in selections:
        selections.remove(value)
    else:
        selections.append(value)

    await state.update_data(cuisine_selections=selections)

    text = "Select your preferred cuisines\nTap to toggle. Tap Done selecting when finished."
    if selections:
        text += f"\n\nCurrently selected: {', '.join(s.title() for s in selections)}"
    await callback.message.edit_text(
        text, reply_markup=cuisine_keyboard(), parse_mode="Markdown"
    )


@router.callback_query(F.data == "pref:skill")
async def pref_skill_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SetPreferencesStates.waiting_for_skill_level)
    await callback.message.edit_text(
        "Select your cooking skill level:",
        reply_markup=SetPreferencesFSM.skill_keyboard(),
        parse_mode="Markdown",
    )


@router.callback_query(
    SetPreferencesStates.waiting_for_skill_level,
    F.data.startswith("skill:"),
)
async def pref_skill_save(callback: CallbackQuery, state: FSMContext):
    skill = callback.data.split(":", 1)[1]
    await callback.answer()
    user_id = callback.from_user.id
    await db.update_preferences(user_id, skill_level=skill)
    await state.clear()
    await callback.message.edit_text(
        f"Skill level set to *{skill.title()}*", parse_mode="Markdown"
    )


@router.callback_query(F.data == "pref:serving")
async def pref_serving_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SetPreferencesStates.waiting_for_serving_size)
    await callback.message.edit_text(
        "How many people do you typically cook for?\n\n"
        "Send a number (1-20):",
        parse_mode="Markdown",
    )


@router.message(SetPreferencesStates.waiting_for_serving_size)
async def pref_serving_save(message: Message, state: FSMContext):
    raw = message.text.strip()
    try:
        servings = int(raw)
        if not 1 <= servings <= 20:
            raise ValueError
    except ValueError:
        await message.answer("Please enter a whole number between 1 and 20.")
        return

    user_id = message.from_user.id
    await db.update_preferences(user_id, serving_size=servings)
    await state.clear()
    await message.answer(
        f"Serving size set to *{servings}*", parse_mode="Markdown"
    )


@router.callback_query(F.data == "pref:notifications")
async def pref_toggle_notifications(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    prefs = await db.get_preferences(user_id)
    current = prefs.get("notifications_enabled", True)
    new_val = not current
    await db.update_preferences(user_id, notifications_enabled=new_val)

    status = "On" if new_val else "Off"
    await callback.message.edit_text(
        f"Notifications are now *{status}*", parse_mode="Markdown"
    )


# ======================================================================
#  /history
# ======================================================================

@router.message(F.text == "/history")
async def cmd_history(message: Message):
    user_id = message.from_user.id
    meals = await db.get_recent_meals(user_id, limit=10)
    text = format_history(meals)
    await message.answer(text, parse_mode="Markdown")


# ======================================================================
#  /favorites
# ======================================================================

@router.message(F.text == "/favorites")
async def cmd_favorites(message: Message):
    user_id = message.from_user.id
    favs = await db.get_favorites(user_id)

    if not favs:
        await message.answer(
            "No favorite meals yet!\n\n"
            "Rate a meal with 4+ stars after cooking to auto-add "
            "it to your favourites.",
            parse_mode="Markdown",
        )
        return

    text = format_favorites(favs)
    await message.answer(text, parse_mode="Markdown")


# ======================================================================
#  /shopping
# ======================================================================

@router.message(F.text == "/shopping")
async def cmd_shopping(message: Message):
    user_id = message.from_user.id
    ingredients = await db.get_ingredients(user_id)

    if not ingredients:
        await message.answer(
            "Your inventory is empty -- so everything is on the "
            "shopping list!\n\nUse /add to start tracking what you "
            "have at home.",
            parse_mode="Markdown",
        )
        return

    inventory_text = format_ingredient_list(ingredients, compact=True)

    prefs = await db.get_preferences(user_id)
    dietary = ", ".join(prefs.get("dietary_restrictions", [])) or "None"
    servings = prefs.get("serving_size", 2)

    prompt = (
        "Based on the user's current inventory, suggest a concise "
        "shopping list of missing staple / pantry items that would "
        "help them cook balanced meals for a week.\n\n"
        f"User dietary restrictions: {dietary}\n"
        f"Servings: {servings}\n"
        f"Current inventory:\n{inventory_text}\n\n"
        "Return a JSON object with a single key 'shopping_list' "
        "containing an array of objects with 'name' and 'reason' "
        "fields. Maximum 15 items."
    )

    try:
        result = await gemini._generate(prompt, response_schema={
            "type": "object",
            "properties": {
                "shopping_list": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["name", "reason"],
                    },
                }
            },
            "required": ["shopping_list"],
        })

        items = result.get("shopping_list", [])
        if items:
            lines = ["Suggested Shopping List\n"]
            for item in items:
                lines.append(f"  - {item['name']} -- _{item['reason']}_")
            lines.append(
                f"\nYour current inventory has {len(ingredients)} items."
            )
            text = "\n".join(lines)
        else:
            text = (
                "Your inventory looks well-stocked -- nothing essential "
                "to add!"
            )
    except Exception as exc:
        logger.warning("Shopping-list generation failed: %s", exc)
        text = (
            f"Your Inventory\n\n{inventory_text}\n\n"
            "Could not generate shopping suggestions right now. "
            "Use /add to add items manually."
        )

    await message.answer(text, parse_mode="Markdown")


# ======================================================================
#  /cook {recipe_name}
# ======================================================================

@router.message(F.text.startswith("/cook"))
async def cmd_cook(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "Quick Cook\n\n"
            "Usage: `/cook <recipe name>`\n\n"
            "Example: `/cook Pasta Carbonara`\n\n"
            "Optionally include cuisine: `/cook Pasta Carbonara italian`",
            parse_mode="Markdown",
        )
        return

    raw = parts[1].strip()

    from data.cuisines import CUISINE_EMOJIS
    words = raw.split()
    cuisine = "International"
    recipe_name = raw

    if len(words) >= 2:
        candidate = words[-1].lower()
        if candidate in CUISINE_EMOJIS:
            cuisine = candidate
            recipe_name = " ".join(words[:-1])

    user_id = message.from_user.id
    meal_id = await db.add_cooked_meal(user_id, recipe_name, cuisine=cuisine)

    emoji = CUISINE_EMOJIS.get(cuisine.lower(), "")
    await message.answer(
        f"{emoji} *{recipe_name}* added to your cooking history!\n\n"
        f"Cuisine: {cuisine.title()}\n"
        f"Meal ID: {meal_id}\n\n"
        f"Rate it: `/rate {meal_id} <1-5>`",
        parse_mode="Markdown",
    )


# ======================================================================
#  /clear
# ======================================================================

@router.message(F.text == "/clear")
async def cmd_clear(message: Message):
    user_id = message.from_user.id
    count = await db.get_ingredient_count(user_id)

    if count == 0:
        await message.answer("Your inventory is already empty!")
        return

    await message.answer(
        f"Are you sure you want to clear your entire inventory?\n\n"
        f"You currently have *{count}* "
        f"item{'s' if count != 1 else ''}.",
        reply_markup=confirm_keyboard("clear_inventory"),
        parse_mode="Markdown",
    )


@router.callback_query(F.data == "confirm:clear_inventory")
async def confirm_clear_inventory(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    removed = await db.clear_inventory(user_id)

    await callback.message.edit_text(
        f"Inventory cleared! Removed *{removed}* "
        f"item{'s' if removed != 1 else ''}.\n\n"
        "Use /add to start adding ingredients again.",
        parse_mode="Markdown",
    )


# ======================================================================
#  /rate {meal_id} {rating}
# ======================================================================

@router.message(F.text.startswith("/rate"))
async def cmd_rate(message: Message):
    parts = message.text.split()
    user_id = message.from_user.id

    if len(parts) >= 3:
        try:
            meal_id = int(parts[1])
            rating = int(parts[2])
            if not 1 <= rating <= 5:
                raise ValueError
        except ValueError:
            await message.answer(
                "Usage: `/rate <meal_id> <1-5>`\n\n"
                "Example: `/rate 5 4`\n\n"
                "Or just type `/rate` to see recent meals you can rate.",
                parse_mode="Markdown",
            )
            return

        await db.rate_meal(user_id, meal_id, rating)

        if rating >= 4:
            await db.toggle_favorite(user_id, meal_id)

        stars = "\u2b50" * rating
        fav_msg = "Automatically added to favourites!\n" if rating >= 4 else ""
        await message.answer(
            f"{stars} Rated meal #{meal_id} with *{rating}/5*!\n"
            f"{fav_msg}"
            "Use /favorites to see your collection.",
            parse_mode="Markdown",
        )
        return

    meals = await db.get_recent_meals(user_id, limit=10)
    unrated = [m for m in meals if m.get("rating") is None]

    if not unrated:
        await message.answer(
            "No unrated meals found. Cook something with /suggest "
            "or /cook, then rate it!"
        )
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    for meal in unrated[:8]:
        label = f"{meal['recipe_name']} (#{meal['id']})"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"show_rating:{meal['id']}",
        )])
    buttons.append([InlineKeyboardButton(
        text="Cancel", callback_data="cancel"
    )])

    await message.answer(
        "Select a meal to rate:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("show_rating:"))
async def show_rating_keyboard(callback: CallbackQuery):
    await callback.answer()
    meal_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        "How would you rate this meal?",
        reply_markup=rating_keyboard(meal_id),
    )

# NOTE: The "rate:{meal_id}:{rating}" callback is handled by
# suggest.py's cb_rate handler (registered first), which includes
# auto-favourite logic. No duplicate handler needed here.


# ======================================================================
#  Generic cancel handler
# ======================================================================

@router.callback_query(F.data == "cancel", SetPreferencesStates)
async def cancel_preferences_flow(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Cancelled")
    await state.clear()
    await callback.message.edit_text(
        "Preference update cancelled.\n\nUse /preferences to start again."
    )
