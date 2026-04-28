import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.schemas import PlatformMessageRequest, PlatformMessageResponse
from app.security import require_platform_token
from app.services.chat_service import run_chat_turn
from app.services.proactive_service import record_qq_proactive_target
from app.services.stats_service import record_chat_stat
from app.utils.logging_utils import log_event, new_trace_id

router = APIRouter(prefix="/platform", tags=["platform"])

SUPPORTED_PLATFORMS = {"qq", "wx", "test"}
SUPPORTED_CHAT_TYPES = {"private", "group"}
MAX_MESSAGE_LENGTH = 2000


def mask_identifier(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "***"
    if len(text) <= 8:
        return f"{text[:2]}...{text[-2:]}"
    return f"{text[:4]}...{text[-4:]}"


def clean_required(value: Any, field_name: str) -> str:
    if value is None:
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field_name} must not be blank")
    return cleaned


def clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="group_id must be a string")
    cleaned = value.strip()
    return cleaned or None


def build_platform_session_id(req: PlatformMessageRequest) -> tuple[str, str, str, str]:
    platform = clean_required(req.platform, "platform")
    user_id = clean_required(req.user_id, "user_id")
    chat_type = clean_required(req.chat_type, "chat_type")

    if platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=400, detail="platform must be one of: qq, wx, test")
    if chat_type not in SUPPORTED_CHAT_TYPES:
        raise HTTPException(status_code=400, detail="chat_type must be private or group")

    if chat_type == "private":
        return f"{platform}:private:{user_id}", platform, user_id, chat_type

    group_id = clean_optional(req.group_id)
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required for group chat")
    return f"{platform}:group:{group_id}:{user_id}", platform, user_id, chat_type


@router.post(
    "/openclaw/message",
    response_model=PlatformMessageResponse,
    dependencies=[Depends(require_platform_token)],
)
def openclaw_message(payload: Any = Body(...)):
    trace_id = new_trace_id()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    try:
        req = PlatformMessageRequest(**payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid request body") from exc

    session_id, platform, user_id, chat_type = build_platform_session_id(req)
    message = clean_required(req.message, "message")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=400, detail="message must be 2000 characters or fewer")

    log_event(
        "platform",
        "message_received",
        trace_id=trace_id,
        platform=platform,
        chat_type=chat_type,
        user_id=user_id,
        session_id=session_id,
        message_len=len(message),
    )

    if platform == "qq" and chat_type == "private":
        try:
            record_qq_proactive_target(session_id=session_id, user_id=user_id)
        except Exception as exc:
            log_event(
                "platform",
                "proactive_target_upsert_warning",
                trace_id=trace_id,
                platform=platform,
                user_id=user_id,
                session_id=session_id,
                error_type=type(exc).__name__,
            )

    started = time.perf_counter()
    try:
        result = run_chat_turn(session_id, message, trace_id=trace_id)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        record_chat_stat(
            source="platform",
            platform=platform,
            session_id=session_id,
            message=message,
            reply="",
            success=False,
            latency_ms=latency_ms,
            error_type=type(exc).__name__,
        )
        log_event(
            "platform",
            "chat_turn_error",
            trace_id=trace_id,
            platform=platform,
            chat_type=chat_type,
            user_id=user_id,
            session_id=session_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            latency_ms=latency_ms,
        )
        raise HTTPException(status_code=500, detail="chat failed") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    record_chat_stat(
        source="platform",
        platform=platform,
        session_id=session_id,
        message=message,
        reply=result["reply"],
        success=True,
        latency_ms=latency_ms,
    )
    log_event(
        "platform",
        "chat_turn_ok",
        trace_id=trace_id,
        platform=platform,
        chat_type=chat_type,
        user_id=user_id,
        session_id=session_id,
        latency_ms=latency_ms,
        reply_len=len(result["reply"] or ""),
    )

    return PlatformMessageResponse(
        success=True,
        reply=result["reply"],
        session_id=session_id,
    )
