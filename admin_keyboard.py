from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

# Главное меню админа
admin_main_ilkb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📆 Настроить расписание", callback_data="admin|schedule|0")],
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data="admin|price")],
        [InlineKeyboardButton(text="📋 Записи", callback_data="admin|bookings")],
        [InlineKeyboardButton(text="🔓 Разблокировать слот", callback_data="admin|unlock")],
    ]
)

def build_dates_ilkb(date_list):
    rows = []
    for ds in date_list:
        try:
            disp = datetime.strptime(ds, "%Y-%m-%d").strftime("%d.%m.%Y")
        except Exception:
            disp = ds
        rows.append([InlineKeyboardButton(text=disp, callback_data=f"sched_date|{ds}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def build_times_manage_ilkb(date_iso, times):
    rows = []
    for t, taken in times:
        if taken:
            rows.append([InlineKeyboardButton(text=f"🔒 {t}", callback_data="noop")])
        else:
            rows.append([InlineKeyboardButton(text=f"❌ Удалить {t}", callback_data=f"delslot|{date_iso}|{t}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def build_add_times_row(date_iso, candidate_times):
    buttons = [[InlineKeyboardButton(text=f"➕ {t}", callback_data=f"addslot|{date_iso}|{t}")]
               for t in candidate_times]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_nav_row_for_dates(page_offset):
    prev_offset = page_offset - 1
    next_offset = page_offset + 1
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="admin|menu"),
                InlineKeyboardButton(text="◀️ Неделя", callback_data=f"admin|schedule|{prev_offset}"),
                InlineKeyboardButton(text="Неделя ▶️", callback_data=f"admin|schedule|{next_offset}"),
            ]
        ]
    )

def build_price_menu_ilkb(current_price):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="−50 ₽", callback_data="price|dec|50"),
                InlineKeyboardButton(text="+50 ₽", callback_data="price|inc|50"),
            ],
            [InlineKeyboardButton(text="↩️ В меню", callback_data="admin|menu")],
        ]
    )

def admin_back_menu_ilkb():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="↩️ В меню", callback_data="admin|menu")]]
    )