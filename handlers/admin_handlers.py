import logging
from datetime import datetime

from aiogram import Router
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

import config
import database
from states import AdminState

router = Router()

# Helper to check if a user is admin
def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

# Admin: view current schedule
@router.message(lambda msg: msg.text and msg.text.startswith('/schedule'))
async def schedule_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    slots = await database.get_all_slots()
    if not slots or len(slots) == 0:
        await message.answer("Расписание пусто. Добавьте слоты через /addslot.")
    else:
        schedule_text = "Расписание:\n"
        current_date = None
        for row in slots:
            date = row["date"]
            time = row["time"]
            taken = row["is_taken"] == 1
            if current_date != date:
                current_date = date
                date_display = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
                schedule_text += f"\n{date_display}:\n"
            status_text = "занято" if taken else "свободно"
            schedule_text += f"  {time} — {status_text}\n"
        schedule_text += "\nДобавить слот: /addslot DD.MM.YYYY HH:MM\nУдалить слот: /delslot DD.MM.YYYY HH:MM (только свободные)\n"
        await message.answer(schedule_text)

# Admin: add a slot (optionally with arguments)
@router.message(lambda msg: msg.text and msg.text.startswith('/addslot'))
async def addslot_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    slot_info = parts[1] if len(parts) > 1 else None
    if not slot_info:
        await message.answer("Введите дату и время для нового слота (в формате ДД.ММ.ГГГГ ЧЧ:ММ):")
        await state.set_state(AdminState.adding_slot)
    else:
        try:
            date_str, time_str = slot_info.split()
            date_obj = datetime.strptime(date_str, "%d.%m.%Y")
            date_iso = date_obj.strftime("%Y-%m-%d")
            time_obj = datetime.strptime(time_str, "%H:%M")
            time_fmt = time_obj.strftime("%H:%M")
        except Exception:
            await message.answer("Неверный формат. Используйте: /addslot ДД.ММ.ГГГГ ЧЧ:ММ")
            return
        success = await database.add_slot(date_iso, time_fmt)
        if success:
            await message.answer(f"Слот {date_str} {time_fmt} добавлен в расписание.")
        else:
            await message.answer("Не удалось добавить слот. Возможно, такой слот уже существует.")

# State: waiting for slot date/time (interactive add slot)
@router.message(AdminState.adding_slot)
async def adding_slot_state(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = message.text.strip()
    try:
        date_str, time_str = text.split()
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
        date_iso = date_obj.strftime("%Y-%m-%d")
        time_obj = datetime.strptime(time_str, "%H:%M")
        time_fmt = time_obj.strftime("%H:%M")
    except Exception:
        await message.answer("Неверный формат. Введите в формате ДД.ММ.ГГГГ ЧЧ:ММ или /cancel для отмены.")
        return
    success = await database.add_slot(date_iso, time_fmt)
    if success:
        await message.answer(f"Слот {date_str} {time_fmt} добавлен.")
    else:
        await message.answer("Не удалось добавить слот. Возможно, он уже существует или данные некорректны.")
    await state.clear()

# Admin: remove a slot
@router.message(lambda msg: msg.text and msg.text.startswith('/delslot'))
async def delslot_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    slot_info = parts[1] if len(parts) > 1 else None
    if not slot_info:
        await message.answer("Введите дату и время слота для удаления (ДД.ММ.ГГГГ ЧЧ:ММ):")
        await state.set_state(AdminState.deleting_slot)
    else:
        try:
            date_str, time_str = slot_info.split()
            date_obj = datetime.strptime(date_str, "%d.%m.%Y")
            date_iso = date_obj.strftime("%Y-%m-%d")
            time_obj = datetime.strptime(time_str, "%H:%M")
            time_fmt = time_obj.strftime("%H:%M")
        except Exception:
            await message.answer("Неверный формат. Используйте: /delslot ДД.ММ.ГГГГ ЧЧ:ММ")
            return
        result = await database.remove_slot(date_iso, time_fmt)
        if result == 1:
            await message.answer(f"Слот {date_str} {time_fmt} удалён.")
        elif result == 0:
            await message.answer("Слот не найден.")
        elif result == -1:
            await message.answer("Нельзя удалить занятый слот (уже есть запись).")
        else:
            await message.answer("Ошибка при удалении слота.")

# State: waiting for slot date/time (interactive delete slot)
@router.message(AdminState.deleting_slot)
async def deleting_slot_state(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = message.text.strip()
    try:
        date_str, time_str = text.split()
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
        date_iso = date_obj.strftime("%Y-%m-%d")
        time_obj = datetime.strptime(time_str, "%H:%M")
        time_fmt = time_obj.strftime("%H:%M")
    except Exception:
        await message.answer("Неверный формат. Попробуйте снова или /cancel для отмены.")
        return
    result = await database.remove_slot(date_iso, time_fmt)
    if result == 1:
        await message.answer(f"Слот {date_str} {time_fmt} удалён.")
    elif result == 0:
        await message.answer("Слот не найден или уже удалён.")
    elif result == -1:
        await message.answer("Этот слот занят и не может быть удалён.")
    else:
        await message.answer("Ошибка при удалении слота.")
    await state.clear()

# Admin: change price per question
@router.message(lambda msg: msg.text and msg.text.startswith('/price'))
async def price_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) == 1:
        current_price = await database.get_price()
        await message.answer(f"Текущая стоимость вопроса: {current_price} ₽. Используйте '/price N' для изменения цены.")
    else:
        try:
            new_price = int(parts[1])
        except:
            await message.answer("Пожалуйста, укажите новую цену числом.")
            return
        await database.db.execute("UPDATE settings SET value=? WHERE key='price_per_question'", (str(new_price),))
        await database.db.commit()
        logging.info(f"Admin changed price to {new_price}")
        await message.answer(f"Цена за вопрос изменена на {new_price} ₽.")

# Admin: list all bookings (summary)
@router.message(lambda msg: msg.text and msg.text.startswith('/bookings'))
async def bookings_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    records = await database.get_all_bookings()
    if not records or len(records) == 0:
        await message.answer("Записей не найдено.")
    else:
        text_lines = ["Список записей:"]
        for rec in records:
            date = rec["date"]
            time = rec["time"]
            status = rec["status"]
            name = rec["user_name"] or "<имя>"
            username = rec["username"] or ""
            date_display = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
            if status == config.STATUS_WAITING_PAYMENT:
                status_text = "Ожидает оплаты"
            elif status == config.STATUS_CHECKING:
                status_text = "На подтверждении"
            elif status == config.STATUS_CONFIRMED:
                status_text = "Подтверждена"
            elif status == config.STATUS_REJECTED:
                status_text = "Отклонена"
            elif status == config.STATUS_CANCELLED:
                status_text = "Отменена"
            else:
                status_text = status
            text_lines.append(f"- {date_display} {time} — {name} (@{username}) — {status_text}")
        await message.answer("\n".join(text_lines))

# Admin: unlock a slot manually (cancel booking if needed)
@router.message(lambda msg: msg.text and msg.text.startswith('/unlockslot'))
async def unlockslot_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    slot_info = parts[1] if len(parts) > 1 else None
    if not slot_info:
        await message.answer("Укажите дату и время слота для разблокировки (ДД.ММ.ГГГГ ЧЧ:ММ):")
        await state.set_state(AdminState.unlocking_slot)
    else:
        try:
            date_str, time_str = slot_info.split()
            date_obj = datetime.strptime(date_str, "%d.%m.%Y")
            date_iso = date_obj.strftime("%Y-%m-%d")
            time_obj = datetime.strptime(time_str, "%H:%M")
            time_fmt = time_obj.strftime("%H:%M")
        except Exception:
            await message.answer("Неверный формат. Используйте: /unlockslot ДД.ММ.ГГГГ ЧЧ:ММ")
            return
        await handle_unlock(date_iso, time_fmt, message)

# State: waiting for slot date/time (interactive unlock slot)
@router.message(AdminState.unlocking_slot)
async def unlocking_slot_state(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = message.text.strip()
    try:
        date_str, time_str = text.split()
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
        date_iso = date_obj.strftime("%Y-%m-%d")
        time_obj = datetime.strptime(time_str, "%H:%M")
        time_fmt = time_obj.strftime("%H:%M")
    except Exception:
        await message.answer("Неверный формат. Попробуйте снова или /cancel для отмены.")
        return
    await handle_unlock(date_iso, time_fmt, message)
    await state.clear()

async def handle_unlock(date_iso: str, time_fmt: str, message: Message):
    """Helper to unlock a slot given date (YYYY-MM-DD) and time (HH:MM)."""
    cur = await database.db.execute("SELECT id, is_taken FROM slots WHERE date=? AND time=?", (date_iso, time_fmt))
    slot = await cur.fetchone()
    if slot is None:
        await message.answer("Слот не найден.")
        return
    slot_id = slot["id"]
    if slot["is_taken"] == 0:
        await message.answer("Слот уже свободен.")
        return
    # Slot is taken, find active booking for this slot
    cur_b = await database.db.execute(
        "SELECT id, status, user_id, admin_message_id FROM bookings WHERE slot_id=? AND status NOT IN (?, ?)",
        (slot_id, config.STATUS_CANCELLED, config.STATUS_REJECTED)
    )
    booking = await cur_b.fetchone()
    if booking is None:
        # No active booking but slot marked taken - free it
        await database.db.execute("UPDATE slots SET is_taken=0 WHERE id=?", (slot_id,))
        await database.db.commit()
        await message.answer("Слот разблокирован.")
        logging.info(f"Slot {slot_id} unlocked (no active booking found).")
        return
    booking_id = booking["id"]
    status = booking["status"]
    user_id = booking["user_id"]
    admin_msg_id = booking["admin_message_id"]
    if status == config.STATUS_WAITING_PAYMENT:
        # Cancel booking and free slot
        await database.update_booking_status(booking_id, config.STATUS_CANCELLED)
        await database.db.execute("UPDATE slots SET is_taken=0 WHERE id=?", (slot_id,))
        await database.db.commit()
        from scheduler import scheduler
        try:
            scheduler.remove_job(f"unlock_{booking_id}")
        except:
            pass
        # Notify user
        try:
            await config.bot.send_message(user_id, "Ваша запись была отменена администратором (истек лимит времени оплаты).")
        except Exception as e:
            logging.error(f"Failed to notify user about unlock: {e}")
        await message.answer("Слот разблокирован. Бронирование отменено (оплата не поступила).")
    elif status == config.STATUS_CHECKING:
        # Payment was sent but not confirmed yet – reject it
        await database.update_booking_status(booking_id, config.STATUS_REJECTED)
        await database.db.execute("UPDATE slots SET is_taken=0 WHERE id=?", (slot_id,))
        await database.db.commit()
        try:
            await config.bot.send_message(user_id, "Оплата не подтверждена, ваша запись отклонена. Слот освобожден.")
        except Exception as e:
            logging.error(f"Failed to notify user about rejection: {e}")
        if admin_msg_id:
            try:
                await config.bot.edit_message_text(chat_id=config.ADMIN_GROUP_ID, message_id=admin_msg_id,
                                                  text=f"Запись #{booking_id} отклонена (разблокирована администратором).")
            except Exception as e:
                logging.error(f"Failed to edit admin message: {e}")
        await message.answer("Слот разблокирован. Запись отклонена.")
    elif status == config.STATUS_CONFIRMED:
        # Booking was confirmed – cancel it
        await database.update_booking_status(booking_id, config.STATUS_CANCELLED)
        await database.db.execute("UPDATE slots SET is_taken=0 WHERE id=?", (slot_id,))
        await database.db.commit()
        try:
            await config.bot.send_message(user_id, f"Ваша подтвержденная запись на {datetime.strptime(date_iso, '%Y-%m-%d').strftime('%d.%m.%Y')} {time_fmt} отменена администратором.")
        except Exception as e:
            logging.error(f"Failed to notify user of admin cancellation: {e}")
        if admin_msg_id:
            try:
                await config.bot.edit_message_text(chat_id=config.ADMIN_GROUP_ID, message_id=admin_msg_id,
                                                  text=f"Запись #{booking_id} отменена администратором.")
            except Exception as e:
                logging.error(f"Failed to edit admin message for cancel: {e}")
        await message.answer("Слот разблокирован. Подтвержденная запись отменена.")
    else:
        await message.answer("Запись уже отменена.")
        
# Admin: confirm payment (from inline button in admin group)
@router.callback_query(lambda c: c.data and c.data.startswith('confirm|'))
async def confirm_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        booking_id = int(callback.data.split('|')[1])
    except:
        await callback.answer()
        return
    details = await database.get_booking_details(booking_id)
    if not details or details["status"] != config.STATUS_CHECKING:
        await callback.answer("Не удалось подтвердить (статус изменился).", show_alert=True)
        return
    # Mark as confirmed
    await database.update_booking_status(booking_id, config.STATUS_CONFIRMED)
    # Cancel any pending unlock job
    from scheduler import scheduler
    try:
        scheduler.remove_job(f"unlock_{booking_id}")
    except:
        pass
    user_id = details["user_id"]
    date = details["date"]; time = details["time"]
    date_disp = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
    # Notify user
    try:
        await config.bot.send_message(user_id, f"Ваша запись подтверждена, расклад будет отправлен {date_disp} с 13:00 до 18:00 (МСК).")
    except Exception as e:
        logging.error(f"Failed to notify user {user_id} of confirmation: {e}")
    # Update admin group's message text
    if details["admin_message_id"]:
        try:
            text = callback.message.text or ""
            if "Статус:" in text:
                new_text = text.split("Статус:")[0] + "Статус: Подтверждена"
            else:
                new_text = text + "\nСтатус: Подтверждена"
            await callback.message.edit_text(new_text)
        except Exception as e:
            logging.error(f"Failed to edit admin group message text: {e}")
    await callback.answer("✅ Подтверждено")

# Admin: reject payment (from inline button in admin group)
@router.callback_query(lambda c: c.data and c.data.startswith('reject|'))
async def reject_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        booking_id = int(callback.data.split('|')[1])
    except:
        await callback.answer()
        return
    details = await database.get_booking_details(booking_id)
    if not details or details["status"] != config.STATUS_CHECKING:
        await callback.answer("Не удалось отклонить (статус изменился).", show_alert=True)
        return
    # Mark as rejected and free slot
    await database.update_booking_status(booking_id, config.STATUS_REJECTED)
    await database.db.execute("UPDATE slots SET is_taken=0 WHERE id=?", (details["slot_id"],))
    await database.db.commit()
    user_id = details["user_id"]
    date = details["date"]; time = details["time"]
    date_disp = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
    # Notify user
    try:
        await config.bot.send_message(user_id, "Ваш платеж не подтвержден. Запись отклонена, слот освобожден. Вы можете записаться снова.")
    except Exception as e:
        logging.error(f"Failed to notify user {user_id} of rejection: {e}")
    # Update admin group's message text
    if details["admin_message_id"]:
        try:
            text = callback.message.text or ""
            if "Статус:" in text:
                new_text = text.split("Статус:")[0] + "Статус: Отклонена"
            else:
                new_text = text + "\nСтатус: Отклонена"
            await callback.message.edit_text(new_text)
        except Exception as e:
            logging.error(f"Failed to edit admin group message text on reject: {e}")
    await callback.answer("❌ Отклонено", show_alert=False)