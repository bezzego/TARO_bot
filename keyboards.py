from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# Main menu keyboard for client
main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Записаться")],
        [KeyboardButton(text="✒️ Выбрать вопрос / расклад")],
        [KeyboardButton(text="📋 Мои записи")],
        [KeyboardButton(text="ℹ Помощь")]
    ],
    resize_keyboard=True
)


# --- Inline-клавиатуры для «Выбрать вопрос / расклад» ---

def kb_choose_type():
    """Выбор: собрать свой (вопросы) или готовый расклад."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Выбрать вопросы из списка", callback_data="spread_type|questions")],
        [InlineKeyboardButton(text="📦 Готовый расклад", callback_data="spread_type|ready")],
    ])


def kb_ready_category():
    """Категории готовых раскладов: Отношения / Общие."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💕 Отношения", callback_data="ready_cat|relations")],
        [InlineKeyboardButton(text="📌 Общие", callback_data="ready_cat|general")],
    ])


def kb_ready_spreads(spreads: list):
    """Список готовых раскладов (кнопки по одному)."""
    buttons = []
    for s in spreads:
        # callback_data до 64 байт; id короткий
        buttons.append([InlineKeyboardButton(
            text=f"{s['name']} — {s['price']}₽",
            callback_data=f"ready|{s['id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_after_ready_spread(spread_id: str):
    """После показа расклада: записаться с этим раскладом."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться с этим раскладом", callback_data=f"book_ready|{spread_id}")],
    ])


def kb_question_categories():
    """Категории вопросов для «собери свой расклад»."""
    from spreads_data import QUESTION_CATEGORIES
    buttons = []
    labels = {
        "sex": "🔞 Секс",
        "relations": "💕 Отношения",
        "universal": "✨ Универсальные (свободные)",
        "friendship": "🫶 Дружба",
    }
    for cid in QUESTION_CATEGORIES.keys():
        buttons.append([InlineKeyboardButton(
            text=labels.get(cid, cid),
            callback_data=f"qcat|{cid}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_after_question_selection(count: int, amount: int):
    """После ввода номеров вопросов: записаться с выбранными (не используем callback, просто кнопка в сообщении или текст)."""
    # Можно было бы inline "Записаться", но тогда нужен callback с сохранением в state.
    # Проще: отправить текст "Нажмите /book_selected чтобы записаться" или показать reply-кнопку.
    # Лучше inline с callback book_custom — в callback мы возьмём из state выбранные вопросы и перейдём в запись.
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📅 Записаться с выбранными ({count} вопр. — {amount}₽)",
            callback_data="book_custom"
        )],
    ])

# Keyboard with contact-request button
contact_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Отправить номер", request_contact=True)]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# Keyboard for finishing photo uploads
done_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Готово")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)