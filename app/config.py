import os
import json as _json
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
OPENROUTER_PROXY = os.getenv("OPENROUTER_PROXY", "").strip() or None
CHAT_MODEL_NAME = os.getenv("OPENROUTER_CHAT_MODEL", "openai/gpt-4o-mini")
VISION_MODEL_NAME = os.getenv("OPENROUTER_VISION_MODEL", CHAT_MODEL_NAME)
MEMORY_MODEL_NAME = os.getenv("OPENROUTER_MEMORY_MODEL", "openai/gpt-4o-mini")
# 理解+选择层（真人感取舍）：极简 JSON 决策，要快。用 MiMo（复用上面 MIMO_* 凭据）+ 关深度思考
# （thinking={"type":"disabled"} 把 ~15s 压到 ~1.2s，决策质量不变）。默认关（示例配置惯例）。
SELECTION_LAYER_ENABLED = os.getenv("CHAT_SELECTION_LAYER_ENABLED", "false").strip().lower() in ("1", "true", "yes")
SELECTION_TIMEOUT = int(os.getenv("CHAT_SELECTION_TIMEOUT", "8"))
SELECTION_THINKING_OFF = {"thinking": {"type": "disabled"}}  # MiMo 关思考；换 OpenRouter 模型时置空
# 声音自我：从她真实回话里结晶「她说话的样子」喂回 prompt（风格从她怎么说话长出来，不写死）。默认关。
VOICE_SELF_ENABLED = os.getenv("CHAT_VOICE_SELF_ENABLED", "false").strip().lower() in ("1", "true", "yes")
VOICE_SELF_MIN_NEW_REPLIES = int(os.getenv("CHAT_VOICE_SELF_MIN_NEW_REPLIES", "15"))  # 攒够这么多新回复才重蒸馏
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "").strip()
MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1").strip()
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5-pro").strip()
MIMO_TIMEOUT = _env_int("MIMO_TIMEOUT", 20)
WORLD_ACTION_LLM_LABEL_ENABLED = _env_bool("WORLD_ACTION_LLM_LABEL_ENABLED", False)
HISTORY_TOKEN_LIMIT = int(os.getenv("HISTORY_TOKEN_LIMIT", "500"))
MEMORY_LIMIT = int(os.getenv("MEMORY_LIMIT", "3"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
PLATFORM_TOKEN = os.getenv("PLATFORM_TOKEN", "").strip()
MOBILE_TOKEN = os.getenv("MOBILE_TOKEN", "").strip()
MOBILE_DEFAULT_SESSION_ID = os.getenv("MOBILE_DEFAULT_SESSION_ID", "mobile:neno").strip() or "mobile:neno"
SYSTEM_PROMPT = load_text("prompts/system.txt")
try:
    NENO_SEED = _json.loads(load_text("prompts/seed.json"))
except Exception:  # 文件缺失或损坏时降级，不让配置导入阻断应用
    NENO_SEED = {}

# Phase 5：把 Neno 真实生活状态（精力/情绪/在干嘛/牵挂）注入主聊天系统提示。
# read-only 零模型成本；置 false 可退回纯人设无状态聊天。
CONSCIOUSNESS_CHAT_SELF_STATE_ENABLED = _env_bool("CONSCIOUSNESS_CHAT_SELF_STATE_ENABLED", True)

# Phase 5：在场门控。她睡着/沉浸时由世界状态决定「晚点回」，攒进 pending，
# 等 world_loop 在她空下来/醒来那拍捡起来回。改变聊天回复时机，默认关闭，
# 需配合 world_loop_enabled 常驻循环消费 pending 才有意义。
WORLD_PRESENCE_GATE_ENABLED = _env_bool("WORLD_PRESENCE_GATE_ENABLED", False)
# 捡起 pending 后，平台来源(WX/QQ)的回复是否真发回去。默认 dry_run(只建候选+演练不真发)，
# 置 true 才经 neno-bridge 真推。web/控制台来源始终只写 session（刷新可见），不受此开关影响。
WORLD_PRESENCE_WX_AUTO_SEND = _env_bool("WORLD_PRESENCE_WX_AUTO_SEND", False)

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

# Phase 3b: Brain intent 消费器总开关。
# false = consume_brain_intents no-op，不创建 candidate，不发送，不改 status。
BRAIN_INTENT_CONSUMER_ENABLED = _env_bool("BRAIN_INTENT_CONSUMER_ENABLED", False)

# Phase 3b: Brain intent 发送白名单。
# 空列表 = brain send 子系统关闭（queued intent 保持积压，设计意图）。
BRAIN_WHITELIST_USERS: list[str] = [
    uid.strip()
    for uid in os.getenv("BRAIN_WHITELIST_USERS", "").split(",")
    if uid.strip()
]
