from aiogram import Router, F
from aiogram.types import Message

import state

router = Router()

HELP_TEXT = """\
📋 <b>Available Commands</b>

🥕 <b>Inventory Management</b>
/add — Add an ingredient (interactive flow)
/add bulk — Add multiple ingredients at once
/remove — Remove an ingredient from inventory
/inventory — View your current ingredients
/clear — Clear all ingredients

⏰ <b>Expiry Tracking</b>
/expiry — Show ingredients expiring soon

🍽️ <b>Meal Suggestions</b>
/suggest — Get AI-powered meal suggestions
/suggest [cuisine] — Filter suggestions by cuisine
/recipe [name] — Get a full recipe with instructions
/cook [name] — Mark a meal as cooked

⚙️ <b>Preferences & History</b>
/preferences — Set dietary preferences & allergens
/history — View your cooking history
/favorites — View your saved favorite recipes

🛒 <b>Shopping & Sync</b>
/shopping — Generate a shopping list from meal plan
/notion sync — Sync your data to Notion

💡 <b>Tips</b>
• Use /suggest Italian for cuisine-specific ideas
• Set your dietary prefs to get personalized results
• Add expiry dates when adding ingredients for alerts
"""


from aiogram.fsm.context import FSMContext

@router.message(F.text == "/start")
async def cmd_start(message: Message, fsm_state: FSMContext):
    # Reset any active FSM state
    await fsm_state.clear()

    # Register the user in the database
    await state.db.register_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    welcome = (
        f"👋 Hey <b>{message.from_user.first_name}</b>!\n\n"
        "I'm your <b>AI Meal Planning Assistant</b> — here to help you "
        "turn whatever is in your kitchen into delicious meals from "
        "around the world.\n\n"
        "🌟 <b>What I can do:</b>\n\n"
        "🥕 <b>Inventory Tracking</b>\n"
        "   Add &amp; remove ingredients to keep your\n"
        "   virtual pantry up to date.\n\n"
        "🍽️ <b>AI-Powered Meal Suggestions</b>\n"
        "   Get smart recipe ideas from diverse global\n"
        "   cuisines based on what you already have.\n\n"
        "⏰ <b>Expiry Alerts</b>\n"
        "   Track expiration dates and get timely\n"
        "   reminders so nothing goes to waste.\n\n"
        "⭐ <b>Saved Favorites</b>\n"
        "   Bookmark recipes you love and build\n"
        "   your personal cookbook.\n\n"
        "📊 <b>Notion Sync</b>\n"
        "   Optionally sync everything to a Notion\n"
        "   dashboard for a visual overview.\n\n"
        "Type /help to see all available commands.\n"
        "Let's get cooking! 🚀"
    )

    await message.answer(welcome, parse_mode="HTML")


@router.message(F.text == "/help")
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")
