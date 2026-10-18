import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

GROQ_MODEL_NAME = "openai/gpt-oss-120b"


if not GROQ_API_KEY:
    raise ValueError("CRITICAL: GROQ_API_KEY missing from environment configuration context.")
