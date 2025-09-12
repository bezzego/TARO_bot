from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Main menu keyboard for client
main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Записаться")],
        [KeyboardButton(text="📋 Мои записи")],
        [KeyboardButton(text="ℹ Помощь")]
    ],
    resize_keyboard=True
)

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