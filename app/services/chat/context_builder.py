from app.config import HISTORY_TOKEN_LIMIT, SYSTEM_PROMPT
from app.services.chat.history_digest import get_history_digest_text, maybe_update_history_digest
from app.services.chat.self_state_context import build_self_state_context
from app.services.chat.voice_self import get_voice_context
from app.services.memory_context_service import build_memory_context, build_memory_context_message
from app.services.relationship_service import (
    build_relationship_context,
    build_relationship_context_readonly,
)
from app.services.time_context_service import (
    build_past_context, build_time_context, build_time_context_message,
)
from app.storage.db import get_recent_messages_by_tokens
from app.storage.relationship import ensure_relationship_state
from app.utils.logging_utils import log_event


def _history_content_with_time(item: dict) -> str:
    content = str(item.get("content") or "")
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    world_time = metadata.get("world_time") if isinstance(metadata, dict) else None
    display_date = ""
    display_time = ""
    if isinstance(world_time, dict):
        display_date = str(world_time.get("display_date") or "").strip()
        display_time = str(world_time.get("display_time") or "").strip()
    if display_time:
        lines = []
        if display_date:
            lines.append(f"【当时世界日期】{display_date}")
        lines.append(f"【当时世界时间】{display_time}")
        return "\n".join(lines + [content])
    return content


def build_chat_messages(
    history: list[dict],
    message: str,
    relationship_context: str | None = None,
    time_context: dict | None = None,
    memory_context: dict | None = None,
    history_digest: str | None = None,
    self_state_context: str | None = None,
    voice_context: str | None = None,
    past_events: str | None = None,
    current_turn_image_inputs: list[str] | None = None,
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
    hist = [{"role": item["role"], "content": _history_content_with_time(item)} for item in history]
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

    # ── 动态上下文（每次都变，放缓存断点之后）：每块一个独立标签、空则跳过。──
    # 不再用「当前情境」大壳；【对方刚说】永远是最后文本块（wx 测试 + 动态指导 insert-before 都依赖）。
    blocks: list[dict] = []

    def _add(label: str, body: str | None) -> None:
        text = (body or "").strip()
        if text:
            blocks.append({"type": "text", "text": f"{label}\n{text}"})

    # self_state_context 自带「【此刻的你】」头，直接放（不重复套标签）
    if self_state_context and self_state_context.strip():
        blocks.append({"type": "text", "text": self_state_context.strip()})
    _add("【你说话的调】", voice_context)        # D·声音自我（暂空，下一步填）
    _add("【你和对方】", relationship_context)
    _add("【往事】", past_events)                 # C·历史世界事件（暂空，下一步填）
    _add("【关于对方】", build_memory_context_message(memory_context or {}))
    if time_context:
        _add("【此刻】", build_time_context_message(time_context))
    # 这波消息：永远最后一个文本块；当前轮图片作为 image_url block 紧随其后。
    blocks.append({"type": "text", "text": "【对方刚说】\n" + message})
    for image_input in current_turn_image_inputs or []:
        value = str(image_input or "").strip()
        if value:
            blocks.append({"type": "image_url", "image_url": {"url": value}})

    messages.append({"role": "user", "content": blocks})
    used_memories = list((memory_context or {}).get("selected_memories") or [])
    return messages, used_memories


def build_executive_output_messages(
    *,
    contexts: dict,
    message: str,
    output_guidance: str,
    current_turn_image_inputs: list[str] | None = None,
) -> list[dict]:
    """构造隔离出口 prompt：保留缓存前缀、历史、声音样本和当前输入。

    主脑看过的 self_state / 关系 / 记忆 / 当前时间不进入这里，避免出口把内部状态
    当成聊天素材主动汇报。主脑只通过 output_guidance 暴露已经裁定的回应面。
    """
    messages, _ = build_chat_messages(
        history=list(contexts.get("history") or []),
        message=message,
        history_digest=str(contexts.get("history_digest") or "") or None,
        voice_context=str(contexts.get("voice_context") or "") or None,
        current_turn_image_inputs=current_turn_image_inputs,
    )
    guidance = (output_guidance or "").strip()
    if not guidance or not messages:
        return messages
    content = messages[-1].get("content")
    if not isinstance(content, list):
        return messages
    insert_at = len(content)
    for index, block in enumerate(content):
        if isinstance(block, dict) and str(block.get("text") or "").startswith("【对方刚说】"):
            insert_at = index
            break
    content.insert(insert_at, {"type": "text", "text": guidance})
    return messages


def load_chat_contexts(
    session_id: str,
    message: str,
    trace_id: str | None = None,
    readonly: bool = False,
    current_turn_image_inputs: list[str] | None = None,
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
    voice_context = get_voice_context()  # 声音自我：她说话的样子（从她真实回话结晶）
    past_events = build_past_context(time_context)  # 往事：隔久了就框成过去的事，别无缝接

    messages, used_memories = build_chat_messages(
        history=history,
        message=message,
        relationship_context=relationship_context,
        time_context=time_context,
        memory_context=memory_context,
        history_digest=history_digest,
        self_state_context=self_state_context,
        voice_context=voice_context,
        past_events=past_events,
        current_turn_image_inputs=current_turn_image_inputs,
    )
    return {
        "history": history,
        "time_context": time_context,
        "relationship_context": relationship_context,
        "memory_context": memory_context,
        "history_digest": history_digest,
        "self_state_context": self_state_context,
        "voice_context": voice_context,
        "past_events": past_events,
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
