# 💰 Expense Tracker Bot

A Telegram bot for logging and analyzing daily expenses using Claude AI and Google Sheets.

## Setup

1. Copy `.env.example` to `.env` and fill in credentials:
   ```bash
   cp .env.example .env
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the bot:
   ```bash
   python bot.py
   ```

## Environment Variables

- `TELEGRAM_TOKEN`: Get from [@BotFather](https://t.me/botfather) on Telegram
- `CLAUDE_API_KEY`: From [console.anthropic.com](https://console.anthropic.com)
- `GOOGLE_SHEET_ID`: The ID from your Google Sheet URL
- `GOOGLE_CREDS_JSON`: Full contents of Google service account JSON file

## Usage

**Log expenses:**
- "mimansa groceries 450 bigbasket"
- "digvijay petrol 1200 hp pump"
- "rent 35000"

**Analyze:**
- "is mahine ka summary"
- "how much did mimansa spend?"
- "dining out this month"

**Commands:**
- `/start` - Welcome & usage
- `/summary` - Current month summary
- `/budget` - Budget vs actual
- `/help` - Show usage guide
