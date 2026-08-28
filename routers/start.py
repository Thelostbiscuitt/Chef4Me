from aiogram import Router, F
from aiogram.types import Message

import state as app_state

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
async def cmd_start(message: Message, state: FSMContext):
    # Reset any active FSM state
    await state.clear()

    # Register the user in the database
    await app_state.db.register_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    welcome = (
        f"👋 Hey <b>{message.from_user.first_name}</b>!\n\n"
        "I'm <b>Chef4Me</b> — tell me what's in your kitchen, and I'll turn "
        "it into meals from 40+ cuisines.\n\n"
        "🌟 <b>What I do:</b>\n"
        "🥕 Track ingredients &amp; expiry dates — nothing goes to waste\n"
        "🍽️ Suggest meals from what you actually have\n"
        "🛒 Build your shopping list\n\n"
        "👉 <b>Start here:</b> send /add and drop in the first ingredient "
        "you can see. Even one is enough for me to suggest dinner.\n\n"
        "All commands: /help"
    )

    await message.answer(welcome, parse_mode="HTML")


@router.message(F.text == "/help")
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")
