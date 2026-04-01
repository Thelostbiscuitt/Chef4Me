import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = BASE_DIR / "data" / "bot.db"

# Telegram Bot
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Google Gemini AI
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")

# Notion (optional)
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_INGREDIENTS_DB = os.getenv("NOTION_INGREDIENTS_DB", "")
NOTION_RECIPES_DB = os.getenv("NOTION_RECIPES_DB", "")
NOTION_SYNC_INTERVAL = int(os.getenv("NOTION_SYNC_INTERVAL", "300"))  # seconds

# Scheduler
EXPIRY_CHECK_INTERVAL = int(os.getenv("EXPIRY_CHECK_INTERVAL", "3600"))  # 1 hour
EXPIRY_WARNING_DAYS = int(os.getenv("EXPIRY_WARNING_DAYS", "2"))

# Bot settings
SUGGESTIONS_PER_REQUEST = int(os.getenv("SUGGESTIONS_PER_REQUEST", "6"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
