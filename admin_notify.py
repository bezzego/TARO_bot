"""Отправка записи в админ-группу: фото участников, чек и карточка с кнопками.

Карточка раньше терялась, если клиент писал длинную историю (лимит Telegram — 4096
символов) или символ «<» (ломал HTML-разметку). Теперь текст экранируется,
а длинные поля уходят отдельными сообщениями перед карточкой.
"""
import json
import logging
import re
from datetime import datetime
from html import escape

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

import bot_texts
import config
import database

MAX_LEN = 4000      # с запасом до лимита 4096
CHUNK_RAW = 3000    # кусок исходного текста; после экранирования влезает в MAX_LEN


async def _call(method, **kwargs):
    """Вызов Bot API в админ-группу с повтором при миграции группы и сбое сети."""
    try:
        return await method(chat_id=config.ADMIN_GROUP_ID, **kwargs)
    except Exception as e:
        err = str(e)
        m = re.search(r"-100\d+", err)
        if m:
            config.ADMIN_GROUP_ID = int(m.group())
            logging.info(f"Admin group migrated, new ADMIN_GROUP_ID={config.ADMIN_GROUP_ID}")
        elif "timeout" not in err.lower() and "connect" not in err.lower():
            raise
        logging.warning(f"Retrying admin group send after error: {err}")
        return await method(chat_id=config.ADMIN_GROUP_ID, **kwargs)


def _chunks(text, size=CHUNK_RAW):
    """Режет текст по строкам на куски не длиннее size."""
    parts, buf = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:size])
            line = line[size:]
        if len(buf) + len(line) > size:
            parts.append(buf)
            buf = ""
        buf += line
    if buf:
        parts.append(buf)
    return parts or [""]


def admin_kb(booking_id):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить чек", callback_data=f"confirm|{booking_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject|{booking_id}"),
    ]])


async def send_booking_to_admin(booking_id, receipt_file_id=None, payment_info="", resent=False):
    """Шлёт в админ-группу всё по записи. Возвращает True, если карточка с кнопками дошла."""
    d = await database.get_booking_details(booking_id)
    if not d:
        return False
    username = d["username"] or ""
    user_name = d["user_name"] or ""

    # Фото участников
    try:
        photos = json.loads(d["photos"]) if d["photos"] else []
    except ValueError:
        photos = []
    for i in range(0, len(photos), 10):  # в альбоме максимум 10 фото
        media = [InputMediaPhoto(media=pid) for pid in photos[i:i + 10]]
        if i == 0:
            label = "созвон" if d["kind"] == "call" else "запись"
            media[0] = InputMediaPhoto(media=photos[0], caption=f"Фото участников ({label} #{booking_id})")
        try:
            await _call(config.bot.send_media_group, media=media)
        except Exception as e:
            logging.error(f"Failed to send participant photos for booking {booking_id}: {e}")

    # Чек
    if receipt_file_id:
        caption = f"{'📞 Созвон. ' if d['kind'] == 'call' else ''}Чек от @{username or user_name}"
        if payment_info:
            caption += f"\n{payment_info}"
        try:
            await _call(config.bot.send_photo, photo=receipt_file_id, caption=escape(caption[:1000]))
        except Exception as e:
            logging.error(f"Failed to send receipt photo for booking {booking_id}: {e}")

    # Карточка
    try:
        date_disp = datetime.strptime(d["date"], "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        date_disp = d["date"] or ""
    is_call = d["kind"] == "call"
    time_disp = d["time"] or ""
    if is_call and time_disp:
        time_disp = f"{time_disp}–{database._add_minutes(time_disp, d['call_minutes'])}"
    title = (f"📞📞 <b>СОЗВОН · {bot_texts.call_duration(d['call_minutes'])}</b> · запись #{booking_id}"
             if is_call else f"📌 <b>Запись #{booking_id}</b>")
    header = (
        f"{title}{' (повторно)' if resent else ''}\n\n"
        f"👤 <b>Клиент:</b> {escape(user_name)} (@{escape(username)})\n"
        f"📞 <b>Телефон:</b> {escape(d['phone'] or '')}\n\n"
    )
    sections = [
        ("📖 <b>История:</b>", d["story"] or ""),
        ("👥 <b>Участники:</b>", d["participants"] or ""),
        (f"❓ <b>Количество вопросов:</b> {d['num_questions']}\n💬 <b>Вопросы:</b>", d["questions"] or ""),
    ]
    footer = (
        f"📅 <b>Дата:</b> {date_disp}  ⏰ <b>Время:</b> {time_disp}\n"
        f"💵 <b>Сумма:</b> {d['amount']} ₽\n"
        f"⏳ <b>Статус:</b> Ожидает подтверждения оплаты"
    )
    body = "".join(f"{title}\n{escape(text)}\n\n" for title, text in sections)
    card = header + body + footer

    if len(card) > MAX_LEN:
        # Длинные поля — отдельными сообщениями, карточка — коротко
        for title, text in sections:
            for n, part in enumerate(_chunks(text)):
                prefix = f"{'📞 СОЗВОН ' if is_call else ''}#{booking_id} · {title}" + (" (продолжение)" if n else "")
                try:
                    await _call(config.bot.send_message, text=f"{prefix}\n{escape(part)}")
                except Exception as e:
                    logging.error(f"Failed to send long field for booking {booking_id}: {e}")
        card = header + "📖 История, участники и вопросы — в сообщениях выше ⬆️\n\n" + footer

    try:
        sent = await _call(config.bot.send_message, text=card, reply_markup=admin_kb(booking_id))
        await database.set_booking_admin_message_id(booking_id, sent.message_id)
        return True
    except Exception as e:
        logging.error(f"Failed to send booking details for booking {booking_id}: {e}")
        return False
