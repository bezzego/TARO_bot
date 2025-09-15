from datetime import datetime


def format_currency(amount: int) -> str:
    return f"{amount} ₽"


def welcome_text(price: int) -> str:
    return (
        "Привет!\n"
        "<b>Я бот для записи на расклад</b>\n\n"
        "Условия:\n"
        f"• 1 вопрос — <b>{format_currency(price)}</b>\n\n"
        "Для расклада необходимо предоставить: краткую историю ситуации, имена всех участников, фото участников, "
        "список вопросов (каждый с новой строки) и контактный телефон.\n\n"
        "Запись и оплата проводятся только через этого бота.\n\n"
        "Примеры вопросов в тг канале: https://t.me/prais_vedma_ari"
    )


def price_summary(num_questions: int, amount: int) -> str:
    return f"Вопросов: <b>{num_questions}</b>. Сумма к оплате: <b>{format_currency(amount)}</b>."


def payment_instructions(amount: int, date_display: str, time_str: str) -> str:
    return (
        f"Слот <b>{date_display} {time_str}</b> зарезервирован на 15 минут.\n"
        f"Оплатите <b>{format_currency(amount)}</b> по реквизитам:\n"
        "Сбербанк: <code>2202 2061 5913 1163</code> (Сергей Александрович С.)\n"
        "Тинькофф: <code>2200 7017 1423 6749</code> (Арианна С.)\n\n"
        "После оплаты следуйте инструкциям в следующем сообщении."
        "В КОММЕНТАРИИ К ПЕРЕВОДУ НИЧЕГО УКАЗЫВАТЬ НЕ НУЖНО! СТРОГО СЛЕДУЙТЕ ИНСТРУКЦИЯМ В БОТЕ."
    )


def booking_details_admin(details: dict) -> str:
    """Format booking details for admin group. Expects keys like user_name, username, phone, story, participants,
    questions, date, time, num_questions, amount"""
    user_name = details.get("user_name") or ""
    username = details.get("username") or ""
    phone = details.get("phone") or ""
    story = details.get("story") or ""
    participants = details.get("participants") or ""
    questions = details.get("questions") or ""
    date = details.get("date") or ""
    time = details.get("time") or ""
    num_q = details.get("num_questions") or 0
    amount = details.get("amount") or 0

    try:
        date_disp = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y") if date else ""
    except Exception:
        date_disp = date

    txt = (
        f"Запись #{details.get('id', '')}\n"
        f"Клиент: {user_name} (@{username})\n"
        f"Телефон: {phone}\n\n"
        f"<b>История:</b> {story}\n"
        f"<b>Участники:</b> {participants}\n"
        f"<b>Вопросов:</b> {num_q}\n"
        f"<b>Вопросы:</b> {questions}\n"
        f"<b>Дата и время:</b> {date_disp} {time}\n"
        f"<b>Сумма:</b> {format_currency(amount)}\n\n"
        "Статус: Ожидает подтверждения оплаты"
    )
    return txt


def admin_price_display(price: int) -> str:
    return f"Текущая стоимость вопроса: <b>{format_currency(price)}</b>"


def receipt_received_ack() -> str:
    return "Чек получен. Ожидайте подтверждения администрации."


def help_text() -> str:
    return (
        "<b>Как воспользоваться ботом</b>\n\n"
        "1. Нажмите «📅 Записаться» и следуйте подсказкам: опишите ситуацию, укажите участников, пришлите фото, "
        "перечислите вопросы и оставьте контактный телефон.\n\n"
        "2. После заполнения вы получите сумму к оплате. Переведите деньги на указанные реквизиты и отправьте фото чека.\n\n"
        "3. Администраторы проверят чек и подтвердят запись. В разделе «📋 Мои записи» вы можете отслеживать статус или отменить запись."
    )