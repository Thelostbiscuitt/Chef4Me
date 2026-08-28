from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class Category(str, Enum):
    PROTEIN = "protein"
    VEGETABLE = "vegetable"
    GRAIN = "grain"
    DAIRY = "dairy"
    SPICE = "spice"
    SAUCE = "sauce"
    OIL = "oil"
    FRUIT = "fruit"
    BEVERAGE = "beverage"
    OTHER = "other"


class Unit(str, Enum):
    GRAMS = "g"
    KILOGRAMS = "kg"
    MILLILITERS = "ml"
    LITERS = "L"
    PIECES = "pcs"
    CUPS = "cups"
    TABLESPOONS = "tbsp"
    TEASPOONS = "tsp"
    POUNDS = "lb"
    OUNCES = "oz"
    BUNCHES = "bunches"
    CLOVES = "cloves"
    PINCHES = "pinches"
    WHOLE = "whole"


class IngredientBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    quantity: float = Field(..., gt=0)
    unit: str
    category: str = Category.OTHER.value
    expiry_date: Optional[str] = None
    purchase_date: Optional[str] = None


class IngredientCreate(IngredientBase):
    user_id: int


class IngredientUpdate(BaseModel):
    quantity: Optional[float] = Field(None, gt=0)
    unit: Optional[str] = None
    category: Optional[str] = None
    expiry_date: Optional[str] = None


class IngredientDB(IngredientBase):
    id: int
    user_id: int
    added_at: str
    updated_at: str


class IngredientSummary(BaseModel):
    total_count: int
    by_category: dict[str, int]
    expiring_soon: list[IngredientBase]
