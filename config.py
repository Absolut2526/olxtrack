import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "120"))
DB_PATH = BASE_DIR / "data" / "bot.db"

# Ensure data directory exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
