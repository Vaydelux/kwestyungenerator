import os
import json
import requests
import asyncio
import telegram
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, ConversationHandler, filters
)

# === CONFIG ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MODEL_NAME = "gemini-2.5-pro"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"

# === Conversation States ===
ASK_TOPIC = 1

# === LET Reviewer Prompt Builder ===
def build_mcq_prompt(topic: str) -> str:
    return (
        "You are a Philippine LET (Licensure Examination for Teachers) reviewer assistant. "
        f"Search from known LET reviewer materials and generate 30 multiple choice questions for the topic: '{topic}'. "
        "Each item must be relevant to the LET exam scope and include four choices: 'a', 'b', 'c', and 'd'. "
        "Also include the correct answer using the format: 'answer': 'a'. "
        "Return only a JSON array like the example below:\n\n"
        "[\n"
        "  {\n"
        "    'question': '...',\n"
        "    'a': '...',\n"
        "    'b': '...',\n"
        "    'c': '...',\n"
        "    'd': '...',\n"
        "    'answer': '...'\n"
        "  },\n"
        "  ... (19 more)\n"
        "]"
    )

def build_explanation_prompt(questions: list) -> str:
    return (
        "For each question object in the JSON array below, add a field called 'explanation'. "
        "The explanation must be concise (under 100 characters) must be (2 sentences). Only return valid JSON. No extra text.\n\n"
        f"{json.dumps(questions, indent=2)}"
    )

# === Gemini API Request ===
def ask_gemini(prompt: str):
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    try:
        res = requests.post(GEMINI_URL, headers=headers, json=payload)
        res.raise_for_status()
        reply = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        start = reply.find("[")
        end = reply.rfind("]") + 1
        return json.loads(reply[start:end])
    except Exception as e:
        print("Gemini Error:", e)
        return None

# === Send Quiz Polls ===
async def send_polls(bot, chat_id, quiz_data):
    for i, q in enumerate(quiz_data, start=1):
        options = [q.get(k, "") for k in ("a", "b", "c", "d")]
        explanation = q.get("explanation", "")

        correct_letter = q.get("answer", "").strip().upper()
        letter_to_index = {"A": 0, "B": 1, "C": 2, "D": 3}
        correct_index = letter_to_index.get(correct_letter, 0)

        msg = await bot.send_message(chat_id=chat_id, text=f"🔹 Question no. {i}")
        await asyncio.sleep(2)
        await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
        await asyncio.sleep(2)

        bold_question = f"*{telegram.helpers.escape_markdown(q.get('question', ''), version=2)}*"
        await bot.send_poll(
            chat_id=chat_id,
            question=bold_question,
            options=options,
            type="quiz",
            correct_option_id=correct_index,
            explanation=explanation,
            is_anonymous=False
        )
        await asyncio.sleep(3)

# === /start Command ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧠 I am your Philippine LET Reviewer bot.\n"
        "What topic do you want to generate MCQs for?\n\n"
        "📌 In group, please reply with the topic and mention me like this:\n"
        "`@YourBotName Professional Education`", parse_mode="Markdown"
    )
    return ASK_TOPIC

# === Handle Topic Input ===
async def handle_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_input = message.text.strip()
    chat_type = message.chat.type

    # In group, only proceed if bot is mentioned
    if chat_type in ["group", "supergroup"]:
        bot_username = context.bot.username.lower()
        if f"@{bot_username}" not in user_input.lower():
            return  # Do not respond unless mentioned

        # Remove bot mention from the topic
        user_input = user_input.replace(f"@{bot_username}", "").strip()

    chat_id = update.effective_chat.id
    await message.reply_text(f"⏳ Generating 20 LET MCQs for topic: *{user_input}*", parse_mode="Markdown")

    raw_mcqs = ask_gemini(build_mcq_prompt(user_input))
    if not raw_mcqs:
        await message.reply_text("❌ Gemini failed to generate questions.")
        return ConversationHandler.END

    enriched_mcqs = ask_gemini(build_explanation_prompt(raw_mcqs))
    if not enriched_mcqs:
        await message.reply_text("❌ Gemini failed to add explanations.")
        return ConversationHandler.END

    await send_polls(context.bot, chat_id, enriched_mcqs)
    await message.reply_text("✅ Quiz complete!")
    return ConversationHandler.END

# === Cancel Command ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Quiz canceled.")
    return ConversationHandler.END

# === Fallback Handler ===
async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_input = message.text.strip()

    if message.chat.type in ["group", "supergroup"]:
        bot_username = context.bot.username.lower()
        if f"@{bot_username}" not in user_input.lower():
            return

    await message.reply_text("Please use /start to begin.")

# === Main App ===
if __name__ == "__main__":
    print("🤖 LET Reviewer Bot is running...")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ASK_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_topic)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    app.run_polling()
