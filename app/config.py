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


def _env_choice(key: str, default: str, choices: set[str]) -> str:
    raw = os.getenv(key, default).strip().lower()
    return raw if raw in choices else default


def _env_time(key: str, default: str) -> time:
    raw = os.getenv(key, default).strip()
    hour_text, minute_text = raw.split(":", 1)
    return time(int(hour_text), int(minute_text))


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

ASR_PROVIDER = os.getenv("ASR_PROVIDER", "openai_whisper").strip().lower()
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()
DASHSCOPE_ASR_MODEL = os.getenv("DASHSCOPE_ASR_MODEL", "qwen3-asr-flash").strip()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CHAT_MODEL_NAME = os.getenv("OPENROUTER_CHAT_MODEL", "openai/gpt-4o-mini")
VISION_MODEL_NAME = os.getenv("OPENROUTER_VISION_MODEL", CHAT_MODEL_NAME)
MEMORY_MODEL_NAME = os.getenv("OPENROUTER_MEMORY_MODEL", "openai/gpt-4o-mini")
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "6"))
MEMORY_LIMIT = int(os.getenv("MEMORY_LIMIT", "3"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
PLATFORM_TOKEN = os.getenv("PLATFORM_TOKEN", "").strip()
SYSTEM_PROMPT = load_text("prompts/system.txt")

BURST_MERGE_ENABLED = _env_bool("BURST_MERGE_ENABLED", True)
BURST_MERGE_WINDOW_SECONDS = _env_float("BURST_MERGE_WINDOW_SECONDS", 12)
BURST_MERGE_MAX_MESSAGES = _env_int("BURST_MERGE_MAX_MESSAGES", 5)
WX_SESSION_AGGREGATE_WINDOW_SECONDS = _env_float("WX_SESSION_AGGREGATE_WINDOW_SECONDS", 5.0)

PROACTIVE_ENABLED = _env_bool("PROACTIVE_ENABLED", False)
PROACTIVE_MODE = _env_choice("PROACTIVE_MODE", "off", {"off", "observe", "candidate", "dry_run", "auto"})
PROACTIVE_CHECK_INTERVAL_SECONDS = _env_int("PROACTIVE_CHECK_INTERVAL_SECONDS", 600)
PROACTIVE_DAILY_LIMIT = _env_int("PROACTIVE_DAILY_LIMIT", 2)
PROACTIVE_MIN_INTERVAL_MINUTES = _env_int("PROACTIVE_MIN_INTERVAL_MINUTES", 240)
PROACTIVE_RECENT_CHAT_SKIP_MINUTES = _env_int("PROACTIVE_RECENT_CHAT_SKIP_MINUTES", 45)
PROACTIVE_HARD_COOLDOWN_MINUTES = _env_int("PROACTIVE_HARD_COOLDOWN_MINUTES", 10)
PROACTIVE_FAILURE_PAUSE_THRESHOLD = _env_int("PROACTIVE_FAILURE_PAUSE_THRESHOLD", 3)
PROACTIVE_ACTIVE_START = os.getenv("PROACTIVE_ACTIVE_START", "10:30").strip()
PROACTIVE_ACTIVE_END = os.getenv("PROACTIVE_ACTIVE_END", "23:30").strip()
PROACTIVE_ACTIVE_START_TIME = _env_time("PROACTIVE_ACTIVE_START", "10:30")
PROACTIVE_ACTIVE_END_TIME = _env_time("PROACTIVE_ACTIVE_END", "23:30")
PROACTIVE_RANDOM_PROBABILITY = _env_float("PROACTIVE_RANDOM_PROBABILITY", 0.25)
PROACTIVE_QQ_ALLOWED_TARGET_HASHES = _env_csv("PROACTIVE_QQ_ALLOWED_TARGET_HASHES")
PROACTIVE_AUTO_SEND = _env_bool("PROACTIVE_AUTO_SEND", False)
PROACTIVE_AUTO_SEND_DRY_RUN = _env_bool("PROACTIVE_AUTO_SEND_DRY_RUN", False)
PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET = _env_bool("PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET", True)
PROACTIVE_AUTO_SEND_MAX_PER_DAY = _env_int("PROACTIVE_AUTO_SEND_MAX_PER_DAY", 1)
NENO_BRIDGE_SEND_QQ_URL = os.getenv(
    "NENO_BRIDGE_SEND_QQ_URL",
    "http://127.0.0.1:18793/proactive/send-qq",
).strip()
NENO_BRIDGE_SEND_WX_URL = os.getenv(
    "NENO_BRIDGE_SEND_WX_URL",
    "http://127.0.0.1:18793/proactive/send-wx",
).strip()
