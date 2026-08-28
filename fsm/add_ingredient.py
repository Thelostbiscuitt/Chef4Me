"""FSM for adding ingredients via multi-step conversation."""
from aiogram.fsm.state import State, StatesGroup


class AddIngredientStates(StatesGroup):
    """States for the add ingredient flow."""
    waiting_for_quantity = State()
    waiting_for_unit = State()
    waiting_for_category = State()
    waiting_for_expiry = State()


class SetPreferencesStates(StatesGroup):
    """States for setting user preferences."""
    waiting_for_dietary = State()
    waiting_for_cuisine_prefs = State()
    waiting_for_skill_level = State()
    waiting_for_serving_size = State()


class BulkAddStates(StatesGroup):
    """States for bulk ingredient addition."""
    waiting_for_bulk_input = State()
