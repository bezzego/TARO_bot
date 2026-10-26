from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAYS_FULL = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

BTN_MENU = InlineKeyboardButton(text="🏠 В меню", callback_data="admin|menu")


def _btn(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def _grid(buttons, cols):
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def _badge(text, count):
    return f"{text} · {count}" if count else text


def build_admin_main_ilkb(checking=0, waiting=0):
    """Главное меню. Счётчики показывают, что требует внимания."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(_badge("📋 Записи", checking), "admin|bookings|chk|0")],
            [
                _btn("📆 Расписание", "admin|schedule|0"),
                _btn("🔓 Слоты", "admin|unlock"),
            ],
            [
                _btn("💰 Цена", "admin|price"),
                _btn("📥 Excel", "admin|excel"),
            ],
            [_btn("🔄 Обновить", "admin|menu")],
        ]
    )


def build_dates_ilkb(date_stats):
    """date_stats: список (date_iso, free, total)."""
    buttons = []
    for ds, free, total in date_stats:
        try:
            d = datetime.strptime(ds, "%Y-%m-%d")
            label = f"{WEEKDAYS_SHORT[d.weekday()]} {d.strftime('%d.%m')}"
        except Exception:
            label = ds
        if total == 0:
            mark = "⚪"
        elif free == 0:
            mark = "🔴"
        else:
            mark = f"🟢 {free}"
        buttons.append(_btn(f"{label} · {mark}", f"sched_date|{ds}"))
    return InlineKeyboardMarkup(inline_keyboard=_grid(buttons, 2))


def build_nav_row_for_dates(page_offset):
    row = [_btn("◀️ Раньше", f"admin|schedule|{page_offset - 1}")]
    if page_offset != 0:
        row.append(_btn("Сегодня", "admin|schedule|0"))
    row.append(_btn("Позже ▶️", f"admin|schedule|{page_offset + 1}"))
    return InlineKeyboardMarkup(inline_keyboard=[row, [BTN_MENU]])


def build_day_ilkb(date_iso, cells, can_add_all, back_offset=0):
    """cells: список (time, state), state: free | taken | absent."""
    buttons = []
    for t, state in cells:
        if state == "taken":
            buttons.append(_btn(f"🔒 {t}", "noop"))
        elif state == "free":
            buttons.append(_btn(f"🟢 {t}", f"delslot|{date_iso}|{t}"))
        else:
            buttons.append(_btn(f"➕ {t}", f"addslot|{date_iso}|{t}"))
    rows = _grid(buttons, 3)
    if can_add_all:
        rows.append([_btn("➕ Добавить всё время", f"addall|{date_iso}")])
    rows.append([_btn("⬅️ К датам", f"admin|schedule|{back_offset}"), BTN_MENU])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_price_menu_ilkb(current_price):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("−100", "price|dec|100"),
                _btn("−50", "price|dec|50"),
                _btn("+50", "price|inc|50"),
                _btn("+100", "price|inc|100"),
            ],
            [BTN_MENU],
        ]
    )


def build_bookings_ilkb(flt, page, total_pages, counts, typ, type_counts, items):
    """counts: {'chk'|'act'|'all': n} для текущего типа; type_counts: {'spread'|'call': n};
    items: [(booking_id, подпись)] — записи текущей страницы, кнопками."""
    def nav_data(f=flt, p=0, t=typ):
        return f"admin|bookings|{f}|{p}|{t}"

    def type_btn(key, title):
        active = key == typ
        # Повторное нажатие на активный тип возвращает «все типы»
        return _btn(f"{'● ' if active else ''}{title} · {type_counts.get(key, 0)}",
                    nav_data(t="all" if active else key))

    def tab(key, title):
        text = f"● {title} · {counts.get(key, 0)}" if key == flt else f"{title} · {counts.get(key, 0)}"
        return [_btn(text, nav_data(f=key))]

    rows = [[type_btn("spread", "🔮 Расклады"), type_btn("call", "📞 Созвоны")]]
    rows += [tab("chk", "⏳ Ждут проверки"), tab("act", "📅 Актуальные"), tab("all", "🗂 Все записи")]
    rows += [[_btn(label, f"bk|{bid}|{flt}|{page}|{typ}")] for bid, label in items]
    nav = []
    if page > 0:
        nav.append(_btn("◀️", nav_data(p=page - 1)))
    if total_pages > 1:
        nav.append(_btn(f"{page + 1}/{total_pages}", "noop"))
    if page < total_pages - 1:
        nav.append(_btn("▶️", nav_data(p=page + 1)))
    if nav:
        rows.append(nav)
    rows.append([_btn("📥 Excel", "admin|excel"), BTN_MENU])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_booking_card_ilkb(booking_id, back, checking, has_media, username):
    rows = []
    if checking:
        rows.append([_btn("✅ Подтвердить", f"bkok|{booking_id}|{back}"),
                     _btn("❌ Отклонить", f"bkno|{booking_id}|{back}")])
    if has_media:
        rows.append([_btn("🖼 Фото участников и чек", f"bkph|{booking_id}")])
    if username:
        rows.append([InlineKeyboardButton(text="💬 Написать клиенту", url=f"https://t.me/{username}")])
    rows.append([_btn("⬅️ К списку", f"admin|bookings|{back}"), BTN_MENU])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_unlock_list_ilkb(items):
    """items: список (slot_id, label)."""
    rows = [[_btn(label, f"unlock|ask|{sid}")] for sid, label in items]
    rows.append([BTN_MENU])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_unlock_confirm_ilkb(slot_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("✅ Да, разблокировать", f"unlock|do|{slot_id}")],
            [_btn("⬅️ Назад", "admin|unlock"), BTN_MENU],
        ]
    )


def admin_back_menu_ilkb():
    return InlineKeyboardMarkup(inline_keyboard=[[BTN_MENU]])
