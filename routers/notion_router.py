import logging
from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.database import DatabaseService
from services.notion_client import NotionService
from utils.keyboards import confirm_keyboard

logger = logging.getLogger(__name__)

# ── Services (set during bot startup) ──

db: Optional[DatabaseService] = None
notion_svc: Optional[NotionService] = None


def init_services(database: DatabaseService, notion: NotionService):
    """Initialize service references. Call once during bot startup."""
    global db, notion_svc
    db = database
    notion_svc = notion


# ── FSM States ──

class NotionSetupStates(StatesGroup):
    waiting_for_notion_token = State()
    waiting_for_ingredients_db_id = State()
    waiting_for_recipes_db_id = State()


# ── Router ──

router = Router()


# ── Helpers ──

def _notion_menu_keyboard() -> list[list]:
    """Inline keyboard for the main /notion command."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f504 Sync Now", callback_data="notion_sync")],
        [InlineKeyboardButton(text="\u2699\ufe0f Setup", callback_data="notion_setup")],
        [InlineKeyboardButton(text="\u2753 Help", callback_data="notion_help")],
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="notion_cancel")],
    ])


def _skip_keyboard() -> list[list]:
    """Keyboard with a Skip button (for optional steps)."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u23ed\ufe0f Skip", callback_data="notion_setup_skip")],
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="notion_cancel")],
    ])


async def _get_user_notion_client(user_id: int) -> Optional[NotionService]:
    """Return a per-user NotionService if the user has a personal token configured."""
    if not db:
        return None
    prefs = await db.get_preferences(user_id)
    token = prefs.get("notion_token")
    if token:
        client = NotionService(token=token)
        await client.connect()
        return client
    return None


async def _effective_notion(user_id: int) -> Optional[NotionService]:
    """Return the global notion_svc if available, otherwise try per-user client."""
    if notion_svc and notion_svc.is_available:
        return notion_svc
    return await _get_user_notion_client(user_id)


# ── /notion command ──

@router.message(Command("notion"))
async def cmd_notion(message: Message):
    if not db:
        await message.answer("Database service is not available. Please try again later.")
        return

    user_id = message.from_user.id
    prefs = await db.get_preferences(user_id)
    has_token = bool(prefs.get("notion_token")) or (notion_svc and notion_svc.is_available)
    has_db = bool(prefs.get("notion_database_id"))

    if has_token:
        status = "\u2705 **Connected**"
        if has_db:
            status += f"\n\u2022 Ingredients DB: `{prefs.get('notion_database_id', '')}`"
    else:
        status = "\u274c **Not connected**"

    text = (
        "\U0001f4d3 *Notion Integration*\n\n"
        f"Status: {status}\n\n"
        "Sync your ingredients and cooked meals to Notion databases "
        "for a full kitchen management experience."
    )
    await message.answer(text, reply_markup=_notion_menu_keyboard(), parse_mode="Markdown")


# ── /notion sync ──

@router.message(Command("notion"), F.args.lower() == "sync")
async def cmd_notion_sync(message: Message):
    """Handle `/notion sync` as a direct command."""
    await _do_sync(message)


@router.message(Command("notion"), F.args.lower() == "setup")
async def cmd_notion_setup(message: Message):
    """Handle `/notion setup` as a direct command."""
    await _start_setup(message)


# ── /notion help ──

@router.message(Command("notion"), F.args.lower() == "help")
async def cmd_notion_help(message: Message):
    text = (
        "\u2753 *Notion Integration Help*\n\n"
        "The Notion integration lets you sync your ingredients and cooked meals "
        "to Notion databases.\n\n"
        "*Setup*\n"
        "1. Create a Notion integration at notion.so/my-integrations\n"
        "2. Share your database with the integration\n"
        "3. Use /notion setup to enter your token and database IDs\n\n"
        "*Commands*\n"
        "\u2022 `/notion` \u2014 View status and options\n"
        "\u2022 `/notion sync` \u2014 Sync ingredients & meals now\n"
        "\u2022 `/notion setup` \u2014 Configure integration\n\n"
        "*Tips*\n"
        "\u2022 You can paste the full database URL; the ID will be extracted automatically.\n"
        "\u2022 The Recipes database is optional; if skipped, only ingredients will sync.\n"
        "\u2022 If the bot-wide Notion token is set, your personal token takes priority."
    )
    await message.answer(text, parse_mode="Markdown")


# ── Callback: Sync ──

@router.callback_query(F.data == "notion_sync")
async def cb_notion_sync(callback: CallbackQuery):
    await callback.answer()
    await _do_sync(callback.message)


async def _do_sync(message: Message):
    """Perform the actual sync of ingredients and recent meals."""
    if not db:
        await message.answer("Database service is not available.")
        return

    user_id = message.from_user.id
    client = await _effective_notion(user_id)

    if not client or not client.is_available:
        await message.answer(
            "\u274c Notion is not configured. Use /notion setup to connect your account."
        )
        return

    prefs = await db.get_preferences(user_id)
    ingredients_db = prefs.get("notion_database_id")
    recipes_db = prefs.get("notion_recipes_db_id")

    status_msg = await message.answer("\U0001f504 Syncing to Notion\u2026")

    # Sync ingredients
    ingredients = await db.get_ingredients(user_id)
    if ingredients:
        ing_ok = await client.sync_ingredients(
            user_id, ingredients, database_id=ingredients_db
        )
        if ing_ok:
            logger.info(f"Synced {len(ingredients)} ingredients for user {user_id}")
        else:
            await status_msg.edit_text(
                "\u26a0\ufe0f Ingredient sync failed. Check that your database ID is correct "
                "and the integration has access to the database."
            )
            return
    else:
        ing_ok = True

    # Sync recent cooked meals
    if recipes_db and client.is_available:
        recent = await db.get_recent_meals(user_id, limit=10)
        synced_meals = 0
        for meal in recent:
            ok = await client.sync_cooked_meal(
                user_id=user_id,
                recipe_name=meal["recipe_name"],
                cuisine=meal.get("cuisine", ""),
                database_id=recipes_db,
            )
            if ok:
                synced_meals += 1

        result = (
            f"\u2705 Sync complete!\n\n"
            f"\u2022 Ingredients: {len(ingredients)} synced"
            f"{' (none in inventory)' if not ingredients else ''}\n"
            f"\u2022 Meals: {synced_meals}/{len(recent)} synced"
        )
    else:
        result = (
            f"\u2705 Sync complete!\n\n"
            f"\u2022 Ingredients: {len(ingredients)} synced"
            f"{' (none in inventory)' if not ingredients else ''}\n"
            f"\u2022 Meals: skipped (no recipes DB configured)"
        )

    await status_msg.edit_text(result)


# ── Callback: Setup ──

@router.callback_query(F.data == "notion_setup")
async def cb_notion_setup(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _start_setup(callback.message, state)


async def _start_setup(message: Message, state: FSMContext = None):
    """Begin the multi-step setup flow."""
    if state:
        await state.clear()

    text = (
        "\u2699\ufe0f *Notion Setup \u2014 Step 1 of 3*\n\n"
        "Please send your **Notion Integration Token**.\n\n"
        "You can find it at: [notion.so/my-integrations](https://notion.so/my-integrations)\n\n"
        "\u26a0\ufe0f The token starts with `ntn_` or `secret_`. Keep it safe!"
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="notion_cancel")]
    ])

    sent = await message.answer(text, reply_markup=cancel_kb, parse_mode="Markdown")
    if state:
        await state.set_state(NotionSetupStates.waiting_for_notion_token)
        await state.update_data(last_setup_message_id=sent.message_id)


# ── Callback: Help ──

@router.callback_query(F.data == "notion_help")
async def cb_notion_help(callback: CallbackQuery):
    await callback.answer()
    await cmd_notion_help(callback.message)


# ── Callback: Cancel ──

@router.callback_query(F.data == "notion_cancel")
async def cb_notion_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Cancelled.")
    await state.clear()
    await callback.message.edit_text(
        "\u274c Notion setup cancelled. Use /notion to try again."
    )


# ── FSM Step 1: Receive Notion Token ──

@router.message(NotionSetupStates.waiting_for_notion_token)
async def step_notion_token(message: Message, state: FSMContext):
    token = message.text.strip()

    # Basic validation
    if len(token) < 20:
        await message.answer(
            "\u274c That doesn't look like a valid Notion token. "
            "It should start with `ntn_` or `secret_`. Please try again."
        )
        return

    # Test the token by creating a temporary client
    await message.answer("\U0001f50d Testing connection\u2026")
    test_client = NotionService(token=token)
    await test_client.connect()

    if not test_client.is_available:
        await message.answer(
            "\u274c Could not connect to Notion with that token. "
            "Please verify it's correct and the integration is active."
        )
        return

    await state.update_data(notion_token=token)
    logger.info(f"User {message.from_user.id} provided a valid Notion token.")

    # Move to step 2
    text = (
        "\u2705 Token verified!\n\n"
        "\u2699\ufe0f *Notion Setup \u2014 Step 2 of 3*\n\n"
        "Please send your **Ingredients Database ID** or its **full URL**.\n\n"
        "The URL looks like:\n"
        "`https://notion.so/workspace/DATABASE_ID?v=...`\n\n"
        "Make sure you've shared the database with your integration!"
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="notion_cancel")]
    ])
    await message.answer(text, reply_markup=cancel_kb, parse_mode="Markdown")
    await state.set_state(NotionSetupStates.waiting_for_ingredients_db_id)


# ── FSM Step 2: Receive Ingredients Database ID ──

@router.message(NotionSetupStates.waiting_for_ingredients_db_id)
async def step_ingredients_db_id(message: Message, state: FSMContext):
    raw = message.text.strip()

    # Try extracting ID from URL
    db_id = await notion_svc.get_database_id_from_url(raw) if notion_svc else None

    # If extraction failed, treat the raw input as the ID itself
    if not db_id:
        db_id = raw

    # Basic sanity check: Notion DB IDs are 32 hex chars (with or without dashes)
    import re
    cleaned = re.sub(r"-", "", db_id)
    if not re.match(r"^[a-f0-9]{32}$", cleaned):
        await message.answer(
            "\u274c That doesn't look like a valid Notion database ID or URL. "
            "The ID is a 32-character hex string. Please try again."
        )
        return

    # Normalize: strip dashes
    db_id = cleaned

    await state.update_data(notion_database_id=db_id)

    # Move to step 3
    text = (
        "\u2705 Ingredients database saved!\n\n"
        "\u2699\ufe0f *Notion Setup \u2014 Step 3 of 3*\n\n"
        "Please send your **Recipes Database ID** (or URL).\n\n"
        "This is *optional* \u2014 press **Skip** if you don't need meal syncing."
    )
    await message.answer(text, reply_markup=_skip_keyboard(), parse_mode="Markdown")
    await state.set_state(NotionSetupStates.waiting_for_recipes_db_id)


# ── FSM Step 3: Receive Recipes Database ID (optional) ──

@router.message(NotionSetupStates.waiting_for_recipes_db_id)
async def step_recipes_db_id(message: Message, state: FSMContext):
    raw = message.text.strip()

    db_id = await notion_svc.get_database_id_from_url(raw) if notion_svc else None
    if not db_id:
        db_id = raw

    import re
    cleaned = re.sub(r"-", "", db_id)
    if not re.match(r"^[a-f0-9]{32}$", cleaned):
        await message.answer(
            "\u274c That doesn't look like a valid database ID. "
            "Send a valid ID or press Skip."
        )
        return

    await state.update_data(notion_recipes_db_id=cleaned)
    await _finalize_setup(message, state)


# ── Skip Recipes DB ──

@router.callback_query(F.data == "notion_setup_skip")
async def cb_skip_recipes_db(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Skipped.")
    await _finalize_setup(callback.message, state)


# ── Finalize Setup ──

async def _finalize_setup(message: Message, state: FSMContext):
    """Save all collected data and test the connection."""
    if not db:
        await message.answer("\u274c Database service is not available. Please try again later.")
        await state.clear()
        return

    data = await state.get_data()
    user_id = message.from_user.id
    token = data.get("notion_token")
    ingredients_db = data.get("notion_database_id")
    recipes_db = data.get("notion_recipes_db_id")

    if not token or not ingredients_db:
        await message.answer(
            "\u274c Setup incomplete. Missing required fields. Please start over with /notion setup."
        )
        await state.clear()
        return

    # Save preferences
    await db.update_preferences(
        user_id,
        notion_token=token,
        notion_database_id=ingredients_db,
    )
    if recipes_db:
        await db.update_preferences(user_id, notion_recipes_db_id=recipes_db)

    # Create a client with the user's token and test
    test_client = NotionService(token=token)
    await test_client.connect()

    if not test_client.is_available:
        await message.answer(
            "\u26a0\ufe0f Your token was saved but the connection test failed. "
            "You can re-run /notion setup to update it."
        )
        await state.clear()
        return

    # Test database access
    try:
        await test_client.client.databases.query(
            database_id=ingredients_db,
            page_size=1,
        )
        db_status = "\u2705 Ingredients database accessible"
    except Exception as e:
        logger.warning(f"Database access test failed for user {user_id}: {e}")
        db_status = (
            "\u26a0\ufe0f Could not access the ingredients database. "
            "Make sure the integration is shared with the database:\n"
            f"  Error: `{e}`"
        )

    await state.clear()

    result = (
        "\u2705 *Notion setup complete!*\n\n"
        f"\u2022 Token: saved\n"
        f"\u2022 Ingredients DB: `{ingredients_db}`\n"
    )
    if recipes_db:
        result += f"\u2022 Recipes DB: `{recipes_db}`\n"
    else:
        result += "\u2022 Recipes DB: not configured (meal sync disabled)\n"
    result += f"\n{db_status}\n\nUse /notion sync to push your data!"
    await message.answer(result, parse_mode="Markdown")


# ── Cancel via /start during setup ──

@router.message(CommandStart(), NotionSetupStates.waiting_for_notion_token)
@router.message(CommandStart(), NotionSetupStates.waiting_for_ingredients_db_id)
@router.message(CommandStart(), NotionSetupStates.waiting_for_recipes_db_id)
async def cancel_setup_on_start(message: Message, state: FSMContext):
    """Allow /start to cancel an in-progress setup."""
    await state.clear()
