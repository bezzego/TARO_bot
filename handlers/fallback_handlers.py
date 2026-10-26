"""Ответ на всё, что не подошло ни одному обработчику (подключается последним)."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

import keyboards

router = Router()


@router.message(F.chat.type == "private")
async def unknown_message(message: Message):
    await message.answer(
        "Не получилось разобрать сообщение 🙏 Выберите действие в меню ниже.\n"
        "Если вы были в процессе записи — начните её заново кнопкой «📅 Записаться» или «📞 Записаться на созвон».",
        reply_markup=keyboards.menu_for(message.from_user.id))


@router.callback_query()
async def unknown_callback(callback: CallbackQuery):
    # Кнопки из старых сообщений: без ответа у клиента бесконечно крутится «часики»
    await callback.answer("Эта кнопка устарела. Выберите действие в меню ниже.", show_alert=True)
