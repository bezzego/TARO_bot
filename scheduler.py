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
            await database.db.execute("UPDATE slots SET is_taken=0 WHERE id=?", (slot_id,))
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