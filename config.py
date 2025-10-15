# config.py (FULL DROP-IN)

from dotenv import load_dotenv
load_dotenv()

import os
from aiogram import Bot
from pathlib import Path

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

OWNER_ID = os.getenv("OWNER_ID")
if not OWNER_ID:
    raise ValueError("OWNER_ID environment variable is required")

try:
    OWNER_ID = int(OWNER_ID)
except ValueError:
    raise ValueError("OWNER_ID must be a valid integer")

# Telethon configuration
TELETHON_API_ID = os.getenv("TELETHON_API_ID")
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH")

if not TELETHON_API_ID or not TELETHON_API_HASH:
    raise ValueError("TELETHON_API_ID and TELETHON_API_HASH are required. Get them from https://my.telegram.org")

try:
    TELETHON_API_ID = int(TELETHON_API_ID)
except ValueError:
    raise ValueError("TELETHON_API_ID must be a valid integer")

# Admin users
ADMIN_USER_IDS = []
admin_ids_str = os.getenv("ADMIN_USER_IDS", "")
if admin_ids_str:
    try:
        ADMIN_USER_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]
    except ValueError:
        print("Warning: Invalid ADMIN_USER_IDS format, ignoring")

if OWNER_ID not in ADMIN_USER_IDS:
    ADMIN_USER_IDS.append(OWNER_ID)

# Create bot instance
# NOTE: aiogram 2.x da 'session' parametri yo'q.
# Timeoutni shu yerda berib barqarorlikni biroz oshiramiz.
bot = Bot(token=BOT_TOKEN, parse_mode="HTML", timeout=60)

# Directory configuration
DATA_DIR = os.getenv("DATA_DIR", "data")
TESTS_DIR = os.path.join(DATA_DIR, "tests")
STUDENTS_DIR = os.path.join(DATA_DIR, "students")

# File paths
ACTIVE_TEST_FILE = os.path.join(TESTS_DIR, "active_tests.json")
GROUPS_FILE = os.path.join(DATA_DIR, "groups.txt")
STUDENTS_FILE = os.path.join(DATA_DIR, "students.json")
USER_GROUPS_FILE = os.path.join(DATA_DIR, "user_groups.json")
GROUP_MEMBERS_FILE = os.path.join(DATA_DIR, "group_members.json")

# Database configuration (optional)
DATABASE_URL = os.getenv("DATABASE_URL")

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("LOG_DIR", "logs")

# Bot update types
ALLOWED_UPDATES = ['message', 'callback_query', 'chat_member', 'my_chat_member']

# Telethon session file
TELETHON_SESSION = os.path.join(DATA_DIR, "telethon_session")

def ensure_directories():
    """Ensure all required directories exist"""
    dirs = [DATA_DIR, TESTS_DIR, STUDENTS_DIR, LOG_DIR]
    for directory in dirs:
        Path(directory).mkdir(parents=True, exist_ok=True)

ensure_directories()
