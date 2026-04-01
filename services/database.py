import aiosqlite
import json
import logging
from datetime import datetime, date
from typing import Optional
from pathlib import Path

import config

logger = logging.getLogger(__name__)


class DatabaseService:
    def __init__(self, db_path: Path = config.DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()
        await self._migrate()
        logger.info(f"Database connected at {self.db_path}")

    async def close(self):
        if self._connection:
            await self._connection.close()
            logger.info("Database connection closed")

    @property
    def db(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._connection

    async def _create_tables(self):
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id BIGINT NOT NULL,
                name TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 1,
                unit TEXT NOT NULL DEFAULT 'pcs',
                category TEXT NOT NULL DEFAULT 'other',
                expiry_date TEXT,
                purchase_date TEXT,
                added_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recipe_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id BIGINT NOT NULL,
                recipe_name TEXT NOT NULL,
                cuisine TEXT DEFAULT '',
                ingredients_used TEXT DEFAULT '[]',
                cooked_at TEXT NOT NULL,
                rating INTEGER CHECK(rating IS NULL OR rating BETWEEN 1 AND 5),
                is_favorite INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id BIGINT PRIMARY KEY,
                dietary_restrictions TEXT DEFAULT '[]',
                allergens TEXT DEFAULT '[]',
                preferred_cuisines TEXT DEFAULT '[]',
                skill_level TEXT DEFAULT 'beginner',
                serving_size INTEGER DEFAULT 2,
                notifications_enabled INTEGER DEFAULT 1,
                notion_token TEXT,
                notion_database_id TEXT,
                notion_recipes_db_id TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TEXT NOT NULL,
                last_active TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ingredients_user ON ingredients(user_id);
            CREATE INDEX IF NOT EXISTS idx_ingredients_expiry ON ingredients(user_id, expiry_date);
            CREATE INDEX IF NOT EXISTS idx_recipe_history_user ON recipe_history(user_id);
            CREATE INDEX IF NOT EXISTS idx_recipe_history_cuisine ON recipe_history(user_id, cuisine);
        """)
        await self.db.commit()

    async def _migrate(self):
        """Apply incremental migrations for schema changes."""
        # Migration: add notion_recipes_db_id column
        try:
            await self.db.execute(
                "ALTER TABLE user_preferences ADD COLUMN notion_recipes_db_id TEXT"
            )
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists

    # ── User Operations ──

    async def register_user(self, user_id: int, username: str = None, first_name: str = None):
        now = datetime.utcnow().isoformat()
        await self.db.execute(
            """INSERT OR IGNORE INTO users (user_id, username, first_name, created_at, last_active)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, username, first_name, now, now)
        )
        await self.db.execute(
            """INSERT OR IGNORE INTO user_preferences (user_id) VALUES (?)""",
            (user_id,)
        )
        await self.db.commit()

    async def update_user_activity(self, user_id: int):
        await self.db.execute(
            "UPDATE users SET last_active = ? WHERE user_id = ?",
            (datetime.utcnow().isoformat(), user_id)
        )
        await self.db.commit()

    # ── Ingredient Operations ──

    async def add_ingredient(self, user_id: int, name: str, quantity: float,
                             unit: str, category: str = "other",
                             expiry_date: str = None, purchase_date: str = None) -> int:
        now = datetime.utcnow().isoformat()
        # Check if same ingredient exists for user, merge quantities
        existing = await self.db.execute(
            "SELECT id, quantity FROM ingredients WHERE user_id = ? AND LOWER(name) = LOWER(?)",
            (user_id, name.strip())
        )
        row = await existing.fetchone()
        if row:
            new_qty = row["quantity"] + quantity
            await self.db.execute(
                """UPDATE ingredients SET quantity = ?, unit = ?, category = ?,
                   expiry_date = COALESCE(?, expiry_date),
                   updated_at = ? WHERE id = ?""",
                (new_qty, unit, category, expiry_date, now, row["id"])
            )
            await self.db.commit()
            return row["id"]

        cursor = await self.db.execute(
            """INSERT INTO ingredients
               (user_id, name, quantity, unit, category, expiry_date, purchase_date, added_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, name.strip(), quantity, unit, category, expiry_date, purchase_date, now, now)
        )
        await self.db.commit()
        return cursor.lastrowid

    async def add_ingredients_bulk(self, user_id: int, items: list[dict]) -> list[int]:
        """Add multiple ingredients at once. Each item is a dict with name, quantity, unit."""
        ids = []
        for item in items:
            ingredient_id = await self.add_ingredient(
                user_id=user_id,
                name=item["name"],
                quantity=item.get("quantity", 1),
                unit=item.get("unit", "pcs"),
                category=item.get("category", "other"),
                expiry_date=item.get("expiry_date"),
                purchase_date=item.get("purchase_date"),
            )
            ids.append(ingredient_id)
        return ids

    async def remove_ingredient(self, user_id: int, ingredient_id: int) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM ingredients WHERE user_id = ? AND id = ?",
            (user_id, ingredient_id)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def remove_ingredient_by_name(self, user_id: int, name: str) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM ingredients WHERE user_id = ? AND LOWER(name) = LOWER(?)",
            (user_id, name.strip())
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_ingredients(self, user_id: int, category: str = None) -> list[dict]:
        if category:
            query = "SELECT * FROM ingredients WHERE user_id = ? AND category = ? ORDER BY name"
            params = (user_id, category.lower())
        else:
            query = "SELECT * FROM ingredients WHERE user_id = ? ORDER BY category, name"
            params = (user_id,)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_ingredients_text(self, user_id: int) -> str:
        """Get all ingredients as a formatted text string for AI prompts."""
        ingredients = await self.get_ingredients(user_id)
        if not ingredients:
            return "No ingredients available."

        # Separate main ingredients from seasonings
        seasoning_cats = {"spice", "sauce", "oil"}
        main_items = []
        seasoning_items = []
        for ing in ingredients:
            entry = f"{ing['name']} ({ing['quantity']} {ing['unit']})"
            if ing["category"] in seasoning_cats:
                seasoning_items.append(entry)
            else:
                main_items.append(entry)

        result = "Main ingredients: " + ", ".join(main_items) if main_items else "No main ingredients."
        if seasoning_items:
            result += "\nSeasonings & condiments: " + ", ".join(seasoning_items)
        return result

    async def get_ingredients_as_lists(self, user_id: int) -> tuple[list[str], list[str]]:
        """Return (main_ingredients, seasonings) as name lists."""
        ingredients = await self.get_ingredients(user_id)
        seasoning_cats = {"spice", "sauce", "oil"}
        main_items = [ing["name"] for ing in ingredients if ing["category"] not in seasoning_cats]
        seasoning_items = [ing["name"] for ing in ingredients if ing["category"] in seasoning_cats]
        return main_items, seasoning_items

    async def get_expiring_soon(self, user_id: int, days: int = 2) -> list[dict]:
        today = date.today().isoformat()
        from datetime import timedelta
        cutoff = (date.today() + timedelta(days=days)).isoformat()
        cursor = await self.db.execute(
            """SELECT * FROM ingredients
               WHERE user_id = ? AND expiry_date IS NOT NULL
               AND expiry_date >= ? AND expiry_date <= ?
               ORDER BY expiry_date ASC""",
            (user_id, today, cutoff)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def search_ingredient(self, user_id: int, name: str) -> list[dict]:
        cursor = await self.db.execute(
            """SELECT * FROM ingredients
               WHERE user_id = ? AND LOWER(name) LIKE LOWER(?)
               ORDER BY name LIMIT 10""",
            (user_id, f"%{name.strip()}%")
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_ingredient_count(self, user_id: int) -> int:
        cursor = await self.db.execute(
            "SELECT COUNT(*) as cnt FROM ingredients WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def get_category_counts(self, user_id: int) -> dict[str, int]:
        cursor = await self.db.execute(
            "SELECT category, COUNT(*) as cnt FROM ingredients WHERE user_id = ? GROUP BY category",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return {row["category"]: row["cnt"] for row in rows}

    async def consume_ingredients(self, user_id: int, ingredient_names: list[str]):
        """Reduce or remove ingredients after cooking."""
        for name in ingredient_names:
            cursor = await self.db.execute(
                "SELECT id, quantity FROM ingredients WHERE user_id = ? AND LOWER(name) = LOWER(?)",
                (user_id, name.strip())
            )
            row = await cursor.fetchone()
            if row:
                if row["quantity"] <= 1:
                    await self.db.execute(
                        "DELETE FROM ingredients WHERE id = ?", (row["id"],)
                    )
                else:
                    await self.db.execute(
                        "UPDATE ingredients SET quantity = quantity - 1, updated_at = ? WHERE id = ?",
                        (datetime.utcnow().isoformat(), row["id"])
                    )
        await self.db.commit()

    async def clear_inventory(self, user_id: int) -> int:
        cursor = await self.db.execute(
            "DELETE FROM ingredients WHERE user_id = ?", (user_id,)
        )
        await self.db.commit()
        return cursor.rowcount

    # ── Recipe History Operations ──

    async def add_cooked_meal(self, user_id: int, recipe_name: str, cuisine: str = "",
                              ingredients_used: list[str] = None) -> int:
        now = datetime.utcnow().isoformat()
        cursor = await self.db.execute(
            """INSERT INTO recipe_history
               (user_id, recipe_name, cuisine, ingredients_used, cooked_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, recipe_name, cuisine,
             json.dumps(ingredients_used or []), now)
        )
        await self.db.commit()
        return cursor.lastrowid

    async def rate_meal(self, user_id: int, meal_id: int, rating: int):
        await self.db.execute(
            "UPDATE recipe_history SET rating = ? WHERE user_id = ? AND id = ?",
            (rating, user_id, meal_id)
        )
        await self.db.commit()

    async def toggle_favorite(self, user_id: int, meal_id: int) -> bool:
        cursor = await self.db.execute(
            "SELECT is_favorite FROM recipe_history WHERE user_id = ? AND id = ?",
            (user_id, meal_id)
        )
        row = await cursor.fetchone()
        if not row:
            return False
        new_val = 0 if row["is_favorite"] else 1
        await self.db.execute(
            "UPDATE recipe_history SET is_favorite = ? WHERE id = ?",
            (new_val, meal_id)
        )
        await self.db.commit()
        return bool(new_val)

    async def get_recent_meals(self, user_id: int, limit: int = 10) -> list[dict]:
        cursor = await self.db.execute(
            """SELECT * FROM recipe_history
               WHERE user_id = ? ORDER BY cooked_at DESC LIMIT ?""",
            (user_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_favorites(self, user_id: int) -> list[dict]:
        cursor = await self.db.execute(
            """SELECT * FROM recipe_history
               WHERE user_id = ? AND is_favorite = 1
               ORDER BY cooked_at DESC"""
            , (user_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_recent_cuisines(self, user_id: int, limit: int = 20) -> list[str]:
        cursor = await self.db.execute(
            """SELECT DISTINCT cuisine FROM recipe_history
               WHERE user_id = ? AND cuisine != ''
               ORDER BY cooked_at DESC LIMIT ?""",
            (user_id, limit)
        )
        rows = await cursor.fetchall()
        return [row["cuisine"] for row in rows]

    # ── Preferences Operations ──

    async def get_preferences(self, user_id: int) -> dict:
        cursor = await self.db.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {
                "user_id": user_id,
                "dietary_restrictions": [],
                "allergens": [],
                "preferred_cuisines": [],
                "skill_level": "beginner",
                "serving_size": 2,
                "notifications_enabled": True,
                "notion_token": None,
                "notion_database_id": None,
            }
        result = dict(row)
        result["dietary_restrictions"] = json.loads(result.get("dietary_restrictions") or "[]")
        result["allergens"] = json.loads(result.get("allergens") or "[]")
        result["preferred_cuisines"] = json.loads(result.get("preferred_cuisines") or "[]")
        result["notifications_enabled"] = bool(result.get("notifications_enabled", 1))
        return result

    async def update_preferences(self, user_id: int, **kwargs) -> bool:
        """Update user preferences. JSON fields (lists) are auto-serialized."""
        json_fields = {"dietary_restrictions", "allergens", "preferred_cuisines"}
        set_clauses = []
        values = []
        for key, value in kwargs.items():
            if key in json_fields and isinstance(value, (list, tuple)):
                value = json.dumps(value)
            set_clauses.append(f"{key} = ?")
            values.append(value)
        if not set_clauses:
            return False
        values.append(user_id)
        await self.db.execute(
            f"UPDATE user_preferences SET {', '.join(set_clauses)} WHERE user_id = ?",
            values
        )
        await self.db.commit()
        return True
