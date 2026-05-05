import json
import random
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from app.config import (
    NENO_BRIDGE_SEND_QQ_URL,
    NENO_BRIDGE_SEND_WX_URL,
    PROACTIVE_ACTIVE_END,
    PROACTIVE_ACTIVE_END_TIME,
    PROACTIVE_ACTIVE_START,
    PROACTIVE_ACTIVE_START_TIME,
    PROACTIVE_DAILY_LIMIT,
    PROACTIVE_QQ_ALLOWED_TARGET_HASHES,
    PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
)
from app.storage.db import (
    add_message,
    add_proactive_event,
    add_proactive_candidate,
    fetch_one,
    get_proactive_candidate,
    get_latest_allowed_proactive_target,
    get_latest_proactive_target,
    get_proactive_target_by_session,
    list_proactive_events,
    list_proactive_candidates,
    list_proactive_targets,
    update_proactive_candidate_metadata,
    update_proactive_candidate_status,
    upsert_proactive_target,
)
from app.utils.logging_utils import log_event

SUPPORTED_PLATFORMS = {"qq", "wx"}
SEND_QQ_TIMEOUT_SECONDS = 10
SEND_QQ_REAL_TIMEOUT_SECONDS = 15
SEND_QQ_DRY_RUN_MAX_MESSAGE_LENGTH = 500
SEND_WX_TIMEOUT_SECONDS = 10
SEND_WX_REAL_TIMEOUT_SECONDS = 15

SAFE_TEMPLATES = [
    "你是不是又在折腾服务器。",
    "喝点水。",
    "别一坐就是几个小时。",
    "今天还顺利吗。",
    "休息一下眼睛。",
    "你那边现在忙不忙。",
]


def _mask_hash(value: str) -> str:
    text = (value or "").strip()
    if len(text) <= 8:
        return text
    return f"{text[:4]}...{text[-4:]}"


def _mask_identifier(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "***"
    if len(text) <= 8:
        return f"{text[:2]}...{text[-2:]}"
    return f"{text[:4]}...{text[-4:]}"


def _within_allowed_time(now: datetime) -> bool:
    current = now.time()
    if PROACTIVE_ACTIVE_START_TIME <= PROACTIVE_ACTIVE_END_TIME:
        return PROACTIVE_ACTIVE_START_TIME <= current <= PROACTIVE_ACTIVE_END_TIME
    return current >= PROACTIVE_ACTIVE_START_TIME or current <= PROACTIVE_ACTIVE_END_TIME


def _count_today_candidates() -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS count
        FROM proactive_candidates
        WHERE date(created_at, 'localtime') = date('now', 'localtime')
          AND status = 'pending'
        """
    )
    return int(row["count"] or 0) if row else 0


def _has_recent_user_message() -> bool:
    row = fetch_one(
        f"""
        SELECT 1 AS found
        FROM chat_stats
        WHERE created_at >= datetime('now', '-{PROACTIVE_RECENT_CHAT_SKIP_MINUTES} minutes')
        LIMIT 1
        """
    )
    return row is not None


def _has_pending_qq_candidate() -> bool:
    row = fetch_one(
        """
        SELECT 1 AS found
        FROM proactive_candidates
        WHERE platform = 'qq'
          AND status = 'pending'
        LIMIT 1
        """
    )
    return row is not None


def _latest_platform_target(platform: str, *, require_24h: bool = False) -> dict[str, Any] | None:
    where_recent = "AND created_at >= datetime('now', '-24 hours')" if require_24h else ""
    return fetch_one(
        f"""
        SELECT session_id, session_id_hash, created_at
        FROM chat_stats
        WHERE platform = ?
          AND session_id IS NOT NULL
          AND session_id != ''
          AND session_id_hash IS NOT NULL
          AND session_id_hash != ''
          {where_recent}
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (platform,),
    )


def _select_platform(requested_platform: str | None) -> tuple[str | None, dict[str, Any] | None, str | None]:
    platform = (requested_platform or "").strip().lower() or None
    if platform is not None and platform not in SUPPORTED_PLATFORMS:
        return None, None, "platform must be qq or wx"

    if platform in (None, "qq"):
        row = get_latest_allowed_proactive_target("qq")
        if row:
            return "qq", row, None
        if platform == "qq":
            return (
                None,
                None,
                "没有可用 QQ 主动目标，请先给机器人发一条 QQ 消息，并在主动目标中允许该目标。",
            )

    if platform == "wx":
        row = get_latest_proactive_target("wx")
        if row:
            return "wx", row, None
        return (
            None,
            None,
            "没有可用 WX 主动目标，请先给机器人发一条微信私聊消息。",
        )

    return (
        None,
        None,
        "没有可用 QQ 主动目标，请先给机器人发一条 QQ 消息，并在主动目标中允许该目标。",
    )


def _stored_allowed_qq_target_exists(target_hash: str) -> bool:
    row = fetch_one(
        """
        SELECT 1 AS found
        FROM proactive_targets
        WHERE platform = 'qq'
          AND target_hash = ?
          AND is_allowed = 1
        LIMIT 1
        """,
        (target_hash,),
    )
    return row is not None

def is_allowed_qq_target(target_hash: str | None) -> bool:
    if not target_hash:
        return False
    target = target_hash.strip()
    return target in PROACTIVE_QQ_ALLOWED_TARGET_HASHES or _stored_allowed_qq_target_exists(target)


def get_recent_proactive_candidates(limit: int = 20) -> list[dict]:
    return [sanitize_proactive_candidate(candidate) for candidate in list_proactive_candidates(limit=limit)]


def sanitize_proactive_target(target: dict | None) -> dict | None:
    if target is None:
        return None
    sanitized = dict(target)
    sanitized.pop("session_id", None)
    real_user_id = str(target.get("real_user_id") or "").strip()
    sanitized.pop("real_user_id", None)
    sanitized["session_id_saved"] = bool(target.get("session_id"))
    sanitized["real_user_id_saved"] = bool(real_user_id)
    if real_user_id:
        sanitized["real_user_label"] = _mask_identifier(real_user_id)
    sanitized["target_hash"] = _mask_hash(str(target.get("target_hash") or ""))
    sanitized["is_allowed"] = bool(target.get("is_allowed"))
    return sanitized


def get_recent_proactive_targets(limit: int = 20) -> list[dict]:
    return [sanitize_proactive_target(target) for target in list_proactive_targets(limit=limit)]


SENSITIVE_EVENT_KEY_PARTS = ("session", "openid", "open_id", "token", "secret")


def _safe_event_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe_event_metadata_value(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in SENSITIVE_EVENT_KEY_PARTS)
        }
    if isinstance(value, list):
        return [_safe_event_metadata_value(item) for item in value[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = str(value) if isinstance(value, str) else ""
        if "qq:private:" in text or "wx:private:" in text:
            return "[redacted]"
        return value
    return str(value)


def _safe_event_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    return _safe_event_metadata_value(metadata)


def record_proactive_event(
    *,
    event_type: str,
    platform: str | None = None,
    target_label: str | None = None,
    candidate_id: int | None = None,
    action: str | None = None,
    success: bool | None = None,
    skipped: bool | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        add_proactive_event(
            event_type=event_type,
            platform=platform,
            target_label=target_label,
            candidate_id=candidate_id,
            action=action,
            success=success,
            skipped=skipped,
            reason=(reason or "")[:240] or None,
            metadata_json=_dump_candidate_metadata(_safe_event_metadata(metadata)),
        )
    except Exception as exc:
        log_event(
            "proactive",
            "proactive_event_write_warning",
            error_type=type(exc).__name__,
            reason="proactive event write failed",
        )


def sanitize_proactive_event(event: dict | None) -> dict | None:
    if event is None:
        return None
    sanitized = dict(event)
    sanitized["success"] = None if event.get("success") is None else bool(event.get("success"))
    sanitized["skipped"] = None if event.get("skipped") is None else bool(event.get("skipped"))
    raw_metadata = event.get("metadata_json") or "{}"
    try:
        metadata = json.loads(raw_metadata)
    except Exception:
        metadata = {}
    sanitized["metadata_json"] = _dump_candidate_metadata(_safe_event_metadata(metadata if isinstance(metadata, dict) else {}))
    return sanitized


def get_recent_proactive_events(limit: int = 50, event_type: str | None = None) -> list[dict]:
    return [
        sanitize_proactive_event(event)
        for event in list_proactive_events(limit=limit, event_type=event_type)
    ]


def _load_candidate_metadata(candidate: dict) -> dict[str, Any]:
    raw = candidate.get("metadata_json") or "{}"
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dump_candidate_metadata(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=False)


def _get_target_session_id(target_row: dict[str, Any]) -> str:
    return str(target_row["session_id"] or "").strip()


def _get_target_hash(target_row: dict[str, Any]) -> str:
    return str(target_row.get("target_hash") or target_row.get("session_id_hash") or "").strip()


def _get_target_label(target_row: dict[str, Any]) -> str:
    return str(target_row.get("target_label") or _mask_hash(_get_target_hash(target_row))).strip()


def _get_target_real_user_id(target_row: dict[str, Any]) -> str:
    return str(target_row.get("real_user_id") or "").strip()


def _get_target_last_seen_at(target_row: dict[str, Any]) -> str | None:
    value = target_row.get("last_seen_at") or target_row.get("created_at")
    return str(value) if value else None


def _log_proactive(event: str, trace_id: str | None = None, **fields: Any) -> None:
    log_event("proactive", event, trace_id=trace_id, **fields)


def sanitize_proactive_candidate(candidate: dict | None) -> dict | None:
    if candidate is None:
        return None

    sanitized = dict(candidate)
    if sanitized.get("target_hash"):
        sanitized["target_hash"] = _mask_hash(str(sanitized.get("target_hash") or ""))
    if not sanitized.get("target_label"):
        sanitized["target_label"] = sanitized.get("target_hash") or ""

    metadata = _load_candidate_metadata(candidate)
    if metadata.pop("session_id", None):
        metadata["session_id_saved"] = True
    real_user_id = str(metadata.pop("wx_real_user_id", "") or "").strip()
    if real_user_id:
        metadata["wx_real_user_id_saved"] = True
        metadata["wx_real_user_label"] = _mask_identifier(real_user_id)
    permission_user_id = str(metadata.pop("wx_permission_user_id", "") or "").strip()
    if permission_user_id:
        metadata["wx_permission_user_id_saved"] = True
        metadata["wx_permission_user_label"] = _mask_identifier(permission_user_id)
    sanitized["metadata_json"] = _dump_candidate_metadata(metadata)
    return sanitized


def record_platform_proactive_target(
    *,
    platform: str,
    session_id: str,
    user_id: str,
    real_user_id: str | None = None,
    seen_at: str | None = None,
) -> dict:
    normalized_platform = (platform or "").strip().lower()
    if normalized_platform not in {"qq", "wx"}:
        raise ValueError("platform must be qq or wx")

    target_hash = _target_hash_for_session(session_id)
    target_label = _mask_identifier(user_id)
    return upsert_proactive_target(
        platform=normalized_platform,
        session_id=session_id,
        target_hash=target_hash,
        target_label=target_label,
        real_user_id=(real_user_id or "").strip() or None,
        is_allowed=(
            normalized_platform == "qq"
            and target_hash in PROACTIVE_QQ_ALLOWED_TARGET_HASHES
        ),
        last_seen_at=seen_at or datetime.now().isoformat(timespec="seconds"),
    )


def record_qq_proactive_target(*, session_id: str, user_id: str, seen_at: str | None = None) -> dict:
    return record_platform_proactive_target(
        platform="qq",
        session_id=session_id,
        user_id=user_id,
        seen_at=seen_at,
    )


def _target_hash_for_session(session_id: str) -> str:
    import hashlib

    text = (session_id or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _post_neno_bridge_send_qq(candidate_id: int, message: str, dry_run: bool) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "message": message,
        "dry_run": dry_run,
    }
    request = urllib.request.Request(
        NENO_BRIDGE_SEND_QQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        timeout = SEND_QQ_TIMEOUT_SECONDS if dry_run else SEND_QQ_REAL_TIMEOUT_SECONDS
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        detail = data.get("error") if isinstance(data, dict) else None
        raise HTTPException(status_code=502, detail=detail or "neno-bridge send failed") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="neno-bridge send unavailable") from exc

    if not isinstance(data, dict) or data.get("success") is not True:
        raise HTTPException(status_code=502, detail="neno-bridge send returned invalid response")
    if dry_run and data.get("dry_run") is not True:
        raise HTTPException(status_code=502, detail="neno-bridge dry_run returned invalid response")
    if not dry_run and data.get("sent") is not True:
        raise HTTPException(status_code=502, detail="neno-bridge send returned invalid response")
    return data


def _post_neno_bridge_send_wx(
    candidate_id: int,
    message: str,
    dry_run: bool,
    *,
    target: dict[str, str] | None = None,
) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "message": message,
        "dry_run": dry_run,
    }
    if target:
        payload["target_session_id"] = target.get("session_id")
        payload["target_user_id"] = target.get("user_id")
        payload["target_permission_user_id"] = target.get("permission_user_id")
        payload["target_hash"] = target.get("target_hash")
        payload["target_label"] = target.get("target_label")
    request = urllib.request.Request(
        NENO_BRIDGE_SEND_WX_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        timeout = SEND_WX_TIMEOUT_SECONDS if dry_run else SEND_WX_REAL_TIMEOUT_SECONDS
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        detail = data.get("error") if isinstance(data, dict) else None
        raise HTTPException(status_code=502, detail=detail or "neno-bridge wx send failed") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="neno-bridge wx send unavailable") from exc

    if not isinstance(data, dict) or data.get("success") is not True:
        raise HTTPException(status_code=502, detail="neno-bridge wx send returned invalid response")
    if dry_run and data.get("dry_run") is not True:
        raise HTTPException(status_code=502, detail="neno-bridge wx dry_run returned invalid response")
    if not dry_run and data.get("sent") is not True:
        raise HTTPException(status_code=502, detail="neno-bridge wx send returned invalid response")
    return data


def _get_sendable_qq_candidate(candidate_id: int) -> dict:
    candidate = get_proactive_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="proactive candidate not found")
    if candidate.get("platform") != "qq":
        raise HTTPException(status_code=400, detail="only qq candidates can be sent")
    if candidate.get("status") != "pending":
        raise HTTPException(status_code=400, detail="only pending candidates can be sent")
    return candidate


def _get_sendable_candidate(candidate_id: int) -> dict:
    candidate = get_proactive_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="proactive candidate not found")
    if candidate.get("status") != "pending":
        raise HTTPException(status_code=400, detail="only pending candidates can be sent")
    return candidate


def _get_candidate_message(candidate: dict) -> str:
    message = str(candidate.get("message") or "").strip()

    if not message:
        raise HTTPException(status_code=400, detail="candidate message is empty")
    if len(message) > SEND_QQ_DRY_RUN_MAX_MESSAGE_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"candidate message must be {SEND_QQ_DRY_RUN_MAX_MESSAGE_LENGTH} characters or fewer",
        )
    return message


def _extract_private_session_user_id(session_id: str, platform: str) -> str:
    normalized_platform = (platform or "").strip().lower()
    prefix = f"{normalized_platform}:private:"
    cleaned = (session_id or "").strip()
    if not cleaned.startswith(prefix):
        raise HTTPException(status_code=400, detail=f"{normalized_platform} candidate session_id is not a private session")
    user_id = cleaned[len(prefix):].strip()
    if not user_id:
        raise HTTPException(status_code=400, detail=f"{normalized_platform} candidate session_id missing user id")
    return user_id


def _resolve_wx_candidate_target(candidate: dict) -> dict[str, str]:
    metadata = _load_candidate_metadata(candidate)
    session_id = str(metadata.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="wx candidate missing session_id")

    permission_user_id = _extract_private_session_user_id(session_id, "wx")
    expected_target_hash = _target_hash_for_session(session_id)
    candidate_target_hash = str(candidate.get("target_hash") or "").strip()
    if not candidate_target_hash:
        raise HTTPException(status_code=400, detail="wx candidate missing target_hash")
    if candidate_target_hash != expected_target_hash:
        raise HTTPException(status_code=409, detail="wx candidate target does not match session_id")

    target_row = get_proactive_target_by_session("wx", session_id)
    real_user_id = str(metadata.get("wx_real_user_id") or "").strip()
    if target_row is not None:
        stored_target_hash = _get_target_hash(target_row)
        if stored_target_hash and stored_target_hash != expected_target_hash:
            raise HTTPException(status_code=409, detail="wx proactive target does not match candidate session_id")
        if not real_user_id:
            real_user_id = _get_target_real_user_id(target_row)

    if not real_user_id:
        raise HTTPException(status_code=400, detail="wx candidate missing real_user_id")

    target_label = str(candidate.get("target_label") or "").strip() or _mask_identifier(permission_user_id)
    return {
        "session_id": session_id,
        "user_id": real_user_id,
        "permission_user_id": permission_user_id,
        "target_hash": expected_target_hash,
        "target_label": target_label,
    }


def _ensure_allowed_qq_target(candidate: dict) -> None:
    if is_allowed_qq_target(str(candidate.get("target_hash") or "")):
        return
    raise HTTPException(status_code=403, detail="qq target is not whitelisted")


def _record_failed_send(candidate: dict, error: str) -> dict | None:
    metadata = _load_candidate_metadata(candidate)
    metadata["failed_at"] = datetime.now().isoformat(timespec="seconds")
    metadata["error"] = (error or "send failed")[:120]
    update_proactive_candidate_metadata(
        candidate["id"],
        _dump_candidate_metadata(metadata),
    )
    return update_proactive_candidate_status(candidate["id"], "failed")


def _save_proactive_context(
    candidate: dict,
    message: str,
    metadata: dict[str, Any],
    trace_id: str | None = None,
) -> None:
    session_id = str(metadata.get("session_id") or "").strip()
    if not session_id:
        metadata["context_save_warning"] = "missing session_id"
        _log_proactive(
            "proactive_context_save_warning",
            trace_id=trace_id,
            candidate_id=candidate.get("id"),
            target_label=candidate.get("target_label"),
            reason="missing session_id",
            success=False,
        )
        return

    try:
        add_message(session_id, "assistant", message)
    except Exception as exc:
        metadata["context_save_warning"] = f"add_message failed: {type(exc).__name__}"
        _log_proactive(
            "proactive_context_save_warning",
            trace_id=trace_id,
            candidate_id=candidate.get("id"),
            target_label=candidate.get("target_label"),
            reason=f"add_message failed: {type(exc).__name__}",
            success=False,
        )
        return

    metadata["proactive_context_saved"] = True
    metadata["proactive_context_saved_at"] = datetime.now().isoformat(timespec="seconds")
    _log_proactive(
        "proactive_context_saved",
        trace_id=trace_id,
        candidate_id=candidate.get("id"),
        target_label=candidate.get("target_label"),
        success=True,
        message_len=len(message or ""),
    )


def _send_qq_candidate(
    candidate_id: int,
    dry_run: bool,
    *,
    event_source: str = "manual",
    trace_id: str | None = None,
) -> dict:
    if not isinstance(dry_run, bool):
        raise HTTPException(status_code=400, detail="dry_run must be a boolean")

    candidate = _get_sendable_qq_candidate(candidate_id)
    message = _get_candidate_message(candidate)

    if dry_run:
        try:
            result = _post_neno_bridge_send_qq(candidate_id, message, dry_run=True)
        except Exception as exc:
            _log_proactive(
                "proactive_dry_run_failed",
                trace_id=trace_id,
                candidate_id=candidate_id,
                target_label=candidate.get("target_label"),
                action=f"{event_source}_dry_run",
                dry_run=True,
                success=False,
                reason=getattr(exc, "detail", None) or type(exc).__name__,
            )
            if event_source == "manual":
                record_proactive_event(
                    event_type="manual_failed",
                    platform="qq",
                    target_label=str(candidate.get("target_label") or ""),
                    candidate_id=candidate_id,
                    action="manual_send_dry_run",
                    success=False,
                    skipped=False,
                    reason=getattr(exc, "detail", None) or type(exc).__name__,
                )
            raise
        metadata = _load_candidate_metadata(candidate)
        metadata["dry_run_at"] = datetime.now().isoformat(timespec="seconds")
        metadata["dry_run_result"] = {
            "success": True,
            "dry_run": True,
            "target_label": result.get("target_label"),
            "message_len": result.get("message_len"),
            "would_send": result.get("would_send") is True,
        }
        updated_candidate = update_proactive_candidate_metadata(
            candidate_id,
            _dump_candidate_metadata(metadata),
        )

        response = {
            "success": True,
            "dry_run": True,
            "target_label": result.get("target_label"),
            "message_len": result.get("message_len"),
            "would_send": result.get("would_send") is True,
            "candidate": sanitize_proactive_candidate(updated_candidate or candidate),
        }
        if event_source == "manual":
            record_proactive_event(
                event_type="manual_send_dry_run",
                platform="qq",
                target_label=result.get("target_label") or str(candidate.get("target_label") or ""),
                candidate_id=candidate_id,
                action="manual_send_dry_run",
                success=True,
                skipped=False,
                metadata={"message_len": result.get("message_len"), "would_send": result.get("would_send") is True},
            )
        _log_proactive(
            "proactive_dry_run_ok",
            trace_id=trace_id,
            candidate_id=candidate_id,
            target_label=result.get("target_label") or candidate.get("target_label"),
            action=f"{event_source}_dry_run",
            dry_run=True,
            success=True,
        )
        return response

    try:
        _ensure_allowed_qq_target(candidate)
    except HTTPException as exc:
        if event_source == "manual":
            _log_proactive(
                "proactive_manual_failed",
                trace_id=trace_id,
                candidate_id=candidate_id,
                target_label=candidate.get("target_label"),
                action="manual_sent",
                dry_run=False,
                success=False,
                reason=str(exc.detail),
            )
        if event_source == "manual":
            record_proactive_event(
                event_type="manual_failed",
                platform="qq",
                target_label=str(candidate.get("target_label") or ""),
                candidate_id=candidate_id,
                action="manual_sent",
                success=False,
                skipped=False,
                reason=str(exc.detail),
            )
        raise

    try:
        result = _post_neno_bridge_send_qq(candidate_id, message, dry_run=False)
    except HTTPException as exc:
        _record_failed_send(candidate, str(exc.detail))
        if event_source == "manual":
            _log_proactive(
                "proactive_manual_failed",
                trace_id=trace_id,
                candidate_id=candidate_id,
                target_label=candidate.get("target_label"),
                action="manual_sent",
                dry_run=False,
                success=False,
                reason=str(exc.detail),
            )
        if event_source == "manual":
            record_proactive_event(
                event_type="manual_failed",
                platform="qq",
                target_label=str(candidate.get("target_label") or ""),
                candidate_id=candidate_id,
                action="manual_sent",
                success=False,
                skipped=False,
                reason=str(exc.detail),
            )
        raise HTTPException(status_code=502, detail="QQ send failed") from exc

    metadata = _load_candidate_metadata(candidate)
    metadata["sent_at"] = datetime.now().isoformat(timespec="seconds")
    metadata["target_label"] = result.get("target_label")
    metadata["send_result"] = {
        "success": True,
        "dry_run": False,
        "sent": True,
        "target_label": result.get("target_label"),
        "message_len": result.get("message_len"),
    }
    _save_proactive_context(candidate, message, metadata, trace_id=trace_id)
    updated_candidate = update_proactive_candidate_metadata(
        candidate_id,
        _dump_candidate_metadata(metadata),
    )

    updated_candidate = update_proactive_candidate_status(candidate_id, "sent") or updated_candidate

    response = {
        "success": True,
        "dry_run": False,
        "sent": True,
        "target_label": result.get("target_label"),
        "message_len": result.get("message_len"),
        "candidate": sanitize_proactive_candidate(updated_candidate or candidate),
    }
    if event_source == "manual":
        record_proactive_event(
            event_type="manual_sent",
            platform="qq",
            target_label=result.get("target_label") or str(candidate.get("target_label") or ""),
            candidate_id=candidate_id,
            action="manual_sent",
            success=True,
            skipped=False,
            metadata={"message_len": result.get("message_len")},
        )
        _log_proactive(
            "proactive_manual_sent",
            trace_id=trace_id,
            candidate_id=candidate_id,
            target_label=result.get("target_label") or candidate.get("target_label"),
            action="manual_sent",
            dry_run=False,
            success=True,
        )
    return response


def _send_wx_candidate_dry_run(
    candidate: dict,
    message: str,
    *,
    event_source: str = "manual",
    trace_id: str | None = None,
) -> dict:
    candidate_id = int(candidate["id"])
    resolved_target = _resolve_wx_candidate_target(candidate)
    target_label = str(resolved_target.get("target_label") or candidate.get("target_label") or "")
    message_len = len(message or "")

    metadata = _load_candidate_metadata(candidate)
    metadata["dry_run_at"] = datetime.now().isoformat(timespec="seconds")
    metadata["dry_run_result"] = {
        "success": True,
        "dry_run": True,
        "platform": "wx",
        "target_label": target_label,
        "target_hash": resolved_target.get("target_hash"),
        "target_source": "candidate_session_id",
        "resolved_target_label": _mask_identifier(resolved_target.get("user_id") or ""),
        "resolved_permission_target_label": _mask_identifier(resolved_target.get("permission_user_id") or ""),
        "message_len": message_len,
        "would_send": True,
        "real_send_supported": True,
    }
    metadata["wx_real_user_id"] = resolved_target.get("user_id")
    metadata["wx_permission_user_id"] = resolved_target.get("permission_user_id")
    updated_candidate = update_proactive_candidate_metadata(
        candidate_id,
        _dump_candidate_metadata(metadata),
    )

    response = {
        "success": True,
        "dry_run": True,
        "platform": "wx",
        "target_label": target_label,
        "message_len": message_len,
        "would_send": True,
        "candidate": sanitize_proactive_candidate(updated_candidate or candidate),
    }
    if event_source == "manual":
        record_proactive_event(
            event_type="manual_send_dry_run",
            platform="wx",
            target_label=target_label,
            candidate_id=candidate_id,
            action="manual_send_dry_run",
            success=True,
            skipped=False,
            metadata={
                "message_len": message_len,
                "would_send": True,
                "real_send_supported": True,
                "target_source": "candidate_session_id",
                "target_hash": resolved_target.get("target_hash"),
            },
        )
    _log_proactive(
        "proactive_dry_run_ok",
        trace_id=trace_id,
        platform="wx",
        candidate_id=candidate_id,
        target_label=target_label,
        action=f"{event_source}_dry_run",
        dry_run=True,
        success=True,
    )
    return response


def _send_wx_candidate(
    candidate_id: int,
    dry_run: bool,
    *,
    event_source: str = "manual",
    trace_id: str | None = None,
) -> dict:
    candidate = _get_sendable_candidate(candidate_id)
    if candidate.get("platform") != "wx":
        raise HTTPException(status_code=400, detail="only wx candidates can be sent by wx sender")
    message = _get_candidate_message(candidate)

    if dry_run:
        return _send_wx_candidate_dry_run(
            candidate,
            message,
            event_source=event_source,
            trace_id=trace_id,
        )

    try:
        resolved_target = _resolve_wx_candidate_target(candidate)
    except HTTPException as exc:
        _record_failed_send(candidate, str(exc.detail))
        if event_source == "manual":
            _log_proactive(
                "proactive_manual_failed",
                trace_id=trace_id,
                platform="wx",
                candidate_id=candidate_id,
                target_label=candidate.get("target_label"),
                action="manual_sent",
                dry_run=False,
                success=False,
                reason=str(exc.detail),
            )
            record_proactive_event(
                event_type="manual_failed",
                platform="wx",
                target_label=str(candidate.get("target_label") or ""),
                candidate_id=candidate_id,
                action="manual_sent",
                success=False,
                skipped=False,
                reason=str(exc.detail),
            )
        raise
    try:
        result = _post_neno_bridge_send_wx(
            candidate_id,
            message,
            dry_run=False,
            target=resolved_target,
        )
    except HTTPException as exc:
        _record_failed_send(candidate, str(exc.detail))
        if event_source == "manual":
            _log_proactive(
                "proactive_manual_failed",
                trace_id=trace_id,
                platform="wx",
                candidate_id=candidate_id,
                target_label=candidate.get("target_label"),
                action="manual_sent",
                dry_run=False,
                success=False,
                reason=str(exc.detail),
            )
            record_proactive_event(
                event_type="manual_failed",
                platform="wx",
                target_label=str(candidate.get("target_label") or ""),
                candidate_id=candidate_id,
                action="manual_sent",
                success=False,
                skipped=False,
                reason=str(exc.detail),
                metadata={
                    "target_source": "candidate_session_id",
                    "target_hash": resolved_target.get("target_hash"),
                },
            )
        raise HTTPException(status_code=502, detail="WX send failed") from exc

    metadata = _load_candidate_metadata(candidate)
    metadata["sent_at"] = datetime.now().isoformat(timespec="seconds")
    metadata["target_label"] = result.get("target_label")
    metadata["resolved_target_label"] = _mask_identifier(resolved_target.get("user_id") or "")
    metadata["resolved_permission_target_label"] = _mask_identifier(resolved_target.get("permission_user_id") or "")
    metadata["resolved_target_hash"] = resolved_target.get("target_hash")
    metadata["wx_real_user_id"] = resolved_target.get("user_id")
    metadata["wx_permission_user_id"] = resolved_target.get("permission_user_id")
    metadata["send_result"] = {
        "success": True,
        "dry_run": False,
        "sent": True,
        "platform": "wx",
        "target_label": result.get("target_label"),
        "target_hash": resolved_target.get("target_hash"),
        "target_source": "candidate_session_id",
        "resolved_target_label": _mask_identifier(resolved_target.get("user_id") or ""),
        "resolved_permission_target_label": _mask_identifier(resolved_target.get("permission_user_id") or ""),
        "message_len": result.get("message_len"),
    }
    _save_proactive_context(candidate, message, metadata, trace_id=trace_id)
    updated_candidate = update_proactive_candidate_metadata(
        candidate_id,
        _dump_candidate_metadata(metadata),
    )

    updated_candidate = update_proactive_candidate_status(candidate_id, "sent") or updated_candidate

    response = {
        "success": True,
        "dry_run": False,
        "sent": True,
        "platform": "wx",
        "target_label": result.get("target_label"),
        "message_len": result.get("message_len"),
        "candidate": sanitize_proactive_candidate(updated_candidate or candidate),
    }
    if event_source == "manual":
        record_proactive_event(
            event_type="manual_sent",
            platform="wx",
            target_label=result.get("target_label") or str(candidate.get("target_label") or ""),
            candidate_id=candidate_id,
            action="manual_sent",
            success=True,
            skipped=False,
            metadata={
                "message_len": result.get("message_len"),
                "target_source": "candidate_session_id",
                "target_hash": resolved_target.get("target_hash"),
                "candidate_target_label": str(candidate.get("target_label") or ""),
                "bridge_target_label": result.get("target_label"),
                "resolved_target_label": _mask_identifier(resolved_target.get("user_id") or ""),
                "resolved_permission_target_label": _mask_identifier(resolved_target.get("permission_user_id") or ""),
            },
        )
        _log_proactive(
            "proactive_manual_sent",
            trace_id=trace_id,
            platform="wx",
            candidate_id=candidate_id,
            target_label=result.get("target_label") or candidate.get("target_label"),
            action="manual_sent",
            dry_run=False,
            success=True,
        )
    return response


def send_proactive_candidate(
    candidate_id: int,
    dry_run: bool,
    *,
    event_source: str = "manual",
    trace_id: str | None = None,
) -> dict:
    if not isinstance(dry_run, bool):
        raise HTTPException(status_code=400, detail="dry_run must be a boolean")

    candidate = _get_sendable_candidate(candidate_id)
    platform = str(candidate.get("platform") or "").strip().lower()
    if platform == "qq":
        return _send_qq_candidate(
            candidate_id,
            dry_run,
            event_source=event_source,
            trace_id=trace_id,
        )
    if platform == "wx":
        return _send_wx_candidate(
            candidate_id,
            dry_run,
            event_source=event_source,
            trace_id=trace_id,
        )
    raise HTTPException(status_code=400, detail="unsupported candidate platform")


def send_qq_candidate(
    candidate_id: int,
    dry_run: bool,
    *,
    event_source: str = "manual",
    trace_id: str | None = None,
) -> dict:
    candidate = _get_sendable_candidate(candidate_id)
    if candidate.get("platform") != "qq":
        raise HTTPException(status_code=400, detail="only qq candidates can be sent")
    return send_proactive_candidate(
        candidate_id,
        dry_run,
        event_source=event_source,
        trace_id=trace_id,
    )


def generate_proactive_candidate(platform: str | None = None, trace_id: str | None = None) -> dict:
    now = datetime.now()

    if not _within_allowed_time(now):
        reason = f"outside allowed generation window: {PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}"
        _log_proactive(
            "proactive_rule_skipped",
            trace_id=trace_id,
            action="generate_candidate",
            reason=reason,
            skipped=True,
            success=True,
        )
        return {
            "success": True,
            "skipped": True,
            "reason": reason,
        }

    if _has_recent_user_message():
        reason = f"user message seen within {PROACTIVE_RECENT_CHAT_SKIP_MINUTES} minutes"
        _log_proactive(
            "proactive_rule_skipped",
            trace_id=trace_id,
            action="generate_candidate",
            reason=reason,
            skipped=True,
            success=True,
        )
        return {
            "success": True,
            "skipped": True,
            "reason": reason,
        }

    if _count_today_candidates() >= PROACTIVE_DAILY_LIMIT:
        reason = f"daily proactive candidate limit reached: {PROACTIVE_DAILY_LIMIT}"
        _log_proactive(
            "proactive_rule_skipped",
            trace_id=trace_id,
            action="generate_candidate",
            reason=reason,
            skipped=True,
            success=True,
        )
        return {
            "success": True,
            "skipped": True,
            "reason": reason,
        }

    selected_platform, target_row, skip_reason = _select_platform(platform)
    if not selected_platform or not target_row:
        reason = skip_reason or "no eligible target"
        _log_proactive(
            "proactive_rule_skipped",
            trace_id=trace_id,
            action="generate_candidate",
            reason=reason,
            skipped=True,
            success=True,
        )
        return {
            "success": True,
            "skipped": True,
            "reason": reason,
        }

    target_hash = _get_target_hash(target_row)
    session_id = _get_target_session_id(target_row)
    message = random.choice(SAFE_TEMPLATES)
    reason = "manual safe template; outbound send disabled in v1"
    metadata = {
        "session_id": session_id,
        "wx_real_user_id": _get_target_real_user_id(target_row) or None,
        "rules": {
            "no_send": True,
            "template_only": True,
            "active_window": f"{PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}",
            "recent_user_message_skip_minutes": PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
            "daily_limit": PROACTIVE_DAILY_LIMIT,
        },
        "target_last_seen_at": _get_target_last_seen_at(target_row),
    }
    candidate = add_proactive_candidate(
        platform=selected_platform,
        target_hash=target_hash,
        target_label=_get_target_label(target_row),
        message=message,
        reason=reason,
        status="pending",
        source="manual",
        metadata_json=_dump_candidate_metadata(metadata),
    )
    _log_proactive(
        "proactive_candidate_generated",
        trace_id=trace_id,
        candidate_id=candidate.get("id"),
        target_label=candidate.get("target_label"),
        action="generate_candidate",
        success=True,
        skipped=False,
    )
    return {
        "success": True,
        "skipped": False,
        "candidate": sanitize_proactive_candidate(candidate),
    }


def generate_test_proactive_candidate(*, force: bool = False, trace_id: str | None = None) -> dict:
    selected_platform, target_row, skip_reason = _select_platform("qq")
    if selected_platform != "qq" or not target_row:
        raise HTTPException(status_code=404, detail=skip_reason or "no allowed qq proactive target")

    target_hash = _get_target_hash(target_row)
    if not target_hash:
        raise HTTPException(status_code=404, detail="qq target hash not found")
    if not is_allowed_qq_target(target_hash):
        raise HTTPException(status_code=403, detail="qq target is not whitelisted")

    if _has_pending_qq_candidate() and not force:
        raise HTTPException(
            status_code=409,
            detail="已有待处理 QQ 候选，可先发送/丢弃，或使用 force=true 强制生成测试候选",
        )

    session_id = _get_target_session_id(target_row)
    if not session_id:
        raise HTTPException(status_code=404, detail="qq session_id not found")

    metadata = {
        "session_id": session_id,
        "rules": {
            "test_candidate": True,
            "template_only": True,
            "platform": "qq",
            "ignored_for_test": [
                "random_probability",
                "recent_chat",
                "active_window",
            ],
            "required_for_test": [
                "qq_target",
                "qq_whitelist",
            ],
        },
        "target_last_seen_at": _get_target_last_seen_at(target_row),
        "test_created_at": datetime.now().isoformat(timespec="seconds"),
    }
    candidate = add_proactive_candidate(
        platform="qq",
        target_hash=target_hash,
        target_label=_get_target_label(target_row),
        message=SAFE_TEMPLATES[0],
        reason="test v3.1 fixed template; no send; ignores random/recent-chat/active-window",
        status="pending",
        source="test",
        metadata_json=_dump_candidate_metadata(metadata),
    )
    record_proactive_event(
        event_type="manual_generate_test",
        platform="qq",
        target_label=_get_target_label(target_row),
        candidate_id=candidate["id"],
        action="manual_generate_test",
        success=True,
        skipped=False,
        metadata={"forced": force, "session_id_saved": True},
    )
    _log_proactive(
        "proactive_candidate_generated",
        trace_id=trace_id,
        candidate_id=candidate.get("id"),
        target_label=candidate.get("target_label"),
        action="manual_generate_test",
        success=True,
        skipped=False,
    )
    return {
        "success": True,
        "skipped": False,
        "forced": force,
        "session_id_saved": True,
        "candidate": sanitize_proactive_candidate(candidate),
    }
