import os
import json
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from anthropic import Anthropic
import gspread
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

# Initialize Claude client
claude_client = Anthropic(api_key=CLAUDE_API_KEY)

# Google Sheets setup
def get_sheets_client():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    scope = ['https://spreadsheets.google.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def get_sheet():
    client = get_sheets_client()
    return client.open_by_key(GOOGLE_SHEET_ID).worksheet("Log")

# System prompt for Claude
PARSING_SYSTEM_PROMPT = """You are an expense parser for an Indian couple (Mimansa and Digvijay).
Extract expense information from messages in English/Hinglish and return ONLY valid JSON.

PERSONS: Mimansa, Digvijay, Both (default if no name mentioned)

CATEGORIES (use EXACTLY these):
Salary, Rent, EMI, Education Loan, Credit Card, Insurance, Subscriptions, Groceries, Utilities, Transport,
Dining Out, Entertainment, Healthcare, Shopping, Education, Miscellaneous, SIP, CC Payment

PAYMENT METHODS: Cash, Credit Card, UPI, Bank Transfer (default: UPI)

HINGLISH CATEGORY MAPPINGS:
- sabzi/kirana/vegetables → Groceries
- petrol/fuel/diesel/cab/driving → Transport
- khana/bhojan/dinner/lunch/zomato/swiggy/blinkit/khane → Dining Out
- bijli/light bill/wifi/internet → Utilities
- dawai/medicine/hospital/doctor → Healthcare
- SIP/mutual fund/investment → SIP
- CC bill/credit card bill → CC Payment
- emi → EMI
- insurance → Insurance
- rent/bhada → Rent
- subscription → Subscriptions
- shopping/kapde/khareed → Shopping
- entertainment/movie/games → Entertainment
- salary/payment → Salary
- loan → Education Loan

EXAMPLES:
- "rent 35000" → {person: "Both", category: "Rent", amount: 35000, description: "", payment_method: "UPI", is_expense: true}
- "mimansa groceries 450 bigbasket" → {person: "Mimansa", category: "Groceries", amount: 450, description: "bigbasket", payment_method: "UPI", is_expense: true}
- "digvijay petrol 1200 pump" → {person: "Digvijay", category: "Transport", amount: 1200, description: "pump", payment_method: "UPI", is_expense: true}
- "dinner 800" → {person: "Both", category: "Dining Out", amount: 800, description: "", payment_method: "UPI", is_expense: true}

RESPONSE FORMAT (ONLY return JSON, no other text):
{
    "person": "Mimansa|Digvijay|Both",
    "category": "Category Name",
    "amount": number,
    "description": "description or empty string",
    "payment_method": "UPI|Cash|Credit Card|Bank Transfer",
    "is_expense": true
}

Always set is_expense to true if you can identify an amount and category, even if format is informal."""

ANALYSIS_SYSTEM_PROMPT = """You are a financial assistant for Mimansa and Digvijay (Indian couple).
Analyze their expenses from the provided data and answer questions conversationally.

Monthly budgets for reference:
Rent: 35000, EMI: 40000, Education Loan: 40000, Credit Card: 15000, Insurance: 5000,
Subscriptions: 2000, Groceries: 15000, Utilities: 5000, Transport: 8000, Dining Out: 5000,
Entertainment: 5000, Healthcare: 3000, Shopping: 5000, Education: 3000, Miscellaneous: 3000, SIP: 16000

Be conversational and use Hindi/Hinglish if the user asked in that language. Use ₹ symbol for currency."""

def parse_expense(message_text):
    """Use Claude to parse expense from message."""
    response = claude_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=200,
        system=PARSING_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message_text}]
    )
    try:
        return json.loads(response.content[0].text)
    except:
        return {"is_expense": False}

def get_analysis(question, sheet_data):
    """Use Claude to analyze expenses and answer questions."""
    context = "Recent expense data:\n" + json.dumps(sheet_data, indent=2, ensure_ascii=False)

    response = claude_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=500,
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"{context}\n\nQuestion: {question}"}
        ]
    )
    return response.content[0].text

def log_to_sheets(parsed_expense):
    """Log parsed expense to Google Sheets."""
    sheet = get_sheet()
    today = datetime.now()
    date_str = today.strftime("%d %b %Y")
    month_str = today.strftime("%B %Y")

    row = [
        date_str,
        parsed_expense.get("category", "Miscellaneous"),
        parsed_expense.get("description", ""),
        parsed_expense.get("amount", 0),
        parsed_expense.get("payment_method", "UPI"),
        "",  # Notes (empty for now)
        parsed_expense.get("person", "Both"),
        month_str
    ]

    sheet.append_row(row)
    return row

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages."""
    message_text = update.message.text

    # Parse expense
    parsed = parse_expense(message_text)

    if not parsed.get("is_expense"):
        # Try to answer as a question
        try:
            sheet = get_sheet()
            all_rows = sheet.get_all_records()
            answer = get_analysis(message_text, all_rows[-20:] if len(all_rows) > 20 else all_rows)
            await update.message.reply_text(answer)
        except Exception as e:
            await update.message.reply_text("Sorry, couldn't understand. Try:\n- 'mimansa groceries 450 bigbasket'\n- 'how much did we spend on dining?'")
        return

    # Log to sheets
    try:
        row = log_to_sheets(parsed)

        # Send confirmation
        confirmation = f"""✅ Logged!
👤 {parsed.get('person', 'Both')}
🏷️ {parsed.get('category', 'Miscellaneous')}
💰 ₹{parsed.get('amount', 0)}
📝 {parsed.get('description', '')}
📅 {datetime.now().strftime('%d %b %Y')}"""

        await update.message.reply_text(confirmation)
    except Exception as e:
        await update.message.reply_text(f"Error logging expense: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message."""
    welcome = """👋 Welcome to Expense Tracker!

**How to log expenses:**
- mimansa groceries 450 bigbasket
- digvijay petrol 1200 hp pump
- rent 35000
- dinner 800 parents ke saath

**Commands:**
/summary - Current month summary
/budget - Budget vs actual
/help - Show this message

**Ask questions:**
- is mahine ka summary
- mimansa ne kitna kharch kiya?
- dining out this month
"""
    await update.message.reply_text(welcome)

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get current month summary."""
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_records()
        answer = get_analysis("Is mahine ka summary do - total spend, category-wise breakdown, aur budget comparison", all_rows)
        await update.message.reply_text(answer)
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get budget vs actual."""
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_records()
        answer = get_analysis("Show budget vs actual spending for this month, category-wise. Highlight categories where we exceeded budget.", all_rows)
        await update.message.reply_text(answer)
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help."""
    await start(update, context)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("budget", budget))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot started! Listening for messages...")
    app.run_polling()

if __name__ == "__main__":
    main()
