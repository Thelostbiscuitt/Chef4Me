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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")

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

# ── Subscriptions ────────────────────────────────────────────────────────────
# Telegram user IDs allowed to run /grant, /revoke and /genpass.
ADMIN_USER_IDS: set[int] = {
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()
}

TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "7"))
SUBSCRIPTION_ENABLED = os.getenv("SUBSCRIPTION_ENABLED", "1") == "1"

# Free-tier daily limits (AI calls are the unit of cost)
FREE_SUGGESTS_PER_DAY = int(os.getenv("FREE_SUGGESTS_PER_DAY", "5"))
FREE_RECIPES_PER_DAY = int(os.getenv("FREE_RECIPES_PER_DAY", "3"))
FREE_BULK_ADDS_PER_DAY = int(os.getenv("FREE_BULK_ADDS_PER_DAY", "10"))
FREE_OCR_PER_MONTH = int(os.getenv("FREE_OCR_PER_MONTH", "3"))

# Premium hard caps (abuse / cost control)
PREMIUM_SUGGESTS_PER_DAY = int(os.getenv("PREMIUM_SUGGESTS_PER_DAY", "100"))
PREMIUM_RECIPES_PER_DAY = int(os.getenv("PREMIUM_RECIPES_PER_DAY", "100"))
PREMIUM_PLANS_PER_DAY = int(os.getenv("PREMIUM_PLANS_PER_DAY", "2"))

# Telegram Stars prices (1 Star ≈ $0.02 USD)
PRICE_WEEKLY_STARS = int(os.getenv("PRICE_WEEKLY_STARS", "100"))    # ~$1.99
PRICE_MONTHLY_STARS = int(os.getenv("PRICE_MONTHLY_STARS", "250"))  # ~$4.99
PRICE_YEARLY_STARS = int(os.getenv("PRICE_YEARLY_STARS", "2000"))   # ~$39.99

# ── Webhook settings ──────────────────────────────────────────────────────────
# The public HTTPS URL of your Render service, e.g. https://yourbot.onrender.com
# Render exposes this automatically as the RENDER_EXTERNAL_URL env var.
# You can also set it manually in your Render environment variables.
WEBHOOK_BASE_URL: str = os.getenv(
    "WEBHOOK_BASE_URL",
    os.getenv("RENDER_EXTERNAL_URL", ""),  # Render sets this automatically
)

# The path Telegram will POST updates to. Keeping the token in the path
# makes it a non-guessable URL — an extra layer of security on top of
# the secret_token header check done by SimpleRequestHandler.
WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", f"/webhook/{BOT_TOKEN}")

# An additional secret sent in the X-Telegram-Bot-Api-Secret-Token header.
# Generate a random string and store it as an env var in Render.
# Example: python -c "import secrets; print(secrets.token_hex(32))"
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

# Port to bind the aiohttp server to.
# Render injects $PORT automatically; default 8080 for local dev.
PORT: int = int(os.getenv("PORT", "8080"))
