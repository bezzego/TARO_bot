import logging
from html import escape
from datetime import datetime, timedelta

from aiogram import Router
from aiogram import F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery
import admin_keyboard as keyboards
import keyboards as keyboards_user
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

import config
import database
from states import AdminState

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Moscow")
except Exception:
    _TZ = None

router = Router()

STATUS_TEXT = {
    config.STATUS_WAITING_PAYMENT: "💳 ждёт оплаты",
    config.STATUS_CHECKING: "⏳ проверка оплаты",
    config.STATUS_CONFIRMED: "✅ подтверждена",
    config.STATUS_REJECTED: "❌ отклонена",
    config.STATUS_CANCELLED: "🚫 отменена",
}
ACTIVE_STATUSES = (config.STATUS_WAITING_PAYMENT, config.STATUS_CHECKING, config.STATUS_CONFIRMED)
BOOKINGS_PAGE_SIZE = 10


def _now():
    return datetime.now(_TZ) if _TZ else datetime.now()


def _today_iso():
    return _now().strftime("%Y-%m-%d")


def _fmt_date(date_iso, weekday=True):
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d")
    except Exception:
        return date_iso or "дата не указана"
    s = d.strftime("%d.%m")
    return f"{keyboards.WEEKDAYS_SHORT[d.weekday()]} {s}" if weekday else s


def _client(name, username):
    parts = [escape(name or "без имени")]
    if username:
        parts.append(f"@{escape(username)}")
    return " ".join(parts)


async def _show(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup):
    """Редактирует сообщение панели одним запросом; игнорирует «не изменилось»."""
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


# ---- Главное меню ----

async def _main_menu_payload():
    price = await database.get_price()
    today = _today_iso()
    cur = await database.db.execute(
        "SELECT b.status, COALESCE(s.date, b.slot_date_cache) >= ? AS upcoming, COUNT(*) AS n "
        "FROM bookings b LEFT JOIN slots s ON b.slot_id=s.id "
        "WHERE b.status IN (?, ?) GROUP BY b.status, upcoming",
        (today, config.STATUS_CHECKING, config.STATUS_WAITING_PAYMENT))
    checking = waiting = stale = 0
    for r in await cur.fetchall():
        if not r["upcoming"]:
            stale += r["n"]
        elif r["status"] == config.STATUS_CHECKING:
            checking += r["n"]
        else:
            waiting += r["n"]
    cur = await database.db.execute(
        "SELECT COUNT(*) AS n FROM bookings b LEFT JOIN slots s ON b.slot_id=s.id "
        "WHERE b.status=? AND COALESCE(s.date, b.slot_date_cache) >= ?",
        (config.STATUS_CONFIRMED, today))
    confirmed = (await cur.fetchone())["n"]
    cur = await database.db.execute(
        "SELECT COUNT(*) AS n FROM slots WHERE is_taken=0 AND date >= ?", (today,))
    free = (await cur.fetchone())["n"]

    lines = ["🔮 <b>Админ-панель</b>", ""]
    if checking:
        lines.append(f"⏳ Ждут вашего подтверждения: <b>{checking}</b>")
    else:
        lines.append("✨ Новых оплат на проверку нет")
    if waiting:
        lines.append(f"💳 Ждут оплаты: {waiting}")
    if stale:
        lines.append(f"🕰 Просрочены без решения: {stale} (в «Все записи»)")
    lines += [
        f"✅ Подтверждено (впереди): {confirmed}",
        f"🟢 Свободных слотов: {free}",
        f"💰 Цена вопроса: {price} ₽",
    ]
    return "\n".join(lines), keyboards.build_admin_main_ilkb(checking, waiting)


@router.message(F.text.in_({"/admin", keyboards_user.ADMIN_PANEL_BTN}))
async def admin_menu_cmd(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    text, kb = await _main_menu_payload()
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "admin|menu")
async def admin_menu_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    text, kb = await _main_menu_payload()
    await _show(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop_cb(callback: CallbackQuery):
    await callback.answer()


# ---- Расписание ----

def _dates_for_page(offset_weeks: int):
    """Return list of 7 ISO dates starting today + offset_weeks*7."""
    start = _now() + timedelta(days=offset_weeks * 7)
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


@router.callback_query(F.data.startswith("admin|schedule|"))
async def admin_schedule_open(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(); return
    try:
        offset = int(callback.data.split("|")[2])
    except Exception:
        offset = 0
    dates = _dates_for_page(offset)
    cur = await database.db.execute(
        "SELECT date, COUNT(*) AS total, SUM(CASE WHEN is_taken=0 THEN 1 ELSE 0 END) AS free "
        "FROM slots WHERE date BETWEEN ? AND ? GROUP BY date", (dates[0], dates[-1]))
    stats = {r["date"]: (r["free"] or 0, r["total"]) for r in await cur.fetchall()}
    date_stats = [(d, *stats.get(d, (0, 0))) for d in dates]
    dates_kb = keyboards.build_dates_ilkb(date_stats)
    nav_kb = keyboards.build_nav_row_for_dates(offset)
    combined = InlineKeyboardMarkup(inline_keyboard=dates_kb.inline_keyboard + nav_kb.inline_keyboard)
    text = (f"📆 <b>Расписание</b>: {_fmt_date(dates[0], False)} — {_fmt_date(dates[-1], False)}\n\n"
            "Выберите день.\n"
            "🟢 N — свободных слотов · 🔴 всё занято · ⚪ слотов нет")
    await _show(callback, text, combined)
    await callback.answer()


def _base_times():
    # 15 слотов каждые 20 минут с 13:00 до 18:40
    return [f"{h:02d}:{m:02d}" for h in range(13, 19) for m in range(0, 60, 20)]


async def show_date_screen(callback: CallbackQuery, date_iso: str):
    cur = await database.db.execute(
        "SELECT s.time, s.is_taken, u.name AS name, u.username AS username "
        "FROM slots s "
        "LEFT JOIN bookings b ON b.slot_id = s.id AND b.status NOT IN (?, ?) "
        "LEFT JOIN users u ON u.user_id = b.user_id "
        "WHERE s.date=? ORDER BY s.time",
        (config.STATUS_CANCELLED, config.STATUS_REJECTED, date_iso))
    rows = await cur.fetchall()
    existing = {r["time"]: r for r in rows}

    all_times = sorted(set(_base_times()) | set(existing))
    cells = []
    for t in all_times:
        r = existing.get(t)
        cells.append((t, "absent" if r is None else ("taken" if r["is_taken"] else "free")))
    can_add_all = any(s == "absent" for _, s in cells)

    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d")
        title = f"{keyboards.WEEKDAYS_FULL[d.weekday()]}, {d.strftime('%d.%m.%Y')}"
        back_offset = max(0, (d.date() - _now().date()).days // 7)
    except Exception:
        title, back_offset = date_iso, 0

    free_n = sum(1 for _, s in cells if s == "free")
    lines = [f"📅 <b>{title}</b>", f"Свободно: {free_n} · занято: {sum(1 for _, s in cells if s == 'taken')}", ""]
    taken = [r for r in rows if r["is_taken"]]
    if taken:
        lines.append("<b>Записаны:</b>")
        for r in taken:
            who = _client(r["name"], r["username"]) if r["name"] else "—"
            lines.append(f"🔒 {r['time']} — {who}")
        lines.append("")
    lines.append("🟢 свободный — нажмите, чтобы убрать\n➕ нет в расписании — нажмите, чтобы добавить\n🔒 занят")

    await _show(callback, "\n".join(lines),
                keyboards.build_day_ilkb(date_iso, cells, can_add_all, back_offset))


@router.callback_query(F.data.startswith("sched_date|"))
async def admin_pick_date(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(); return
    date_iso = callback.data.split("|", 1)[1]
    await show_date_screen(callback, date_iso)
    await callback.answer()


@router.callback_query(F.data.startswith("addslot|"))
async def admin_addslot_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(); return
    _, date_iso, time_str = callback.data.split("|", 2)
    ok = await database.add_slot(date_iso, time_str)
    await callback.answer("Добавлено" if ok else "Уже существует", show_alert=False)
    await show_date_screen(callback, date_iso)


@router.callback_query(F.data.startswith("addall|"))
async def admin_addall_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(); return
    date_iso = callback.data.split("|", 1)[1]
    added = 0
    for t in _base_times():
        if await database.add_slot(date_iso, t):
            added += 1
    await callback.answer(f"Добавлено слотов: {added}")
    await show_date_screen(callback, date_iso)


@router.callback_query(F.data.startswith("delslot|"))
async def admin_delslot_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(); return
    _, date_iso, time_str = callback.data.split("|", 2)
    res = await database.remove_slot(date_iso, time_str)
    if res == 1:
        msg, alert = "Удалено", False
    elif res == -1:
        msg, alert = "Нельзя удалить слот: есть активные записи или он занят", True
    elif res == 0:
        msg, alert = "Слот не найден", False
    else:
        msg, alert = "Не удалось удалить слот", True
    await callback.answer(msg, show_alert=alert)
    await show_date_screen(callback, date_iso)


# ---- Цена ----

def _price_text(price):
    return (f"💰 <b>Стоимость вопроса</b>\n\nСейчас: <b>{price} ₽</b>\n\n"
            "Изменить шаг кнопками ниже или командой <code>/price 500</code>.")


@router.callback_query(F.data == "admin|price")
async def admin_price_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(); return
    current = await database.get_price()
    await _show(callback, _price_text(current), keyboards.build_price_menu_ilkb(current))
    await callback.answer()


@router.callback_query(F.data.startswith("price|"))
async def admin_price_change(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(); return
    _, action, step_str = callback.data.split("|", 2)
    try:
        step = int(step_str)
    except Exception:
        step = 50
    current = await database.get_price()
    new_price = current + step if action == "inc" else max(0, current - step)
    await database.db.execute("UPDATE settings SET value=? WHERE key='price_per_question'", (str(new_price),))
    await database.db.commit()
    await _show(callback, _price_text(new_price), keyboards.build_price_menu_ilkb(new_price))
    await callback.answer(f"Цена: {new_price} ₽")


# ---- Записи ----

async def _load_bookings():
    cur = await database.db.execute(
        "SELECT COALESCE(s.date, b.slot_date_cache) AS date, "
        "COALESCE(s.time, b.slot_time_cache) AS time, "
        "b.status, u.name AS user_name, u.username AS username "
        "FROM bookings b JOIN users u ON b.user_id = u.user_id "
        "LEFT JOIN slots s ON b.slot_id = s.id "
        "ORDER BY COALESCE(s.date, b.slot_date_cache), COALESCE(s.time, b.slot_time_cache)")
    return await cur.fetchall()


@router.callback_query(F.data.startswith("admin|bookings"))
async def admin_bookings_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(); return
    parts = callback.data.split("|")
    flt = parts[2] if len(parts) > 2 and parts[2] in ("chk", "act", "all") else "act"
    try:
        page = int(parts[3]) if len(parts) > 3 else (int(parts[2]) if len(parts) > 2 else 0)
    except ValueError:
        page = 0

    today = _today_iso()
    records = await _load_bookings()
    sets = {
        "chk": [r for r in records if r["status"] == config.STATUS_CHECKING and (r["date"] or "9999") >= today],
        "act": [r for r in records if r["status"] in ACTIVE_STATUSES and (r["date"] or "9999") >= today],
        "all": list(records),
    }
    counts = {k: len(v) for k, v in sets.items()}
    items = sets[flt]
    if flt == "all":
        items = items[::-1]  # свежие сверху
    total_pages = max(1, (len(items) + BOOKINGS_PAGE_SIZE - 1) // BOOKINGS_PAGE_SIZE)
    page = min(max(page, 0), total_pages - 1)
    chunk = items[page * BOOKINGS_PAGE_SIZE:(page + 1) * BOOKINGS_PAGE_SIZE]

    titles = {"chk": "⏳ Ждут проверки оплаты", "act": "📅 Актуальные записи", "all": "🗂 Все записи"}
    lines = [f"📋 <b>{titles[flt]}</b>", ""]
    if not chunk:
        lines.append("Пока пусто ✨")
    last_date = object()
    for rec in chunk:
        if rec["date"] != last_date:
            last_date = rec["date"]
            if len(lines) > 2:
                lines.append("")
            lines.append(f"<b>{_fmt_date(rec['date'])}</b>" if rec["date"] else "<b>Дата не указана</b>")
        st = STATUS_TEXT.get(rec["status"], escape(str(rec["status"])))
        lines.append(f"  {rec['time'] or '--:--'} · {_client(rec['user_name'], rec['username'])}\n      {st}")
    kb = keyboards.build_bookings_ilkb(flt, page, total_pages, counts)
    await _show(callback, "\n".join(lines), kb)
    await callback.answer()


# ---- Разблокировка слотов ----

class _Collector:
    """Подменяет Message для handle_unlock: собирает текст ответа."""
    def __init__(self):
        self.text = ""

    async def answer(self, text, **kwargs):
        self.text = text


async def _taken_slots():
    cur = await database.db.execute(
        "SELECT s.id, s.date, s.time, u.name AS name, u.username AS username "
        "FROM slots s "
        "LEFT JOIN bookings b ON b.slot_id = s.id AND b.status NOT IN (?, ?) "
        "LEFT JOIN users u ON u.user_id = b.user_id "
        "WHERE s.is_taken=1 AND s.date >= ? ORDER BY s.date, s.time LIMIT 40",
        (config.STATUS_CANCELLED, config.STATUS_REJECTED, _today_iso()))
    return await cur.fetchall()


@router.callback_query(F.data == "admin|unlock")
async def admin_unlock_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(); return
    slots = await _taken_slots()
    if not slots:
        text = "🔓 <b>Занятых слотов нет</b>\n\nРазблокировать нечего ✨"
    else:
        text = ("🔓 <b>Занятые слоты</b>\n\nВыберите слот. Запись клиента будет отменена, "
                "а слот снова станет свободным.")
    items = [(r["id"], f"{_fmt_date(r['date'])} {r['time']} · {(r['name'] or 'без записи')[:20]}") for r in slots]
    await _show(callback, text, keyboards.build_unlock_list_ilkb(items))
    await callback.answer()


async def _slot_row(slot_id):
    cur = await database.db.execute("SELECT id, date, time FROM slots WHERE id=?", (slot_id,))
    return await cur.fetchone()


@router.callback_query(F.data.startswith("unlock|ask|"))
async def admin_unlock_ask(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(); return
    slot = await _slot_row(int(callback.data.split("|")[2]))
    if not slot:
        await callback.answer("Слот не найден", show_alert=True)
        return
    text = (f"🔓 Разблокировать <b>{_fmt_date(slot['date'])} {slot['time']}</b>?\n\n"
            "Клиент получит уведомление об отмене записи.")
    await _show(callback, text, keyboards.build_unlock_confirm_ilkb(slot["id"]))
    await callback.answer()


@router.callback_query(F.data.startswith("unlock|do|"))
async def admin_unlock_do(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(); return
    slot = await _slot_row(int(callback.data.split("|")[2]))
    if not slot:
        await callback.answer("Слот не найден", show_alert=True)
        return
    result = _Collector()
    await handle_unlock(slot["date"], slot["time"], result)
    await callback.answer(result.text or "Готово", show_alert=True)
    await admin_unlock_list(callback)

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
            await message.answer("Нельзя удалить слот: он занят или есть активные записи.")
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
        await message.answer("Этот слот занят или по нему есть активные записи, удалить нельзя.")
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
            date_raw = rec["date"]
            time_raw = rec["time"]
            status = rec["status"]
            name = rec["user_name"] or "<имя>"
            username = rec["username"] or ""
            if date_raw:
                try:
                    date_display = datetime.strptime(date_raw, "%Y-%m-%d").strftime("%d.%m.%Y")
                except ValueError:
                    date_display = date_raw
            else:
                date_display = "Дата не указана"
            time_display = time_raw if time_raw else "Время не указано"
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
            text_lines.append(f"- {date_display} {time_display} — {name} (@{username}) — {status_text}")
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
    # Temporary debug log for details keys
    logging.debug(f"reject_payment details keys: {list(details.keys())}")
    # Mark as rejected and free slot
    await database.update_booking_status(booking_id, config.STATUS_REJECTED)
    slot_id = details["slot_id"] if "slot_id" in details.keys() else None
    if not slot_id:
        # Попробуем найти слот по дате и времени, если slot_id не передан
        cur = await database.db.execute(
            "SELECT id FROM slots WHERE date=? AND time=?",
            (details["date"], details["time"])
        )
        row = await cur.fetchone()
        slot_id = row["id"] if row else None
    if slot_id:
        await database.db.execute("UPDATE slots SET is_taken=0 WHERE id=?", (slot_id,))
        await database.db.commit()
    else:
        logging.error(f"reject_payment: slot_id not found in details for booking {booking_id}")
        await callback.answer("Ошибка: слот не найден для этой записи.", show_alert=True)
        return
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
