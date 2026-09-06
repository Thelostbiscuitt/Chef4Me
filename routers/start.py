from aiogram import Router, F
from aiogram.types import Message

import state as app_state
import services.subscriptions as subs

router = Router()

HELP_TEXT = """\
📋 <b>Available Commands</b>

🥕 <b>Inventory Management</b>
/add — Add an ingredient (interactive flow)
/add chicken, rice, eggs — Add a whole list at once (AI-parsed)
/add bulk — Bulk-add mode: send a sentence or list, however you like
/addbulk — Same as /add bulk (paste your shopping list straight in)
📸 Send a photo of a receipt, shopping list or fridge — I'll extract the items
/remove — Remove an ingredient from inventory
/inventory — View your current ingredients
/clear — Clear all ingredients

⏰ <b>Expiry Tracking</b>
/expiry — Show ingredients expiring soon
💡 Expiry accepts natural dates: <i>tomorrow</i>, <i>in 3 days</i>, <i>next week</i>, or DD/MM

🍽️ <b>Meal Suggestions</b>
/suggest — Get AI-powered meal suggestions
/suggest [cuisine] — Filter suggestions by cuisine
/recipe [name] — Get a full recipe with instructions
/cook [name] — Mark a meal as cooked

⚙️ <b>Preferences & History</b>
/preferences — Set dietary preferences & allergens
/history — View your cooking history
/favorites — View your saved favorite recipes

🛒 <b>Shopping &amp; Sync</b>
/shopping — Generate a shopping list
🗓️ /plan — Weekly meal planner (Pro)
🍳 /leftover — Recipes for leftovers (Pro)
🔄 /substitute — Ingredient swaps (Pro)
🎙️ Send a voice note — hands-free add (Pro)

💎 <b>Subscription</b>
/subscribe — Upgrade to Pro (Stars payments)
/pricing — Plans &amp; prices
/mypass — View your plan
/notion sync — Sync your data to Notion (Pro)

💡 <b>Tips</b>
• Use /suggest Italian for cuisine-specific ideas
• Set your dietary prefs to get personalized results
• Add expiry dates when adding ingredients for alerts
"""

WHATS_NEW = """🆕 <b>What's new in Chef4Me</b>

🗓️ <b>Weekly Meal Planner</b> — /plan builds a 3–7 day meal plan from your pantry, with a smart shopping list.
🛒 <b>Smart Shopping Lists</b> — AI-organized by supermarket aisle.
⏰ <b>Smart Expiry Alerts</b> — Pro alerts suggest what to cook tonight.
🥗 <b>Nutrition</b> — calories &amp; macros on every recipe.
👥 <b>Recipe scaling</b> — 1x to 4x with one tap.
🍳 <b>/leftover</b> &amp; <b>/substitute</b> — rescue leftovers, swap missing ingredients.
🎙️ <b>Voice adds</b> — just say what you bought.
🎟️ <b>Lifetime passes</b> — /redeem a code for free Pro.

Your plan: /mypass • Upgrade: /subscribe
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

    # Start the 7-day Pro trial for brand-new users
    tier = await subs.start_trial(app_state.db, message.from_user.id)

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

    if tier == "trial":
        welcome += (
            "\n\n🎁 <b>You're on a 7-day Pro trial!</b>\n"
            "Weekly meal plans, unlimited recipes, nutrition — try /plan. "
            "When it ends you keep everything on the free tier."
        )
    elif tier == "lifetime":
        welcome += "\n\n🎟️ <b>Lifetime Pro pass active</b> — enjoy every feature!"

    await message.answer(welcome, parse_mode="HTML")


@router.message(F.text == "/whatsnew")
async def cmd_whatsnew(message: Message):
    await message.answer(WHATS_NEW, parse_mode="HTML")


@router.message(F.text == "/help")
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")
