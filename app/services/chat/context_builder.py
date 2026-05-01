from app.config import HISTORY_LIMIT, SYSTEM_PROMPT
from app.services.memory_context_service import build_memory_context, build_memory_context_message
from app.services.relationship_service import (
    build_relationship_context,
    build_relationship_context_readonly,
)
from app.services.time_context_service import build_time_context, build_time_context_message
from app.storage.db import get_recent_messages
from app.storage.relationship import ensure_relationship_state
from app.utils.logging_utils import log_event


def build_chat_messages(
    history: list[dict],
    message: str,
    relationship_context: str | None = None,
    time_context: dict | None = None,
    memory_context: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if relationship_context:
        messages.append({"role": "system", "content": relationship_context})
    if time_context:
        messages.append({"role": "system", "content": build_time_context_message(time_context)})

    memory_text = build_memory_context_message(memory_context or {})
    if memory_text:
        messages.append({"role": "system", "content": memory_text})

    messages.extend({"role": item["role"], "content": item["content"]} for item in history)
    messages.append({"role": "user", "content": message})
    used_memories = list((memory_context or {}).get("selected_memories") or [])
    return messages, used_memories


def load_chat_contexts(
    session_id: str,
    message: str,
    trace_id: str | None = None,
    readonly: bool = False,
) -> dict:
    history = get_recent_messages(session_id, limit=HISTORY_LIMIT)
    time_context = build_time_context(session_id)
    relationship_context = None
    try:
        if readonly:
            relationship_context = build_relationship_context_readonly(session_id)
        else:
            ensure_relationship_state(session_id)
            relationship_context = build_relationship_context(session_id)
    except Exception as exc:
        log_event(
            "chat",
            "relationship_context_warning",
            trace_id=trace_id,
            session_id=session_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    memory_context = build_memory_context(session_id, message)
    messages, used_memories = build_chat_messages(
        history=history,
        message=message,
        relationship_context=relationship_context,
        time_context=time_context,
        memory_context=memory_context,
    )
    return {
        "history": history,
        "time_context": time_context,
        "relationship_context": relationship_context,
        "memory_context": memory_context,
        "messages": messages,
        "used_memories": used_memories,
    }


def mask_session_id(session_id: str) -> str:
    value = (session_id or "").strip()
    if not value:
        return ""
    if len(value) <= 4:
        return "***"
    if len(value) <= 10:
        return f"{value[:2]}...{value[-2:]}"
    return f"{value[:4]}...{value[-4:]}"
