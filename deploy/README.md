# Deploying Chef4Me on a VPS (Oracle Cloud) — systemd + long polling

The bot is a long-running Python process, so it belongs on a VPS. The
recommended transport is **long polling**: the bot makes outbound HTTPS
calls to Telegram only, so you need **no open inbound ports, no domain,
no TLS certificate, and no reverse proxy**. Nothing in the Oracle Cloud
security list needs to change (SSH stays as-is).

> Do **not** deploy this bot to Vercel. Vercel runs short-lived serverless
> functions and looks for an ASGI/WSGI entrypoint (`app.py`, `main.py`, …),
> which is why it reports `Error: No python entrypoint found`. Renaming
> `bot.py` would not help: the bot's persistent process, in-process
> APScheduler (proactive expiry alerts) and local SQLite file are
> fundamentally incompatible with the serverless model.

## 1. Install prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-venv git
python3 --version   # 3.12+ recommended
```

## 2. Put the code on the server

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin chef4me
sudo mkdir -p /opt/chef4me
sudo chown chef4me:chef4me /opt/chef4me
sudo -u chef4me git clone <your-repo-url> /opt/chef4me
# ... or upload the files any other way and chown them to chef4me.
# NOTE: data/ contains required source files (cuisines.py,
# ingredient_aliases.json). Only exclude data/bot.db*, .env and .git.
```

## 3. Create the virtualenv and install dependencies

```bash
cd /opt/chef4me
sudo -u chef4me python3 -m venv venv
sudo -u chef4me venv/bin/pip install -r requirements.txt
```

## 4. Configure environment variables

Create `/opt/chef4me/.env` (owned by `chef4me`, mode 600):

```bash
TELEGRAM_BOT_TOKEN=<token from @BotFather>
GEMINI_API_KEY=<key from Google AI Studio>
# Optional:
# NOTION_TOKEN=...
# NOTION_INGREDIENTS_DB=...
# NOTION_RECIPES_DB=...
```

**Leave `WEBHOOK_BASE_URL` unset/empty.** That is what switches the bot
into long-polling mode (`bot.py` falls back to polling automatically and
clears any webhook left over from a previous deployment).

## 5. Install the systemd service

```bash
sudo cp deploy/chef4me.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chef4me
```

If you used a different user or path, edit `User=`, `Group=`,
`WorkingDirectory=`, `ExecStart=` and `ReadWritePaths=` in the unit file
first.

## 6. Verify

```bash
systemctl status chef4me
journalctl -u chef4me -f
```

You should see:

```
WEBHOOK_BASE_URL not set — POLLING mode (local dev).
Database connected at /opt/chef4me/data/bot.db
...
Starting long polling…
```

Then send `/start` to your bot in Telegram.

## 7. Updating the bot

```bash
cd /opt/chef4me
sudo -u chef4me git pull
sudo -u chef4me venv/bin/pip install -r requirements.txt
sudo systemctl restart chef4me
```
## Optional: webhook mode

If you later point a domain at this VPS and put Caddy/nginx with TLS in
front, you can switch to webhook mode: set `WEBHOOK_BASE_URL` (e.g.
`https://bot.example.com`) and `WEBHOOK_SECRET` in `.env`, open ports
80/443 in the Oracle security list, and restart. The bot will register
the webhook with Telegram itself on startup. For a single-user bot,
polling is simpler and equally reliable — there is no urgency to switch.
