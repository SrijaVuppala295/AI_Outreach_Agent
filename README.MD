# Instagram Cold Mailer Bot

A powerful AI-driven outreach system for Instagram lead generation, email creation, queue management, and multi-account Gmail delivery using Discord slash commands.

---

## Overview

This project combines:
- Instagram profile scraping and insight extraction
- AI-powered cold email creation and follow-up generation
- Google Sheets queue management
- Multi-account Gmail sending
- Discord slash command orchestration

It is designed to automate outreach at scale while preserving configurable rate controls and thread-based follow-ups.

---

## Key Features

- Instagram scraping of profile metadata, bio, engagement, and reels
- AI email generation for initial outreach and follow-ups
- Queue creation in Google Sheets (`Day1Queue`, `Day2Queue`, etc.)
- Multi-account Gmail sending with send delay and thread handling
- Discord interface for remote command control
- Shared rate limiting and retry handling
- Configurable Google Sheets and Discord bot settings via `.env`

---

## Architecture

```text
[Instagram Scraper] ---> [AI Email Generator] ---> [Google Sheets Queue]
        |                                           |
        v                                           v
[Profile Insights]                             [Discord Bot]
                                                     |
                                                     v
                                            [Gmail Multi-Account Sender]
```

1. `scrapper.py` reads leads from Google Sheets and extracts Instagram profile data.
2. Insights are used to generate personalized cold emails and follow-ups.
3. Generated leads are queued into sheet tabs such as `Day1Queue`.
4. `main.py` runs the Discord bot that triggers email sends via slash commands.
5. Gmail accounts send emails with rate limiting and optional reply threading.

---

## Folder Structure

- `main.py` — Discord bot launcher and command sync
- `scrapper.py` — Instagram scraping, AI email generation, queue creation
- `discord_bot.py` — email sending, queue processing, bot behaviors
- `commands/` — Discord command cogs for send and follow-up workflows
- `utils/` — shared helpers for AI, email handling, rate limiting, Google Sheets, Instagram scraping
- `logs/` — runtime logs and rate limit state files
- `rate_limits.json` — configured quotas and limits
- `SETUP.md` — setup instructions and configuration guidance
- `verify_setup.py` — local environment verification script

---

## Tech Stack

- Python `>= 3.13`
- `py-cord` / `discord.py` for Discord bot interactions
- `python-dotenv` for environment variable loading
- `gspread` + Google Sheets API for queue/storage
- `google-generativeai` / `openai` / custom AI integration
- `pandas` for sheet and queue data handling
- `requests`, `tenacity` for HTTP and retry logic
- Multi-account Gmail delivery via app passwords

---

## Setup

### Requirements

- Python `3.13+`
- Google Cloud service account for Sheets API
- Discord bot token and `MY_GUILD_ID`
- One or more AI provider API keys
- One or more Gmail app passwords
- A Google Sheet with lead/queue tabs

### Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install audioop-lts generativeai>=0.0.1 google-generativeai>=0.8.5 gspread openai>=1.104.1 pandas pandas-stubs py-cord python-dotenv requests tenacity>=9.1.2
```

There is no `requirements.txt` in this repository, so install packages directly from the dependency list above.

### Configure `.env`

Create a `.env` file in the repository root and add the required keys.

Example values:

```env
# Discord
DISCORD_BOT_TOKEN=your_discord_bot_token
MY_GUILD_ID=your_discord_guild_id

# Google Sheets
GOOGLE_SHEETS_SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_SHEETS_TYPE=service_account
GOOGLE_SHEETS_PROJECT_ID=...
GOOGLE_SHEETS_PRIVATE_KEY_ID=...
GOOGLE_SHEETS_PRIVATE_KEY=...
GOOGLE_SHEETS_CLIENT_EMAIL=...
GOOGLE_SHEETS_CLIENT_ID=...
GOOGLE_SHEETS_CLIENT_X509_CERT_URL=...

# AI Provider
AI_PROVIDER=gemini
GEMINI_API_KEY_1=...
GEMINI_API_KEY_2=...
# ... additional AI keys as needed

# Gmail accounts
EMAIL_ADDRESS_1=...
EMAIL_PASSWORD_1=...
EMAIL_ADDRESS_2=...
EMAIL_PASSWORD_2=...

# Optional settings
META_TOKEN=...
META_PAGE_ID=...
META_APP_ID=...
META_APP_SECRET=...
```

Keep `service_account.json` and all secrets out of Git. This repository already ignores `service_account.json`.

---

## Running the Project

### Start the Discord bot

```powershell
python main.py
```

The bot will sync slash commands to the configured guild and print the available commands.

### Run the Instagram scraper / email generator

```powershell
python scrapper.py
```

Follow the prompts to:
- connect to Google Sheets
- scrape Instagram leads
- generate AI emails
- create queue tabs such as `Day1Queue`

### Send emails from Discord

Use the bot slash commands in your guild.

Example:
- `/send queue:Day1Queue count:100 delay:5`
- `/sendfollow queue:Day1Queue followup:1 count:50 delay:5`

---

## Workflow Summary

1. Add Instagram lead URLs or handles to the `Leads` sheet.
2. Run `python scrapper.py` to fetch profiles and generate emails.
3. Use Discord to send initial outreach with `/send`.
4. Schedule follow-ups using `/sendfollow`.
5. Monitor rate usage and logs in the `logs/` folder.

---

## Collaboration

This project is open to collaboration.

If you want to contribute:
- open an issue with a feature request or bug report
- submit a pull request with improvements
- add tests or documentation updates
- help simplify setup and reliability

### How to contribute

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Open a PR with a clear description

I’m happy to collaborate on improvements, better installation docs, and stronger email delivery handling.

---

## Important Notes

- Use this system responsibly and in compliance with anti-spam laws.
- Do not commit API keys, service account credentials, or Gmail passwords.
- Store secrets in `.env` or an external secrets manager.

---

## Additional Files

- `SETUP.md` — deeper setup notes for keys and accounts
- `verify_setup.py` — environment validation helper
- `rate_limits.json` — configured quotas and limits

---

## Contact

If you want to collaborate, improve the system, or add automation features, feel free to open an issue or PR.

