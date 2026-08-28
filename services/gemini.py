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
                            "calories_per_serving": {"type": ["integer", "null"]},
                            "step_count": {"type": ["integer", "null"]}
                        },
                        "required": ["name", "cuisine", "description", "difficulty",
                                     "cook_time_minutes", "ingredients", "match_percentage"]
                    }
                }
            },
            "required": ["suggestions"]
        }

        try:
            response = await self._generate(prompt, schema)
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
                "calories_per_serving": {"type": ["integer", "null"]}
            },
            "required": ["name", "cuisine", "description", "difficulty",
                         "cook_time_minutes", "prep_time_minutes", "ingredients", "steps", "tips"]
        }

        try:
            data = await self._generate(prompt, schema)
            return FullRecipe(**data)
        except Exception as e:
            logger.error(f"Failed to get recipe for {recipe_name}: {e}")
            return None

    async def identify_ingredients_from_text(self, text: str) -> list[dict]:
        """Parse a text list of ingredients into structured data."""
        prompt = f"""Parse this list of ingredients into structured data. For each item, extract:
- name: the ingredient name (normalized, singular form)
- quantity: the amount (number)
- unit: the unit (g, ml, pcs, cups, tbsp, tsp, kg, lb, bunches, cloves, whole, L)
- category: one of: protein, vegetable, grain, dairy, spice, sauce, oil, fruit, beverage, other

Input text: "{text}"

Return a JSON array of objects with these fields. Only return valid JSON."""

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "category": {"type": "string"}
                },
                "required": ["name", "quantity", "unit", "category"]
            }
        }

        try:
            return await self._generate(prompt, schema)
        except Exception as e:
            logger.error(f"Failed to parse ingredients from text: {e}")
            return []

    async def _generate(self, prompt: str, response_schema: dict = None) -> dict:
        """Call the Gemini API with structured output support."""
        gen_config = GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7,
            max_output_tokens=8192,
        )
        if response_schema:
            gen_config.response_mime_type = "application/json"
            gen_config.response_schema = response_schema

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
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
                    model=self.fallback_model,
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
