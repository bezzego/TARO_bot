import re
import json
import logging
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.fsm.context import FSMContext

import config
import database
import keyboards
from states import BookingState

router = Router()

# Cancel command handler to abort the booking process
@router.message(F.text.lower() == "/cancel")
async def cancel_command(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активного процесса для отмены.", reply_markup=keyboards.main_menu_kb)
    else:
        data = await state.get_data()
        # If a booking was already created and waiting (e.g., slot reserved)
        if data.get("booking_id"):
            booking_id = data["booking_id"]
            record = await database.get_booking_by_id(booking_id)
            if record:
                status = record["status"]
                if status in (config.STATUS_WAITING_PAYMENT, config.STATUS_CHECKING, config.STATUS_CONFIRMED):
                    # Cancel booking in DB and free slot
                    slot_id = record["slot_id"]
                    await database.update_booking_status(booking_id, config.STATUS_CANCELLED)
                    await database.db.execute("UPDATE slots SET is_taken=0 WHERE id=?", (slot_id,))
                    await database.db.commit()
                    logging.info(f"Booking {booking_id} cancelled by user via /cancel")
                    # Notify admin group if a payment was pending or booking confirmed
                    admin_msg_id = record["admin_message_id"]
                    if admin_msg_id:
                        # Edit admin's message to note cancellation
                        try:
                            await config.bot.edit_message_text(chat_id=config.ADMIN_GROUP_ID, message_id=admin_msg_id,
                                                              text=f"Запись #{booking_id} отменена пользователем.")
                        except Exception as e:
                            logging.error(f"Failed to edit admin message for cancellation: {e}")
                    else:
                        # If no admin message existed (cancelled before payment sent), inform admin group
                        try:
                            if config.ADMIN_GROUP_ID:
                                user = message.from_user
                                await config.bot.send_message(config.ADMIN_GROUP_ID,
                                    f"Пользователь {user.full_name} (@{user.username}) отменил запись #{booking_id}.")
                        except Exception as e:
                            logging.error(f"Failed to notify admin of cancellation: {e}")
        await state.clear()
        await message.answer("Запись отменена.", reply_markup=keyboards.main_menu_kb)

# Start command /start - greeting and main menu
@router.message(F.text == "/start")
async def start_command(message: Message, state: FSMContext):
    user = message.from_user
    # Register or update user in database
    await database.get_or_create_user(user.id, user.username, user.full_name)
    # Greeting message with current price fetched from DB
    try:
        price = await database.get_price()
    except Exception:
        # Fallback if DB call fails
        price = 350
    welcome_text = (
        f"Привет! Я бот для записи на расклад. Условия:\n"
        f"1 вопрос = {price} ₽.\n"
        "Для расклада необходимо предоставить историю ситуации, имена всех участников, фото участников, список вопросов и телефон для связи.\n"
        "Запись и оплата проводятся только через этого бота."
    )
    await message.answer(welcome_text, reply_markup=keyboards.main_menu_kb)

# Help menu
@router.message(F.text == "ℹ Помощь")
async def help_command(message: Message):
    help_text = (
        "Чтобы записаться на расклад, нажмите «📅 Записаться» и следуйте инструкциям.\n"
        "В разделе «📋 Мои записи» можно просмотреть ваши записи и их статус, а при необходимости отменить запись.\n"
        "Оплата происходит переводом на указанные реквизиты, после чего нужно отправить фото чека для подтверждения."
    )
    await message.answer(help_text, reply_markup=keyboards.main_menu_kb)

# Begin booking process when user selects "📅 Записаться"
@router.message(F.text == "📅 Записаться")
async def book_appointment(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Пожалуйста, опишите вашу ситуацию (краткая история).", reply_markup=None)
    await state.set_state(BookingState.story)

# State: waiting for the story of the situation
@router.message(BookingState.story)
async def receive_story(message: Message, state: FSMContext):
    if not message.text or message.text.strip() == "":
        await message.answer("Опишите, пожалуйста, вашу ситуацию.")
        return
    await state.update_data(story=message.text.strip())
    await message.answer("Теперь укажите имена всех участников ситуации.")
    await state.set_state(BookingState.participants)

# State: waiting for participants' names
@router.message(BookingState.participants)
async def receive_participants(message: Message, state: FSMContext):
    if not message.text or message.text.strip() == "":
        await message.answer("Введите имена участников (например: Иван, Мария, ...).")
        return
    await state.update_data(participants=message.text.strip())
    # Request photos of all participants
    await message.answer("Прикрепите фото всех участников. После отправки всех фото нажмите кнопку «Готово».", reply_markup=keyboards.done_kb)
    await state.set_state(BookingState.photos)

# State: waiting for photos of participants and then "Готово"
@router.message(BookingState.photos)
async def receive_photos(message: Message, state: FSMContext):
    if message.photo:
        # Collect photo file_id
        photo_id = message.photo[-1].file_id
        data = await state.get_data()
        photos = data.get("photos", [])
        photos.append(photo_id)
        await state.update_data(photos=photos)
        # (No immediate response to avoid flooding the chat for each photo)
        return
    text = (message.text or "").lower()
    if text in ["готово", "/done", "done"]:
        data = await state.get_data()
        photos = data.get("photos", [])
        if not photos:
            await message.answer("Вы не отправили ни одной фотографии. Пожалуйста, отправьте хотя бы одно фото участника.")
            return
        # Proceed to next step: ask for questions
        await message.answer("Теперь отправьте список ваших вопросов (каждый вопрос с новой строки).", reply_markup=None)
        await state.set_state(BookingState.questions)
    else:
        # If some other text was sent instead of photos or "Готово"
        await message.answer("Отправьте фото участников и нажмите «Готово», когда закончите.")

# State: waiting for list of questions
@router.message(BookingState.questions)
async def receive_questions(message: Message, state: FSMContext):
    if not message.text or message.text.strip() == "":
        await message.answer("Введите, пожалуйста, ваши вопросы (каждый вопрос с новой строки).")
        return
    questions_text = message.text.strip()
    # Split by lines to count questions
    question_lines = [q for q in questions_text.splitlines() if q.strip()]
    num_questions = len(question_lines)
    if num_questions == 0:
        await message.answer("Список вопросов пуст. Введите хотя бы один вопрос.")
        return
    price = await database.get_price()
    amount = num_questions * price
    await state.update_data(questions=questions_text, num_questions=num_questions, amount=amount)
    await message.answer(f"Вопросов: {num_questions}. Сумма к оплате: {amount} ₽.")
    # Request phone number
    await message.answer("Теперь отправьте свой номер телефона для связи.", reply_markup=keyboards.contact_kb)
    await state.set_state(BookingState.phone)

# State: waiting for phone contact or manual input
@router.message(BookingState.phone)
async def receive_phone(message: Message, state: FSMContext):
    phone_number = None
    if message.contact:
        phone_number = message.contact.phone_number
    elif message.text:
        raw = message.text.strip()
        digits = re.sub(r"\\D", "", raw)
        if raw.startswith('+'):
            phone_number = '+' + digits
        else:
            if len(digits) == 11 and digits.startswith('8'):
                phone_number = '+7' + digits[1:]
            else:
                phone_number = '+' + digits
        clean_digits = re.sub(r"\\D", "", phone_number)
        if len(clean_digits) < 10 or len(clean_digits) > 15:
            phone_number = None
    if not phone_number:
        await message.answer("Неверный формат номера. Пожалуйста отправьте корректный номер, например +79991234567.", reply_markup=keyboards.contact_kb)
        return
    # Save phone and update user record
    user = message.from_user
    await database.update_user_phone(user.id, phone_number)
    await state.update_data(phone=phone_number)
    # Show available dates
    free_dates = await database.get_free_dates()
    if not free_dates:
        await message.answer("Извините, сейчас нет доступных дат для записи. Попробуйте позже.", reply_markup=keyboards.main_menu_kb)
        await state.clear()
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    date_buttons = []
    for date_str in free_dates:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            display = dt.strftime("%d.%m.%Y")
        except:
            display = date_str
        date_buttons.append([InlineKeyboardButton(text=display, callback_data=f"date|{date_str}")])

    date_kb = InlineKeyboardMarkup(inline_keyboard=date_buttons)
    await message.answer("Выберите дату:", reply_markup=date_kb)
    await state.set_state(BookingState.select_date)

# State: waiting for date selection (inline button)
@router.callback_query(BookingState.select_date)
async def select_date_callback(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    if not data or not data.startswith("date|"):
        await callback.answer()
        return
    selected_date = data.split("|", 1)[1]
    free_times = await database.get_free_times(selected_date)
    if not free_times:
        # No times available for that date (possibly taken just now)
        await callback.answer("Нет доступного времени на эту дату.", show_alert=True)
        free_dates = await database.get_free_dates()
        if free_dates:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            date_buttons = []
            for date_str in free_dates:
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    display = dt.strftime("%d.%m.%Y")
                except:
                    display = date_str
                date_buttons.append([InlineKeyboardButton(text=display, callback_data=f"date|{date_str}")])
            date_kb = InlineKeyboardMarkup(inline_keyboard=date_buttons)
            try:
                await callback.message.edit_text("Выберите дату:", reply_markup=date_kb)
            except:
                await callback.message.answer("Выберите дату:", reply_markup=date_kb)
            # Remain in select_date state
        else:
            await callback.message.edit_text("Нет доступных слотов для записи на текущий момент.")
            await state.clear()
        await callback.answer()
        return
    # List available times for selected date
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    time_buttons = [
        [InlineKeyboardButton(text=time, callback_data=f"time|{slot_id}")]
        for slot_id, time in free_times
    ]
    time_kb = InlineKeyboardMarkup(inline_keyboard=time_buttons)
    try:
        await callback.message.edit_text(f"Дата {datetime.strptime(selected_date, '%Y-%m-%d').strftime('%d.%m.%Y')} выбрана. Выберите время:", reply_markup=time_kb)
    except:
        await callback.message.answer("Выберите время:", reply_markup=time_kb)
    await state.update_data(selected_date=selected_date)
    await state.set_state(BookingState.select_time)
    await callback.answer()

# State: waiting for time selection (inline button)
@router.callback_query(BookingState.select_time)
async def select_time_callback(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    if not data or not data.startswith("time|"):
        await callback.answer()
        return
    try:
        slot_id = int(data.split("|", 1)[1])
    except:
        await callback.answer()
        return
    fsm_data = await state.get_data()
    story = fsm_data.get("story")
    participants = fsm_data.get("participants")
    photos = fsm_data.get("photos", [])
    questions = fsm_data.get("questions")
    num_questions = fsm_data.get("num_questions", 0)
    amount = fsm_data.get("amount", 0)
    user_id = callback.from_user.id
    booking_id = await database.reserve_slot_and_create_booking(user_id, slot_id, story, participants, photos, questions, num_questions, amount)
    if not booking_id:
        # If slot just got taken by someone else
        free_times = await database.get_free_times(fsm_data.get("selected_date"))
        if free_times:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            time_buttons = [
                [InlineKeyboardButton(text=t, callback_data=f"time|{sid}")]
                for sid, t in free_times
            ]
            time_kb = InlineKeyboardMarkup(inline_keyboard=time_buttons)
            try:
                await callback.message.edit_text("Выберите время:", reply_markup=time_kb)
            except:
                await callback.message.answer("Выберите время:", reply_markup=time_kb)
            await callback.answer("Выбранное время уже занято, выберите другое.", show_alert=True)
            return
        else:
            # If no times left on that date, go back to date selection
            free_dates = await database.get_free_dates()
            if free_dates:
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                date_buttons = []
                for date_str in free_dates:
                    try:
                        dt = datetime.strptime(date_str, "%Y-%m-%d")
                        display = dt.strftime("%d.%m.%Y")
                    except:
                        display = date_str
                    date_buttons.append([InlineKeyboardButton(text=display, callback_data=f"date|{date_str}")])
                date_kb = InlineKeyboardMarkup(inline_keyboard=date_buttons)
                await callback.message.edit_text("Выберите дату:", reply_markup=date_kb)
                await state.set_state(BookingState.select_date)
            else:
                await callback.message.edit_text("Свободные слоты отсутствуют.")
                await state.clear()
            await callback.answer("Выбранное время уже занято.", show_alert=True)
            return
    # Slot reserved and booking created
    await state.update_data(booking_id=booking_id)
    # Remove the times keyboard from the message
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    # Compose payment instructions
    slot_cur = await database.db.execute("SELECT date, time FROM slots WHERE id=?", (slot_id,))
    slot_row = await slot_cur.fetchone()
    if slot_row:
        date_obj = datetime.strptime(slot_row['date'], "%Y-%m-%d")
        date_disp = date_obj.strftime("%d.%m.%Y")
        time_str = slot_row['time']
    else:
        date_disp = fsm_data.get('selected_date')
        time_str = ""
    pay_text = (f"Слот {date_disp} {time_str} зарезервирован на 15 минут.\n"
                f"Оплатите {amount} ₽ по реквизитам:\n"
                "Сбербанк: 2202 2061 5913 1163 (Сергей Александрович С.)\n"
                "Тинькофф: 2200 7017 1423 6749 (Арианна С.)\n"
                "В комментарии к переводу укажите имя отправителя и последние 4 цифры карты.\n"
                "После оплаты отправьте фото чека.")
    await callback.message.answer(pay_text)
    await state.set_state(BookingState.waiting_receipt)
    # Schedule auto-unlock job in 15 minutes
    from scheduler import scheduler, unlock_timeout
    run_time = datetime.now() + timedelta(minutes=15)
    try:
        scheduler.add_job(unlock_timeout, "date", run_date=run_time, args=[booking_id], id=f"unlock_{booking_id}")
    except Exception as e:
        logging.error(f"Failed to schedule unlock job: {e}")
    await callback.answer()

# State: waiting for payment receipt photo
@router.message(BookingState.waiting_receipt)
async def receive_receipt(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Пожалуйста, отправьте фотографию чека об оплате.")
        return
    data = await state.get_data()
    booking_id = data.get("booking_id")
    if not booking_id:
        await message.answer("Ошибка: нет активной записи.", reply_markup=keyboards.main_menu_kb)
        await state.clear()
        return
    record = await database.get_booking_by_id(booking_id)
    if not record or record["status"] != config.STATUS_WAITING_PAYMENT:
        await message.answer("Время ожидания истекло или запись уже отменена.", reply_markup=keyboards.main_menu_kb)
        await state.clear()
        return
    # Update status to "CHECKING" (awaiting admin confirmation)
    await database.update_booking_status(booking_id, config.STATUS_CHECKING)
    # Cancel the scheduled unlock job
    from scheduler import scheduler
    try:
        scheduler.remove_job(f"unlock_{booking_id}")
    except Exception as e:
        logging.warning(f"Unlock job removal failed or not found: {e}")
    # Notify admin group with booking details
    details = await database.get_booking_details(booking_id)
    if details:
        user_name = details["user_name"] or ""
        username = details["username"] or ""
        phone = details["phone"] or ""
        story = details["story"] or ""
        participants = details["participants"] or ""
        questions = details["questions"] or ""
        date = details["date"] or ""
        time = details["time"] or ""
        num_q = details["num_questions"]
        amount = details["amount"]
        photos_json = details["photos"]
        participant_photos = []
        if photos_json:
            try:
                participant_photos = json.loads(photos_json)
            except:
                participant_photos = []
        # Send participants' photos to admin group
        try:
            if participant_photos:
                media_group = []
                for idx, pid in enumerate(participant_photos):
                    if idx == 0:
                        media_group.append(InputMediaPhoto(media=pid, caption=f"Фото участников (запись #{booking_id})"))
                    else:
                        media_group.append(InputMediaPhoto(media=pid))
                await config.bot.send_media_group(chat_id=config.ADMIN_GROUP_ID, media=media_group)
        except Exception as e:
            # Handle possible supergroup migration: extract new chat id and retry once
            err_text = str(e)
            logging.error(f"Failed to send participant photos to admin group: {err_text}")
            m = re.search(r"-100\d+", err_text)
            if m:
                try:
                    new_id = int(m.group())
                    config.ADMIN_GROUP_ID = new_id
                    logging.info(f"Detected admin group migration. Updating ADMIN_GROUP_ID to {new_id} and retrying media group send.")
                    if participant_photos:
                        media_group = []
                        for idx, pid in enumerate(participant_photos):
                            if idx == 0:
                                media_group.append(InputMediaPhoto(media=pid, caption=f"Фото участников (запись #{booking_id})"))
                            else:
                                media_group.append(InputMediaPhoto(media=pid))
                        await config.bot.send_media_group(chat_id=config.ADMIN_GROUP_ID, media=media_group)
                except Exception as e2:
                    logging.error(f"Retry after migration failed: {e2}")
        # Send payment receipt photo
        try:
            receipt_file_id = message.photo[-1].file_id
            await config.bot.send_photo(chat_id=config.ADMIN_GROUP_ID, photo=receipt_file_id, caption=f"Чек от @{username or user_name}")
        except Exception as e:
            err_text = str(e)
            logging.error(f"Failed to send receipt photo to admin group: {err_text}")
            m = re.search(r"-100\d+", err_text)
            if m:
                try:
                    new_id = int(m.group())
                    config.ADMIN_GROUP_ID = new_id
                    logging.info(f"Detected admin group migration. Updating ADMIN_GROUP_ID to {new_id} and retrying receipt send.")
                    await config.bot.send_photo(chat_id=config.ADMIN_GROUP_ID, photo=receipt_file_id, caption=f"Чек от @{username or user_name}")
                except Exception as e2:
                    logging.error(f"Retry after migration (receipt) failed: {e2}")
        # Send booking details text with inline confirm/reject buttons
        details_text = (
            f"Запись #{booking_id}\n"
            f"Клиент: {user_name} (@{username})\n"
            f"Телефон: {phone}\n"
            f"История: {story}\n"
            f"Участники: {participants}\n"
            f"Вопросов: {num_q}\n"
            f"Вопросы: {questions}\n"
            f"Дата и время: {datetime.strptime(date, '%Y-%m-%d').strftime('%d.%m.%Y')} {time}\n"
            f"Сумма: {amount} ₽\n"
            f"Статус: Ожидает подтверждения оплаты"
        )
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить чек", callback_data=f"confirm|{booking_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject|{booking_id}")
            ]
        ])
        try:
            sent_msg = await config.bot.send_message(chat_id=config.ADMIN_GROUP_ID, text=details_text, reply_markup=admin_kb)
            await database.set_booking_admin_message_id(booking_id, sent_msg.message_id)
        except Exception as e:
            err_text = str(e)
            logging.error(f"Failed to send booking details to admin group: {err_text}")
            m = re.search(r"-100\d+", err_text)
            if m:
                try:
                    new_id = int(m.group())
                    config.ADMIN_GROUP_ID = new_id
                    logging.info(f"Detected admin group migration. Updating ADMIN_GROUP_ID to {new_id} and retrying details send.")
                    sent_msg = await config.bot.send_message(chat_id=config.ADMIN_GROUP_ID, text=details_text, reply_markup=admin_kb)
                    await database.set_booking_admin_message_id(booking_id, sent_msg.message_id)
                except Exception as e2:
                    logging.error(f"Retry after migration (details) failed: {e2}")
    # Acknowledge user
    await message.answer("Чек получен. Ожидайте подтверждения администрации.", reply_markup=keyboards.main_menu_kb)
    await state.clear()

# List the user's bookings and provide cancel options
@router.message(F.text == "📋 Мои записи")
async def list_bookings(message: Message):
    user_id = message.from_user.id
    records = await database.get_user_bookings(user_id)
    if not records or len(records) == 0:
        await message.answer("У вас нет активных записей.", reply_markup=keyboards.main_menu_kb)
    else:
        text_lines = ["Ваши записи:"]
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = []
        for rec in records:
            status = rec["status"]
            date = rec["date"]
            time = rec["time"]
            # Map status to Russian text
            if status == config.STATUS_WAITING_PAYMENT:
                status_text = "Ожидает оплаты"
            elif status == config.STATUS_CHECKING:
                status_text = "На подтверждении"
            elif status == config.STATUS_CONFIRMED:
                status_text = "Подтверждена"
            else:
                status_text = status
            date_display = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
            text_lines.append(f"- {date_display} {time} — {status_text}")
            buttons.append([InlineKeyboardButton(text=f"Отменить {date_display} {time}", callback_data=f"cancel|{rec['id']}")])
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("\n".join(text_lines), reply_markup=cancel_kb)

# Handle inline cancel button for a specific booking
@router.callback_query(F.data.startswith("cancel|"))
async def cancel_booking_callback(callback: CallbackQuery, state: FSMContext):
    try:
        booking_id = int(callback.data.split("|", 1)[1])
    except:
        await callback.answer()
        return
    record = await database.get_booking_by_id(booking_id)
    if record is None or record["user_id"] != callback.from_user.id:
        await callback.answer("Ошибка или запись не найдена.", show_alert=True)
        return
    status = record["status"]
    if status in (config.STATUS_WAITING_PAYMENT, config.STATUS_CHECKING, config.STATUS_CONFIRMED):
        await database.update_booking_status(booking_id, config.STATUS_CANCELLED)
        await database.db.execute("UPDATE slots SET is_taken=0 WHERE id=?", (record["slot_id"],))
        await database.db.commit()
        logging.info(f"Booking {booking_id} cancelled by user via inline button")
        # Remove scheduled unlock job (if any)
        from scheduler import scheduler
        try:
            scheduler.remove_job(f"unlock_{booking_id}")
        except:
            pass
        # Notify admin group
        admin_msg_id = record["admin_message_id"]
        if admin_msg_id:
            try:
                await config.bot.edit_message_text(chat_id=config.ADMIN_GROUP_ID, message_id=admin_msg_id,
                                                  text=f"Запись #{booking_id} отменена пользователем.")
            except Exception as e:
                logging.error(f"Failed to edit admin message on user cancel: {e}")
        else:
            try:
                if config.ADMIN_GROUP_ID:
                    await config.bot.send_message(config.ADMIN_GROUP_ID,
                        f"Запись #{booking_id} отменена пользователем (до оплаты).")
            except Exception as e:
                logging.error(f"Failed to notify admin group of cancellation: {e}")
        # Update the list message by removing inline keyboard
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except:
            pass
        # Optionally, update the list of bookings
        await list_bookings(callback.message)
        await callback.answer("Запись отменена.", show_alert=False)
    else:
        await callback.answer("Нельзя отменить эту запись.", show_alert=True)