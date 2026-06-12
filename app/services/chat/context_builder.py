from app.config import HISTORY_TOKEN_LIMIT, SYSTEM_PROMPT
from app.services.chat.history_digest import get_history_digest_text, maybe_update_history_digest
from app.services.chat.self_state_context import build_self_state_context
from app.services.memory_context_service import build_memory_context, build_memory_context_message
from app.services.relationship_service import (
    build_relationship_context,
    build_relationship_context_readonly,
)
from app.services.time_context_service import build_time_context, build_time_context_message
from app.storage.db import get_recent_messages_by_tokens
from app.storage.relationship import ensure_relationship_state
from app.utils.logging_utils import log_event


def build_chat_messages(
    history: list[dict],
    message: str,
    relationship_context: str | None = None,
    time_context: dict | None = None,
    memory_context: dict | None = None,
    history_digest: str | None = None,
    self_state_context: str | None = None,
) -> tuple[list[dict], list[dict]]:
    # ── 稳定前缀（可缓存）：系统人设 + 历史摘要，缓存断点打在末尾 ──
    # 这段几乎不变，单独成缓存块。
    system_blocks: list[dict] = [{"type": "text", "text": SYSTEM_PROMPT}]
    if history_digest:
        system_blocks.append({"type": "text", "text": history_digest})
    system_blocks[-1]["cache_control"] = {"type": "ephemeral"}

    messages: list[dict] = [{"role": "system", "content": system_blocks}]

    # ── 会话历史（可缓存）：断点打在最后一条历史上，缓存 [系统+全部历史] 这段大头。──
    # 关键：动态上下文（时间/关系/记忆/self_state）绝不能排在历史之前，否则每次变化
    # 会把缓存前缀在历史之前打断，导致历史永远缓存不到（这是之前缓存一直不命中的根因）。
    hist = [{"role": item["role"], "content": item["content"]} for item in history]
    if hist:
        last = hist[-1]
        content = last["content"]
        if isinstance(content, str):
            last["content"] = [
                {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
            ]
        elif isinstance(content, list) and content:
            last["content"] = content[:-1] + [
                {**content[-1], "cache_control": {"type": "ephemeral"}}
            ]
    messages.extend(hist)

    # ── 动态上下文（每次都变，放缓存断点之后）：随新用户消息一起送 ──
    ctx_parts: list[str] = []
    if relationship_context:
        ctx_parts.append(relationship_context)
    if time_context:
        ctx_parts.append(build_time_context_message(time_context))
    if self_state_context:
        ctx_parts.append(self_state_context)
    memory_text = build_memory_context_message(memory_context or {})
    if memory_text:
        ctx_parts.append(memory_text)

    if ctx_parts:
        user_content: list[dict] = [
            {"type": "text", "text": "【当前情境，仅供你参考，不是对方说的话】\n" + "\n\n".join(ctx_parts)},
            {"type": "text", "text": "【对方刚说】\n" + message},
        ]
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": message})

    used_memories = list((memory_context or {}).get("selected_memories") or [])
    return messages, used_memories


def load_chat_contexts(
    session_id: str,
    message: str,
    trace_id: str | None = None,
    readonly: bool = False,
) -> dict:
    history = get_recent_messages_by_tokens(session_id, token_limit=HISTORY_TOKEN_LIMIT)
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

    raw_history_start_id = history[0]["id"] if history else None

    if not readonly:
        try:
            maybe_update_history_digest(session_id, trace_id=trace_id, raw_history_start_id=raw_history_start_id)
        except Exception as exc:
            log_event(
                "chat",
                "history_digest_update_warning",
                trace_id=trace_id,
                session_id=session_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    history_digest = get_history_digest_text(session_id)
    self_state_context = build_self_state_context(trace_id=trace_id)

    messages, used_memories = build_chat_messages(
        history=history,
        message=message,
        relationship_context=relationship_context,
        time_context=time_context,
        memory_context=memory_context,
        history_digest=history_digest,
        self_state_context=self_state_context,
    )
    return {
        "history": history,
        "time_context": time_context,
        "relationship_context": relationship_context,
        "memory_context": memory_context,
        "history_digest": history_digest,
        "self_state_context": self_state_context,
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
