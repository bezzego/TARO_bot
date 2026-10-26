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
import bot_texts
import admin_notify
import spreads_data
from states import BookingState, ChooseQuestionState

router = Router()

# Нажатие кнопки меню не считается ответом на шаг записи
NOT_MENU = ~F.text.in_(keyboards.MENU_TEXTS)

# Cancel command handler to abort the booking process
@router.message(F.text.lower() == "/cancel")
async def cancel_command(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активного процесса для отмены.", reply_markup=keyboards.menu_for(message.from_user.id))
    else:
        data = await state.get_data()
        cancelled = False
        # If a booking was already created and waiting (e.g., slot reserved)
        if data.get("booking_id"):
            booking_id = data["booking_id"]
            record = await database.get_booking_by_id(booking_id)
            if record:
                status = record["status"]
                if status in (config.STATUS_WAITING_PAYMENT, config.STATUS_CHECKING):
                    # Cancel booking in DB and free slot
                    await database.update_booking_status(booking_id, config.STATUS_CANCELLED)
                    await database.free_booking_slots(record)
                    await database.db.commit()
                    logging.info(f"Booking {booking_id} cancelled by user via /cancel")
                    cancelled = True
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
        if cancelled:
            await message.answer("Запись отменена.", reply_markup=keyboards.menu_for(message.from_user.id))
        else:
            await message.answer("Процесс отменен. Возвращаемся в главное меню.", reply_markup=keyboards.menu_for(message.from_user.id))

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
        price = 350
    await message.answer(bot_texts.welcome_text(price), reply_markup=keyboards.menu_for(message.from_user.id), parse_mode="HTML")

# Help menu
@router.message(F.text == "ℹ Помощь")
async def help_command(message: Message):
    await message.answer(bot_texts.help_text(), reply_markup=keyboards.menu_for(message.from_user.id), parse_mode="HTML")


# --- Выбрать вопрос / готовый расклад ---
@router.message(F.text == "📋 Выбрать вопрос / расклад")
async def choose_question_or_spread(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Вы можете <b>выбрать вопросы из списка</b> (собрать свой расклад) или выбрать <b>готовый расклад</b> с фиксированными вопросами и ценой.",
        reply_markup=keyboards.kb_choose_type(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "spread_type|questions")
@router.callback_query(F.data == "spread_type|ready")
async def spread_type_callback(callback: CallbackQuery, state: FSMContext):
    if callback.data == "spread_type|questions":
        await callback.message.edit_text(
            "Выберите категорию вопросов. Затем вам будет показан нумерованный список — напишите номера нужных вопросов через запятую (например: 1, 5, 10).\n\n"
            f"Стоимость одного вопроса из списка — <b>{spreads_data.QUESTION_PRICE}₽</b>.",
            reply_markup=keyboards.kb_question_categories(),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            "Выберите категорию готовых раскладов:",
            reply_markup=keyboards.kb_ready_category()
        )
    await callback.answer()


@router.callback_query(F.data.startswith("ready_cat|"))
async def ready_category_callback(callback: CallbackQuery, state: FSMContext):
    cat = callback.data.split("|", 1)[1]
    spreads = spreads_data.get_ready_spreads_by_category(cat)
    if not spreads:
        await callback.answer("Нет раскладов в этой категории.", show_alert=True)
        return
    label = "Отношения" if cat == "relations" else "Общие"
    await callback.message.edit_text(
        f"Готовые расклады — <b>{label}</b>. Выберите расклад:",
        reply_markup=keyboards.kb_ready_spreads(spreads),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ready|"))
async def show_ready_spread_callback(callback: CallbackQuery, state: FSMContext):
    spread_id = callback.data.split("|", 1)[1]
    spread = spreads_data.get_ready_spread_by_id(spread_id)
    if not spread:
        await callback.answer("Расклад не найден.", show_alert=True)
        return
    text = spreads_data.format_ready_spread_text(spread)
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.kb_after_ready_spread(spread_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("book_ready|"))
async def book_with_ready_spread_callback(callback: CallbackQuery, state: FSMContext):
    spread_id = callback.data.split("|", 1)[1]
    spread = spreads_data.get_ready_spread_by_id(spread_id)
    if not spread:
        await callback.answer("Расклад не найден.", show_alert=True)
        return
    questions_text = "\n".join(spread["questions"])
    await state.clear()
    await state.set_state(BookingState.story)
    await state.update_data(
        prefilled_questions=questions_text,
        prefilled_num_questions=len(spread["questions"]),
        prefilled_amount=spread["price"],
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"Вы выбрали расклад «{spread['name']}» ({spread['price']}₽).\n\n"
        "Пожалуйста, опишите вашу ситуацию (краткая история).",
        reply_markup=keyboards.menu_for(callback.from_user.id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("qcat|"))
async def question_category_callback(callback: CallbackQuery, state: FSMContext):
    cat_id = callback.data.split("|", 1)[1]
    questions = spreads_data.get_category_questions(cat_id)
    title = spreads_data.get_category_title(cat_id)
    if not questions:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    lines = [f"{title}", "", "Напишите номера нужных вопросов через запятую (например: 1, 5, 10):", ""]
    for i, q in enumerate(questions, 1):
        lines.append(f"{i}. {q}")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = "\n".join(lines[:3] + [f"{i}. {q}" for i, q in enumerate(questions[:50], 1)])
        text += "\n\n... (показаны первые 50). Напишите номера через запятую."
    await state.set_state(ChooseQuestionState.enter_numbers)
    await state.update_data(question_category_id=cat_id, question_list=questions)
    try:
        await callback.message.edit_text(text)
    except Exception:
        await callback.message.answer(text)
    await callback.answer()


@router.message(ChooseQuestionState.enter_numbers, F.text, NOT_MENU)
async def receive_question_numbers(message: Message, state: FSMContext):
    data = await state.get_data()
    questions = data.get("question_list", [])
    if not questions:
        await message.answer("Ошибка: список вопросов не найден. Начните заново из меню «Выбрать вопрос / расклад».", reply_markup=keyboards.menu_for(message.from_user.id))
        await state.clear()
        return
    raw = message.text.strip().replace(" ", "")
    parts = re.split(r"[,;\s]+", raw)
    indices = []
    for p in parts:
        if not p:
            continue
        try:
            n = int(p)
            if 1 <= n <= len(questions):
                indices.append(n)
        except ValueError:
            pass
    indices = sorted(set(indices))
    if not indices:
        await message.answer(
            f"Не удалось разобрать номера. Введите числа от 1 до {len(questions)} через запятую (например: 1, 5, 10)."
        )
        return
    selected = [questions[i - 1] for i in indices]
    amount = len(selected) * spreads_data.QUESTION_PRICE
    await state.update_data(
        selected_questions="\n".join(selected),
        selected_num_questions=len(selected),
        selected_amount=amount,
    )
    summary = (
        f"Выбрано вопросов: <b>{len(selected)}</b>. Сумма: <b>{amount}₽</b>.\n\n"
        "Нажмите кнопку ниже, чтобы записаться с этими вопросами (далее: ситуация, участники, фото, контакт, дата и время)."
    )
    await message.answer(
        summary,
        reply_markup=keyboards.kb_after_question_selection(len(selected), amount),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "book_custom")
async def book_with_custom_questions_callback(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    questions_text = data.get("selected_questions")
    num = data.get("selected_num_questions", 0)
    amount = data.get("selected_amount", 0)
    if not questions_text or num <= 0:
        await callback.answer("Сначала выберите вопросы (напишите номера через запятую).", show_alert=True)
        return
    await state.clear()
    await state.set_state(BookingState.story)
    await state.update_data(
        prefilled_questions=questions_text,
        prefilled_num_questions=num,
        prefilled_amount=amount,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"Вы выбрали {num} вопросов ({amount}₽).\n\n"
        "Пожалуйста, опишите вашу ситуацию (краткая история).",
        reply_markup=keyboards.menu_for(callback.from_user.id)
    )
    await callback.answer()


# Begin booking process when user selects "📅 Записаться"
@router.message(F.text == "📅 Записаться")
async def book_appointment(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Пожалуйста, опишите вашу ситуацию (краткая история).", reply_markup=None)
    await state.set_state(BookingState.story)

# --- Созвон ---
@router.message(F.text == keyboards.CALL_BTN)
async def book_call(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(bot_texts.call_intro(), reply_markup=keyboards.kb_call_durations(), parse_mode="HTML")


@router.callback_query(F.data.startswith("call|"))
async def book_call_duration(callback: CallbackQuery, state: FSMContext):
    try:
        minutes = int(callback.data.split("|", 1)[1])
        price = dict(config.CALL_OPTIONS)[minutes]
    except (ValueError, KeyError):
        await callback.answer("Эта длительность недоступна.", show_alert=True)
        return
    await state.clear()
    await state.set_state(BookingState.story)
    await state.update_data(call_minutes=minutes, call_price=price)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"{bot_texts.call_summary(minutes, price)}\n\nПожалуйста, опишите вашу ситуацию (краткая история).",
        parse_mode="HTML")
    await callback.answer()


# State: waiting for the story of the situation
@router.message(BookingState.story, NOT_MENU)
async def receive_story(message: Message, state: FSMContext):
    if not message.text or message.text.strip() == "":
        await message.answer("Опишите, пожалуйста, вашу ситуацию.")
        return
    await state.update_data(story=message.text.strip())
    await message.answer("Теперь укажите имена всех участников ситуации.")
    await state.set_state(BookingState.participants)

# State: waiting for participants' names
@router.message(BookingState.participants, NOT_MENU)
async def receive_participants(message: Message, state: FSMContext):
    if not message.text or message.text.strip() == "":
        await message.answer("Введите имена участников (например: Иван, Мария, ...).")
        return
    await state.update_data(participants=message.text.strip())
    # Request photos of all participants
    await message.answer("Прикрепите фото всех участников. После отправки всех фото нажмите кнопку «Готово».", reply_markup=keyboards.done_kb)
    await state.set_state(BookingState.photos)

# State: waiting for photos of participants and then "Готово"
@router.message(BookingState.photos, NOT_MENU)
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
        # Если вопросы уже выбраны (готовый расклад или список) — переходим сразу к сумме и телефону
        prefilled = data.get("prefilled_questions")
        if prefilled:
            num_questions = data.get("prefilled_num_questions", 0)
            amount = data.get("prefilled_amount", 0)
            await state.update_data(questions=prefilled, num_questions=num_questions, amount=amount)
            await message.answer(bot_texts.price_summary(num_questions, amount), parse_mode="HTML")
            await message.answer("Теперь отправьте свой номер телефона для связи.", reply_markup=keyboards.contact_kb)
            await state.set_state(BookingState.phone)
            return
        # Иначе запрашиваем вопросы вручную
        await message.answer("Теперь отправьте список ваших вопросов (каждый вопрос с новой строки).", reply_markup=None)
        await state.set_state(BookingState.questions)
    else:
        # If some other text was sent instead of photos or "Готово"
        await message.answer("Отправьте фото участников и нажмите «Готово», когда закончите.")

# State: waiting for list of questions
@router.message(BookingState.questions, NOT_MENU)
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
    data = await state.get_data()
    if data.get("call_minutes"):
        # Созвон: цена фиксирована длительностью, вопросы на неё не влияют
        amount = data["call_price"]
        summary = bot_texts.call_summary(data["call_minutes"], amount)
    else:
        price = await database.get_price()
        amount = num_questions * price
        summary = bot_texts.price_summary(num_questions, amount)
    await state.update_data(questions=questions_text, num_questions=num_questions, amount=amount)
    await message.answer(summary, parse_mode="HTML")
    # Request phone number
    await message.answer("Теперь отправьте свой номер телефона для связи.", reply_markup=keyboards.contact_kb)
    await state.set_state(BookingState.phone)

# State: waiting for phone contact or manual input
@router.message(BookingState.phone, NOT_MENU)
async def receive_phone(message: Message, state: FSMContext):
    phone_number = None
    if message.contact:
        phone_number = message.contact.phone_number
    elif message.text:
        raw = message.text.strip()
        digits = re.sub(r"\D", "", raw)
        if raw.startswith('+'):
            phone_number = '+' + digits
        else:
            if len(digits) == 11 and digits.startswith('8'):
                phone_number = '+7' + digits[1:]
            else:
                phone_number = '+' + digits
        clean_digits = re.sub(r"\D", "", phone_number)
        if len(clean_digits) < 10 or len(clean_digits) > 15:
            phone_number = None
    if not phone_number:
        await message.answer("Неверный формат номера. Пожалуйста отправьте корректный номер, например +79991234567.", reply_markup=keyboards.contact_kb)
        return
    # Save phone and update user record
    user = message.from_user
    # Обновляем имя и юзернейм: по ним админ ищет клиента, а с /start он мог их сменить
    await database.get_or_create_user(user.id, user.username, user.full_name)
    await database.update_user_phone(user.id, phone_number)
    await state.update_data(phone=phone_number)
    # Show available dates
    data = await state.get_data()
    free_dates = await _free_dates(data)
    if not free_dates:
        await message.answer("Извините, сейчас нет доступных дат для записи. Попробуйте позже.", reply_markup=keyboards.menu_for(message.from_user.id))
        await state.clear()
        return
    await message.answer("Выберите дату:", reply_markup=_dates_kb(free_dates))
    await state.set_state(BookingState.select_date)


# --- Даты и время: общие для расклада и созвона ---

async def _free_dates(data):
    minutes = data.get("call_minutes")
    return await database.get_call_free_dates(minutes) if minutes else await database.get_free_dates()


async def _free_times(data, date):
    """[(slot_id, подпись)]; для созвона подпись — интервал «17:00–18:00»."""
    minutes = data.get("call_minutes")
    if minutes:
        return [(first, label) for first, _, label in await database.get_call_starts(date, minutes)]
    return await database.get_free_times(date)


def _dates_kb(dates):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for date_str in dates:
        try:
            display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
        except Exception:
            display = date_str
        rows.append([InlineKeyboardButton(text=display, callback_data=f"date|{date_str}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _times_kb(times):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"time|{slot_id}")] for slot_id, label in times
    ])


async def _back_to_dates(callback: CallbackQuery, state: FSMContext, data):
    """Вернуть клиента к выбору даты (или завершить, если свободных дат нет)."""
    free_dates = await _free_dates(data)
    if free_dates:
        try:
            await callback.message.edit_text("Выберите дату:", reply_markup=_dates_kb(free_dates))
        except Exception:
            await callback.message.answer("Выберите дату:", reply_markup=_dates_kb(free_dates))
        await state.set_state(BookingState.select_date)
    else:
        await callback.message.edit_text("Свободные слоты отсутствуют.")
        await state.clear()


# State: waiting for date selection (inline button)
@router.callback_query(BookingState.select_date)
async def select_date_callback(callback: CallbackQuery, state: FSMContext):
    if not callback.data or not callback.data.startswith("date|"):
        await callback.answer()
        return
    selected_date = callback.data.split("|", 1)[1]
    data = await state.get_data()
    free_times = await _free_times(data, selected_date)
    if not free_times:
        # No times available for that date (possibly taken just now)
        await callback.answer("Нет доступного времени на эту дату.", show_alert=True)
        await _back_to_dates(callback, state, data)
        return
    date_disp = datetime.strptime(selected_date, '%Y-%m-%d').strftime('%d.%m.%Y')
    try:
        await callback.message.edit_text(f"Дата {date_disp} выбрана. Выберите время:", reply_markup=_times_kb(free_times))
    except Exception:
        await callback.message.answer("Выберите время:", reply_markup=_times_kb(free_times))
    await state.update_data(selected_date=selected_date)
    await state.set_state(BookingState.select_time)
    await callback.answer()


# State: waiting for time selection (inline button)
@router.callback_query(BookingState.select_time)
async def select_time_callback(callback: CallbackQuery, state: FSMContext):
    if not callback.data or not callback.data.startswith("time|"):
        await callback.answer()
        return
    try:
        slot_id = int(callback.data.split("|", 1)[1])
    except ValueError:
        await callback.answer()
        return
    fsm_data = await state.get_data()
    amount = fsm_data.get("amount", 0)
    call_minutes = fsm_data.get("call_minutes")
    booking_id = None
    if call_minutes:
        # Слоты созвона пересчитываем в момент брони: соседние могли занять
        starts = await database.get_call_starts(fsm_data.get("selected_date"), call_minutes)
        extra = next((ex for first, ex, _ in starts if first == slot_id), None)
        if extra is not None:
            booking_id = await database.reserve_slot_and_create_booking(
                callback.from_user.id, slot_id, fsm_data.get("story"), fsm_data.get("participants"),
                fsm_data.get("photos", []), fsm_data.get("questions"), fsm_data.get("num_questions", 0), amount,
                extra_slot_ids=extra, kind="call", call_minutes=call_minutes)
    else:
        booking_id = await database.reserve_slot_and_create_booking(
            callback.from_user.id, slot_id, fsm_data.get("story"), fsm_data.get("participants"),
            fsm_data.get("photos", []), fsm_data.get("questions"), fsm_data.get("num_questions", 0), amount)
    if not booking_id:
        # If slot just got taken by someone else
        free_times = await _free_times(fsm_data, fsm_data.get("selected_date"))
        if free_times:
            try:
                await callback.message.edit_text("Выберите время:", reply_markup=_times_kb(free_times))
            except Exception:
                await callback.message.answer("Выберите время:", reply_markup=_times_kb(free_times))
            await callback.answer("Выбранное время уже занято, выберите другое.", show_alert=True)
        else:
            await _back_to_dates(callback, state, fsm_data)
            await callback.answer("Выбранное время уже занято.", show_alert=True)
        return
    # Slot reserved and booking created
    await state.update_data(booking_id=booking_id)
    # Remove the times keyboard from the message
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    # Compose payment instructions
    slot_cur = await database.db.execute("SELECT date, time FROM slots WHERE id=?", (slot_id,))
    slot_row = await slot_cur.fetchone()
    if slot_row:
        date_disp = datetime.strptime(slot_row['date'], "%Y-%m-%d").strftime("%d.%m.%Y")
        time_str = slot_row['time']
        if call_minutes:
            time_str = f"{time_str}–{database._add_minutes(time_str, call_minutes)} (созвон {bot_texts.call_duration(call_minutes)})"
    else:
        date_disp = fsm_data.get('selected_date')
        time_str = ""
    await callback.message.answer(bot_texts.payment_instructions(amount, date_disp, time_str), parse_mode="HTML")
    await callback.message.answer("УКАЖИТЕ ОТ КОГО ПЕРЕВОД и номер карты, на которую был сделан перевод (например: От Анны Гавриловны К., карта: (номер карты)).")
    await state.set_state(BookingState.payment_info)
    # Schedule auto-unlock job in 15 minutes
    from scheduler import scheduler, unlock_timeout
    run_time = datetime.now() + timedelta(minutes=15)  # = scheduler.PAYMENT_TIMEOUT
    try:
        scheduler.add_job(unlock_timeout, "date", run_date=run_time, args=[booking_id], id=f"unlock_{booking_id}")
    except Exception as e:
        logging.error(f"Failed to schedule unlock job: {e}")
    await callback.answer()

# State: waiting for payment info
@router.message(BookingState.payment_info, NOT_MENU)
async def receive_payment_info(message: Message, state: FSMContext):
    if not message.text or message.text.strip() == "":
        await message.answer("Пожалуйста, укажите от кого перевод и на какую карту.")
        return
    await state.update_data(payment_info=message.text.strip())
    await message.answer("Теперь отправьте фотографию чека об оплате.")
    await state.set_state(BookingState.waiting_receipt)

# State: waiting for payment receipt photo
@router.message(BookingState.waiting_receipt, NOT_MENU)
async def receive_receipt(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Пожалуйста, отправьте фотографию чека об оплате.")
        return
    data = await state.get_data()
    booking_id = data.get("booking_id")
    if not booking_id:
        await message.answer("Ошибка: нет активной записи.", reply_markup=keyboards.menu_for(message.from_user.id))
        await state.clear()
        return
    record = await database.get_booking_by_id(booking_id)
    if not record or record["status"] != config.STATUS_WAITING_PAYMENT:
        await message.answer("Время ожидания истекло или запись уже отменена.", reply_markup=keyboards.menu_for(message.from_user.id))
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
    ok = await admin_notify.send_booking_to_admin(
        booking_id, receipt_file_id=message.photo[-1].file_id, payment_info=data.get("payment_info", ""))
    if not ok and config.ADMIN_GROUP_ID:
        # Хотя бы короткое оповещение: запись есть в /admin → Записи → Ждут проверки
        try:
            await config.bot.send_message(config.ADMIN_GROUP_ID,
                f"⚠️ Запись #{booking_id}: чек получен, но карточку отправить не удалось. Смотрите /admin → Записи.")
        except Exception as e:
            logging.error(f"Failed to send fallback admin alert for booking {booking_id}: {e}")
    # Acknowledge user
    await message.answer("Чек получен. Ожидайте подтверждения администрации.", reply_markup=keyboards.menu_for(message.from_user.id))
    await state.clear()

# List the user's bookings and provide cancel options
@router.message(F.text == "📋 Мои записи")
async def list_bookings(message: Message):
    user_id = message.from_user.id
    records = await database.get_user_bookings(user_id)
    if not records or len(records) == 0:
        await message.answer("У вас нет активных записей.", reply_markup=keyboards.menu_for(message.from_user.id))
    else:
        text_lines = ["Ваши записи:"]
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = []
        for rec in records:
            status = rec["status"]
            date = rec["date"]
            time = rec["time"]
            cancel_allowed = status in (config.STATUS_WAITING_PAYMENT, config.STATUS_CHECKING)
            # Map status to Russian text
            if status == config.STATUS_WAITING_PAYMENT:
                status_text = "Ожидает оплаты"
            elif status == config.STATUS_CHECKING:
                status_text = "На подтверждении"
            elif status == config.STATUS_CONFIRMED:
                status_text = "Подтверждена"
                if not cancel_allowed:
                    status_text += " (отменить можно через администратора)"
            else:
                status_text = status
            date_display = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
            if rec["kind"] == "call":
                time = f"{time}–{database._add_minutes(time, rec['call_minutes'])} 📞 созвон"
            text_lines.append(f"- {date_display} {time} — {status_text}")
            if cancel_allowed:
                buttons.append([InlineKeyboardButton(text=f"Отменить {date_display} {time}", callback_data=f"cancel|{rec['id']}")])
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
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
    if status == config.STATUS_CONFIRMED:
        await callback.answer("Подтвержденную запись может отменить только администратор.", show_alert=True)
        return
    if status in (config.STATUS_WAITING_PAYMENT, config.STATUS_CHECKING):
        await database.update_booking_status(booking_id, config.STATUS_CANCELLED)
        await database.free_booking_slots(record)
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
