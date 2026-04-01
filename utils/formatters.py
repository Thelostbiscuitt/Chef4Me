import re
import json
from pathlib import Path

ALIASES_PATH = Path(__file__).parent.parent / "data" / "ingredient_aliases.json"

# Load aliases lazily
_aliases_cache: dict[str, str] = {}


def _load_aliases() -> dict[str, str]:
    global _aliases_cache
    if not _aliases_cache and ALIASES_PATH.exists():
        with open(ALIASES_PATH) as f:
            _aliases_cache = json.load(f)
    return _aliases_cache


def normalize_name(name: str) -> str:
    """Normalize an ingredient name to a canonical form."""
    name = name.strip().lower()
    aliases = _load_aliases()
    return aliases.get(name, name)


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)


def escape_markdown_v1(text: str) -> str:
    """Escape special characters for Telegram Markdown (v1)."""
    return text.replace("*", "").replace("_", "").replace("`", "").replace("[", "").replace("]", "")


def format_ingredient_list(ingredients: list[dict], compact: bool = False) -> str:
    """Format a list of ingredient dicts into a readable Telegram message."""
    if not ingredients:
        return "Your inventory is empty. Use /add to add ingredients!"

    # Group by category
    from data.cuisines import CATEGORIES
    grouped: dict[str, list[dict]] = {}
    for ing in ingredients:
        cat = ing.get("category", "other")
        grouped.setdefault(cat, []).append(ing)

    if compact:
        lines = []
        for cat, items in grouped.items():
            cat_label = CATEGORIES.get(cat, cat)
            items_text = ", ".join(f"{i['name']} ({i['quantity']} {i['unit']})" for i in items)
            lines.append(f"{cat_label}: {items_text}")
        return "\n".join(lines)

    lines = ["📋 *Your Inventory*\n"]
    for cat, items in grouped.items():
        cat_label = CATEGORIES.get(cat, cat)
        lines.append(f"\n{cat_label}")
        lines.append("─" * 20)
        for ing in items:
            expiry_info = ""
            if ing.get("expiry_date"):
                expiry_info = f" | Expires: {ing['expiry_date']}"
            lines.append(
                f"  • {ing['name']} — {ing['quantity']} {ing['unit']}{expiry_info}"
            )

    lines.append(f"\n📊 Total: {len(ingredients)} items")
    return "\n".join(lines)


def format_meal_suggestion(suggestion: dict, index: int) -> str:
    """Format a single meal suggestion for Telegram."""
    from data.cuisines import CUISINE_EMOJIS

    cuisine = suggestion.get("cuisine", "").lower()
    emoji = CUISINE_EMOJIS.get(cuisine, "🍽️")

    difficulty_stars = "⭐" * suggestion.get("difficulty", 3)
    match_pct = suggestion.get("match_percentage", 0)
    match_emoji = "🟢" if match_pct >= 90 else ("🟡" if match_pct >= 70 else "🟠")

    lines = [
        f"{emoji} *{suggestion['name']}*",
        f"🌍 Cuisine: {suggestion.get('cuisine', 'International').title()}",
        f"⏱ {suggestion.get('cook_time_minutes', '?')} min | {difficulty_stars} | {match_emoji} {match_pct}% match",
        f"",
        f"{suggestion.get('description', '')}",
    ]

    # Ingredients list
    ingredients = suggestion.get("ingredients", [])
    if ingredients:
        have_items = [i["name"] for i in ingredients if i.get("have")]
        missing_items = [i["name"] for i in ingredients if not i.get("have")]
        if have_items:
            lines.append(f"\n✅ You have: {', '.join(have_items)}")
        if missing_items:
            lines.append(f"\n🛒 Need: {', '.join(missing_items)}")

    if suggestion.get("calories_per_serving"):
        lines.append(f"\n🔥 ~{suggestion['calories_per_serving']} cal/serving")

    return "\n".join(lines)


def format_full_recipe(recipe: dict) -> str:
    """Format a complete recipe for Telegram."""
    from data.cuisines import CUISINE_EMOJIS

    cuisine = recipe.get("cuisine", "").lower()
    emoji = CUISINE_EMOJIS.get(cuisine, "🍽️")

    lines = [
        f"{emoji} *{recipe['name']}*",
        f"🌍 {recipe.get('cuisine', 'International').title()} Cuisine",
        f"⏱ Cook: {recipe.get('cook_time_minutes', '?')} min",
    ]

    if recipe.get("prep_time_minutes"):
        lines.append(f"🔪 Prep: {recipe['prep_time_minutes']} min")
    if recipe.get("servings"):
        lines.append(f"👥 Servings: {recipe['servings']}")

    difficulty = recipe.get("difficulty", 3)
    diff_labels = {1: "Beginner", 2: "Easy", 3: "Medium", 4: "Advanced", 5: "Expert"}
    lines.append(f"📊 Difficulty: {diff_labels.get(difficulty, 'Medium')} ({'⭐' * difficulty})")

    lines.append(f"\n📝 *Description*")
    lines.append(recipe.get("description", ""))

    # Ingredients
    ingredients = recipe.get("ingredients", [])
    if ingredients:
        lines.append(f"\n🧾 *Ingredients*")
        for ing in ingredients:
            status = "✅" if ing.get("have") else "🛒"
            lines.append(f"  {status} {ing['name']}")

    # Steps
    steps = recipe.get("steps", [])
    if steps:
        lines.append(f"\n👨‍🍳 *Instructions*")
        for i, step in enumerate(steps, 1):
            lines.append(f"  *{i}.* {step}")

    # Tips
    tips = recipe.get("tips", [])
    if tips:
        lines.append(f"\n💡 *Tips*")
        for tip in tips:
            lines.append(f"  • {tip}")

    if recipe.get("calories_per_serving"):
        lines.append(f"\n🔥 ~{recipe['calories_per_serving']} calories per serving")

    return "\n".join(lines)


def format_history(meals: list[dict]) -> str:
    """Format cooking history for Telegram."""
    if not meals:
        return "📭 No meals cooked yet. Use /suggest to find something to make!"

    lines = ["📅 *Cooking History*\n"]
    for meal in meals[:10]:
        date_str = meal.get("cooked_at", "")[:10]
        cuisine = meal.get("cuisine", "")
        from data.cuisines import CUISINE_EMOJIS
        emoji = CUISINE_EMOJIS.get(cuisine.lower(), "🍽️")
        fav = "⭐" if meal.get("is_favorite") else ""
        rating = f" ({'⭐' * meal['rating']})" if meal.get("rating") else ""
        lines.append(
            f"{emoji} *{meal['recipe_name']}* — {cuisine.title() if cuisine else 'International'}{rating} {fav}"
        )
        lines.append(f"   📅 {date_str}")

    return "\n".join(lines)


def format_favorites(meals: list[dict]) -> str:
    """Format favorite meals for Telegram."""
    if not meals:
        return "⭐ No favorite meals yet! Rate a meal with /rate after cooking."

    lines = ["⭐ *Favorite Recipes*\n"]
    for meal in meals[:15]:
        cuisine = meal.get("cuisine", "")
        from data.cuisines import CUISINE_EMOJIS
        emoji = CUISINE_EMOJIS.get(cuisine.lower(), "🍽️")
        lines.append(f"{emoji} *{meal['recipe_name']}* — {cuisine.title() if cuisine else 'International'}")

    return "\n".join(lines)


def truncate_text(text: str, max_length: int = 4096) -> str:
    """Truncate text to fit within Telegram's message limit."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 50] + "\n\n... (message truncated, use /recipe for full details)"
