# Meal Planning Bot

**Intelligent Kitchen Assistant for Telegram**

AI-Powered Ingredient Management & Meal Suggestions from 40+ World Cuisines

**Version 1.0.0** | 2026

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Telegram Command Reference](#telegram-command-reference)
  - [Inventory Management](#inventory-management)
  - [Expiry Tracking](#expiry-tracking)
  - [Meal Suggestions & Recipes](#meal-suggestions--recipes)
  - [Preferences & History](#preferences--history)
  - [Shopping List](#shopping-list)
  - [Notion Integration](#notion-integration)
- [Setup & Deployment](#setup--deployment)
  - [Prerequisites](#prerequisites)
  - [Deploying on a VPS](#deploying-on-a-vps-systemd--long-polling)
  - [Running Locally](#running-locally)
- [Environment Variables](#environment-variables)
- [Project Structure](#project-structure)
- [Supported Cuisines](#supported-cuisines)
- [Tips for Getting the Best Results](#tips-for-getting-the-best-results)
- [Troubleshooting](#troubleshooting)

---

## Overview

The Meal Planning Bot is a Telegram-based intelligent kitchen assistant designed to simplify meal planning and reduce food waste. It manages your ingredient inventory, tracks expiration dates, and leverages Google Gemini AI to suggest meals from over 40 different world cuisines based on what you already have in your kitchen. Whether you are a beginner cook or an experienced home chef, the bot adapts to your dietary preferences, skill level, and cooking habits to deliver personalized recipe recommendations.

Built with Python and the aiogram 3.x framework, the bot runs as a lightweight background service and can be deployed on any cloud platform that supports Docker containers. It features a robust SQLite database for persistent storage, an optional Notion integration for visual dashboard sync, and an intelligent scheduling system that sends you proactive expiry alerts before your ingredients go bad.

## Key Features

- **Smart Ingredient Management** – Add ingredients individually or in bulk via natural language. The bot normalizes names, merges duplicates, and tracks quantities across multiple units.
- **AI-Powered Meal Suggestions** – Gemini analyzes your available ingredients and seasonings to recommend meals from diverse global cuisines. Each suggestion includes match percentage, difficulty level, cook time, and a full ingredient breakdown showing what you have versus what you need.
- **Expiry Tracking & Alerts** – Track expiration dates for every ingredient. The built-in scheduler runs periodic checks and proactively notifies you when items are about to expire, so you can prioritize cooking with them first.
- **Cooking History & Ratings** – Log meals you have cooked, rate them on a 1-5 scale, and automatically build a favourites collection. The bot learns from your history to avoid repeating cuisines too frequently.
- **Dietary Preferences** – Configure dietary restrictions (vegetarian, vegan, halal, gluten-free, and more), allergens, preferred cuisines, skill level, and serving size. All suggestions are personalized to your profile.
- **Shopping List Generator** – Based on your current inventory and dietary preferences, the AI suggests missing staple items that would round out your pantry for a balanced week of meals.
- **Notion Dashboard Sync** – Optionally sync your ingredients and cooked meals to Notion databases for a visual overview of your kitchen inventory and meal history.

## Technology Stack

| Component            | Technology            | Purpose                                        |
|----------------------|-----------------------|------------------------------------------------|
| Bot Framework        | aiogram 3.x           | Async Telegram bot framework                   |
| AI Engine            | Google Gemini 2.5 Flash | Structured meal suggestions and recipe generation |
| Database             | SQLite (via aiosqlite) | Persistent async storage for all user data     |
| Scheduler            | APScheduler           | Periodic expiry check and alert dispatch       |
| Notion Integration   | notion-client (async) | Optional sync to Notion databases              |
| Data Validation      | Pydantic v2           | Schema validation for recipes and ingredients  |
| Environment          | python-dotenv         | Configuration management from environment vars |
| Runtime              | Python 3.12           | Dockerized deployment on cloud platforms       |

## Telegram Command Reference

The bot provides a comprehensive set of commands organized into six categories. All commands are accessible directly via the Telegram chat interface. Commands that accept optional arguments can be used with or without them.

### Inventory Management

| Command              | Description                                                                                     | Example                |
|----------------------|-------------------------------------------------------------------------------------------------|------------------------|
| **/start**           | Initialize the bot and register your account. Resets any active input flow.                     | /start                 |
| **/help**            | Display the full list of available commands with usage tips.                                    | /help                  |
| **/add [name]**      | Start the ingredient addition flow. Optionally provide a name to skip the first step. The bot then asks how many items you bought and how much is in each one (e.g. `20` × `625 ml` = `12500 ml`), followed by category and expiry date. | /add chicken breast    |
| **/add bulk**        | Enter bulk-add mode. Send a freeform list of ingredients (comma or newline separated) and the AI will parse names, quantities, units, and categories automatically. | /add bulk              |
| **/remove**          | Display an interactive keyboard of your current ingredients. Tap one to remove it from your inventory. | /remove                |
| **/inventory [cat]** | View your full ingredient list grouped by category. Optionally filter by a specific category name to see only items in that group. | /inventory protein     |
| **/clear**           | Request confirmation, then delete all ingredients from your inventory. Use with caution as this action cannot be undone. | /clear                 |

### Expiry Tracking

| Command      | Description                                                                                           | Example   |
|--------------|-------------------------------------------------------------------------------------------------------|-----------|
| **/expiry**  | Show all ingredients expiring within the next 2 days, color-coded by urgency. Expired items appear in red, items expiring tomorrow in orange, and items expiring in 2 days in yellow. Tap any item to get recipe suggestions that use it. | /expiry   |

### Meal Suggestions & Recipes

| Command                | Description                                                                                                                              | Example                |
|------------------------|------------------------------------------------------------------------------------------------------------------------------------------|------------------------|
| **/suggest**           | Get 6 AI-generated meal suggestions based on your current ingredients, seasonings, and dietary preferences. Suggestions are drawn from diverse world cuisines. Navigate results with inline buttons. | /suggest               |
| **/suggest [cuisine]** | Filter meal suggestions to a specific cuisine. The bot will prioritize matching recipes from that tradition while still using your available ingredients. | /suggest Italian       |
| **/suggest [diet]**    | Apply a dietary filter to suggestions. Supported diets include vegetarian, vegan, pescatarian, halal, kosher, gluten-free, dairy-free, nut-free, low-carb, and keto. | /suggest vegan         |
| **/recipe [name]**     | Get a complete, detailed recipe for a specific dish. Includes full ingredient list (marked as available or needed), step-by-step instructions, cooking tips, estimated calories, and difficulty rating. | /recipe Pad Thai       |
| **/cook [name]**       | Quick-log a meal you cooked to your history. Optionally append a cuisine name. Returns a meal ID you can use to rate it later.           | /cook Jollof Rice nigerian |

After the bot presents meal suggestions, you can interact with the results using the inline keyboard buttons beneath each message. Tap a meal name to see its full details including all ingredients, step-by-step instructions, and cooking tips. Use the **Cooked** button to log that you made the dish (this automatically consumes the ingredients you had). The **More Suggestions** button loads additional ideas, and the **Back to List** button returns you to the overview.

### Preferences & History

| Command               | Description                                                                                                                      | Example        |
|-----------------------|----------------------------------------------------------------------------------------------------------------------------------|----------------|
| **/preferences**      | Open the preferences panel with interactive buttons to configure dietary restrictions, preferred cuisines, cooking skill level, serving size, and notification settings. Each setting opens a guided multi-step flow. | /preferences   |
| **/history**          | View your 10 most recently cooked meals with cuisine, rating, and favourite status.                                              | /history       |
| **/favorites**        | View all meals you have favourited. Meals are auto-added to favourites when you rate them 4 stars or higher.                    | /favorites     |
| **/rate [id] [1-5]**  | Rate a cooked meal by its ID and a score from 1 to 5. Ratings of 4 or above automatically add the meal to your favourites. Without arguments, displays a picker of your recent unrated meals. | /rate 5 4      |

### Shopping List

| Command        | Description                                                                                                                                                                           | Example    |
|----------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------|
| **/shopping**  | Generate an AI-powered shopping list. The bot analyzes your current inventory against your dietary profile and suggests missing pantry staples that would help you cook balanced meals for the week. Each suggestion includes a reason explaining why it was recommended. | /shopping  |

### Notion Integration

| Command          | Description                                                                                                                                                                     | Example        |
|------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------|
| **/notion**      | Display the Notion integration status panel with options to sync data, configure the connection, or view help documentation.                                                    | /notion        |
| **/notion sync** | Push all current ingredients and recent cooked meals to your configured Notion databases. Ingredients are upserted (existing entries are updated, new ones are created).       | /notion sync   |
| **/notion setup**| Start the guided setup flow to connect your Notion account. You will be asked for your integration token, ingredients database ID (or full URL), and optionally a recipes database ID. The bot validates each step before proceeding. | /notion setup  |
| **/notion help** | Display detailed instructions on how to create a Notion integration, share databases with it, and configure the bot to sync data.                                               | /notion help   |

## Setup & Deployment

### Prerequisites

1. A **Telegram Bot Token** – Create a bot via [@BotFather](https://t.me/botfather) on Telegram and save the token.
2. A **Google Gemini API Key** – Obtain a free API key from [Google AI Studio](https://aistudio.google.com/) (supports the free tier).
3. A cloud hosting account (Render recommended) or a local machine with Python 3.12 and Docker.

### Deploying on a VPS (systemd + long polling)

The bot is a long-running Python process, so it belongs on a Virtual
Private Server (e.g. an Oracle Cloud VPS), not on a serverless platform
such as Vercel. The recommended setup uses **long polling** managed by
**systemd**: the bot makes outbound HTTPS calls to Telegram only, so you
need no open inbound ports, no domain, no TLS certificate and no reverse
proxy. Nothing in the Oracle Cloud security list needs to change.

Full step-by-step instructions: see **[deploy/README.md](deploy/README.md)**.
Summary:

1. Install Python 3.12+ and git on the VPS.
2. Place the project in `/opt/chef4me` and create a venv:
   ```bash
   cd /opt/chef4me
   python3 -m venv venv
   venv/bin/pip install -r requirements.txt
   ```
3. Create `/opt/chef4me/.env` with `TELEGRAM_BOT_TOKEN` and
   `GEMINI_API_KEY` (see `env.example`). Leave `WEBHOOK_BASE_URL` unset —
   the bot then runs in long-polling mode automatically.
4. Install and start the systemd service:
   ```bash
   sudo cp deploy/chef4me.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now chef4me
   ```
5. Watch the logs (`journalctl -u chef4me -f`) and send `/start` to the
   bot in Telegram to verify it is working.

#### Why not Vercel?

Vercel's Python runtime executes short-lived serverless functions and
requires an ASGI/WSGI entrypoint it can auto-detect (`app.py`,
`main.py`, ...) or one declared as `tool.vercel.entrypoint` in
`pyproject.toml`. This project's entrypoint is `bot.py`, which is why
Vercel reports `Error: No python entrypoint found`. Renaming the file
would not fix anything: the bot is a persistent aiohttp/aiogram process
with an in-process APScheduler (proactive expiry alerts) and a local
SQLite database — none of which fit the serverless model. Use a VPS
(this guide) or a long-running container platform instead. The included
`Dockerfile` and `Procfile` are for container-based hosting (e.g. Render
Web Service), where the bot should run in webhook mode by setting
`WEBHOOK_BASE_URL` and `WEBHOOK_SECRET`.


### Running Locally

You can run the bot locally for development or testing. Ensure you have Python 3.12 or later installed.

1. Clone or extract the project files into a directory.
2. Create a `.env` file in the project root (a `.env.example` file is included as a reference) with your `TELEGRAM_BOT_TOKEN` and `GEMINI_API_KEY`.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the bot:
   ```bash
   python bot.py
   ```
The bot will start polling for updates from Telegram. Send `/start` to your bot to begin using it. Press `Ctrl+C` to stop the bot gracefully.
