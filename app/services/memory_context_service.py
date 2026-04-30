import re

from app.config import MEMORY_LIMIT
from app.services.memory_service import get_relevant_memories

MAX_SELECTED_MEMORIES = 3
MIN_OBVIOUS_SCORE = 4
MIN_FALLBACK_SCORE = 3
RECENT_CONTEXT_TYPES = {"project", "routine"}
PROFILE_TYPES = {"profile"}
PREFERENCE_STYLE_TYPES = {"preference", "boundary"}
RECENT_CONTEXT_KEYWORDS = [
    "最近",
    "目前",
    "正在",
    "这段时间",
    "项目",
    "计划",
    "目标",
    "开发",
    "任务",
    "工作流",
]
STYLE_KEYWORDS = [
    "风格",
    "语气",
    "回复",
    "聊天",
    "短句",
    "自然",
    "套话",
    "称呼",
]
SENSITIVE_PATTERNS = [
    (re.compile(r"(?i)\b(bearer)\s+[a-z0-9._~+/=-]{8,}"), r"\1 ***"),
    (re.compile(r"(?i)\b(token|api[_-]?key|authorization)\s*[:=]\s*[^\s,;，；]+"), r"\1=***"),
    (re.compile(r"(?i)\b(openid|open_id|session_id)\s*[:=]\s*[a-z0-9_.:-]{6,}"), r"\1=***"),
    (re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}"), "sk-***"),
]


def _memory_layer(memory: dict) -> str | None:
    content = str(memory.get("content") or "")
    memory_type = str(memory.get("memory_type") or "")

    if memory_type in RECENT_CONTEXT_TYPES or any(keyword in content for keyword in RECENT_CONTEXT_KEYWORDS):
        return "recent_context"
    if memory_type in PREFERENCE_STYLE_TYPES or any(keyword in content for keyword in STYLE_KEYWORDS):
        return "preference_style"
    if memory_type in PROFILE_TYPES:
        return "profile"
    return None


def _layer_priority(layer: str | None) -> int:
    priorities = {
        "recent_context": 0,
        "preference_style": 1,
        "profile": 2,
    }
    return priorities.get(layer or "", 99)


def _format_memory_content(content: str) -> str:
    text = _redact_sensitive(content).strip().rstrip("。")
    if not text:
        return ""
    return text if text.startswith("用户") else f"用户{text}"


def _redact_sensitive(content: str) -> str:
    text = str(content or "")
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _public_selected_memory(memory: dict, context: str) -> dict:
    return {
        "id": memory.get("id"),
        "content": _redact_sensitive(str(memory.get("content") or "")),
        "memory_type": memory.get("memory_type"),
        "context_layer": memory.get("context_layer"),
        "score": int(memory.get("score") or 0),
        "created_at": memory.get("created_at"),
        "context": context,
    }


def _select_memories(relevant_memories: list[dict]) -> list[dict]:
    layered = []
    for memory in relevant_memories:
        layer = _memory_layer(memory)
        score = int(memory.get("score") or 0)
        if layer is None:
            continue
        if score < MIN_FALLBACK_SCORE:
            continue
        item = dict(memory)
        item["context_layer"] = layer
        layered.append(item)

    if not layered:
        return []

    max_score = max(int(memory.get("score") or 0) for memory in layered)
    if max_score < MIN_OBVIOUS_SCORE:
        layered.sort(key=lambda item: (-int(item.get("score") or 0), _layer_priority(item.get("context_layer"))))
        return layered[:1]

    obvious = [memory for memory in layered if int(memory.get("score") or 0) >= MIN_OBVIOUS_SCORE]
    obvious.sort(
        key=lambda item: (
            _layer_priority(item.get("context_layer")),
            -int(item.get("score") or 0),
            str(item.get("created_at") or ""),
        )
    )
    return obvious[:MAX_SELECTED_MEMORIES]


def build_memory_context(session_id: str, message: str) -> dict:
    del session_id
    relevant_memories = get_relevant_memories(message, limit=max(MEMORY_LIMIT, 8))
    selected_memories = _select_memories(relevant_memories)
    memory_contexts = []
    public_memories = []
    for memory in selected_memories:
        context = _format_memory_content(str(memory.get("content") or ""))
        if not context:
            continue
        memory_contexts.append(context)
        public_memories.append(_public_selected_memory(memory, context))

    return {
        "memory_contexts": memory_contexts,
        "selected_memories": public_memories,
        "memory_count": len(memory_contexts),
    }


def build_memory_context_message(memory_context: dict) -> str:
    contexts = list(memory_context.get("memory_contexts") or [])
    if not contexts:
        return ""

    return "\n".join(
        [
            "记忆背景：",
            "以下是与当前聊天相关的少量背景信息，仅在自然相关时轻量使用，不要像背资料一样硬提。",
            *[f"- {context}" for context in contexts[:MAX_SELECTED_MEMORIES]],
        ]
    )
