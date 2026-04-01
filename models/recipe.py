from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class RequiredIngredient(BaseModel):
    name: str
    have: bool = False


class MealSuggestion(BaseModel):
    name: str = Field(..., min_length=1)
    cuisine: str = Field(..., min_length=1)
    description: str = Field(..., min_length=10)
    difficulty: int = Field(..., ge=1, le=5)
    cook_time_minutes: int = Field(..., ge=1)
    ingredients: list[RequiredIngredient] = Field(default_factory=list)
    match_percentage: int = Field(..., ge=0, le=100)
    calories_per_serving: Optional[int] = None
    step_count: Optional[int] = None


class MealSuggestionsResponse(BaseModel):
    suggestions: list[MealSuggestion] = Field(default_factory=list)
    total_ingredients_available: int = 0
    total_seasonings_available: int = 0


class FullRecipe(BaseModel):
    name: str
    cuisine: str
    description: str
    difficulty: int = Field(ge=1, le=5)
    cook_time_minutes: int = Field(ge=1)
    prep_time_minutes: Optional[int] = None
    servings: int = Field(default=2, ge=1)
    ingredients: list[RequiredIngredient] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    calories_per_serving: Optional[int] = None


class CookedMeal(BaseModel):
    user_id: int
    recipe_name: str
    cuisine: str = ""
    ingredients_used: list[str] = Field(default_factory=list)
    rating: Optional[int] = Field(None, ge=1, le=5)
    is_favorite: bool = False
