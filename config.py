import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Gemini model to use (gemini-2.5-flash or gemini-1.5-flash are super fast and have free tiers!)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Temporary folder to hold downloaded videos
DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

def validate_config() -> tuple[bool, str]:
    """Validates that necessary keys are provided."""
    if not TELEGRAM_BOT_TOKEN:
        return False, "❌ Missing TELEGRAM_BOT_TOKEN in .env file! Please get one from @BotFather."
    if not GEMINI_API_KEY:
        return False, "❌ Missing GEMINI_API_KEY in .env file! Please get one from https://aistudio.google.com/."
    return True, "Config is valid! ✅"
