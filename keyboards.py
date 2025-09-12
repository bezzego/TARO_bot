from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Main menu keyboard for client
main_menu_kb = ReplyKeyboardMarkup(resize_keyboard=True)
main_menu_kb.add(KeyboardButton("📅 Записаться"))
main_menu_kb.add(KeyboardButton("📋 Мои записи"))
main_menu_kb.add(KeyboardButton("ℹ Помощь"))

# Keyboard with contact-request button
contact_kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
contact_kb.add(KeyboardButton("📱 Отправить номер", request_contact=True))

# Keyboard for finishing photo uploads
done_kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
done_kb.add(KeyboardButton("Готово"))