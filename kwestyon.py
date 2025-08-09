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

# === Global Variable ===
bot_username = None  # global variable to store bot's username

async def fetch_bot_username(app):
    global bot_username
    me = await app.bot.get_me()
    bot_username = me.username.lower()


# === Optimized LET Reviewer Prompt with Explanation Included ===
def build_mcq_prompt(topic: str) -> str:
    return (
        "You are a Philippine LET (Licensure Examination for Teachers) reviewer assistant. "
        f"Generate 20 multiple choice questions for the topic: '{topic}'.\n"
        "Each question object must include:\n"
        "- 'question': the question text (max 280 characters)\n"
        "- 'a', 'b', 'c', 'd': answer choices (max 100 characters total per choice)\n"
        "- 'answer': correct letter (a/b/c/d)\n"
        "- 'keywords': 3–6 short keywords or hints (comma-separated) that summarize the main concepts in the question \n"
        "   • (useful for quick recall during review)\n"
        "- 'explanation': a clear 2–3 sentence explanation that:\n"
        "   • States why the correct answer is correct\n"
        "   • Mentions relevant subtopics or concepts\n"
        "   • Includes any important theory, law, or rule related to the topic\n"
        "Return only a JSON array, like this example:\n"
        "[\n"
        "  {\n"
        "    \"question\": \"...\",\n"
        "    \"a\": \"...\",\n"
        "    \"b\": \"...\",\n"
        "    \"c\": \"...\",\n"
        "    \"d\": \"...\",\n"
        "    \"answer\": \"a\",\n"
        "    \"keywords\": \",\n"
        "    \"explanation\": \"Short but informative reason referencing related theory or subtopic.\"\n"
        "  }\n"
        "]"
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
async def send_polls(bot, chat_id, quiz_data, thread_id=None):
    for i, q in enumerate(quiz_data, start=1):
        options = [q.get(k, "") for k in ("a", "b", "c", "d")]
        explanation = q.get("explanation", "")
        keywords = q.get("keywords", "")
        correct_letter = q.get("answer", "").strip().lower()
        letter_to_index = {"a": 0, "b": 1, "c": 2, "d": 3}
        correct_index = letter_to_index.get(correct_letter, 0)

        question_text = f"🔹 Question no. {i}\n{q.get('question', '')}"
        escaped_question = telegram.helpers.escape_markdown(question_text, version=2)
        # spoiler_question = f"||{escaped_question}||"  # Blur the text
        bold_question = f"*{escaped_question}*"


        msg = await bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=bold_question,
            parse_mode="MarkdownV2"
        )
        await asyncio.sleep(2)
        
        await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
        await asyncio.sleep(2)
        
        await bot.send_poll(
            chat_id=chat_id,
            message_thread_id=thread_id,
            question="🔹",
            options=options,
            type="quiz",
            correct_option_id=correct_index,
            #explanation=explanation,
            is_anonymous=False
        )
        
        await asyncio.sleep(2)
        hint_title = "Hint : "
        escaped_hinttitle = telegram.helpers.escape_markdown(hint_title, version=2)
        escaped_hinttext = telegram.helpers.escape_markdown(keywords, version=2)
        spoiler_keyword = f"{escaped_hinttitle} ||{escaped_hinttext}||"
        await bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=spoiler_keyword,
            parse_mode="MarkdownV2"
        )
        
        await asyncio.sleep(2)
        explanation_title = "🔹Explanation: "
        escaped_title = telegram.helpers.escape_markdown(explanation_title, version=2)
        escaped_text = telegram.helpers.escape_markdown(explanation, version=2)
        spoiler_explanation = f"{escaped_title} ||{escaped_text}||"
        await bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=spoiler_explanation,
            parse_mode="MarkdownV2"
        )
        await asyncio.sleep(3)


# === /start Command ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_username
    await update.message.reply_text(
        "🧠 I am your Philippine LET Reviewer bot.\n"
        "What topic do you want to generate MCQs for?\n\n"
        "📌 In group, please reply with the topic and mention me like this:\n"
        f"`@{bot_username} Professional Education`", parse_mode="Markdown"
    )
    return ASK_TOPIC

# === Handle Topic Input ===
async def handle_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_username
    message = update.message
    user_input = message.text.strip()
    chat_type = message.chat.type
    message_thread_id = message.message_thread_id  # 🧵 get topic/thread ID
    

    # In group, only proceed if bot is mentioned
    if chat_type in ["group", "supergroup"]:
        if f"@{bot_username}" not in user_input.lower():
            return  # Do not respond unless mentioned

        # Clean mention after checking / Remove bot mention from the topic
        user_input = user_input.replace(f"@{bot_username}", "").strip()

    chat_id = update.effective_chat.id
    await message.reply_text(f"⏳ Generating 20 LET MCQs for topic: *{user_input}*", parse_mode="Markdown")

    raw_mcqs = ask_gemini(build_mcq_prompt(user_input))
    if not raw_mcqs:
        await message.reply_text("❌ Gemini failed to generate questions.")
        return ConversationHandler.END

    await send_polls(context.bot, chat_id, raw_mcqs, message_thread_id)
    await message.reply_text("✅ Quiz complete!")
    return ConversationHandler.END

# === Cancel Command ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Quiz canceled.", parse_mode="Markdown")
    return ConversationHandler.END

# === Fallback Handler ===
async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id  # for forum/topic messages

    if update.message.chat.type in ["group", "supergroup"]:
        if f"@{bot_username}" not in user_input.lower():
            return

    await context.bot.send_message(
        chat_id=chat_id,
        message_thread_id=thread_id,
        text="Please use /start to begin."
    )
    return ConversationHandler.END
    
# === Main App ===
if __name__ == "__main__":
    print("🤖 LET Reviewer Bot is running...")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Schedule bot username fetch after initialization
    app.post_init = fetch_bot_username

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ASK_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_topic)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    app.run_polling()import os
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

# === Global Variable ===
bot_username = None  # global variable to store bot's username

async def fetch_bot_username(app):
    global bot_username
    me = await app.bot.get_me()
    bot_username = me.username.lower()


# === Optimized LET Reviewer Prompt with Explanation Included ===
def build_mcq_prompt(topic: str) -> str:
    return (
        "You are a Philippine LET (Licensure Examination for Teachers) reviewer assistant. "
        f"Generate 20 multiple choice questions for the topic: '{topic}'.\n"
        "Each question object must include:\n"
        "- 'question': the question text (max 280 characters)\n"
        "- 'a', 'b', 'c', 'd': answer choices (max 100 characters total per choice)\n"
        "- 'answer': correct letter (a/b/c/d)\n"
        "- 'explanation': a clear 2–3 sentence explanation that:\n"
        "   • States why the correct answer is correct\n"
        "   • Mentions relevant subtopics or concepts\n"
        "   • Includes any important theory, law, or rule related to the topic\n"
        "Return only a JSON array, like this example:\n"
        "[\n"
        "  {\n"
        "    \"question\": \"...\",\n"
        "    \"a\": \"...\",\n"
        "    \"b\": \"...\",\n"
        "    \"c\": \"...\",\n"
        "    \"d\": \"...\",\n"
        "    \"answer\": \"a\",\n"
        "    \"explanation\": \"Short but informative reason referencing related theory or subtopic.\"\n"
        "  }\n"
        "]"
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
async def send_polls(bot, chat_id, quiz_data, thread_id=None):
    for i, q in enumerate(quiz_data, start=1):
        options = [q.get(k, "") for k in ("a", "b", "c", "d")]
        explanation = q.get("explanation", "")
        correct_letter = q.get("answer", "").strip().lower()
        letter_to_index = {"a": 0, "b": 1, "c": 2, "d": 3}
        correct_index = letter_to_index.get(correct_letter, 0)

        question_text = f"🔹 Question no. {i}\n{q.get('question', '')}"
        escaped_question = telegram.helpers.escape_markdown(question_text, version=2)
        # spoiler_question = f"||{escaped_question}||"  # Blur the text
        bold_question = f"*{escaped_question}*"


        msg = await bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=bold_question,
            parse_mode="MarkdownV2"
        )
        await asyncio.sleep(2)
        
        await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
        await asyncio.sleep(2)
        
        await bot.send_poll(
            chat_id=chat_id,
            message_thread_id=thread_id,
            question="🔹",
            options=options,
            type="quiz",
            correct_option_id=correct_index,
            #explanation=explanation,
            is_anonymous=False
        )
        
        await asyncio.sleep(2)
        explanation_title = "🔹Explanation: "
        escaped_title = telegram.helpers.escape_markdown(explanation_title, version=2)
        escaped_text = telegram.helpers.escape_markdown(explanation, version=2)
        spoiler_explanation = f"{escaped_title} ||{escaped_text}||"
        msg = await bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=spoiler_explanation,
            parse_mode="MarkdownV2"
        )
        await asyncio.sleep(3)


# === /start Command ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_username
    await update.message.reply_text(
        "🧠 I am your Philippine LET Reviewer bot.\n"
        "What topic do you want to generate MCQs for?\n\n"
        "📌 In group, please reply with the topic and mention me like this:\n"
        f"`@{bot_username} Professional Education`", parse_mode="Markdown"
    )
    return ASK_TOPIC

# === Handle Topic Input ===
async def handle_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_username
    message = update.message
    user_input = message.text.strip()
    chat_type = message.chat.type
    message_thread_id = message.message_thread_id  # 🧵 get topic/thread ID
    

    # In group, only proceed if bot is mentioned
    if chat_type in ["group", "supergroup"]:
        if f"@{bot_username}" not in user_input.lower():
            return  # Do not respond unless mentioned

        # Clean mention after checking / Remove bot mention from the topic
        user_input = user_input.replace(f"@{bot_username}", "").strip()

    chat_id = update.effective_chat.id
    await message.reply_text(f"⏳ Generating 20 LET MCQs for topic: *{user_input}*", parse_mode="Markdown")

    raw_mcqs = ask_gemini(build_mcq_prompt(user_input))
    if not raw_mcqs:
        await message.reply_text("❌ Gemini failed to generate questions.")
        return ConversationHandler.END

    await send_polls(context.bot, chat_id, raw_mcqs, message_thread_id)
    await message.reply_text("✅ Quiz complete!")
    return ConversationHandler.END

# === Cancel Command ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Quiz canceled.", parse_mode="Markdown")
    return ConversationHandler.END

# === Fallback Handler ===
async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id  # for forum/topic messages

    if update.message.chat.type in ["group", "supergroup"]:
        if f"@{bot_username}" not in user_input.lower():
            return

    await context.bot.send_message(
        chat_id=chat_id,
        message_thread_id=thread_id,
        text="Please use /start to begin."
    )
    return ConversationHandler.END
    
# === Main App ===
if __name__ == "__main__":
    print("🤖 LET Reviewer Bot is running...")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Schedule bot username fetch after initialization
    app.post_init = fetch_bot_username

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ASK_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_topic)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    app.run_polling()
