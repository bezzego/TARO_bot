import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram Bot token and configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env file")

# List of admin user IDs (from environment, comma-separated)
_admin_ids = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x) for x in _admin_ids.replace(" ", "").split(",") if x.isdigit() or (x and x[0] == '-' and x[1:].isdigit())]

# Telegram group chat ID for admin notifications
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID")
if ADMIN_GROUP_ID:
    try:
        ADMIN_GROUP_ID = int(ADMIN_GROUP_ID)
    except ValueError:
        raise ValueError("ADMIN_GROUP_ID must be an integer (Telegram chat ID)")

# Database path (SQLite file)
DB_PATH = os.getenv("DB_PATH", "bot.db")

# Booking status constants
STATUS_CREATED = "CREATED"
STATUS_WAITING_PAYMENT = "WAITING_PAYMENT"
STATUS_CHECKING = "CHECKING"       # waiting admin confirmation
STATUS_CONFIRMED = "CONFIRMED"
STATUS_REJECTED = "REJECTED"
STATUS_CANCELLED = "CANCELLED"

# Global bot instance (will be set in bot.py)
bot = None