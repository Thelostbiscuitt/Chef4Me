
MEAL PLANNING BOT
Intelligent Kitchen Assistant for Telegram
AI-Powered Ingredient Management & Meal Suggestions from 40+ World Cuisines
Version 1.0.0
2026
 
Table of Contents
Overview	3
Key Features	3
Technology Stack	3
Telegram Command Reference	4
Inventory Management	4
Expiry Tracking	5
Meal Suggestions & Recipes	5
Preferences & History	6
Shopping List	7
Notion Integration	7
Setup & Deployment	8
Prerequisites	8
Deploying on Render (Background Worker)	8
Running Locally	8
Environment Variables	9
Project Structure	9
Supported Cuisines	10
Tips for Getting the Best Results	11
Troubleshooting	11
Bot is not responding	11
Gemini suggestions are empty or slow	12
Ingredient names are not recognized	12
Notion sync fails	12

Note: Right-click the Table of Contents and select "Update Field" to ensure page numbers are correct.
 
Overview
The Meal Planning Bot is a Telegram-based intelligent kitchen assistant designed to simplify meal planning and reduce food waste. It manages your ingredient inventory, tracks expiration dates, and leverages Google Gemini AI to suggest meals from over 40 different world cuisines based on what you already have in your kitchen. Whether you are a beginner cook or an experienced home chef, the bot adapts to your dietary preferences, skill level, and cooking habits to deliver personalized recipe recommendations.
Built with Python and the aiogram 3.x framework, the bot runs as a lightweight background service and can be deployed on any cloud platform that supports Docker containers. It features a robust SQLite database for persistent storage, an optional Notion integration for visual dashboard sync, and an intelligent scheduling system that sends you proactive expiry alerts before your ingredients go bad.
Key Features
•	Smart Ingredient Management -- Add ingredients individually or in bulk via natural language. The bot normalizes names, merges duplicates, and tracks quantities across multiple units.
•	AI-Powered Meal Suggestions -- Gemini analyzes your available ingredients and seasonings to recommend meals from diverse global cuisines. Each suggestion includes match percentage, difficulty level, cook time, and a full ingredient breakdown showing what you have versus what you need.
•	Expiry Tracking & Alerts -- Track expiration dates for every ingredient. The built-in scheduler runs periodic checks and proactively notifies you when items are about to expire, so you can prioritize cooking with them first.
•	Cooking History & Ratings -- Log meals you have cooked, rate them on a 1-5 scale, and automatically build a favourites collection. The bot learns from your history to avoid repeating cuisines too frequently.
•	Dietary Preferences -- Configure dietary restrictions (vegetarian, vegan, halal, gluten-free, and more), allergens, preferred cuisines, skill level, and serving size. All suggestions are personalized to your profile.
•	Shopping List Generator -- Based on your current inventory and dietary preferences, the AI suggests missing staple items that would round out your pantry for a balanced week of meals.
•	Notion Dashboard Sync -- Optionally sync your ingredients and cooked meals to Notion databases for a visual overview of your kitchen inventory and meal history.
Technology Stack
Component	Technology	Purpose
Bot Framework	aiogram 3.x	Async Telegram bot framework
AI Engine	Google Gemini 2.5 Flash	Structured meal suggestions and recipe generation
Database	SQLite (via aiosqlite)	Persistent async storage for all user data
Scheduler	APScheduler	Periodic expiry check and alert dispatch
Notion Integration	notion-client (async)	Optional sync to Notion databases
Data Validation	Pydantic v2	Schema validation for recipes and ingredients
Environment	python-dotenv	Configuration management from environment variables
Runtime	Python 3.12	Dockerized deployment on cloud platforms
Table 1: Technology stack overview
Telegram Command Reference
The bot provides a comprehensive set of commands organized into six categories. All commands are accessible directly via the Telegram chat interface. Commands that accept optional arguments can be used with or without them.
Inventory Management
Command	Description	Example
/start	Initialize the bot and register your account. Resets any active input flow.	/start
/help	Display the full list of available commands with usage tips.	/help
/add [name]	Start the ingredient addition flow. Optionally provide a name to skip the first step. The bot will then prompt for quantity, unit, category, and expiry date through an interactive guided process.	/add chicken breast
/add bulk	Enter bulk-add mode. Send a freeform list of ingredients (comma or newline separated) and the AI will parse names, quantities, units, and categories automatically.	/add bulk
/remove	Display an interactive keyboard of your current ingredients. Tap one to remove it from your inventory.	/remove
/inventory [cat]	View your full ingredient list grouped by category. Optionally filter by a specific category name to see only items in that group.	/inventory protein
/clear	Request confirmation, then delete all ingredients from your inventory. Use with caution as this action cannot be undone.	/clear
Table 2: Inventory management commands
Expiry Tracking
Command	Description	Example
/expiry	Show all ingredients expiring within the next 2 days, color-coded by urgency. Expired items appear in red, items expiring tomorrow in orange, and items expiring in 2 days in yellow. Tap any item to get recipe suggestions that use it.	/expiry
Table 3: Expiry tracking command
Meal Suggestions & Recipes
Command	Description	Example
/suggest	Get 6 AI-generated meal suggestions based on your current ingredients, seasonings, and dietary preferences. Suggestions are drawn from diverse world cuisines. Navigate results with inline buttons.	/suggest
/suggest [cuisine]	Filter meal suggestions to a specific cuisine. The bot will prioritize matching recipes from that tradition while still using your available ingredients.	/suggest Italian
/suggest [diet]	Apply a dietary filter to suggestions. Supported diets include vegetarian, vegan, pescatarian, halal, kosher, gluten-free, dairy-free, nut-free, low-carb, and keto.	/suggest vegan
/recipe [name]	Get a complete, detailed recipe for a specific dish. Includes full ingredient list (marked as available or needed), step-by-step instructions, cooking tips, estimated calories, and difficulty rating.	/recipe Pad Thai
/cook [name]	Quick-log a meal you cooked to your history. Optionally append a cuisine name. Returns a meal ID you can use to rate it later.	/cook Jollof Rice nigerian
Table 4: Meal suggestion and recipe commands
After the bot presents meal suggestions, you can interact with the results using the inline keyboard buttons beneath each message. Tap a meal name to see its full details including all ingredients, step-by-step instructions, and cooking tips. Use the Cooked button to log that you made the dish (this automatically consumes the ingredients you had). The More Suggestions button loads additional ideas, and the Back to List button returns you to the overview.
Preferences & History
Command	Description	Example
/preferences	Open the preferences panel with interactive buttons to configure dietary restrictions, preferred cuisines, cooking skill level, serving size, and notification settings. Each setting opens a guided multi-step flow.	/preferences
/history	View your 10 most recently cooked meals with cuisine, rating, and favourite status.	/history
/favorites	View all meals you have favourited. Meals are auto-added to favourites when you rate them 4 stars or higher.	/favorites
/rate [id] [1-5]	Rate a cooked meal by its ID and a score from 1 to 5. Ratings of 4 or above automatically add the meal to your favourites. Without arguments, displays a picker of your recent unrated meals.	/rate 5 4
Table 5: Preferences and history commands
Shopping List
Command	Description	Example
/shopping	Generate an AI-powered shopping list. The bot analyzes your current inventory against your dietary profile and suggests missing pantry staples that would help you cook balanced meals for the week. Each suggestion includes a reason explaining why it was recommended.	/shopping
Table 6: Shopping list command
Notion Integration
Command	Description	Example
/notion	Display the Notion integration status panel with options to sync data, configure the connection, or view help documentation.	/notion
/notion sync	Push all current ingredients and recent cooked meals to your configured Notion databases. Ingredients are upserted (existing entries are updated, new ones are created).	/notion sync
/notion setup	Start the guided setup flow to connect your Notion account. You will be asked for your integration token, ingredients database ID (or full URL), and optionally a recipes database ID. The bot validates each step before proceeding.	/notion setup
/notion help	Display detailed instructions on how to create a Notion integration, share databases with it, and configure the bot to sync data.	/notion help
Table 7: Notion integration commands
Setup & Deployment
Prerequisites
1.	A Telegram Bot Token -- Create a bot via @BotFather on Telegram and save the token.
2.	A Google Gemini API Key -- Obtain a free API key from Google AI Studio (supports the free tier).
3.	A cloud hosting account (Render recommended) or a local machine with Python 3.12 and Docker.
Deploying on Render (Background Worker)
Render is the recommended deployment platform for this bot. It provides a free tier for background workers, automatic HTTPS, and straightforward environment variable management. Follow these steps to get the bot running:
1.	Create a new Web Service or Background Worker on Render and connect your Git repository (or upload the provided ZIP file directly).
2.	Set the build type to Docker and ensure the Dockerfile is in the root of your project.
3.	Select Background Worker as the instance type (not Web Service). The bot runs as a long-polling process, not an HTTP server.
4.	Add the following environment variables in the Render environment settings panel: TELEGRAM_BOT_TOKEN (your bot token from @BotFather) and GEMINI_API_KEY (your Google AI Studio API key). Optionally add NOTION_TOKEN, NOTION_INGREDIENTS_DB, and NOTION_RECIPES_DB if you want Notion sync.
5.	Deploy. The bot will start polling automatically. On first deploy, it may take 2-3 minutes for the Docker image to build and the bot to come online.
6.	After deploying, send /start to your bot in Telegram to verify it is working.
Running Locally
You can run the bot locally for development or testing. Ensure you have Python 3.12 or later installed, then follow these steps:
4.	Clone or extract the project files into a directory.
5.	Create a .env file in the project root (a .env.example file is included as a reference) with your TELEGRAM_BOT_TOKEN and GEMINI_API_KEY.
6.	Install dependencies: pip install -r requirements.txt
7.	Run the bot: python bot.py
The bot will start polling for updates from Telegram. Send /start to your bot to begin using it. Press Ctrl+C to stop the bot gracefully.
Environment Variables
The bot is configured entirely through environment variables. There are no configuration files to edit. All variables have sensible defaults where applicable, and the two required variables (TELEGRAM_BOT_TOKEN and GEMINI_API_KEY) will cause the bot to exit immediately with a clear error message if they are not set.
Variable	Required	Description
TELEGRAM_BOT_TOKEN	Yes	Authentication token for your Telegram bot, obtained from @BotFather.
GEMINI_API_KEY	Yes	API key for Google Gemini AI, obtained from Google AI Studio.
GEMINI_MODEL	No	Gemini model to use for suggestions and recipes. Default: gemini-2.5-flash.
NOTION_TOKEN	No	Integration token for Notion API. Required for Notion sync features.
NOTION_INGREDIENTS_DB	No	Database ID for the Notion database where ingredients are synced.
NOTION_RECIPES_DB	No	Database ID for the Notion database where cooked meals are synced.
EXPIRY_CHECK_INTERVAL	No	Seconds between automated expiry checks. Default: 3600 (1 hour).
EXPIRY_WARNING_DAYS	No	How many days ahead to warn about expiring ingredients. Default: 2.
LOG_LEVEL	No	Logging verbosity. Options: DEBUG, INFO, WARNING, ERROR. Default: INFO.
Table 8: Environment variable reference
Project Structure
The project follows a clean modular architecture with clear separation of concerns. The router layer handles Telegram command routing, the services layer encapsulates business logic and external integrations, and the models layer provides data validation schemas.
Path	Description
bot.py	Main entry point. Initializes services, wires routers, and starts the polling loop.
config.py	Loads and validates all environment variables with sensible defaults.
state.py	Shared service container for dependency injection across modules.
routers/	Telegram command handlers organized by domain: start, inventory, suggest, planner, notion.
services/	Business logic layer: database (SQLite), Gemini AI client, Notion sync, and expiry scheduler.
models/	Pydantic v2 data models for ingredients, recipes, users, and preferences.
fsm/	Finite State Machine definitions for multi-step conversation flows (add ingredient, set preferences).
data/	Static data: cuisine categories with emojis, ingredient name aliases (120+ mappings).
utils/	Utility functions: text formatters, inline keyboard builders, ingredient name normalization.
Dockerfile	Docker image definition with build dependencies for all Python packages.
Procfile	Render process definition: runs bot.py as a background worker.
requirements.txt	Python package dependencies with compatible version ranges.
Table 9: Project directory structure
Supported Cuisines
The bot can suggest meals from over 40 distinct cuisine traditions. The AI engine is aware of the signature ingredients, seasonings, and cooking techniques associated with each cuisine, enabling it to make intelligent suggestions based on what you have in your pantry. When you have certain seasonings or spices, the bot will naturally gravitate toward cuisines that rely on those flavor profiles.
The following cuisines are currently recognized in the suggestion engine, each with a corresponding flag emoji and a curated list of signature ingredients:
Thai, Chinese, Japanese, Korean, Indian, Italian, Mexican, French, Spanish, Greek, Turkish, Moroccan, Ethiopian, Nigerian, Ghanaian, Kenyan, Vietnamese, Filipino, Indonesian, Malaysian, Brazilian, Peruvian, Colombian, Argentine, Jamaican, Cuban, Lebanese, Iranian, Israeli, American, British, German, Polish, Russian, Ukrainian, Caribbean, Mediterranean, African, Latin, Asian, Fusion, and Comfort Food.
You can set your preferred cuisines using the /preferences command. The bot will prioritize those cuisines in its suggestions while still occasionally offering variety from other traditions to keep your meals interesting.
Tips for Getting the Best Results
•	Add your seasonings and condiments -- The bot can suggest a much wider variety of cuisines when it knows you have soy sauce, cumin, turmeric, olive oil, or other common seasonings. These dramatically expand the range of possible meals.
•	Set your expiry dates -- When adding ingredients, always include the expiry date when prompted. This enables the automated alert system and helps you prioritize cooking with ingredients that are about to go bad.
•	Configure your dietary preferences -- Use /preferences to set your restrictions, allergens, and preferred cuisines. This ensures every suggestion is relevant and safe for you.
•	Rate your meals -- After cooking a suggested meal, rate it. Ratings of 4 or 5 stars automatically save the recipe to your favourites, and the history data helps the bot avoid suggesting cuisines you have recently cooked.
•	Use /suggest with filters -- Try commands like /suggest Thai, /suggest vegan, or /suggest Mexican vegan to narrow down suggestions. You can combine cuisine and diet in a single command.
•	Try bulk add for speed -- After grocery shopping, use /add bulk and paste your entire receipt list. The AI will parse it into structured ingredient entries automatically.
•	Check /expiry regularly -- The bot sends proactive alerts, but you can also manually check /expiry at any time to see what needs to be used soon.
Troubleshooting
Bot is not responding
If your bot is online but not responding to messages, the most common cause is a conflict with another running instance. This typically happens during a deployment when the old instance has not fully shut down yet. Wait 2-3 minutes and try again. If the issue persists, manually restart the service on your hosting platform.
Gemini suggestions are empty or slow
The Google Gemini free tier has rate limits. If you are making many requests in a short period, you may hit these limits. The bot includes an automatic fallback to a lighter model, but if both models are throttled, wait a few minutes before trying again. Also verify that your GEMINI_API_KEY is valid and has not expired.
Ingredient names are not recognized
The bot includes a built-in normalization engine with over 120 ingredient name aliases (for example, "bell pepper" maps to "capsicum", "cilantro" maps to "coriander"). If a name is not recognized, try using a more common or standard English name. You can also add custom aliases by editing the data/ingredient_aliases.json file.
Notion sync fails
Notion sync requires that you have created a Notion integration, shared the target databases with that integration, and provided the correct database IDs. Common issues include using an integration token that starts with the wrong prefix, or forgetting to share the database with the integration after creating it. Use /notion help for step-by-step setup instructions.
