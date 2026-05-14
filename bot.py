import os
import json
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
from anthropic import Anthropic
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

claude_client = Anthropic(api_key=CLAUDE_API_KEY)

VALID_CATEGORIES = [
    "Salary", "Rent", "EMI", "Education Loan", "Credit Card", "Insurance",
    "Subscriptions", "Groceries", "Utilities", "Transport", "Dining Out",
    "Entertainment", "Healthcare", "Shopping", "Education", "Miscellaneous", "SIP", "CC Payment"
]

MONTHLY_BUDGETS = {
    "Rent": 35000, "EMI": 40000, "Education Loan": 40000, "Credit Card": 15000,
    "Insurance": 5000, "Subscriptions": 2000, "Groceries": 15000, "Utilities": 5000,
    "Transport": 8000, "Dining Out": 5000, "Entertainment": 5000, "Healthcare": 3000,
    "Shopping": 5000, "Education": 3000, "Miscellaneous": 3000, "SIP": 16000
}

def get_sheets_client():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

def get_sheet():
    client = get_sheets_client()
    return client.open_by_key(GOOGLE_SHEET_ID).worksheet("Log")

PARSING_SYSTEM_PROMPT = """Parse expense. Return ONLY JSON, no other text.

Rules:
1. Person: Mimansa, Digvijay, or Both (default: Both if no name)
2. Category: Use EXACTLY one of: Salary, Rent, EMI, Education Loan, Credit Card, Insurance, Subscriptions, Groceries, Utilities, Transport, Dining Out, Entertainment, Healthcare, Shopping, Education, Miscellaneous, SIP, CC Payment
3. Amount: Extract the number
4. Payment: UPI (default), Cash, Credit Card, Bank Transfer
5. Description: Any other text mentioned
6. is_expense: Always true if amount exists

Hinglish: rent/bhada→Rent, sabzi/kirana→Groceries, petrol/fuel→Transport, khana/dinner→Dining Out, bijli/wifi→Utilities, dawai/doctor→Healthcare, SIP/investment→SIP

Return JSON only:
{"person": "Both", "category": "Rent", "amount": 35000, "description": "", "payment_method": "UPI", "is_expense": true}"""

ANALYSIS_SYSTEM_PROMPT = """You are a financial assistant for Mimansa and Digvijay (Indian couple).
Analyze their expenses and answer questions conversationally in the language asked.

Monthly budgets: Rent: 35000, EMI: 40000, Education Loan: 40000, Credit Card: 15000,
Insurance: 5000, Subscriptions: 2000, Groceries: 15000, Utilities: 5000, Transport: 8000,
Dining Out: 5000, Entertainment: 5000, Healthcare: 3000, Shopping: 5000, Education: 3000,
Miscellaneous: 3000, SIP: 16000

Be conversational, use ₹ symbol, and reply in Hindi/Hinglish if asked in that language."""

def parse_expense(message_text):
    """Use Claude to parse expense from message."""
    try:
        response = claude_client.messages.create(
            model="claude-opus-4-5",
            max_tokens=200,
            system=PARSING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message_text}]
        )
        text = response.content[0].text.strip()
        # Remove markdown code blocks if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:].lstrip("\n")
            text = text.split("```")[0]
        return json.loads(text)
    except Exception as e:
        print(f"[Parse Error] {e}")
        return {"is_expense": False}

def get_analysis(question, sheet_data):
    """Use Claude to analyze expenses and answer questions."""
    try:
        context = "Recent expense data:\n" + json.dumps(sheet_data, indent=2, ensure_ascii=False)
        response = claude_client.messages.create(
            model="claude-opus-4-5",
            max_tokens=500,
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"{context}\n\nQuestion: {question}"}]
        )
        result = response.content[0].text
        print(f"[Analysis Response] {result[:100]}...")
        return result
    except Exception as e:
        print(f"[Analysis Error] {e}")
        raise

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
        "",
        parsed_expense.get("person", "Both"),
        month_str
    ]
    sheet.append_row(row)
    return row

async def log_and_confirm(update: Update, parsed_expense):
    """Log expense and send confirmation."""
    try:
        print(f"[LOGGING] Saving to sheets: {parsed_expense}")
        log_to_sheets(parsed_expense)
        print(f"[SUCCESS] Logged expense")
        confirmation = f"""✅ Logged!
👤 {parsed_expense.get('person', 'Both')}
🏷️ {parsed_expense.get('category', 'Miscellaneous')}
💰 ₹{parsed_expense.get('amount', 0)}
📝 {parsed_expense.get('description', '') or '—'}
📅 {datetime.now().strftime('%d %b %Y')}"""
        await update.message.reply_text(confirmation)
    except Exception as e:
        print(f"[SHEETS ERROR] {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        await update.message.reply_text(f"Sheets Error: {str(e)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages."""
    message_text = update.message.text
    user_id = update.effective_user.id
    print(f"\n[MESSAGE] User {user_id}: '{message_text}'")

    # Handle pending delete confirmation
    if user_id in context.user_data and context.user_data[user_id].get('pending_delete'):
        if message_text.lower() == 'confirm':
            try:
                sheet = get_sheet()
                sheet.delete_rows(context.user_data[user_id]['delete_row_index'])
                await update.message.reply_text("✅ Expense deleted!")
                del context.user_data[user_id]['pending_delete']
                del context.user_data[user_id]['delete_row_index']
                return
            except Exception as e:
                await update.message.reply_text(f"Error: {str(e)}")
                return
        else:
            await update.message.reply_text("❌ Cancelled")
            del context.user_data[user_id]['pending_delete']
            return

    # Handle pending edit instruction
    if user_id in context.user_data and context.user_data[user_id].get('pending_edit'):
        try:
            parts = message_text.strip().split(' ', 1)
            if len(parts) != 2:
                await update.message.reply_text("Format: **field value**\nExample: category Groceries")
                return

            field, new_value = parts[0].lower(), parts[1]
            sheet = get_sheet()
            row_index = context.user_data[user_id]['edit_row_index']

            field_mapping = {
                'person': 'Person',
                'category': 'Category',
                'amount': 'Amount (₹)',
                'description': 'Description',
                'payment': 'Payment Method'
            }

            if field not in field_mapping:
                await update.message.reply_text("Field not found. Use: person, category, amount, description, or payment")
                return

            col_name = field_mapping[field]
            if field == 'amount':
                try:
                    new_value = float(new_value)
                except:
                    await update.message.reply_text("Amount must be a number")
                    return
            elif field == 'category' and new_value not in VALID_CATEGORIES:
                await update.message.reply_text(f"Invalid category. Use: {', '.join(VALID_CATEGORIES[:5])}...")
                return

            headers = sheet.row_values(1)
            col_index = headers.index(col_name) + 1
            sheet.update_cell(row_index, col_index, new_value)

            await update.message.reply_text(f"✅ Updated! {col_name} → {new_value}")
            del context.user_data[user_id]['pending_edit']
            return
        except Exception as e:
            await update.message.reply_text(f"Error: {str(e)}")
            del context.user_data[user_id]['pending_edit']
            return

    # Handle pending person field
    if user_id in context.user_data and 'pending_expense' in context.user_data[user_id]:
        pending = context.user_data[user_id]['pending_expense']
        if message_text.lower() in ['mimansa', 'digvijay', 'both']:
            pending['person'] = message_text.capitalize()
            await log_and_confirm(update, pending)
            del context.user_data[user_id]['pending_expense']
            return
        else:
            await update.message.reply_text("Please reply: Mimansa, Digvijay, or Both")
            return

    # Parse as expense
    print(f"[PARSING] Starting parse...")
    parsed = parse_expense(message_text)
    print(f"[PARSED] Result: {parsed}")
    await update.message.reply_text(f"[DEBUG] Parsed: {parsed}")

    if not parsed.get("is_expense"):
        # Try to answer as a question
        try:
            sheet = get_sheet()
            all_rows = sheet.get_all_records()
            answer = get_analysis(message_text, all_rows[-30:] if len(all_rows) > 30 else all_rows)
            await update.message.reply_text(answer)
        except Exception as e:
            await update.message.reply_text("Sorry, couldn't understand. Try:\n- 'rent 35000'\n- 'how much on groceries?'")
        return

    # Check if person is missing
    if parsed.get("person") == "Both" and not any(name.lower() in message_text.lower() for name in ['mimansa', 'digvijay']):
        await update.message.reply_text("Who paid - Mimansa, Digvijay, or Both?")
        if user_id not in context.user_data:
            context.user_data[user_id] = {}
        context.user_data[user_id]['pending_expense'] = parsed
        return

    # Log expense
    await log_and_confirm(update, parsed)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message."""
    welcome = """👋 Welcome to Expense Tracker!

**Log expenses:**
- mimansa groceries 450 bigbasket
- digvijay petrol 1200
- rent 35000
- dinner 800

**Commands:**
/history [n] - Last N expenses (default 10, max 30)
/search <query> - Find expenses by keyword
/today - Today's expenses
/delete - Remove last expense
/edit <field> <value> - Edit last expense
/categories - List all categories
/help - This message

**Ask questions:**
- how much on groceries?
- mimansa ne kitna kharch kiya?
- dining out this month"""
    await update.message.reply_text(welcome)

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent expenses."""
    try:
        args = update.message.text.split()
        n = int(args[1]) if len(args) > 1 else 10
        n = min(n, 30)

        sheet = get_sheet()
        all_rows = sheet.get_all_records()

        if not all_rows:
            await update.message.reply_text("No expenses yet.")
            return

        recent = all_rows[-n:][::-1]
        message = f"📝 **Last {len(recent)} Expenses**\n\n"

        for exp in recent:
            message += f"• {exp.get('Date', '')} | {exp.get('Person', '')} | {exp.get('Category', '')} | ₹{exp.get('Amount (₹)', '0')} | {exp.get('Description', '') or '—'}\n"

        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search expenses by keyword."""
    try:
        query = ' '.join(update.message.text.split()[1:]).lower()
        if not query:
            await update.message.reply_text("Usage: /search <keyword>")
            return

        sheet = get_sheet()
        all_rows = sheet.get_all_records()

        matches = [r for r in all_rows if query in str(r.get('Category', '')).lower()
                   or query in str(r.get('Description', '')).lower()
                   or query in str(r.get('Person', '')).lower()]

        if not matches:
            await update.message.reply_text(f"No expenses found for '{query}'")
            return

        total = sum(float(r.get('Amount (₹)', 0)) for r in matches)
        message = f"🔍 **Found {len(matches)} entries** | Total: ₹{total}\n\n"

        for exp in matches[-15:][::-1]:
            message += f"• {exp.get('Date', '')} | {exp.get('Person', '')} | {exp.get('Category', '')} | ₹{exp.get('Amount (₹)', '0')}\n"

        if len(matches) > 15:
            message += f"\n... and {len(matches) - 15} more"

        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's expenses."""
    try:
        today_str = datetime.now().strftime("%d %b %Y")
        sheet = get_sheet()
        all_rows = sheet.get_all_records()

        today_expenses = [r for r in all_rows if r.get('Date', '') == today_str]

        if not today_expenses:
            await update.message.reply_text(f"No expenses logged today ({today_str})")
            return

        total = sum(float(r.get('Amount (₹)', 0)) for r in today_expenses)
        message = f"📅 **Today's Expenses** ({today_str})\n**Total: ₹{total}**\n\n"

        for exp in today_expenses:
            message += f"• {exp.get('Person', '')} | {exp.get('Category', '')} | ₹{exp.get('Amount (₹)', '0')} | {exp.get('Description', '') or '—'}\n"

        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete last expense."""
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_records()

        if not all_rows:
            await update.message.reply_text("No expenses to delete.")
            return

        last_row = all_rows[-1]
        user_id = update.effective_user.id

        msg = f"""🗑️ Delete this expense?

👤 {last_row.get('Person', '')}
🏷️ {last_row.get('Category', '')}
💰 ₹{last_row.get('Amount (₹)', '0')}
📝 {last_row.get('Description', '') or '—'}

Reply: **confirm** to delete"""

        await update.message.reply_text(msg, parse_mode='Markdown')

        if user_id not in context.user_data:
            context.user_data[user_id] = {}
        context.user_data[user_id]['pending_delete'] = True
        context.user_data[user_id]['delete_row_index'] = len(all_rows)

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def edit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit last expense."""
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_records()

        if not all_rows:
            await update.message.reply_text("No expenses to edit.")
            return

        last_row = all_rows[-1]
        user_id = update.effective_user.id

        msg = f"""✏️ Edit last expense:

👤 Person: {last_row.get('Person', '')}
🏷️ Category: {last_row.get('Category', '')}
💰 Amount: ₹{last_row.get('Amount (₹)', '0')}
📝 Description: {last_row.get('Description', '') or '—'}

Reply: **field value**
Example: "category Groceries" or "amount 500" """

        await update.message.reply_text(msg, parse_mode='Markdown')

        if user_id not in context.user_data:
            context.user_data[user_id] = {}
        context.user_data[user_id]['pending_edit'] = True
        context.user_data[user_id]['edit_row_index'] = len(all_rows)

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all valid categories."""
    fixed = ["Salary", "Rent", "EMI", "Education Loan", "Credit Card", "Insurance", "Subscriptions", "SIP"]
    variable = ["Groceries", "Utilities", "Transport", "Dining Out", "Entertainment", "Healthcare", "Shopping", "Education", "Miscellaneous", "CC Payment"]

    msg = """📊 **Expense Categories**

**Fixed:**
""" + ", ".join(fixed) + """

**Variable:**
""" + ", ".join(variable)

    await update.message.reply_text(msg, parse_mode='Markdown')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help."""
    await start(update, context)

def main():
    request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30)
    app = Application.builder().token(TELEGRAM_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("edit", edit_cmd))
    app.add_handler(CommandHandler("categories", categories))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
