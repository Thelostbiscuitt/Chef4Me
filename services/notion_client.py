import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from notion_client import AsyncClient

import config

logger = logging.getLogger(__name__)


class NotionService:
    def __init__(self, token: str = None):
        self.token = token or config.NOTION_TOKEN
        self.client: Optional[AsyncClient] = None
        self.enabled = bool(self.token)

    async def connect(self):
        if not self.enabled:
            logger.info("Notion integration not configured, skipping.")
            return
        self.client = AsyncClient(auth=self.token)
        # Verify connection (newer notion-client uses .self() or skip check)
        try:
            me = getattr(self.client, "me", None)
            if me and callable(me):
                result = await me()
                logger.info(f"Notion connected as: {result.get('name', 'Unknown')}")
            else:
                # Fallback: try a lightweight API call to verify token works
                await self.client.search(query="", page_size=1)
                logger.info("Notion client connected (token verified).")
        except Exception as e:
            logger.warning(f"Notion connection failed: {e}")
            self.enabled = False

    @property
    def is_available(self) -> bool:
        return self.enabled and self.client is not None

    async def sync_ingredients(self, user_id: int, ingredients: list[dict], database_id: str = None):
        """Sync all user ingredients to a Notion database."""
        if not self.is_available:
            return False
        db_id = database_id or config.NOTION_INGREDIENTS_DB
        if not db_id:
            logger.warning("No Notion ingredients database ID configured.")
            return False

        try:
            # Query existing pages for this user
            existing = await self.client.databases.query(
                database_id=db_id,
                filter={"property": "User ID", "rich_text": {"equals": str(user_id)}}
            )
            existing_map = {}
            for page in existing.get("results", []):
                name_prop = page.get("properties", {}).get("Name", {}).get("title", [])
                if name_prop:
                    name = name_prop[0].get("plain_text", "")
                    existing_map[name.lower()] = page["id"]

            # Upsert each ingredient
            for ing in ingredients:
                name = ing["name"]
                props = {
                    "Name": {"title": [{"text": {"content": name}}]},
                    "User ID": {"rich_text": [{"text": {"content": str(user_id)}}]},
                    "Category": {"select": {"name": ing.get("category", "other").capitalize()}},
                    "Quantity": {"number": ing.get("quantity", 0)},
                    "Unit": {"select": {"name": ing.get("unit", "pcs")}},
                    "In Stock": {"checkbox": True},
                }
                if ing.get("expiry_date"):
                    props["Expiry Date"] = {"date": {"start": ing["expiry_date"]}}

                if name.lower() in existing_map:
                    await self.client.pages.update(
                        page_id=existing_map[name.lower()], properties=props
                    )
                else:
                    await self.client.pages.create(
                        parent={"database_id": db_id}, properties=props
                    )

            logger.info(f"Synced {len(ingredients)} ingredients to Notion for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Notion sync failed: {e}")
            return False

    async def sync_cooked_meal(self, user_id: int, recipe_name: str,
                                cuisine: str = "", database_id: str = None):
        """Add a cooked meal to the Notion recipes database."""
        if not self.is_available:
            return False
        db_id = database_id or config.NOTION_RECIPES_DB
        if not db_id:
            return False

        try:
            props = {
                "Name": {"title": [{"text": {"content": recipe_name}}]},
                "User ID": {"rich_text": [{"text": {"content": str(user_id)}}]},
                "Cuisine": {"select": {"name": cuisine.capitalize() if cuisine else "International"}},
                "Last Cooked": {"date": {"start": datetime.utcnow().strftime("%Y-%m-%d")}},
                "Cooked": {"checkbox": True},
            }
            await self.client.pages.create(
                parent={"database_id": db_id}, properties=props
            )
            logger.info(f"Synced cooked meal '{recipe_name}' to Notion for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Notion meal sync failed: {e}")
            return False

    async def get_database_id_from_url(self, url: str) -> Optional[str]:
        """Extract database ID from a Notion database URL."""
        # URLs look like: https://notion.so/workspace/DATABASE_ID?v=...
        import re
        match = re.search(r"([a-f0-9]{32})", url)
        if match:
            return match.group(1)
        return None
