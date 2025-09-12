import json
import aiosqlite
import logging
from datetime import datetime

import config

# Global database connection
db: aiosqlite.Connection = None

async def init_db():
    """Initialize the database: create tables if not exist, and ensure default settings."""
    global db
    db = await aiosqlite.connect(config.DB_PATH)
    # Enable foreign key constraints
    await db.execute("PRAGMA foreign_keys = ON")
    # Use row factory to get results as dict-like
    db.row_factory = aiosqlite.Row

    # Create tables
    await db.execute(
        """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                name TEXT,
                phone TEXT
            )""")
    await db.execute(
        """CREATE TABLE IF NOT EXISTS slots (
                id       INTEGER PRIMARY KEY,
                date     TEXT,
                time     TEXT,
                is_taken INTEGER DEFAULT 0,
                UNIQUE(date, time)
            )""")
    await db.execute(
        """CREATE TABLE IF NOT EXISTS bookings (
                id            INTEGER PRIMARY KEY,
                user_id       INTEGER,
                slot_id       INTEGER,
                story         TEXT,
                participants  TEXT,
                photos        TEXT,   -- JSON array of file_ids
                questions     TEXT,
                num_questions INTEGER,
                amount        INTEGER,
                status        TEXT,
                admin_message_id INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(slot_id) REFERENCES slots(id)
            )""")
    await db.execute(
        """CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )""")
    # Insert default price if not set
    cur = await db.execute("SELECT value FROM settings WHERE key='price_per_question'")
    row = await cur.fetchone()
    if row is None:
        default_price = 350  # default price per question
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("price_per_question", str(default_price)))
        logging.info(f"Default price_per_question set to {default_price}")
    await db.commit()

async def get_price():
    """Get current price per question."""
    cur = await db.execute("SELECT value FROM settings WHERE key='price_per_question'")
    row = await cur.fetchone()
    if row:
        try:
            return int(row[0])
        except:
            return int(float(row[0]) if row[0] else 0)
    return 0

async def get_or_create_user(user_id: int, username: str, name: str):
    """Insert or update a user (without changing phone if already present)."""
    await db.execute(
        "INSERT INTO users (user_id, username, name, phone) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, name=excluded.name",
        (user_id, username or "", name or "", None)
    )
    await db.commit()

async def update_user_phone(user_id: int, phone: str):
    """Update user's phone number."""
    await db.execute("UPDATE users SET phone=? WHERE user_id=?", (phone, user_id))
    await db.commit()

async def add_slot(date: str, time: str):
    """Add a new available slot (date in YYYY-MM-DD, time in HH:MM). Return True if added, False if already exists."""
    try:
        await db.execute("INSERT INTO slots (date, time, is_taken) VALUES (?, ?, 0)", (date, time))
        await db.commit()
        logging.info(f"Added slot {date} {time}")
        return True
    except aiosqlite.IntegrityError:
        # slot already exists
        return False

async def remove_slot(date: str, time: str):
    """Remove a slot by date and time if it is free. Return 1 if removed, 0 if not found, -1 if taken."""
    cur = await db.execute("SELECT id, is_taken FROM slots WHERE date=? AND time=?", (date, time))
    row = await cur.fetchone()
    if row is None:
        return 0  # not found
    slot_id = row["id"]
    if row["is_taken"] != 0:
        return -1  # slot is taken (cannot remove)
    await db.execute("DELETE FROM slots WHERE id=?", (slot_id,))
    await db.commit()
    logging.info(f"Removed slot {date} {time}")
    return 1

async def reserve_slot_and_create_booking(user_id: int, slot_id: int, story: str, participants: str, photo_ids: list, questions: str, num_questions: int, amount: int):
    """Reserve a slot (if available) and create a booking entry. Returns booking_id or None if slot already taken."""
    try:
        await db.execute("BEGIN")
        cur = await db.execute("UPDATE slots SET is_taken=1 WHERE id=? AND is_taken=0", (slot_id,))
        if cur.rowcount == 0:
            await db.execute("ROLLBACK")
            return None
        photos_json = json.dumps(photo_ids) if photo_ids is not None else json.dumps([])
        await db.execute(
            "INSERT INTO bookings (user_id, slot_id, story, participants, photos, questions, num_questions, amount, status, admin_message_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, slot_id, story, participants, photos_json, questions, num_questions, amount, config.STATUS_WAITING_PAYMENT, None)
        )
        # Get last inserted booking id
        cur2 = await db.execute("SELECT last_insert_rowid()")
        row = await cur2.fetchone()
        booking_id = row[0] if row else None
        await db.execute("COMMIT")
        logging.info(f"Created booking {booking_id} for user {user_id} on slot {slot_id}")
        return booking_id
    except Exception as e:
        logging.exception(f"Error in reserve_slot_and_create_booking: {e}")
        try:
            await db.execute("ROLLBACK")
        except:
            pass
        return None

async def get_free_dates():
    """Get a list of dates (YYYY-MM-DD) that have at least one free slot."""
    today = datetime.now().strftime("%Y-%m-%d")
    cur = await db.execute("SELECT DISTINCT date FROM slots WHERE is_taken=0 AND date >= ? ORDER BY date", (today,))
    rows = await cur.fetchall()
    return [row["date"] for row in rows]

async def get_free_times(date: str):
    """Get list of (slot_id, time) for free slots on a given date."""
    cur = await db.execute("SELECT id, time FROM slots WHERE date=? AND is_taken=0 ORDER BY time", (date,))
    rows = await cur.fetchall()
    return [(row["id"], row["time"]) for row in rows]

async def get_booking_by_id(booking_id: int):
    """Get a booking record by ID."""
    cur = await db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,))
    return await cur.fetchone()

async def get_booking_details(booking_id: int):
    """Get detailed booking info joined with user and slot."""
    query = """SELECT b.id, b.status, b.num_questions, b.amount, b.story, b.participants, b.questions, b.photos, b.admin_message_id,
                      u.name as user_name, u.username as username, u.phone as phone,
                      s.date as date, s.time as time, b.user_id
               FROM bookings b 
               JOIN users u ON b.user_id = u.user_id
               JOIN slots s ON b.slot_id = s.id
               WHERE b.id = ?"""
    cur = await db.execute(query, (booking_id,))
    return await cur.fetchone()

async def update_booking_status(booking_id: int, new_status: str):
    """Update booking status."""
    await db.execute("UPDATE bookings SET status=? WHERE id=?", (new_status, booking_id))
    await db.commit()

async def set_booking_admin_message_id(booking_id: int, message_id: int):
    """Store the admin group message ID associated with a booking."""
    await db.execute("UPDATE bookings SET admin_message_id=? WHERE id=?", (message_id, booking_id))
    await db.commit()

async def get_user_bookings(user_id: int):
    """Get list of upcoming bookings for a user (excluding cancelled/rejected)."""
    today = datetime.now().strftime("%Y-%m-%d")
    query = """SELECT b.id, b.status, s.date, s.time 
               FROM bookings b JOIN slots s ON b.slot_id = s.id
               WHERE b.user_id = ? AND b.status NOT IN (?, ?) AND s.date >= ?
               ORDER BY s.date, s.time"""
    cur = await db.execute(query, (user_id, config.STATUS_CANCELLED, config.STATUS_REJECTED, today))
    return await cur.fetchall()

async def get_all_slots():
    """Get all slots (date, time, is_taken) from today onward."""
    today = datetime.now().strftime("%Y-%m-%d")
    cur = await db.execute("SELECT date, time, is_taken FROM slots WHERE date >= ? ORDER BY date, time", (today,))
    return await cur.fetchall()

async def get_all_bookings():
    """Get all bookings joined with user info."""
    query = """SELECT s.date, s.time, b.status, u.name as user_name, u.username as username
               FROM bookings b 
               JOIN users u ON b.user_id = u.user_id
               JOIN slots s ON b.slot_id = s.id
               ORDER BY s.date, s.time"""
    cur = await db.execute(query)
    return await cur.fetchall()