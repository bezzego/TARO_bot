import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import database

scheduler = AsyncIOScheduler()

async def unlock_timeout(booking_id: int):
    """Job: unlock a reserved slot if payment was not completed in time."""
    try:
        record = await database.get_booking_by_id(booking_id)
        if record is None:
            return
        status = record["status"]
        if status == config.STATUS_WAITING_PAYMENT:
            # Cancel the booking and free the slot
            slot_id = record["slot_id"]
            user_id = record["user_id"]
            await database.update_booking_status(booking_id, config.STATUS_CANCELLED)
            await database.free_booking_slots(record)
            await database.db.commit()
            logging.info(f"Auto-unlocked slot {slot_id} for booking {booking_id} (payment timeout)")
            # Notify user
            try:
                await config.bot.send_message(user_id, "Истекло время ожидания оплаты, ваша запись отменена.")
            except Exception as e:
                logging.error(f"Failed to send timeout message to user {user_id}: {e}")
            # Notify admins (in admin group)
            try:
                if config.ADMIN_GROUP_ID:
                    await config.bot.send_message(config.ADMIN_GROUP_ID, f"Запись #{booking_id} автоматически отменена (не оплачена вовремя).")
            except Exception as e:
                logging.error(f"Failed to notify admin group about timeout: {e}")
    except Exception as e:
        logging.exception(f"Error in unlock_timeout job for booking {booking_id}: {e}")

PAYMENT_TIMEOUT = timedelta(minutes=15)


async def restore_unlock_jobs():
    """После рестарта планировщик пуст: заново ставим автоотмену неоплаченных броней.

    Без этого бронь, созданная прямо перед рестартом, навсегда держала слот закрытым.
    Брони без created_at (созданные до этой правки) не трогаем — их разбирает админ.
    """
    cur = await database.db.execute(
        "SELECT id, created_at FROM bookings WHERE status=? AND created_at IS NOT NULL",
        (config.STATUS_WAITING_PAYMENT,))
    rows = await cur.fetchall()
    now = datetime.now()
    for r in rows:
        try:
            run_time = max(datetime.fromisoformat(r["created_at"]) + PAYMENT_TIMEOUT, now + timedelta(seconds=5))
            scheduler.add_job(unlock_timeout, "date", run_date=run_time, args=[r["id"]],
                              id=f"unlock_{r['id']}", replace_existing=True)
        except Exception as e:
            logging.error(f"Failed to restore unlock job for booking {r['id']}: {e}")
    if rows:
        logging.info(f"Restored {len(rows)} unlock job(s)")
