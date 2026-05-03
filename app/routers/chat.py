import time

from fastapi import APIRouter, HTTPException

from app.schemas import ChatRequest, ChatResponse
from app.services.chat.multimodal_input_service import (
    MULTIMODAL_USER_ERROR_MESSAGE,
    MultimodalInputError,
    normalize_multimodal_message,
)
from app.services.chat_service import run_chat_turn
from app.services.stats_service import record_chat_stat
from app.utils.logging_utils import log_event, new_trace_id

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    started = time.perf_counter()
    trace_id = new_trace_id()
    message = req.message
    has_image_attachment = any(item.kind == "image" for item in req.attachments)

    if has_image_attachment:
        try:
            message = normalize_multimodal_message(
                message=req.message,
                attachments=req.attachments,
                trace_id=trace_id,
            )
        except MultimodalInputError as exc:
            record_chat_stat(
                source="web",
                platform="web",
                session_id=req.session_id,
                message=req.message,
                reply="",
                success=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_type=type(exc).__name__,
            )
            log_event(
                "chat",
                "multimodal_normalize_failed",
                trace_id=trace_id,
                session_id=req.session_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise HTTPException(status_code=400, detail=MULTIMODAL_USER_ERROR_MESSAGE) from exc

        if not message:
            raise HTTPException(status_code=400, detail="normalized message must not be blank")

        log_event(
            "chat",
            "multimodal_normalize_ok",
            trace_id=trace_id,
            session_id=req.session_id,
            normalized_message_len=len(message),
        )

    try:
        result = run_chat_turn(req.session_id, message, trace_id=trace_id)
    except RuntimeError as exc:
        record_chat_stat(
            source="web",
            platform="web",
            session_id=req.session_id,
            message=message,
            reply="",
            success=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        record_chat_stat(
            source="web",
            platform="web",
            session_id=req.session_id,
            message=message,
            reply="",
            success=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
        )
        raise

    record_chat_stat(
        source="web",
        platform="web",
        session_id=req.session_id,
        message=message,
        reply=result["reply"],
        success=True,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )

    return ChatResponse(
        reply=result["reply"],
        candidate_memory=result["candidate_memory"],
        candidate_memory_decision=result["candidate_memory_decision"],
        auto_added=result["auto_added"],
        auto_added_memory=result["auto_added_memory"],
        used_memories=result["used_memories"],
        relationship_state=result["relationship_state"],
        relationship_context=result["relationship_context"],
    )
