from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from data.cuisines import CATEGORIES, CUISINE_EMOJIS


def category_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard for ingredient category selection."""
    buttons = []
    row = []
    for cat_key, cat_label in CATEGORIES.items():
        row.append(InlineKeyboardButton(
            text=cat_label, callback_data=f"cat:{cat_key}"
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def unit_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard for unit selection."""
    units = [
        [("g", "unit:g"), ("kg", "unit:kg"), ("ml", "unit:ml"), ("L", "unit:L")],
        [("pcs", "unit:pcs"), ("cups", "unit:cups"), ("tbsp", "unit:tbsp"), ("tsp", "unit:tsp")],
        [("lb", "unit:lb"), ("oz", "unit:oz"), ("bunches", "unit:bunches"), ("whole", "unit:whole")],
        [("❌ Cancel", "cancel")],
    ]
    buttons = [[InlineKeyboardButton(text=u, callback_data=d) for u, d in row] for row in units]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cuisine_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard for cuisine preference selection."""
    buttons = []
    row = []
    for cuisine, emoji in list(CUISINE_EMOJIS.items())[:20]:
        label = f"{emoji} {cuisine.title()}"
        row.append(InlineKeyboardButton(text=label, callback_data=f"cuisine_pref:{cuisine}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✅ Done selecting", callback_data="cuisine_pref:done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def dietary_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard for dietary restriction selection."""
    restrictions = [
        "vegetarian", "vegan", "pescatarian", "halal", "kosher",
        "gluten-free", "dairy-free", "nut-free", "low-carb", "keto",
        "none"
    ]
    buttons = []
    row = []
    for r in restrictions:
        label = r.replace("-", " ").title()
        row.append(InlineKeyboardButton(text=label, callback_data=f"diet:{r}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✅ Done", callback_data="diet:done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def meal_suggestion_keyboard(suggestions: list[dict], offset: int = 0) -> InlineKeyboardMarkup:
    """Build inline keyboard for meal suggestions."""
    buttons = []
    for i, sug in enumerate(suggestions):
        idx = offset + i
        match_pct = sug.get("match_percentage", 0)
        cuisine = sug.get("cuisine", "")
        emoji = CUISINE_EMOJIS.get(cuisine.lower(), "🍽️")
        label = f"{emoji} {sug['name']} ({match_pct}%)"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"recipe_select:{idx}"
        )])

    buttons.append([
        InlineKeyboardButton(text="🔄 More Suggestions", callback_data="suggest_more"),
        InlineKeyboardButton(text="❌ Close", callback_data="close"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def recipe_action_keyboard(recipe_idx: int = 0, meal_id: int = None) -> InlineKeyboardMarkup:
    """Build inline keyboard for recipe actions."""
    buttons = []
    if meal_id:
        buttons.append([InlineKeyboardButton(
            text="⭐ Toggle Favorite", callback_data=f"toggle_fav:{meal_id}"
        )])
        buttons.append([InlineKeyboardButton(
            text="⭐ Rate 1-5",
            callback_data="show_rating"
        )])
    buttons.append([
        InlineKeyboardButton(text="✅ I Cooked This!", callback_data=f"cooked:{recipe_idx}"),
        InlineKeyboardButton(text="🔄 Another Suggestion", callback_data="suggest_more"),
    ])
    buttons.append([InlineKeyboardButton(text="🔙 Back to List", callback_data="back_to_list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def rating_keyboard(meal_id: int) -> InlineKeyboardMarkup:
    """Build inline keyboard for rating a meal."""
    buttons = [[
        InlineKeyboardButton(text=f"{'⭐' * i}", callback_data=f"rate:{meal_id}:{i}")
        for i in range(1, 6)
    ]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """Build a yes/no confirmation keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes", callback_data=f"confirm:{action}"),
            InlineKeyboardButton(text="❌ No", callback_data="cancel"),
        ]
    ])


def ingredient_remove_keyboard(ingredients: list[dict]) -> InlineKeyboardMarkup:
    """Build keyboard for selecting ingredient to remove."""
    buttons = []
    row = []
    for ing in ingredients[:20]:
        label = f"{ing['name']} ({ing['quantity']} {ing['unit']})"
        row.append(InlineKeyboardButton(text=label, callback_data=f"remove_ing:{ing['id']}"))
        if len(row) == 1:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def expiry_keyboard(expiring: list[dict]) -> InlineKeyboardMarkup:
    """Build keyboard for expiring ingredients."""
    buttons = []
    for ing in expiring:
        label = f"{ing['name']} — {ing['expiry_date']}"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"expiry_recipe:{ing['name']}"
        )])
    if buttons:
        buttons.append([InlineKeyboardButton(text="❌ Close", callback_data="close")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
