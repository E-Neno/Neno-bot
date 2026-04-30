import json
import time

from app.config import (
    CHAT_MODEL_NAME,
    HISTORY_LIMIT,
    MEMORY_MODEL_NAME,
    OPENROUTER_API_KEY,
    OPENROUTER_URL,
    SYSTEM_PROMPT,
)
from app.llm.openrouter_client import chat_with_openrouter
from app.services.memory_candidate_decision_service import (
    apply_memory_candidate_decision,
    decide_memory_candidate,
)
from app.services.memory_context_service import build_memory_context, build_memory_context_message
from app.services.relationship_service import (
    apply_relationship_update,
    build_relationship_context,
    build_relationship_context_readonly,
    get_relationship_state_for_api,
)
from app.services.time_context_service import build_time_context, build_time_context_message
from app.storage.db import add_message, get_recent_messages
from app.storage.relationship import ensure_relationship_state
from app.utils.logging_utils import log_event, new_trace_id

MEMORY_EXTRACTION_PROMPT = """
请判断下面这句话是否包含适合长期记忆的信息。

判断标准：
1. 只有在这句话未来大概率还会反复影响聊天体验时，才允许存。
2. 普通口味、随口提到的小偏好、一次性表达，默认不存。
3. 如果适合存，请提炼成简短自然的一句话
4. memory_type 只能是以下之一：
profile
preference
boundary
routine
relationship
project
5. 提炼后的 content 必须使用自然、简洁、贴近中文口语的表达
6. 不要使用“他们”、“她们”、“其”、“该用户”这类泛化或书面化代词
7. 统一写成“用户……”开头，或者直接写自然事实，不要写得像报告

请只返回 JSON，不要解释，不要加代码块。

格式如下：
{{
  "should_store": true,
  "content": "提炼后的记忆",
  "memory_type": "preference"
}}

如果不该存，就返回：
{{
  "should_store": false,
  "content": "",
  "memory_type": ""
}}

用户原话：
{message}
""".strip()


def require_api_key() -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return OPENROUTER_API_KEY


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


def _load_chat_contexts(
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


def build_chat_messages_preview(session_id: str, message: str) -> dict:
    contexts = _load_chat_contexts(session_id, message, readonly=True)
    time_context_text = build_time_context_message(contexts["time_context"])
    memory_context_text = build_memory_context_message(contexts["memory_context"])
    recent_messages = [
        {"role": item["role"], "content": item["content"]}
        for item in contexts["history"]
    ]

    return {
        "system_prompt": SYSTEM_PROMPT,
        "relationship_context": contexts["relationship_context"],
        "time_context": time_context_text,
        "memory_context": memory_context_text,
        "memory_contexts": contexts["memory_context"]["memory_contexts"],
        "selected_memories": contexts["memory_context"]["selected_memories"],
        "recent_messages": recent_messages,
        "current_user_message": message,
        "final_messages": contexts["messages"],
        "counts": {
            "memory_count": contexts["memory_context"]["memory_count"],
            "recent_message_count": len(recent_messages),
            "final_message_count": len(contexts["messages"]),
        },
    }


def request_memory_candidate(message: str, trace_id: str | None = None) -> dict | None:
    prompt = MEMORY_EXTRACTION_PROMPT.format(message=message)
    messages = [
        {"role": "system", "content": "你是一个专门负责提取长期记忆的助手。"},
        {"role": "user", "content": prompt},
    ]

    try:
        result = chat_with_openrouter(
            api_key=require_api_key(),
            url=OPENROUTER_URL,
            model_name=MEMORY_MODEL_NAME,
            messages=messages,
            timeout=60,
            trace_id=trace_id,
        )
        data = json.loads(result)
    except Exception as exc:
        log_event(
            "chat",
            "memory_candidate_error",
            trace_id=trace_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return None

    if data.get("content"):
        data["content"] = data["content"].strip().rstrip("。")

    return data


def generate_chat_reply(messages: list[dict], trace_id: str | None = None) -> str:
    return chat_with_openrouter(
        api_key=require_api_key(),
        url=OPENROUTER_URL,
        model_name=CHAT_MODEL_NAME,
        messages=messages,
        timeout=60,
        trace_id=trace_id,
    )


def run_chat_turn(session_id: str, message: str, trace_id: str | None = None) -> dict:
    trace_id = trace_id or new_trace_id()
    turn_started = time.perf_counter()
    log_event(
        "chat",
        "chat_turn_start",
        trace_id=trace_id,
        session_id=session_id,
        message_len=len(message or ""),
    )

    try:
        contexts = _load_chat_contexts(session_id, message, trace_id=trace_id)
        history = contexts["history"]
        relationship_context = contexts["relationship_context"]
        messages = contexts["messages"]
        used_memories = contexts["used_memories"]
        log_event(
            "chat",
            "recent_messages_loaded",
            trace_id=trace_id,
            session_id=session_id,
            count=len(history),
        )

        relationship_state = None
        log_event(
            "chat",
            "memories_loaded",
            trace_id=trace_id,
            session_id=session_id,
            count=len(used_memories),
        )

        candidate_memory_raw = request_memory_candidate(message, trace_id=trace_id)
        candidate_memory_decision = decide_memory_candidate(candidate_memory_raw)
        candidate_result = apply_memory_candidate_decision(
            candidate_memory_raw,
            candidate_memory_decision,
        )
        candidate_memory = candidate_result["candidate_memory"]
        auto_added_memory = candidate_result["auto_added"]

        model_started = time.perf_counter()
        log_event(
            "chat",
            "model_request_start",
            trace_id=trace_id,
            model=CHAT_MODEL_NAME,
        )
        reply = generate_chat_reply(messages, trace_id=trace_id)
        log_event(
            "chat",
            "model_response_ok",
            trace_id=trace_id,
            reply_len=len(reply or ""),
            latency_ms=int((time.perf_counter() - model_started) * 1000),
        )

        add_message(session_id, "user", message)
        add_message(session_id, "assistant", reply)

        try:
            relationship_state = apply_relationship_update(session_id, message)
        except Exception as exc:
            log_event(
                "chat",
                "relationship_update_warning",
                trace_id=trace_id,
                session_id=session_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            try:
                relationship_state = get_relationship_state_for_api(session_id)
            except Exception as fallback_exc:
                log_event(
                    "chat",
                    "relationship_state_fallback_warning",
                    trace_id=trace_id,
                    session_id=session_id,
                    error_type=type(fallback_exc).__name__,
                    error_message=str(fallback_exc),
                )
                relationship_state = None

        log_event(
            "chat",
            "chat_turn_finished",
            trace_id=trace_id,
            session_id=session_id,
            latency_ms=int((time.perf_counter() - turn_started) * 1000),
        )
        return {
            "reply": reply,
            "candidate_memory": candidate_memory,
            "candidate_memory_decision": candidate_memory_decision,
            "auto_added": auto_added_memory,
            "auto_added_memory": auto_added_memory,
            "used_memories": used_memories,
            "relationship_state": relationship_state,
            "relationship_context": relationship_context,
        }
    except Exception as exc:
        log_event(
            "chat",
            "chat_turn_error",
            trace_id=trace_id,
            session_id=session_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            latency_ms=int((time.perf_counter() - turn_started) * 1000),
        )
        raise
