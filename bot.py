import logging
import random
from enum import Enum, auto
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# ─────────────────────────── CONFIG ───────────────────────────
BOT_TOKEN = "СЮДА_ВСТАВЬ_СВОЙ_ТОКЕН"

# ─────────────────────────── LOGGING ──────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ─────────────────────────── STATES ───────────────────────────
class UserState(Enum):
    IDLE = auto()        # Ничего не делает
    SEARCHING = auto()   # Ищет собеседника
    CHATTING = auto()    # В чате


# ──────────────── IN-MEMORY STORAGE (простая БД) ──────────────
# user_id → UserState
user_states: dict[int, UserState] = {}

# user_id → partner_user_id  (взаимная связь)
partners: dict[int, int] = {}

# Очередь ожидающих поиска
search_queue: list[int] = []

# Статистика
total_chats: int = 0


# ─────────────────────── HELPER FUNCS ─────────────────────────
def get_state(user_id: int) -> UserState:
    return user_states.get(user_id, UserState.IDLE)


def set_state(user_id: int, state: UserState) -> None:
    user_states[user_id] = state


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура главного меню."""
    keyboard = [
        ["🔍 Найти собеседника"],
        ["ℹ️ Помощь"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_chat_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура во время чата."""
    keyboard = [
        ["⏭ Следующий", "🛑 Остановить"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_search_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура во время поиска."""
    keyboard = [
        ["❌ Отменить поиск"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────── CONNECT / DISCONNECT ─────────────────
async def connect_users(
    user1: int, user2: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Соединяет двух пользователей."""
    global total_chats
    total_chats += 1

    partners[user1] = user2
    partners[user2] = user1
    set_state(user1, UserState.CHATTING)
    set_state(user2, UserState.CHATTING)

    text = (
        "🎉 <b>Собеседник найден!</b>\n\n"
        "Вы можете общаться анонимно.\n"
        "Нажмите <b>⏭ Следующий</b> чтобы найти нового собеседника,\n"
        "или <b>🛑 Остановить</b> чтобы завершить диалог."
    )

    await context.bot.send_message(
        chat_id=user1, text=text, parse_mode="HTML", reply_markup=get_chat_keyboard()
    )
    await context.bot.send_message(
        chat_id=user2, text=text, parse_mode="HTML", reply_markup=get_chat_keyboard()
    )


async def disconnect_user(
    user_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    notify_partner: bool = True,
    reason: str = "🔚 Собеседник покинул чат.",
) -> int | None:
    """Отключает пользователя от партнёра. Возвращает ID партнёра."""
    partner_id = partners.pop(user_id, None)
    set_state(user_id, UserState.IDLE)

    if partner_id is not None:
        partners.pop(partner_id, None)
        set_state(partner_id, UserState.IDLE)

        if notify_partner:
            await context.bot.send_message(
                chat_id=partner_id,
                text=reason,
                reply_markup=get_main_keyboard(),
            )

    return partner_id


# ─────────────────────── COMMAND HANDLERS ─────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка /start."""
    user = update.effective_user
    user_id = user.id

    # Если пользователь в чате — отключаем
    if get_state(user_id) == UserState.CHATTING:
        await disconnect_user(user_id, context)
    elif get_state(user_id) == UserState.SEARCHING:
        if user_id in search_queue:
            search_queue.remove(user_id)

    set_state(user_id, UserState.IDLE)

    welcome = (
        f"👋 <b>Привет, {user.first_name}!</b>\n\n"
        "Это бот для <b>анонимного общения</b>.\n"
        "Нажми <b>🔍 Найти собеседника</b> — и я подберу тебе случайного человека.\n\n"
        "Никто не узнает, кто ты. Полная анонимность! 🕶\n\n"
        "Используй /help для подробностей."
    )

    await update.message.reply_text(
        welcome,
        parse_mode="HTML",
        reply_markup=get_main_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка /help."""
    help_text = (
        "📖 <b>Как пользоваться ботом</b>\n\n"
        "1️⃣ Нажми <b>🔍 Найти собеседника</b> — бот поставит тебя в очередь.\n"
        "2️⃣ Как только найдётся другой человек, вы будете соединены.\n"
        "3️⃣ Пишите друг другу — бот пересылает сообщения анонимно.\n"
        "4️⃣ Поддерживаются: текст, фото, видео, голосовые, стикеры, "
        "документы, GIF, видеосообщения.\n\n"
        "🔧 <b>Команды:</b>\n"
        "/start — перезапустить бота\n"
        "/help — эта справка\n"
        "/search — найти собеседника\n"
        "/stop — остановить диалог\n"
        "/next — найти нового собеседника\n"
        "/stats — статистика бота\n\n"
        "⚠️ <b>Правила:</b>\n"
        "• Будьте вежливы\n"
        "• Не спамьте\n"
        "• Не отправляйте запрещённый контент"
    )

    await update.message.reply_text(help_text, parse_mode="HTML")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начать поиск собеседника."""
    user_id = update.effective_user.id
    state = get_state(user_id)

    # Уже в чате
    if state == UserState.CHATTING:
        await update.message.reply_text(
            "⚠️ Вы уже в чате! Сначала завершите текущий диалог.\n"
            "Нажмите <b>🛑 Остановить</b> или <b>⏭ Следующий</b>.",
            parse_mode="HTML",
        )
        return

    # Уже ищет
    if state == UserState.SEARCHING:
        await update.message.reply_text(
            "🔍 Вы уже в очереди поиска. Подождите...",
            reply_markup=get_search_keyboard(),
        )
        return

    # Ставим в очередь
    set_state(user_id, UserState.SEARCHING)

    # Проверяем, есть ли кто-то в очереди
    if search_queue:
        # Берём первого из очереди
        partner_id = search_queue.pop(0)

        # Проверка что партнёр всё ещё ищет
        if get_state(partner_id) != UserState.SEARCHING:
            # Партнёр уже не ищет — добавляем себя
            search_queue.append(user_id)
            await update.message.reply_text(
                "🔍 <b>Ищу собеседника...</b>\n"
                "Подождите, пока кто-нибудь подключится.",
                parse_mode="HTML",
                reply_markup=get_search_keyboard(),
            )
            return

        # Соединяем
        await connect_users(user_id, partner_id, context)
    else:
        search_queue.append(user_id)
        queue_size = len(search_queue)
        await update.message.reply_text(
            f"🔍 <b>Ищу собеседника...</b>\n"
            f"Вы в очереди. Ожидающих: {queue_size}\n"
            f"Подождите, пока кто-нибудь подключится.",
            parse_mode="HTML",
            reply_markup=get_search_keyboard(),
        )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Остановить чат."""
    user_id = update.effective_user.id
    state = get_state(user_id)

    if state == UserState.CHATTING:
        await disconnect_user(user_id, context)
        await update.message.reply_text(
            "🛑 Вы завершили диалог.",
            reply_markup=get_main_keyboard(),
        )
    elif state == UserState.SEARCHING:
        if user_id in search_queue:
            search_queue.remove(user_id)
        set_state(user_id, UserState.IDLE)
        await update.message.reply_text(
            "❌ Поиск отменён.",
            reply_markup=get_main_keyboard(),
        )
    else:
        await update.message.reply_text(
            "ℹ️ Вы сейчас не в чате и не ищете собеседника.",
            reply_markup=get_main_keyboard(),
        )


async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Найти нового собеседника (отключиться от текущего и сразу искать)."""
    user_id = update.effective_user.id
    state = get_state(user_id)

    if state == UserState.CHATTING:
        await disconnect_user(user_id, context)
        await update.message.reply_text("🔄 Ищу нового собеседника...")

    elif state == UserState.SEARCHING:
        await update.message.reply_text(
            "🔍 Вы уже ищете собеседника...",
            reply_markup=get_search_keyboard(),
        )
        return

    # Запускаем поиск
    await cmd_search(update, context)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Статистика бота."""
    online = len(user_states)
    chatting = sum(1 for s in user_states.values() if s == UserState.CHATTING)
    searching = len(search_queue)

    stats_text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: {online}\n"
        f"💬 Сейчас в чатах: {chatting}\n"
        f"🔍 Ищут собеседника: {searching}\n"
        f"📈 Всего чатов создано: {total_chats}"
    )

    await update.message.reply_text(stats_text, parse_mode="HTML")


# ─────────────────── BUTTON TEXT HANDLERS ─────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий кнопок Reply-клавиатуры."""
    text = update.message.text
    user_id = update.effective_user.id

    if text == "🔍 Найти собеседника":
        await cmd_search(update, context)
    elif text == "⏭ Следующий":
        await cmd_next(update, context)
    elif text == "🛑 Остановить":
        await cmd_stop(update, context)
    elif text == "❌ Отменить поиск":
        await cmd_stop(update, context)
    elif text == "ℹ️ Помощь":
        await cmd_help(update, context)
    else:
        # Это обычное текстовое сообщение — пересылаем собеседнику
        await forward_message(update, context)


# ─────────────────── MESSAGE FORWARDING ───────────────────────
async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пересылка сообщения собеседнику (анонимно)."""
    user_id = update.effective_user.id
    state = get_state(user_id)

    if state != UserState.CHATTING:
        if state == UserState.SEARCHING:
            await update.message.reply_text(
                "🔍 Вы ещё ищете собеседника. Подождите...",
                reply_markup=get_search_keyboard(),
            )
        else:
            await update.message.reply_text(
                'ℹ️ Вы не в чате. Нажмите <b>"🔍 Найти собеседника"</b> чтобы начать.',
                parse_mode="HTML",
                reply_markup=get_main_keyboard(),
            )
        return

    partner_id = partners.get(user_id)
    if partner_id is None:
        set_state(user_id, UserState.IDLE)
        await update.message.reply_text(
            "⚠️ Произошла ошибка. Собеседник не найден.",
            reply_markup=get_main_keyboard(),
        )
        return

    message = update.message

    try:
        # Текст
        if message.text:
            await context.bot.send_message(
                chat_id=partner_id,
                text=f"💬 {message.text}",
            )

        # Фото
        elif message.photo:
            photo = message.photo[-1]  # лучшее качество
            caption = f"💬 {message.caption}" if message.caption else None
            await context.bot.send_photo(
                chat_id=partner_id,
                photo=photo.file_id,
                caption=caption,
            )

        # Видео
        elif message.video:
            caption = f"💬 {message.caption}" if message.caption else None
            await context.bot.send_video(
                chat_id=partner_id,
                video=message.video.file_id,
                caption=caption,
            )

        # Голосовое сообщение
        elif message.voice:
            await context.bot.send_voice(
                chat_id=partner_id,
                voice=message.voice.file_id,
            )

        # Видеосообщение (кружок)
        elif message.video_note:
            await context.bot.send_video_note(
                chat_id=partner_id,
                video_note=message.video_note.file_id,
            )

        # Стикер
        elif message.sticker:
            await context.bot.send_sticker(
                chat_id=partner_id,
                sticker=message.sticker.file_id,
            )

        # GIF (анимация)
        elif message.animation:
            caption = f"💬 {message.caption}" if message.caption else None
            await context.bot.send_animation(
                chat_id=partner_id,
                animation=message.animation.file_id,
                caption=caption,
            )

        # Документ
        elif message.document:
            caption = f"💬 {message.caption}" if message.caption else None
            await context.bot.send_document(
                chat_id=partner_id,
                document=message.document.file_id,
                caption=caption,
            )

        # Аудио
        elif message.audio:
            caption = f"💬 {message.caption}" if message.caption else None
            await context.bot.send_audio(
                chat_id=partner_id,
                audio=message.audio.file_id,
                caption=caption,
            )

        # Контакт
        elif message.contact:
            await context.bot.send_contact(
                chat_id=partner_id,
                phone_number=message.contact.phone_number,
                first_name=message.contact.first_name,
                last_name=message.contact.last_name or "",
            )

        # Локация
        elif message.location:
            await context.bot.send_location(
                chat_id=partner_id,
                latitude=message.location.latitude,
                longitude=message.location.longitude,
            )

        # Dice (кубик, казино и т.д.)
        elif message.dice:
            await context.bot.send_dice(
                chat_id=partner_id,
                emoji=message.dice.emoji,
            )

        # Неподдерживаемый тип
        else:
            await update.message.reply_text(
                "⚠️ Этот тип сообщения не поддерживается."
            )

    except Exception as e:
        logger.error(f"Ошибка пересылки сообщения: {e}")
        await update.message.reply_text(
            "⚠️ Не удалось доставить сообщение. Возможно, собеседник заблокировал бота."
        )
        await disconnect_user(user_id, context, notify_partner=False)
        await update.message.reply_text(
            "🔚 Диалог завершён.", reply_markup=get_main_keyboard()
        )


# ─────────────────── MAIN ─────────────────────────────────────
def main() -> None:
    """Запуск бота."""
    if BOT_TOKEN == "СЮДА_ВСТАВЬ_СВОЙ_ТОКЕН":
        print("❌ ОШИБКА: Вставьте токен бота в переменную BOT_TOKEN!")
        print("   Получить токен можно у @BotFather в Telegram.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("search", cmd_search))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(CommandHandler("next", cmd_next))
    application.add_handler(CommandHandler("stats", cmd_stats))

    # Кнопки Reply-клавиатуры (конкретные тексты)
    button_texts = filters.Text(
        [
            "🔍 Найти собеседника",
            "⏭ Следующий",
            "🛑 Остановить",
            "❌ Отменить поиск",
            "ℹ️ Помощь",
        ]
    )
    application.add_handler(MessageHandler(button_texts, button_handler))

    # Все остальные сообщения — пересылка собеседнику
    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND & ~button_texts,
            forward_message,
        )
    )

    print("✅ Бот запущен! Нажмите Ctrl+C для остановки.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
