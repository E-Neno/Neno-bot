import time

from fastapi import APIRouter, HTTPException

from app.schemas import ChatRequest, ChatResponse
from app.services.chat.multimodal_input_service import (
    MULTIMODAL_USER_ERROR_MESSAGE,
    MultimodalInputError,
    normalize_multimodal_message,
)
from app.services.chat_service import run_chat_turn
from app.services.visual_input_service import archive_current_turn_images
from app.services.stats_service import record_chat_stat
from app.utils.logging_utils import log_event, new_trace_id

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    started = time.perf_counter()
    trace_id = new_trace_id()
    message = req.message
    attachments = req.attachments or []
    has_image_attachment = any(item.kind == "image" for item in attachments)
    input_record = {
        "source": "web",
        "message_type": "image" if has_image_attachment else "text",
        "raw_input": req.message,
        "normalized_input": req.message,
        "attachments": [item.dict() for item in attachments],
        "pipeline": {
            "vision": {"hit": has_image_attachment, "success": None},
            "asr": {"hit": False, "success": None},
            "normalization": {"status": "bypassed" if not has_image_attachment else "pending"},
        },
    }

    if has_image_attachment:
        visual_projection = archive_current_turn_images(
            message=req.message,
            attachments=attachments,
            session_id=req.session_id,
            trace_id=trace_id,
            input_record=input_record,
        )
        if visual_projection is not None:
            message = visual_projection
            input_record["normalized_input"] = message
        else:
            try:
                message = normalize_multimodal_message(
                    message=req.message,
                    attachments=attachments,
                    trace_id=trace_id,
                )
            except MultimodalInputError as exc:
                input_record["pipeline"]["vision"]["success"] = False
                input_record["pipeline"]["normalization"] = {
                    "status": "failed",
                    "failed_at": "vision",
                    "error": str(exc),
                }
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

            input_record["normalized_input"] = message
            input_record["pipeline"]["vision"]["success"] = True
            input_record["pipeline"]["normalization"] = {
                "status": "success",
                "failed_at": None,
            }
            log_event(
                "chat",
                "multimodal_normalize_ok",
                trace_id=trace_id,
                session_id=req.session_id,
                normalized_message_len=len(message),
            )

    try:
        result = run_chat_turn(
            req.session_id,
            message,
            trace_id=trace_id,
            input_record=input_record,
        )
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
        trace_id=result.get("trace_id"),
        user_message_id=result.get("user_message_id"),
        assistant_message_id=result.get("assistant_message_id"),
        message_type=result.get("message_type"),
        source=result.get("source"),
        candidate_memory=result["candidate_memory"],
        candidate_memory_debug=result.get("candidate_memory_debug"),
        candidate_memory_decision=result["candidate_memory_decision"],
        auto_added=result["auto_added"],
        auto_added_memory=result["auto_added_memory"],
        used_memories=result["used_memories"],
        relationship_state=result["relationship_state"],
        relationship_context=result["relationship_context"],
    )
