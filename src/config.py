import os
from dotenv import load_dotenv

load_dotenv()


def _setting(name):
    """Read a setting from the environment, falling back to Streamlit's secrets (hosting)."""
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st
        return st.secrets.get(name)
    except Exception:
        return None


GROQ_API_KEY = _setting("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = _setting("TELEGRAM_BOT_TOKEN")

GROQ_MODEL_NAME = "openai/gpt-oss-120b"


if not GROQ_API_KEY:
    raise ValueError(
        "CRITICAL: GROQ_API_KEY missing. Set it in .env locally, or in the host's secrets."
    )
