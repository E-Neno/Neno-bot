import time
from copy import deepcopy

from app.config import CHAT_MODEL_NAME
from app.services.chat.context_builder import load_chat_contexts
from app.services.chat.llm_gateway import generate_chat_reply
from app.services.chat.memory_candidate_service import process_memory_candidate
from app.services.chat.preview_service import build_chat_messages_preview_from_contexts
from app.services.relationship_service import (
    apply_relationship_update,
    get_relationship_state_for_api,
)
from app.storage.db import add_message
from app.utils.logging_utils import log_event, new_trace_id


def run_chat_turn(
    session_id: str,
    message: str,
    trace_id: str | None = None,
    input_record: dict | None = None,
) -> dict:
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
        contexts = load_chat_contexts(session_id, message, trace_id=trace_id)
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

        memory_result = process_memory_candidate(
            message,
            trace_id=trace_id,
            input_record=input_record,
        )
        preview = build_chat_messages_preview_from_contexts(contexts, message)
        input_record_with_memory = deepcopy(input_record or {})
        input_record_with_memory["memory_candidate_snapshot"] = memory_result.get("candidate_memory_debug")
        input_record_with_memory["memory_candidate_decision"] = memory_result.get("candidate_memory_decision")
        input_record_with_memory["memory_auto_added"] = bool(memory_result.get("auto_added_memory"))

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

        user_message_id = add_message(
            session_id,
            "user",
            message,
            trace_id=trace_id,
            message_type=str((input_record or {}).get("message_type") or "text"),
            source=str((input_record or {}).get("source") or "chat"),
            metadata=input_record_with_memory,
            preview_payload={
                "trace_id": trace_id,
                "session_id": session_id,
                "preview": preview,
            },
        )
        assistant_message_id = add_message(
            session_id,
            "assistant",
            reply,
            trace_id=trace_id,
            message_type="assistant",
            source=str((input_record or {}).get("source") or "chat"),
        )

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
            "trace_id": trace_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "message_type": str((input_record or {}).get("message_type") or "text"),
            "source": str((input_record or {}).get("source") or "chat"),
            "reply": reply,
            "candidate_memory": memory_result["candidate_memory"],
            "candidate_memory_debug": memory_result.get("candidate_memory_debug"),
            "candidate_memory_decision": memory_result["candidate_memory_decision"],
            "auto_added": memory_result["auto_added_memory"],
            "auto_added_memory": memory_result["auto_added_memory"],
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
