import os
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
import sqlite3
from uuid import uuid4
import logging
import asyncio
import traceback

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация Flask
app = Flask(__name__)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect("support_bot.db")
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS tickets
                 (ticket_id TEXT, user_id INTEGER, username TEXT, moderator_id INTEGER, moderator_username TEXT, status TEXT)"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS ratings
                 (ticket_id TEXT, rating INTEGER)"""
    )
    conn.commit()
    conn.close()

# Функции для работы с базой данных
def create_ticket(user_id, username):
    ticket_id = str(uuid4())
    conn = sqlite3.connect("support_bot.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO tickets (ticket_id, user_id, username, status) VALUES (?, ?, ?, ?)",
        (ticket_id, user_id, username, "open"),
    )
    conn.commit()
    conn.close()
    return ticket_id

def update_ticket(ticket_id, moderator_id=None, moderator_username=None, status=None):
    conn = sqlite3.connect("support_bot.db")
    c = conn.cursor()
    if moderator_id:
        c.execute(
            "UPDATE tickets SET moderator_id = ?, moderator_username = ?, status = ? WHERE ticket_id = ?",
            (moderator_id, moderator_username, "in_progress", ticket_id),
        )
    elif status:
        c.execute("UPDATE tickets SET status = ? WHERE ticket_id = ?", (status, ticket_id))
    conn.commit()
    conn.close()

def save_rating(ticket_id, rating):
    conn = sqlite3.connect("support_bot.db")
    c = conn.cursor()
    c.execute("INSERT INTO ratings (ticket_id, rating) VALUES (?, ?)", (ticket_id, rating))
    conn.commit()
    conn.close()

# Состояния разговора
CHOOSE_MODERATOR, AWAITING_RESPONSE, AWAITING_RATING = range(3)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    logger.info(f"User {user.id} started the bot")
    keyboard = [[InlineKeyboardButton("Я не бот", callback_data="verify")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋 Я бот техподдержки **DRΛVΣX Support**.  \n"
        "Помогу тебе с любыми вопросами! Нажми кнопку ниже, чтобы подтвердить, что ты не бот.  \n"
        "Затем напиши свой вопрос, и модератор скоро ответит. Когда решишь все вопросы, пожалуйста, нажми кнопку 'Завершить диалог', чтобы закрыть тикет — это поможет нашей администрации не перегружаться. Спасибо! 😊",
        reply_markup=reply_markup,
    )
    return CHOOSE_MODERATOR

# Подтверждение пользователя
async def verify_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    ticket_id = create_ticket(user.id, user.username or user.first_name)
    context.user_data["ticket_id"] = ticket_id
    logger.info(f"User {user.id} verified, ticket {ticket_id} created")

    keyboard = [[InlineKeyboardButton("Взять тикет", callback_data=f"take_{ticket_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id="-1002672157892",
        text=f"Новый запрос от {user.first_name} (@{user.username or 'без имени'})",
        reply_markup=reply_markup,
    )

    await query.message.reply_text("Напиши свой вопрос, модератор скоро ответит.")
    return AWAITING_RESPONSE

# Обработка сообщения пользователя
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message_text = update.message.text.lower() if update.message and update.message.text else ""
    if "vpn" in message_text or "vpn.arturshi.ru" in message_text:
        logger.warning(f"VPN-related message blocked from user {user.id}: {message_text}")
        await update.message.reply_text("Сообщения о VPN не разрешены.")
        return

    ticket_id = context.user_data.get("ticket_id")
    if not ticket_id:
        await update.message.reply_text("Начни с команды /start.")
        return

    conn = sqlite3.connect("support_bot.db")
    c = conn.cursor()
    c.execute("SELECT moderator_id FROM tickets WHERE ticket_id = ?", (ticket_id,))
    result = c.fetchone()
    conn.close()

    if not result or not result[0]:
        await update.message.reply_text("Ждем модератора...")
        await context.bot.forward_message(
            chat_id="-1002672157892",
            from_chat_id=user.id,
            message_id=update.message.message_id,
        )
    else:
        moderator_id = result[0]
        await context.bot.forward_message(
            chat_id=moderator_id,
            from_chat_id=user.id,
            message_id=update.message.message_id,
        )
    logger.info(f"Message from user {user.id} forwarded for ticket {ticket_id}")

# Модератор берет тикет
async def take_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    ticket_id = query.data.split("_")[1]
    moderator = update.effective_user
    moderator_name = moderator.username or moderator.first_name

    conn = sqlite3.connect("support_bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM tickets WHERE ticket_id = ?", (ticket_id,))
    result = c.fetchone()
    conn.close()

    if not result:
        await query.message.reply_text("Тикет не найден.")
        logger.error(f"Ticket {ticket_id} not found")
        return

    user_id, username = result
    update_ticket(ticket_id, moderator.id, moderator_name)
    await query.message.reply_text(f"Ты взял тикет от {username}. Пиши ответ сюда.")
    await context.bot.send_message(
        chat_id=user_id,
        text=f"Модератор @{moderator_name} взял твой запрос.",
    )
    logger.info(f"Moderator {moderator.id} took ticket {ticket_id}")

# Ответ модератора
async def handle_moderator_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != "-1002672157892":
        return

    message_text = update.message.text.lower() if update.message and update.message.text else ""
    if "vpn" in message_text or "vpn.arturshi.ru" in message_text:
        logger.warning(f"VPN-related message blocked from moderator: {message_text}")
        await update.message.reply_text("Сообщения о VPN не разрешены.")
        return

    moderator = update.effective_user
    conn = sqlite3.connect("support_bot.db")
    c = conn.cursor()
    c.execute("SELECT ticket_id, user_id FROM tickets WHERE moderator_id = ? AND status = ?", (moderator.id, "in_progress"))
    result = c.fetchone()
    conn.close()

    if not result:
        await update.message.reply_text("У тебя нет активных тикетов.")
        return

    ticket_id, user_id = result
    await context.bot.send_message(chat_id=user_id, text=update.message.text)
    keyboard = [[InlineKeyboardButton("Завершить", callback_data=f"finish_{ticket_id}")]]
    await context.bot.send_message(
        chat_id=user_id,
        text="Если вопросов нет, нажми 'Завершить'.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    logger.info(f"Moderator {moderator.id} responded to ticket {ticket_id}")

# Завершение диалога
async def finish_dialogue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    ticket_id = query.data.split("_")[1]
    user = update.effective_user

    conn = sqlite3.connect("support_bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id, status FROM tickets WHERE ticket_id = ?", (ticket_id,))
    result = c.fetchone()
    if not result or result[0] != user.id:
        await query.message.reply_text("Ты не можешь завершить этот диалог.")
        conn.close()
        return
    if result[1] != "in_progress":
        await query.message.reply_text("Диалог уже завершен.")
        conn.close()
        return
    conn.close()

    keyboard = [[InlineKeyboardButton(str(i), callback_data=f"rate_{ticket_id}_{i}") for i in range(1, 6)]]
    await query.message.reply_text("Оцени работу модератора (1–5):", reply_markup=InlineKeyboardMarkup(keyboard))
    update_ticket(ticket_id, status="awaiting_rating")
    logger.info(f"User {user.id} requested to finish ticket {ticket_id}")

# Обработка рейтинга
async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, ticket_id, rating = query.data.split("_")
    rating = int(rating)

    conn = sqlite3.connect("support_bot.db")
    c = conn.cursor()
    c.execute("SELECT username, moderator_username FROM tickets WHERE ticket_id = ?", (ticket_id,))
    result = c.fetchone()
    conn.close()

    if not result:
        await query.message.reply_text("Тикет не найден.")
        logger.error(f"Ticket {ticket_id} not found during rating")
        return ConversationHandler.END

    username, moderator_username = result
    save_rating(ticket_id, rating)
    update_ticket(ticket_id, status="closed")

    await context.bot.send_message(
        chat_id="-1002672157892",
        text=f"{username} оценил модератора @{moderator_username} на {rating}/5.",
    )
    await query.message.reply_text("Спасибо за оценку! Диалог завершен.")
    logger.info(f"User {username} rated moderator {moderator_username} {rating}/5 for ticket {ticket_id}")
    return ConversationHandler.END

# Команда /active_tickets
async def active_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != "-1002672157892":
        await update.message.reply_text("Эта команда только для модераторов.")
        return

    conn = sqlite3.connect("support_bot.db")
    c = conn.cursor()
    c.execute("SELECT ticket_id, username, status, moderator_username FROM tickets WHERE status != ?", ("closed",))
    results = c.fetchall()
    conn.close()

    if not results:
        await update.message.reply_text("Нет активных тикетов.")
        return

    response = "Активные тикеты:\n"
    for ticket_id, username, status, mod_username in results:
        assigned = f"Модератор: @{mod_username}" if mod_username else "Без модератора"
        response += f"- {username} ({status}): {assigned}\n"
    await update.message.reply_text(response)
    logger.info("Active tickets requested by moderator")

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Я бот техподдержки DRΛVΣX Support! 😊\n"
        "Вот что я умею:\n"
        "- Напиши /start, чтобы задать вопрос.\n"
        "- После ответа модератора нажми 'Завершить' и оцени работу.\n"
        "- Модераторы могут видеть тикеты через /active_tickets."
    )

# Инициализация Telegram-бота
bot_token = "7792029680:AAGOTtdBmgPj6oJa7INA9pPy95Cqvv7AZJw"
application = Application.builder().token(bot_token).build()

# Настройка обработчиков
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        CHOOSE_MODERATOR: [CallbackQueryHandler(verify_user, pattern="^verify$", per_message=True)],
        AWAITING_RESPONSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message)],
        AWAITING_RATING: [CallbackQueryHandler(handle_rating, pattern="^rate_", per_message=True)],
    },
    fallbacks=[],
)

application.add_handler(conv_handler)
application.add_handler(CallbackQueryHandler(take_ticket, pattern="^take_", per_message=True))
application.add_handler(CallbackQueryHandler(finish_dialogue, pattern="^finish_", per_message=True))
application.add_handler(CommandHandler("active_tickets", active_tickets))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_moderator_message))
application.add_handler(MessageHandler(filters.ALL, handle_user_message))

# Инициализация базы данных
init_db()

# Flask-роут для вебхука
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        logger.info("Received webhook request")
        data = request.get_json(force=True)
        logger.info(f"Webhook data: {data}")
        if "vpn" in str(data).lower() or "vpn.arturshi.ru" in str(data):
            logger.warning("VPN-related message detected in webhook data")
            return "VPN-related content blocked", 403
        update = Update.de_json(data, application.bot)
        if update is None:
            logger.error("Failed to parse update from webhook data")
            return "Failed to parse update", 400
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(application.process_update(update))
        loop.close()
        logger.info("Webhook processed successfully")
        return "OK"
    except Exception as e:
        logger.error(f"Error in webhook: {str(e)}")
        logger.error(traceback.format_exc())
        return "Error", 500

# Установка вебхука при запуске
@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    try:
        webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/webhook"
        logger.info(f"Setting webhook to {webhook_url}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(application.bot.set_webhook(webhook_url))
        loop.close()
        if result:
            logger.info(f"Webhook set to {webhook_url}")
            return "Webhook set"
        else:
            logger.error("Failed to set webhook")
            return "Failed to set webhook"
    except Exception as e:
        logger.error(f"Error setting webhook: {str(e)}")
        logger.error(traceback.format_exc())
        return "Error setting webhook", 500