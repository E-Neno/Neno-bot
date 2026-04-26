import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.schemas import PlatformMessageRequest, PlatformMessageResponse
from app.security import require_platform_token
from app.services.chat_service import run_chat_turn
from app.services.stats_service import record_chat_stat

router = APIRouter(prefix="/platform", tags=["platform"])

SUPPORTED_PLATFORMS = {"qq", "wx", "test"}
SUPPORTED_CHAT_TYPES = {"private", "group"}
MAX_MESSAGE_LENGTH = 2000


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

    print(
        "platform message:",
        f"platform={platform}",
        f"user_id={user_id}",
        f"chat_type={chat_type}",
        f"session_id={session_id}",
    )

    started = time.perf_counter()
    try:
        result = run_chat_turn(session_id, message)
    except Exception as exc:
        record_chat_stat(
            source="platform",
            platform=platform,
            session_id=session_id,
            message=message,
            reply="",
            success=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
        )
        print("platform chat failed:", exc)
        raise HTTPException(status_code=500, detail="chat failed") from exc

    record_chat_stat(
        source="platform",
        platform=platform,
        session_id=session_id,
        message=message,
        reply=result["reply"],
        success=True,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )

    return PlatformMessageResponse(
        success=True,
        reply=result["reply"],
        session_id=session_id,
    )
