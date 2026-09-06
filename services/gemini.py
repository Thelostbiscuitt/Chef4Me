import json
import logging
from typing import Optional
from datetime import date, timedelta

from google import genai
from google.genai import types
from google.genai.types import GenerateContentConfig

from models.recipe import MealSuggestion, MealSuggestionsResponse, FullRecipe
import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a world-class chef with deep knowledge of every major global cuisine including but not limited to: Thai, Chinese, Japanese, Korean, Indian, Italian, Mexican, French, Spanish, Greek, Turkish, Moroccan, Ethiopian, Nigerian, Ghanaian, Vietnamese, Filipino, Indonesian, Malaysian, Brazilian, Peruvian, Colombian, Jamaican, Lebanese, Iranian, American, British, German, and many more.

Given a list of available ingredients and seasonings, suggest meals that can be prepared with minimal or no additional ingredients. For each suggestion, you MUST match at least 80% of the non-trivial ingredients from the provided list. You should prioritize diverse cuisines: suggest meals from at least 3 different ethnic traditions. Always consider what seasonings and sauces are available, as they dramatically expand the range of possible cuisines.

Important rules:
- Be creative with cuisine selection. If soy sauce and ginger are available, explore East Asian cuisines. If cumin and turmeric are present, explore South Asian or Middle Eastern.
- Rate authenticity (how close to the traditional version given available ingredients).
- Consider substitutions: suggest what can replace a missing ingredient.
- For each meal, clearly mark which ingredients the user has vs. which they need.
- Always suggest meals that are realistically achievable with the listed ingredients.
- Include both simple and moderately complex options.
- NEVER suggest a recipe where more than 20% of key ingredients are missing.
- Respond ONLY with valid JSON matching the requested schema.

RECIPE DETAIL RULES — these are non-negotiable:
- Every ingredient MUST have an exact measurement with unit (e.g. 500g, 2 tbsp, 1 tsp, 3 cloves). Never use vague amounts like "some", "a handful", or "to taste" alone.
- Every recipe MUST include a realistic prep_time_minutes AND cook_time_minutes as separate values.
- Every instruction step must be specific and actionable — include cooking temperature (e.g. medium-high heat, 180°C/350°F), duration (e.g. cook for 5-7 minutes), and a sensory cue so the user knows when it's done (e.g. until golden brown, until juices run clear, until fragrant).
- Steps must be granular — never combine multiple actions into one step. Aim for 8-12 steps minimum for any non-trivial recipe.
- Always include at least 3 tips covering: a substitution, a storage instruction, and a serving suggestion."""

SUGGEST_PROMPT_TEMPLATE = """Here are my available ingredients:
{ingredients}

Here are my seasonings and condiments:
{seasonings}

My dietary restrictions: {restrictions}
My allergens to avoid: {allergens}
My cooking skill level: {skill_level}
Servings I typically cook for: {servings}

{cuisine_constraint}

Please suggest exactly {count} meals I can make. Each should be from a different cuisine where possible. For each meal provide:
- name: the dish name
- cuisine: the ethnic cuisine category
- description: 2-3 sentences about the dish and why it works with these ingredients
- difficulty: 1 (beginner) to 5 (expert)
- cook_time_minutes: realistic cooking time excluding prep
- ingredients: list of required ingredients with exact measurement (e.g. "500g chicken breast") and "have" (true if user has it, false if missing)
- match_percentage: what fraction of required ingredients the user already has (0-100)
- calories_per_serving: estimated if possible (null if not)
- step_count: approximate number of cooking steps"""

RECIPE_PROMPT_TEMPLATE = """I want to cook: {recipe_name}
This is from {cuisine} cuisine.

My available ingredients: {ingredients}
My available seasonings: {seasonings}
My dietary restrictions: {restrictions}
My skill level: {skill_level}
Servings: {servings}

Provide a COMPLETE, DETAILED recipe. You must follow these rules strictly:

INGREDIENTS:
- Every single ingredient must have an exact quantity and unit (e.g. "500g boneless chicken breast", "2 tbsp olive oil", "3 garlic cloves minced", "1 tsp salt").
- Never write vague amounts. Always be specific.
- Mark have=true if the ingredient is in my available list, have=false if I need to buy it.

TIMING:
- prep_time_minutes: time spent chopping, marinating, mixing before any heat is applied.
- cook_time_minutes: active time on heat or in oven.
- These must be separate, realistic values — not combined.

INSTRUCTIONS (steps array):
- Minimum 8 steps for any non-trivial recipe, 12+ for complex dishes.
- Each step must be a single focused action.
- Include exact heat level (low / medium / medium-high / high / 180°C / 350°F etc.).
- Include exact duration ("cook for 5-7 minutes", "simmer for 20 minutes", "rest for 10 minutes").
- Include a sensory or visual cue for doneness ("until golden brown", "until the onions are translucent", "until the sauce coats the back of a spoon").
- Never combine multiple actions in one step.

NUTRITION (nutrition object):
- Estimate per-serving calories, protein (g), carbs (g) and fat (g).
- Base the estimate on the ingredient quantities listed above.

TIPS (tips array — minimum 3):
- One substitution tip (e.g. what to use if a key ingredient is unavailable).
- One storage/make-ahead tip.
- One serving suggestion (what to pair the dish with).

Respond ONLY with valid JSON matching the schema."""


class GeminiService:
    def __init__(self):
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.model = config.GEMINI_MODEL
        self.fallback_model = config.GEMINI_FALLBACK_MODEL

    async def suggest_meals(
        self,
        ingredients: list[str],
        seasonings: list[str],
        dietary_restrictions: list[str] = None,
        allergens: list[str] = None,
        skill_level: str = "beginner",
        servings: int = 2,
        count: int = 6,
        preferred_cuisines: list[str] = None,
        avoid_cuisines: list[str] = None,
        premium: bool = True,
    ) -> MealSuggestionsResponse:
        """Generate meal suggestions based on available ingredients."""
        cuisine_constraint = ""
        if avoid_cuisines:
            cuisine_constraint += f"Please AVOID suggesting these cuisines that were recently cooked: {', '.join(avoid_cuisines)}. "
        if preferred_cuisines:
            cuisine_constraint += f"Prioritize these preferred cuisines: {', '.join(preferred_cuisines)}. "

        prompt = SUGGEST_PROMPT_TEMPLATE.format(
            ingredients=", ".join(ingredients) if ingredients else "None",
            seasonings=", ".join(seasonings) if seasonings else "None",
            restrictions=", ".join(dietary_restrictions) if dietary_restrictions else "None",
            allergens=", ".join(allergens) if allergens else "None",
            skill_level=skill_level,
            servings=servings,
            cuisine_constraint=cuisine_constraint,
            count=count,
        )

        schema = {
            "type": "object",
            "properties": {
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "cuisine": {"type": "string"},
                            "description": {"type": "string"},
                            "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                            "cook_time_minutes": {"type": "integer", "minimum": 1},
                            "ingredients": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "have": {"type": "boolean"}
                                    },
                                    "required": ["name", "have"]
                                }
                            },
                            "match_percentage": {"type": "integer", "minimum": 0, "maximum": 100},
                            "calories_per_serving": {"type": "integer", "nullable": True},
                            "step_count": {"type": "integer", "nullable": True}
                        },
                        "required": ["name", "cuisine", "description", "difficulty",
                                     "cook_time_minutes", "ingredients", "match_percentage"]
                    }
                }
            },
            "required": ["suggestions"]
        }

        try:
            response = await self._generate(prompt, schema, premium=premium)
            return MealSuggestionsResponse(
                suggestions=response.get("suggestions", []),
                total_ingredients_available=len(ingredients),
                total_seasonings_available=len(seasonings),
            )
        except Exception as e:
            logger.error(f"Failed to get meal suggestions: {e}")
            return MealSuggestionsResponse()

    async def get_full_recipe(
        self,
        recipe_name: str,
        cuisine: str = "International",
        ingredients: list[str] = None,
        seasonings: list[str] = None,
        dietary_restrictions: list[str] = None,
        skill_level: str = "beginner",
        servings: int = 2,
        premium: bool = True,
    ) -> Optional[FullRecipe]:
        """Get a complete detailed recipe for a specific dish."""
        prompt = RECIPE_PROMPT_TEMPLATE.format(
            recipe_name=recipe_name,
            cuisine=cuisine,
            ingredients=", ".join(ingredients) if ingredients else "Various",
            seasonings=", ".join(seasonings) if seasonings else "Various",
            restrictions=", ".join(dietary_restrictions) if dietary_restrictions else "None",
            skill_level=skill_level,
            servings=servings,
        )

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "cuisine": {"type": "string"},
                "description": {"type": "string"},
                "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                "cook_time_minutes": {"type": "integer", "minimum": 1},
                "prep_time_minutes": {"type": "integer", "minimum": 0},
                "servings": {"type": "integer", "minimum": 1},
                "ingredients": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "have": {"type": "boolean"}
                        },
                        "required": ["name", "have"]
                    }
                },
                "steps": {"type": "array", "items": {"type": "string"}, "minItems": 8},
                "tips": {"type": "array", "items": {"type": "string"}, "minItems": 3},
                "calories_per_serving": {"type": "integer", "nullable": True},
                "nutrition": {
                    "type": "object",
                    "properties": {
                        "calories": {"type": "number"},
                        "protein_g": {"type": "number"},
                        "carbs_g": {"type": "number"},
                        "fat_g": {"type": "number"},
                    },
                }
            },
            "required": ["name", "cuisine", "description", "difficulty",
                         "cook_time_minutes", "prep_time_minutes", "ingredients", "steps", "tips"]
        }

        try:
            data = await self._generate(prompt, schema, premium=premium)
            return FullRecipe(**data)
        except Exception as e:
            logger.error(f"Failed to get recipe for {recipe_name}: {e}")
            return None

    async def identify_ingredients_from_text(self, text: str) -> list[dict]:
        """Parse a text list of ingredients into structured data."""
        prompt = f"""Parse this text into a list of kitchen ingredients. The text may be a
plain list, a shopping list, or a casual sentence (e.g. "I bought 2kg of
chicken, a dozen eggs and some rice yesterday"). It may contain brand names
and packaging descriptions — this is normal grocery shopping language.
For each ingredient extract:
- name: the ingredient name (normalized, singular form). Brand names and pack
  sizes are part of the name and must be kept, e.g. "1 carton of Indomie
  noodles chicken flavour 70g small size" → name "indomie noodles chicken
  flavour 70g"; "5 500g golden penny twist pasta" → name "golden penny twist
  pasta 500g"; "1 5kg bag of Basmati rice" → name "basmati rice 5kg".
- quantity: the amount of items/packages as a number, or null if the amount is
  not explicitly stated in the text. NEVER guess or invent an amount — if the
  text doesn't say how much, use null and the user will be asked. Exceptions
  where a number IS stated in words: "a dozen" = 12, "a couple" = 2,
  "half a litre" = 0.5, "a pinch" = 1.
- unit: one of g, kg, ml, L, pcs, cups, tbsp, tsp, lb, oz, bunches, cloves, whole.
  Container and packaging words (carton, sachet, bag, bottle, pack, tin,
  "paint plastic") describe how many items were bought — map them to "pcs" and
  keep the pack size in the name. Examples: "10 sachets of Gino pepper and
  onions tomato paste" → quantity 10, unit "pcs", name "gino pepper and onions
  tomato paste"; "1 625ml bottle of sesame oil" → quantity 1, unit "pcs",
  name "sesame oil 625ml". For loose quantities ("2kg of chicken") use the
  weight/volume unit instead. If quantity is null, still give the most likely
  unit for this ingredient (it will be shown as a hint when the user is asked).
- category: one of protein, vegetable, grain, dairy, spice, sauce, oil, fruit, beverage, other
- expiry_hint: ONLY if the text mentions expiry/freshness for that item
  (e.g. "expires in 3 days", "going off tomorrow", "use by friday").
  Keep the hint in natural English. Otherwise omit this field entirely.

Input text: "{text}"

Return a JSON array of objects with these fields. Only return valid JSON."""

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "number", "nullable": True},
                    "unit": {"type": "string"},
                    "category": {"type": "string"},
                    "expiry_hint": {"type": "string"},
                },
                "required": ["name", "quantity", "unit", "category"]
            }
        }

        try:
            return await self._generate(prompt, schema)
        except Exception as e:
            logger.error(f"Failed to parse ingredients from text: {e}")
            return []

    async def extract_ingredients_from_image(
        self, image_bytes: bytes, mime_type: str = "image/jpeg"
    ) -> list[dict]:
        """Vision/OCR: extract ingredients from a photo (receipt, shopping list,
        fridge or pantry shot, food packaging)."""
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        prompt = """Look at this image and extract every kitchen ingredient you can
identify. The image may be a grocery receipt, a handwritten or printed shopping
list, a fridge/pantry photo, or food packaging. For each ingredient extract:
- name: the ingredient name (normalized, singular form)
- quantity: the amount as a number, or null if the amount is not readable or
  explicitly shown. NEVER guess or estimate an amount — if the label weight/
  volume isn't visible (e.g. a generic bottle or jar), use null and the user
  will be asked. Only use a number when it is actually written on or clearly
  inferable from the image (e.g. "500 ml" on a carton, 6 eggs in a box).
- unit: one of g, kg, ml, L, pcs, cups, tbsp, tsp, lb, oz, bunches, cloves, whole.
  Use pcs for countable items. If quantity is null, still give the most likely
  unit for this ingredient (it will be shown as a hint when the user is asked).
- category: one of protein, vegetable, grain, dairy, spice, sauce, oil, fruit, beverage, other
- expiry_hint: ONLY if the image shows an expiry/best-before/use-by date or a
  clearly visible freshness context. Otherwise omit this field entirely.

Only include actual food ingredients - skip prices, totals, barcodes, store
names and non-food items. Return a JSON array of objects with these fields.
Only return valid JSON."""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "number", "nullable": True},
                    "unit": {"type": "string"},
                    "category": {"type": "string"},
                    "expiry_hint": {"type": "string"},
                },
                "required": ["name", "quantity", "unit", "category"]
            }
        }
        try:
            return await self._generate([image_part, prompt], schema)
        except Exception as e:
            logger.error(f"Failed to extract ingredients from image: {e}")
            return []

    async def apply_correction(
        self, items: list[dict], correction: str
    ) -> list[dict]:
        """Apply a user's plain-English correction to a previously parsed
        ingredient list and return the full updated list."""
        prompt = f"""Here is a list of kitchen ingredients that was parsed earlier,
as JSON:

{json.dumps(items, ensure_ascii=False)}

The user reviewed this list and says:

"{correction}"

Apply their correction. Rules:
- Change, add or remove items exactly as the user asks.
- Keep every item they did NOT mention unchanged (same name, quantity, unit,
  category, expiry).
- If the user corrects or supplies an amount ("the soy sauce is 500ml",
  "2 bottles of milk"), set that item's quantity to the number they mean.
  Never guess an amount they didn't state — use null instead.
- quantity: a number, or null when the amount is unknown. unit: one of
  g, kg, ml, L, pcs, cups, tbsp, tsp, lb, oz, bunches, cloves, whole.
- category: one of protein, vegetable, grain, dairy, spice, sauce, oil,
  fruit, beverage, other.
- Keep any expiry information unless the user changes it.

Return the FULL updated list as a JSON array. Only return valid JSON."""

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "number", "nullable": True},
                    "unit": {"type": "string"},
                    "category": {"type": "string"},
                    "expiry_hint": {"type": "string"},
                },
                "required": ["name", "quantity", "unit", "category"]
            }
        }

        try:
            return await self._generate(prompt, schema)
        except Exception as e:
            logger.error(f"Failed to apply correction: {e}")
            return []

    # ── Premium features ─────────────────────────────────────────────────────

    async def generate_meal_plan(
        self,
        ingredients: list[str],
        seasonings: list[str],
        dietary_restrictions: list[str] = None,
        allergens: list[str] = None,
        skill_level: str = "beginner",
        servings: int = 2,
        days: int = 7,
        calories_target: int = None,
        premium: bool = True,
    ) -> dict:
        """Build a multi-day meal plan (breakfast/lunch/dinner + snack)."""
        calorie_line = (
            f"Daily calorie target: {calories_target} kcal per day."
            if calories_target else ""
        )
        prompt = f"""Build a {days}-day meal plan, using the ingredients I already
have as much as possible and minimizing new things to buy.

My available ingredients: {', '.join(ingredients) if ingredients else 'None'}
My seasonings and condiments: {', '.join(seasonings) if seasonings else 'None'}
My dietary restrictions: {', '.join(dietary_restrictions) if dietary_restrictions else 'None'}
My allergens to avoid: {', '.join(allergens) if allergens else 'None'}
My skill level: {skill_level}
Servings: {servings}
{calorie_line}

Rules:
- Produce exactly {days} days, each with slots: breakfast, lunch, dinner, snack.
- Vary cuisines across the plan; never repeat a dish.
- For every meal mark each ingredient have=true if it is in my available list,
  otherwise have=false with a quantity I need to buy (e.g. "500g chicken thighs").
- Every ingredient must have an exact quantity string (number + unit).
- Give realistic difficulty (1-5) and cook_time_minutes for every meal.
- Include a nutrition estimate per meal (calories, protein_g, carbs_g, fat_g).
- 1-2 sentences of description per meal.

Respond ONLY with valid JSON matching the schema."""

        schema = {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "integer"},
                            "day_name": {"type": "string"},
                            "meals": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "slot": {"type": "string"},
                                        "name": {"type": "string"},
                                        "cuisine": {"type": "string"},
                                        "description": {"type": "string"},
                                        "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                                        "cook_time_minutes": {"type": "integer", "minimum": 1},
                                        "ingredients": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "name": {"type": "string"},
                                                    "quantity": {"type": "string"},
                                                    "have": {"type": "boolean"},
                                                },
                                                "required": ["name", "have"],
                                            },
                                        },
                                        "nutrition": {
                                            "type": "object",
                                            "properties": {
                                                "calories": {"type": "number"},
                                                "protein_g": {"type": "number"},
                                                "carbs_g": {"type": "number"},
                                                "fat_g": {"type": "number"},
                                            },
                                        },
                                    },
                                    "required": ["slot", "name", "cuisine", "description",
                                                 "difficulty", "cook_time_minutes",
                                                 "ingredients"],
                                },
                            },
                        },
                        "required": ["day", "day_name", "meals"],
                    },
                },
            },
            "required": ["plan"],
        }

        try:
            return await self._generate(
                prompt, schema, premium=premium, max_output_tokens=16384
            )
        except Exception as e:
            logger.error(f"Failed to generate meal plan: {e}")
            return {"plan": []}

    async def organize_shopping_list(
        self, items: list[str], premium: bool = True
    ) -> dict:
        """Group shopping items by supermarket aisle and merge duplicates."""
        prompt = f"""Here is a shopping list of kitchen ingredients:
{json.dumps(items, ensure_ascii=False)}

Organize it for a supermarket trip:
- Merge duplicate/similar items (e.g. two entries of chicken thighs) into one
  entry with a combined quantity (e.g. "1 kg chicken thighs").
- Group items by aisle. Use these aisles only: Produce, Dairy & Eggs,
  Meat & Fish, Bakery, Pantry & Dry Goods, Spices & Sauces, Frozen, Household.
- Keep quantities exact and combined.
Return ONLY valid JSON matching the schema."""

        schema = {
            "type": "object",
            "properties": {
                "aisles": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "aisle": {"type": "string"},
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "quantity": {"type": "string"},
                                    },
                                    "required": ["name"],
                                },
                            },
                        },
                        "required": ["aisle", "items"],
                    },
                },
            },
            "required": ["aisles"],
        }

        try:
            return await self._generate(prompt, schema, premium=premium)
        except Exception as e:
            logger.error(f"Failed to organize shopping list: {e}")
            return {"aisles": []}

    async def use_up_recipes(
        self, expiring: list[str], premium: bool = True
    ) -> list[dict]:
        """2 quick recipes that use ingredients expiring soon."""
        prompt = f"""These ingredients in my kitchen are about to expire:
{', '.join(expiring)}

Suggest exactly 2 quick meals that use as many of them as possible, with
minimal extra ingredients. For each give:
- name, description (1-2 sentences), match_percentage (0-100),
- ingredients: list with name and have (true only if it is one of the
  expiring items above, otherwise false).

Respond ONLY with valid JSON: an array of meal objects."""

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "match_percentage": {"type": "integer", "minimum": 0, "maximum": 100},
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "have": {"type": "boolean"},
                            },
                            "required": ["name", "have"],
                        },
                    },
                },
                "required": ["name", "description"],
            },
        }

        try:
            result = await self._generate(prompt, schema, premium=premium)
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Failed to get use-up recipes: {e}")
            return []

    async def scale_recipe(
        self, recipe_name: str, ingredients: list[str], factor: float,
        premium: bool = True,
    ) -> dict:
        """Scale every ingredient quantity in a recipe by `factor`."""
        prompt = f"""Recipe: {recipe_name}
Current ingredient list:
{json.dumps(ingredients, ensure_ascii=False)}

Scale EVERY ingredient quantity by exactly {factor}x. Keep units, and give the
scaled quantity as a clean number (e.g. 500g x 2 = 1kg, 2 tbsp x 0.5 = 1 tbsp).
Return a JSON object with an 'ingredients' array; each item has 'name' (the
ingredient without its quantity) and 'quantity' (scaled number + unit)."""

        schema = {
            "type": "object",
            "properties": {
                "ingredients": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "string"},
                        },
                        "required": ["name", "quantity"],
                    },
                },
            },
            "required": ["ingredients"],
        }

        try:
            return await self._generate(prompt, schema, premium=premium)
        except Exception as e:
            logger.error(f"Failed to scale recipe: {e}")
            return {"ingredients": []}

    async def leftover_recipes(
        self, leftover: str, ingredients: list[str], seasonings: list[str],
        premium: bool = True,
    ) -> list[dict]:
        """3 recipes built around a specific leftover ingredient."""
        prompt = f"""I have leftover: {leftover}
Also available: {', '.join(ingredients) if ingredients else 'None'}
Seasonings: {', '.join(seasonings) if seasonings else 'None'}

Suggest exactly 3 meals that use the leftover as the main ingredient, and
minimize extra shopping. For each give: name, cuisine, description (1-2
sentences), difficulty (1-5), cook_time_minutes, match_percentage (0-100),
and ingredients (name + have; have=true only if the ingredient is the leftover
or in my available list).

Respond ONLY with valid JSON: an array of meal objects."""

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "cuisine": {"type": "string"},
                    "description": {"type": "string"},
                    "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                    "cook_time_minutes": {"type": "integer", "minimum": 1},
                    "match_percentage": {"type": "integer", "minimum": 0, "maximum": 100},
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "have": {"type": "boolean"},
                            },
                            "required": ["name", "have"],
                        },
                    },
                },
                "required": ["name", "cuisine", "description"],
            },
        }

        try:
            result = await self._generate(prompt, schema, premium=premium)
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Failed to get leftover recipes: {e}")
            return []

    async def substitutes(self, ingredient: str, premium: bool = True) -> list[dict]:
        """Cooking substitutes for a missing ingredient."""
        prompt = f"""I'm out of: {ingredient}

Give me exactly 3 practical cooking substitutes. For each: 'substitute' (name),
'ratio' (how much to use to replace the original, e.g. "1 egg = 1/4 cup"),
and 'notes' (how it changes taste/texture).

Respond ONLY with valid JSON: an array of substitute objects."""

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "substitute": {"type": "string"},
                    "ratio": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["substitute", "ratio", "notes"],
            },
        }

        try:
            result = await self._generate(prompt, schema, premium=premium)
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Failed to get substitutes: {e}")
            return []

    async def transcribe_voice(
        self, audio_bytes: bytes, mime_type: str = "audio/ogg",
        premium: bool = True,
    ) -> str:
        """Transcribe a Telegram voice note to text."""
        model = self.model if premium else self.fallback_model
        part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        prompt = (
            "Transcribe this voice note. Return only the spoken words, with "
            "punctuation. It is a list of kitchen ingredients or groceries."
        )
        try:
            response = await self.client.aio.models.generate_content(
                model=model,
                contents=[prompt, part],
                config=GenerateContentConfig(temperature=0),
            )
            return (response.text or "").strip()
        except Exception as e:
            logger.error(f"Failed to transcribe voice note: {e}")
            return ""

    async def _generate(
        self, prompt: str, response_schema: dict = None,
        premium: bool = True, max_output_tokens: int = 8192,
    ) -> dict:
        """Call the Gemini API with structured output support.

        Free-tier users get the lighter (cheaper) model; premium get the
        main model. Failures fall back to the other model automatically.
        """
        gen_config = GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7,
            max_output_tokens=max_output_tokens,
        )
        if response_schema:
            gen_config.response_mime_type = "application/json"
            gen_config.response_schema = response_schema

        model = self.model if premium else self.fallback_model
        fallback_model = self.fallback_model if premium else self.model

        try:
            response = await self.client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=gen_config,
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0] if "```" in text else text
                text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()
            return json.loads(text)
        except Exception as primary_error:
            logger.warning(f"Primary model failed ({primary_error}), trying fallback...")
            try:
                response = await self.client.aio.models.generate_content(
                    model=fallback_model,
                    contents=prompt,
                    config=gen_config,
                )
                text = response.text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    text = text.rsplit("```", 1)[0] if "```" in text else text
                    text = text.strip()
                if text.startswith("json"):
                    text = text[4:].strip()
                return json.loads(text)
            except Exception as fallback_error:
                logger.error(f"Fallback model also failed: {fallback_error}")
                raise
