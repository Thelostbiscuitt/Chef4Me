"""FSM for setting user preferences."""
from aiogram.fsm.state import State, StatesGroup


class SetPreferencesFSM:
    """Helper class with preference FSM constants and utilities."""
    SKILL_LEVELS = ["beginner", "intermediate", "advanced"]

    @staticmethod
    def skill_keyboard():
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍳 Beginner", callback_data="skill:beginner")],
            [InlineKeyboardButton(text="👨‍🍳 Intermediate", callback_data="skill:intermediate")],
            [InlineKeyboardButton(text="👨‍🎓 Advanced", callback_data="skill:advanced")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")],
        ])
