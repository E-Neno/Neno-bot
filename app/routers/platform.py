import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app import config
from app.schemas import (
    PlatformMessageRequest,
    PlatformMessageResponse,
    PlatformRoutingOverrideClearRequest,
    PlatformRoutingOverrideRequest,
)
from app.security import require_admin_token, require_platform_token
from app.services.burst_merge_service import BurstMergeService
from app.services.chat.multimodal_input_service import (
    MULTIMODAL_USER_ERROR_MESSAGE,
    MultimodalInputError,
    normalize_multimodal_message,
)
from app.services.chat.voice_asr_service import transcribe_voice, VoiceASRError
from app.services.chat_service import run_chat_turn
from app.services.proactive_service import record_platform_proactive_target
from app.services.session_submit_controller import SessionSubmitController, SubmitTicket
from app.services.stats_service import record_chat_stat
from app.storage.db import (
    clear_platform_routing_override,
    get_platform_routing_override,
    update_message_metadata,
    upsert_platform_routing_override,
)
from app.utils.logging_utils import log_event, new_trace_id

router = APIRouter(prefix="/platform", tags=["platform"])
burst_merge_service = BurstMergeService(
    window_seconds=config.BURST_MERGE_WINDOW_SECONDS,
    max_messages=config.BURST_MERGE_MAX_MESSAGES,
)
session_submit_controller = SessionSubmitController()

SUPPORTED_PLATFORMS = {"qq", "wx", "test"}
SUPPORTED_CHAT_TYPES = {"private", "group"}
MAX_MESSAGE_LENGTH = 2000


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _write_submit_debug(
    input_record: dict[str, Any] | None,
    *,
    snapshot: dict[str, object | None] | None,
) -> None:
    if input_record is None or not snapshot:
        return
    input_record["submit_debug"] = {
        "session_id": snapshot.get("session_id"),
        "arrival_seq": snapshot.get("arrival_seq"),
        "trace_id": snapshot.get("trace_id"),
        "submit_state": snapshot.get("submit_state"),
        "phase": snapshot.get("phase"),
        "controller_mode": snapshot.get("controller_mode"),
        "message_type": snapshot.get("message_type"),
        "received_at": snapshot.get("received_at"),
        "preprocessing_started_at": snapshot.get("preprocessing_started_at"),
        "ready_at": snapshot.get("ready_at"),
        "waiting_started_at": snapshot.get("waiting_started_at"),
        "submit_started_at": snapshot.get("submit_started_at"),
        "completed_at": snapshot.get("completed_at"),
        "failed_at": snapshot.get("failed_at"),
        "failed_phase": snapshot.get("failed_phase"),
        "fallback_completed_at": snapshot.get("fallback_completed_at"),
        "blocked_by_seq": snapshot.get("blocked_by_seq"),
        "submit_seq": snapshot.get("submit_seq"),
        "queue_wait_ms": snapshot.get("queue_wait_ms"),
        "submit_latency_ms": snapshot.get("submit_latency_ms"),
        "error_type": snapshot.get("error_type"),
        "error_message": snapshot.get("error_message"),
        "updated_at": snapshot.get("updated_at"),
    }


def _update_submit_debug_from_ticket(
    *,
    input_record: dict[str, Any] | None,
    submit_ticket: SubmitTicket | None,
) -> None:
    if input_record is None or submit_ticket is None:
        return
    snapshot = session_submit_controller.get_ticket_snapshot(ticket=submit_ticket)
    _write_submit_debug(input_record, snapshot=snapshot)


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


def clean_message_value(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="message must be a string")
    cleaned = value.strip()
    if len(cleaned) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=400, detail="message must be 2000 characters or fewer")
    return cleaned or None


def clean_optional_identifier(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a string")
    cleaned = value.strip()
    return cleaned or None


def clean_account_id(value: Any) -> str:
    cleaned = clean_optional_identifier(value, "account_id")
    return cleaned or "default"


def parse_platform_message_context(req: PlatformMessageRequest) -> dict[str, str | None]:
    platform = clean_required(req.platform, "platform")
    account_id = clean_account_id(req.account_id)
    user_id = clean_required(req.user_id, "user_id")
    chat_type = clean_required(req.chat_type, "chat_type")

    if platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=400, detail="platform must be one of: qq, wx, test")
    if chat_type not in SUPPORTED_CHAT_TYPES:
        raise HTTPException(status_code=400, detail="chat_type must be private or group")

    group_id = None
    if chat_type == "private":
        auto_session_id = f"{platform}:private:{user_id}"
    else:
        group_id = clean_optional(req.group_id)
        if not group_id:
            raise HTTPException(status_code=400, detail="group_id is required for group chat")
        auto_session_id = f"{platform}:group:{group_id}:{user_id}"

    routing_key = build_platform_routing_key(
        platform=platform,
        account_id=account_id,
        chat_type=chat_type,
        user_id=user_id,
        group_id=group_id,
    )
    return {
        "platform": platform,
        "account_id": account_id,
        "user_id": user_id,
        "chat_type": chat_type,
        "group_id": group_id,
        "auto_session_id": auto_session_id,
        "routing_key": routing_key,
    }


def build_platform_routing_key(
    *,
    platform: str,
    account_id: str,
    user_id: str,
    chat_type: str,
    group_id: str | None,
) -> str:
    if chat_type == "group":
        if not group_id:
            raise HTTPException(status_code=400, detail="group_id is required for group chat")
        return f"{platform}:{account_id}:group:{group_id}:{user_id}"
    return f"{platform}:{account_id}:private:{user_id}"


def resolve_platform_session_route(
    req: PlatformMessageRequest,
    *,
    trace_id: str | None = None,
    log_decision: bool = True,
) -> dict[str, Any]:
    context = parse_platform_message_context(req)
    platform = str(context["platform"])
    account_id = str(context["account_id"])
    routing_key = str(context["routing_key"])
    auto_session_id = str(context["auto_session_id"])
    override = get_platform_routing_override(
        platform=platform,
        account_id=account_id,
        routing_key=routing_key,
        active_only=True,
    )
    final_session_id = str((override or {}).get("session_id") or auto_session_id)
    routing_mode = "override" if override else "auto"
    routing_reason = "active override" if override else "default auto session routing"

    resolved = {
        **context,
        "final_session_id": final_session_id,
        "routing_mode": routing_mode,
        "routing_reason": routing_reason,
        "override_session_id": override.get("session_id") if override else None,
        "override_operator": override.get("operator") if override else None,
        "override_updated_at": override.get("updated_at") if override else None,
    }
    if log_decision:
        log_event(
            "platform",
            "session_routing_resolved",
            trace_id=trace_id,
            platform=platform,
            account_id=account_id,
            user_id=str(context["user_id"]),
            chat_type=str(context["chat_type"]),
            group_id=context["group_id"],
            routing_key=routing_key,
            routing_mode=routing_mode,
            auto_session_id=auto_session_id,
            final_session_id=final_session_id,
            override_session_id=override.get("session_id") if override else None,
            operator=override.get("operator") if override else None,
            reason=routing_reason if not override else override.get("reason"),
        )
    return resolved


def run_platform_chat_turn(
    *,
    trace_id: str,
    session_id: str,
    platform: str,
    user_id: str,
    chat_type: str,
    message: str,
    input_record: dict | None = None,
    submit_ticket: SubmitTicket | None = None,
) -> PlatformMessageResponse:
    started = time.perf_counter()
    try:
        result = run_chat_turn(
            session_id,
            message,
            trace_id=trace_id,
            input_record=input_record,
        )
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
    if input_record is not None:
        input_record["_submit_user_message_id"] = result["user_message_id"]
        input_record["_submit_assistant_message_id"] = result["assistant_message_id"]

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


def raise_http_exception(exc: HTTPException) -> None:
    raise exc


def should_use_session_submit_controller(*, platform: str) -> bool:
    return platform == "wx"


def preprocess_platform_message(
    *,
    trace_id: str,
    session_id: str,
    platform: str,
    user_id: str,
    chat_type: str,
    raw_message: str | None,
    attachments: list,
    input_record: dict,
    submit_ticket: SubmitTicket | None = None,
) -> str | PlatformMessageResponse:
    has_image_attachment = any(item.kind == "image" for item in attachments)
    has_voice_attachment = any(item.kind == "voice" for item in attachments)

    log_event(
        "platform",
        "message_preprocess_start",
        trace_id=trace_id,
        platform=platform,
        chat_type=chat_type,
        user_id=user_id,
        session_id=session_id,
        message_type=input_record.get("message_type"),
        attachment_count=len(attachments),
    )

    if has_voice_attachment and not has_image_attachment:
        voice_attachment = next((item for item in attachments if item.kind == "voice"), None)
        if voice_attachment and voice_attachment.media_path:
            try:
                raw_message = transcribe_voice(voice_attachment.media_path, trace_id)
                if not raw_message:
                    raw_message = "[语音消息(未听清)]"
                input_record["pipeline"]["asr"]["success"] = True
                input_record["pipeline"]["asr"]["text"] = raw_message
            except VoiceASRError:
                input_record["pipeline"]["asr"] = {
                    "hit": True,
                    "success": False,
                    "failed_at": "asr",
                }
                if submit_ticket is not None:
                    snapshot = session_submit_controller.mark_state(
                        ticket=submit_ticket,
                        submit_state="preprocessing",
                        phase="preprocess_failed",
                        message_type=str(input_record.get("message_type") or "text"),
                        error_type="VoiceASRError",
                        error_message="voice transcription failed",
                        failed_phase="preprocess",
                    )
                    _write_submit_debug(input_record, snapshot=snapshot)
                log_event(
                    "platform",
                    "asr_failed_fallback",
                    trace_id=trace_id,
                    session_id=session_id,
                    user_id=user_id,
                    platform=platform,
                    chat_type=chat_type,
                )
                return PlatformMessageResponse(
                    success=True,
                    reply="这条语音我刚刚没听清，你再发一次试试。",
                    session_id=session_id,
                )
        elif not raw_message:
            raw_message = "[语音消息]"
            input_record["pipeline"]["asr"]["success"] = False
            input_record["pipeline"]["asr"]["failed_at"] = "missing_media_path"

    if has_image_attachment:
        try:
            normalized_message = normalize_multimodal_message(
                message=raw_message,
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
            if submit_ticket is not None:
                snapshot = session_submit_controller.mark_state(
                    ticket=submit_ticket,
                    submit_state="failed",
                    phase="preprocess",
                    message_type=str(input_record.get("message_type") or "text"),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    failed_phase="preprocess",
                )
                _write_submit_debug(input_record, snapshot=snapshot)
            log_event(
                "platform",
                "multimodal_normalize_failed",
                trace_id=trace_id,
                platform=platform,
                chat_type=chat_type,
                user_id=user_id,
                session_id=session_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise HTTPException(status_code=400, detail=MULTIMODAL_USER_ERROR_MESSAGE) from exc

        if not normalized_message:
            raise HTTPException(status_code=400, detail="normalized message must not be blank")

        input_record["pipeline"]["vision"]["success"] = True
        input_record["pipeline"]["normalization"] = {
            "status": "success",
            "failed_at": None,
        }
        log_event(
            "platform",
            "multimodal_normalize_ok",
            trace_id=trace_id,
            platform=platform,
            chat_type=chat_type,
            user_id=user_id,
            session_id=session_id,
            normalized_message_len=len(normalized_message),
        )
        message = normalized_message
    else:
        if raw_message is None:
            raise HTTPException(status_code=400, detail="message must not be blank")
        message = raw_message

    input_record["raw_input"] = raw_message
    input_record["normalized_input"] = message
    if submit_ticket is not None:
        snapshot = session_submit_controller.mark_state(
            ticket=submit_ticket,
            submit_state="ready",
            phase="preprocess",
            message_type=str(input_record.get("message_type") or "text"),
        )
        _write_submit_debug(input_record, snapshot=snapshot)
    log_event(
        "platform",
        "message_preprocess_finished",
        trace_id=trace_id,
        platform=platform,
        chat_type=chat_type,
        user_id=user_id,
        session_id=session_id,
        normalized_message_len=len(message or ""),
    )
    return message


def submit_platform_chat_turn(
    *,
    trace_id: str,
    session_id: str,
    platform: str,
    user_id: str,
    chat_type: str,
    message: str,
    input_record: dict | None = None,
    submit_ticket: SubmitTicket | None = None,
) -> PlatformMessageResponse:
    if submit_ticket is None:
        return run_platform_chat_turn(
            trace_id=trace_id,
            session_id=session_id,
            platform=platform,
            user_id=user_id,
            chat_type=chat_type,
            message=message,
            input_record=input_record,
        )

    response_future = session_submit_controller.submit_ready(
        ticket=submit_ticket,
        handler=lambda: (
            _update_submit_debug_from_ticket(
                input_record=input_record,
                submit_ticket=submit_ticket,
            ),
            run_platform_chat_turn(
                trace_id=trace_id,
                session_id=session_id,
                platform=platform,
                user_id=user_id,
                chat_type=chat_type,
                message=message,
                input_record=input_record,
                submit_ticket=submit_ticket,
            ),
        )[1],
    )
    response = response_future.wait()
    _update_submit_debug_from_ticket(
        input_record=input_record,
        submit_ticket=submit_ticket,
    )
    user_message_id = None if input_record is None else input_record.pop("_submit_user_message_id", None)
    if input_record is not None:
        input_record.pop("_submit_assistant_message_id", None)
    if isinstance(user_message_id, int):
        update_message_metadata(user_message_id, input_record)
    if isinstance(response, PlatformMessageResponse):
        return response
    raise HTTPException(status_code=500, detail="chat failed")


def submit_platform_response(
    *,
    submit_ticket: SubmitTicket | None,
    response: PlatformMessageResponse,
) -> PlatformMessageResponse:
    if submit_ticket is None:
        return response

    future = session_submit_controller.submit_ready(
        ticket=submit_ticket,
        handler=lambda: response,
        completion_state="fallback_completed",
    )
    result = future.wait()
    if isinstance(result, PlatformMessageResponse):
        return result
    raise HTTPException(status_code=500, detail="chat failed")


def submit_platform_exception(
    *,
    submit_ticket: SubmitTicket | None,
    exc: HTTPException,
) -> None:
    if submit_ticket is None:
        raise exc

    future = session_submit_controller.submit_ready(
        ticket=submit_ticket,
        handler=lambda: raise_http_exception(exc),
    )
    future.wait()


def build_routing_explain(req: PlatformMessageRequest) -> dict[str, Any]:
    resolved = resolve_platform_session_route(req, log_decision=False)
    stored_override = get_platform_routing_override(
        platform=str(resolved["platform"]),
        account_id=str(resolved["account_id"]),
        routing_key=str(resolved["routing_key"]),
        active_only=False,
    )
    return {
        "platform": resolved["platform"],
        "account_id": resolved["account_id"],
        "user_id": resolved["user_id"],
        "chat_type": resolved["chat_type"],
        "group_id": resolved["group_id"],
        "routing_key": resolved["routing_key"],
        "auto_session_id": resolved["auto_session_id"],
        "final_session_id": resolved["final_session_id"],
        "routing_mode": resolved["routing_mode"],
        "routing_reason": resolved["routing_reason"],
        "override": {
            "exists": stored_override is not None,
            "active": bool((stored_override or {}).get("is_active")),
            "session_id": (stored_override or {}).get("session_id"),
            "operator": (stored_override or {}).get("operator"),
            "reason": (stored_override or {}).get("reason"),
            "updated_at": (stored_override or {}).get("updated_at"),
        },
        "effective_scope": "future inbound messages only",
    }


@router.get("/session-routing", dependencies=[Depends(require_admin_token)])
def get_session_routing(
    platform: str = Query(..., max_length=16),
    user_id: str = Query(..., max_length=128),
    chat_type: str = Query(..., max_length=16),
    account_id: str | None = Query(default=None, max_length=64),
    group_id: str | None = Query(default=None, max_length=128),
):
    req = PlatformMessageRequest(
        platform=platform,
        account_id=account_id,
        user_id=user_id,
        chat_type=chat_type,
        group_id=group_id,
    )
    explain = build_routing_explain(req)
    return {
        "success": True,
        "explain": explain,
    }


@router.post("/session-routing/override", dependencies=[Depends(require_admin_token)])
def set_session_routing_override(req: PlatformRoutingOverrideRequest):
    request_context = PlatformMessageRequest(
        platform=req.platform,
        account_id=req.account_id,
        user_id=req.user_id,
        chat_type=req.chat_type,
        group_id=req.group_id,
    )
    explain_before = build_routing_explain(request_context)
    override = upsert_platform_routing_override(
        platform=str(explain_before["platform"]),
        account_id=str(explain_before["account_id"]),
        routing_key=str(explain_before["routing_key"]),
        session_id=clean_required(req.session_id, "session_id"),
        operator=clean_optional_identifier(req.operator, "operator"),
        reason=clean_optional_identifier(req.reason, "reason"),
    )
    log_event(
        "platform",
        "session_routing_override_set",
        platform=str(explain_before["platform"]),
        account_id=str(explain_before["account_id"]),
        user_id=str(explain_before["user_id"]),
        chat_type=str(explain_before["chat_type"]),
        group_id=explain_before["group_id"],
        routing_key=str(explain_before["routing_key"]),
        auto_session_id=str(explain_before["auto_session_id"]),
        final_session_id=override.get("session_id"),
        override_session_id=override.get("session_id"),
        operator=override.get("operator"),
        reason=override.get("reason"),
    )
    explain_after = build_routing_explain(request_context)
    return {
        "success": True,
        "action": "override_set",
        "override": override,
        "explain": explain_after,
        "effective_scope": "future inbound messages only",
    }


@router.post("/session-routing/clear", dependencies=[Depends(require_admin_token)])
def clear_session_routing_override(req: PlatformRoutingOverrideClearRequest):
    request_context = PlatformMessageRequest(
        platform=req.platform,
        account_id=req.account_id,
        user_id=req.user_id,
        chat_type=req.chat_type,
        group_id=req.group_id,
    )
    explain_before = build_routing_explain(request_context)
    cleared = clear_platform_routing_override(
        platform=str(explain_before["platform"]),
        account_id=str(explain_before["account_id"]),
        routing_key=str(explain_before["routing_key"]),
        operator=clean_optional_identifier(req.operator, "operator"),
        reason=clean_optional_identifier(req.reason, "reason"),
    )
    log_event(
        "platform",
        "session_routing_override_cleared",
        platform=str(explain_before["platform"]),
        account_id=str(explain_before["account_id"]),
        user_id=str(explain_before["user_id"]),
        chat_type=str(explain_before["chat_type"]),
        group_id=explain_before["group_id"],
        routing_key=str(explain_before["routing_key"]),
        auto_session_id=str(explain_before["auto_session_id"]),
        final_session_id=str(explain_before["auto_session_id"]),
        override_session_id=(cleared or {}).get("session_id"),
        operator=(cleared or {}).get("operator"),
        reason=(cleared or {}).get("reason"),
    )
    explain_after = build_routing_explain(request_context)
    return {
        "success": True,
        "action": "override_cleared",
        "cleared": cleared is not None,
        "override": cleared,
        "explain": explain_after,
        "effective_scope": "future inbound messages only",
    }


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

    route = resolve_platform_session_route(req, trace_id=trace_id)
    session_id = str(route["final_session_id"])
    platform = str(route["platform"])
    account_id = str(route["account_id"])
    user_id = str(route["user_id"])
    chat_type = str(route["chat_type"])
    raw_message = clean_message_value(req.message)
    attachments = req.attachments or []
    has_image_attachment = any(item.kind == "image" for item in attachments)
    has_voice_attachment = any(item.kind == "voice" for item in attachments)
    message_type = (req.message_type or "").strip().lower() or None

    if raw_message is None and not attachments:
        raise HTTPException(status_code=400, detail="message must not be blank")

    submit_ticket = (
        session_submit_controller.allocate_ticket(session_id=session_id, trace_id=trace_id)
        if should_use_session_submit_controller(platform=platform)
        else None
    )
    input_record = {
        "source": f"platform:{platform}",
        "platform": platform,
        "account_id": account_id,
        "user_id": user_id,
        "chat_type": chat_type,
        "group_id": route["group_id"],
        "message_type": "voice" if has_voice_attachment and not has_image_attachment else "image" if has_image_attachment else "text",
        "raw_input": raw_message,
        "normalized_input": raw_message,
        "attachments": [item.model_dump() for item in attachments],
        "pipeline": {
            "vision": {"hit": has_image_attachment, "success": None},
            "asr": {"hit": has_voice_attachment and not has_image_attachment, "success": None},
            "normalization": {"status": "pending" if has_image_attachment else "bypassed", "failed_at": None},
        },
        "ingress": {
            "controller_mode": "session_serial_submit" if submit_ticket is not None else "direct",
            "arrival_seq": submit_ticket.arrival_seq if submit_ticket is not None else None,
            "received_at": _now_iso(),
        },
        "routing": {
            "routing_key": route["routing_key"],
            "routing_mode": route["routing_mode"],
            "routing_reason": route["routing_reason"],
            "auto_session_id": route["auto_session_id"],
            "final_session_id": route["final_session_id"],
            "override_session_id": route["override_session_id"],
            "override_operator": route["override_operator"],
            "override_updated_at": route["override_updated_at"],
        },
        "platform_message_type": message_type,
    }
    if submit_ticket is not None:
        snapshot = session_submit_controller.mark_state(
            ticket=submit_ticket,
            submit_state="preprocessing",
            phase="preprocess",
            message_type=str(input_record.get("message_type") or "text"),
        )
        _write_submit_debug(input_record, snapshot=snapshot)

    log_event(
        "platform",
        "message_received",
        trace_id=trace_id,
        platform=platform,
        account_id=account_id,
        chat_type=chat_type,
        user_id=user_id,
        session_id=session_id,
        auto_session_id=route["auto_session_id"],
        routing_mode=route["routing_mode"],
        routing_key=route["routing_key"],
        message_len=len(raw_message or ""),
        message_type=message_type,
        attachment_count=len(attachments),
        has_image_attachment=has_image_attachment,
        has_voice_attachment=has_voice_attachment,
    )
    try:
        preprocessed = preprocess_platform_message(
            trace_id=trace_id,
            session_id=session_id,
            platform=platform,
            user_id=user_id,
            chat_type=chat_type,
            raw_message=raw_message,
            attachments=attachments,
            input_record=input_record,
            submit_ticket=submit_ticket,
        )
    except HTTPException as exc:
        if submit_ticket is not None:
            snapshot = session_submit_controller.mark_state(
                ticket=submit_ticket,
                submit_state="failed",
                phase="preprocess",
                message_type=str(input_record.get("message_type") or "text"),
                error_type=type(exc).__name__,
                error_message=str(exc.detail),
                failed_phase="preprocess",
            )
            _write_submit_debug(input_record, snapshot=snapshot)
        submit_platform_exception(submit_ticket=submit_ticket, exc=exc)
        raise

    if isinstance(preprocessed, PlatformMessageResponse):
        return submit_platform_response(
            submit_ticket=submit_ticket,
            response=preprocessed,
        )

    message = preprocessed

    if platform in {"qq", "wx"} and chat_type == "private":
        try:
            record_platform_proactive_target(
                platform=platform,
                session_id=session_id,
                user_id=user_id,
                real_user_id=clean_optional_identifier(req.real_user_id, "real_user_id"),
            )
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

    if config.BURST_MERGE_ENABLED and chat_type == "private" and platform != "wx":
        submit_result = burst_merge_service.submit_burst_message(
            session_id=session_id,
            message=message,
            trace_id=trace_id,
            handler=lambda merged_session_id, merged_message: submit_platform_chat_turn(
                trace_id=trace_id,
                session_id=merged_session_id,
                platform=platform,
                user_id=user_id,
                chat_type=chat_type,
                message=merged_message,
                input_record=input_record,
                submit_ticket=submit_ticket,
            ),
        )
        if submit_result.accepted and submit_result.future is not None:
            response = submit_result.future.wait()
            if isinstance(response, PlatformMessageResponse):
                return response
            raise HTTPException(status_code=500, detail="chat failed")

    return submit_platform_chat_turn(
        trace_id=trace_id,
        session_id=session_id,
        platform=platform,
        user_id=user_id,
        chat_type=chat_type,
        message=message,
        input_record=input_record,
        submit_ticket=submit_ticket,
    )
