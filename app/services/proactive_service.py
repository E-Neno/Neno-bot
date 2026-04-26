import json
import random
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from app.config import (
    NENO_BRIDGE_SEND_QQ_URL,
    PROACTIVE_ACTIVE_END,
    PROACTIVE_ACTIVE_END_TIME,
    PROACTIVE_ACTIVE_START,
    PROACTIVE_ACTIVE_START_TIME,
    PROACTIVE_DAILY_LIMIT,
    PROACTIVE_QQ_ALLOWED_TARGET_HASHES,
    PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
)
from app.storage.db import (
    add_proactive_candidate,
    fetch_one,
    get_proactive_candidate,
    list_proactive_candidates,
    update_proactive_candidate_metadata,
    update_proactive_candidate_status,
)

SUPPORTED_PLATFORMS = {"qq"}
SEND_QQ_TIMEOUT_SECONDS = 10
SEND_QQ_REAL_TIMEOUT_SECONDS = 15
SEND_QQ_DRY_RUN_MAX_MESSAGE_LENGTH = 500

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


def _latest_platform_target(platform: str, *, require_24h: bool = False) -> dict[str, Any] | None:
    where_recent = "AND created_at >= datetime('now', '-24 hours')" if require_24h else ""
    return fetch_one(
        f"""
        SELECT session_id_hash, created_at
        FROM chat_stats
        WHERE platform = ?
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
        return None, None, "platform must be qq"

    if platform == "qq":
        row = _latest_platform_target("qq")
        return ("qq", row, None) if row else (None, None, "no qq target found in chat_stats")

    qq_row = _latest_platform_target("qq")
    if qq_row:
        return "qq", qq_row, None

    return None, None, "no qq target found in chat_stats"

def is_allowed_qq_target(target_hash: str | None) -> bool:
    if not target_hash:
        return False
    return target_hash in PROACTIVE_QQ_ALLOWED_TARGET_HASHES


def get_recent_proactive_candidates(limit: int = 20) -> list[dict]:
    return list_proactive_candidates(limit=limit)


def _load_candidate_metadata(candidate: dict) -> dict[str, Any]:
    raw = candidate.get("metadata_json") or "{}"
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


def _get_sendable_qq_candidate(candidate_id: int) -> dict:
    candidate = get_proactive_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="proactive candidate not found")
    if candidate.get("platform") != "qq":
        raise HTTPException(status_code=400, detail="only qq candidates can be sent")
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
        json.dumps(metadata, ensure_ascii=False),
    )
    return update_proactive_candidate_status(candidate["id"], "failed")


def send_qq_candidate(candidate_id: int, dry_run: bool) -> dict:
    if not isinstance(dry_run, bool):
        raise HTTPException(status_code=400, detail="dry_run must be a boolean")

    candidate = _get_sendable_qq_candidate(candidate_id)
    message = _get_candidate_message(candidate)

    if dry_run:
        result = _post_neno_bridge_send_qq(candidate_id, message, dry_run=True)
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
            json.dumps(metadata, ensure_ascii=False),
        )

        return {
            "success": True,
            "dry_run": True,
            "target_label": result.get("target_label"),
            "message_len": result.get("message_len"),
            "would_send": result.get("would_send") is True,
            "candidate": updated_candidate or candidate,
        }

    _ensure_allowed_qq_target(candidate)

    try:
        result = _post_neno_bridge_send_qq(candidate_id, message, dry_run=False)
    except HTTPException as exc:
        _record_failed_send(candidate, str(exc.detail))
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
    updated_candidate = update_proactive_candidate_metadata(
        candidate_id,
        json.dumps(metadata, ensure_ascii=False),
    )

    updated_candidate = update_proactive_candidate_status(candidate_id, "sent") or updated_candidate

    return {
        "success": True,
        "dry_run": False,
        "sent": True,
        "target_label": result.get("target_label"),
        "message_len": result.get("message_len"),
        "candidate": updated_candidate or candidate,
    }


def generate_proactive_candidate(platform: str | None = None) -> dict:
    now = datetime.now()

    if not _within_allowed_time(now):
        return {
            "success": True,
            "skipped": True,
            "reason": f"outside allowed generation window: {PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}",
        }

    if _has_recent_user_message():
        return {
            "success": True,
            "skipped": True,
            "reason": f"user message seen within {PROACTIVE_RECENT_CHAT_SKIP_MINUTES} minutes",
        }

    if _count_today_candidates() >= PROACTIVE_DAILY_LIMIT:
        return {
            "success": True,
            "skipped": True,
            "reason": f"daily proactive candidate limit reached: {PROACTIVE_DAILY_LIMIT}",
        }

    selected_platform, target_row, skip_reason = _select_platform(platform)
    if not selected_platform or not target_row:
        return {
            "success": True,
            "skipped": True,
            "reason": skip_reason or "no eligible target",
        }

    target_hash = str(target_row["session_id_hash"] or "")
    message = random.choice(SAFE_TEMPLATES)
    reason = "manual safe template; outbound send disabled in v1"
    metadata = {
        "rules": {
            "no_send": True,
            "template_only": True,
            "active_window": f"{PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}",
            "recent_user_message_skip_minutes": PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
            "daily_limit": PROACTIVE_DAILY_LIMIT,
        },
        "target_last_seen_at": target_row["created_at"],
    }
    candidate = add_proactive_candidate(
        platform=selected_platform,
        target_hash=target_hash,
        target_label=_mask_hash(target_hash),
        message=message,
        reason=reason,
        status="pending",
        source="manual",
        metadata_json=json.dumps(metadata, ensure_ascii=False),
    )
    return {
        "success": True,
        "skipped": False,
        "candidate": candidate,
    }
