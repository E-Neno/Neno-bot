import os
from datetime import time

from app.prompt.prompt_loader import load_text


def _env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key, str(default)).strip()
    return int(raw)


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key, str(default)).strip()
    return float(raw)


def _env_csv(key: str) -> tuple[str, ...]:
    raw = os.getenv(key, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_time(key: str, default: str) -> time:
    raw = os.getenv(key, default).strip()
    hour_text, minute_text = raw.split(":", 1)
    return time(int(hour_text), int(minute_text))


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CHAT_MODEL_NAME = os.getenv("OPENROUTER_CHAT_MODEL", "openai/gpt-4o-mini")
MEMORY_MODEL_NAME = os.getenv("OPENROUTER_MEMORY_MODEL", "openai/gpt-4o-mini")
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "6"))
MEMORY_LIMIT = int(os.getenv("MEMORY_LIMIT", "3"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
PLATFORM_TOKEN = os.getenv("PLATFORM_TOKEN", "").strip()
SYSTEM_PROMPT = load_text("prompts/system.txt")

PROACTIVE_ENABLED = _env_bool("PROACTIVE_ENABLED", False)
PROACTIVE_CHECK_INTERVAL_SECONDS = _env_int("PROACTIVE_CHECK_INTERVAL_SECONDS", 600)
PROACTIVE_DAILY_LIMIT = _env_int("PROACTIVE_DAILY_LIMIT", 2)
PROACTIVE_MIN_INTERVAL_MINUTES = _env_int("PROACTIVE_MIN_INTERVAL_MINUTES", 240)
PROACTIVE_RECENT_CHAT_SKIP_MINUTES = _env_int("PROACTIVE_RECENT_CHAT_SKIP_MINUTES", 45)
PROACTIVE_ACTIVE_START = os.getenv("PROACTIVE_ACTIVE_START", "10:30").strip()
PROACTIVE_ACTIVE_END = os.getenv("PROACTIVE_ACTIVE_END", "23:30").strip()
PROACTIVE_ACTIVE_START_TIME = _env_time("PROACTIVE_ACTIVE_START", "10:30")
PROACTIVE_ACTIVE_END_TIME = _env_time("PROACTIVE_ACTIVE_END", "23:30")
PROACTIVE_RANDOM_PROBABILITY = _env_float("PROACTIVE_RANDOM_PROBABILITY", 0.25)
PROACTIVE_QQ_ALLOWED_TARGET_HASHES = _env_csv("PROACTIVE_QQ_ALLOWED_TARGET_HASHES")
NENO_BRIDGE_SEND_QQ_URL = os.getenv(
    "NENO_BRIDGE_SEND_QQ_URL",
    "http://127.0.0.1:18793/proactive/send-qq",
).strip()
