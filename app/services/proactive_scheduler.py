import asyncio
import json
import random
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException

from app.config import (
    PROACTIVE_ACTIVE_END,
    PROACTIVE_ACTIVE_END_TIME,
    PROACTIVE_ACTIVE_START,
    PROACTIVE_ACTIVE_START_TIME,
    PROACTIVE_CHECK_INTERVAL_SECONDS,
    PROACTIVE_DAILY_LIMIT,
    PROACTIVE_ENABLED,
    PROACTIVE_MIN_INTERVAL_MINUTES,
    PROACTIVE_QQ_ALLOWED_TARGET_HASHES,
    PROACTIVE_RANDOM_PROBABILITY,
    PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
)
from app.services.proactive_service import SAFE_TEMPLATES, _mask_hash, is_allowed_qq_target, send_qq_candidate
from app.storage.db import (
    add_proactive_candidate,
    fetch_one,
    update_proactive_candidate_status,
)

_scheduler_task: asyncio.Task | None = None
_last_check_at: str | None = None
_last_result: dict[str, Any] | None = None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_sqlite_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _within_active_window(now: datetime) -> bool:
    current = now.time()
    if PROACTIVE_ACTIVE_START_TIME <= PROACTIVE_ACTIVE_END_TIME:
        return PROACTIVE_ACTIVE_START_TIME <= current <= PROACTIVE_ACTIVE_END_TIME
    return current >= PROACTIVE_ACTIVE_START_TIME or current <= PROACTIVE_ACTIVE_END_TIME


def _today_sent_count() -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS count
        FROM proactive_candidates
        WHERE platform = 'qq'
          AND source = 'auto'
          AND status = 'sent'
          AND date(created_at, 'localtime') = date('now', 'localtime')
        """
    )
    return int(row["count"] or 0) if row else 0


def _last_sent_at() -> str | None:
    row = fetch_one(
        """
        SELECT created_at
        FROM proactive_candidates
        WHERE platform = 'qq'
          AND source = 'auto'
          AND status = 'sent'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    )
    return str(row["created_at"]) if row else None


def _has_recent_user_message() -> bool:
    row = fetch_one(
        f"""
        SELECT 1 AS found
        FROM chat_stats
        WHERE platform = 'qq'
          AND created_at >= datetime('now', '-{PROACTIVE_RECENT_CHAT_SKIP_MINUTES} minutes')
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


def _latest_qq_target() -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT session_id_hash, created_at
        FROM chat_stats
        WHERE platform = 'qq'
          AND session_id_hash IS NOT NULL
          AND session_id_hash != ''
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    )


def _skip(reason: str) -> dict[str, Any]:
    return {
        "success": True,
        "skipped": True,
        "reason": reason,
    }


def _create_auto_candidate(target_row: dict[str, Any]) -> dict:
    target_hash = str(target_row["session_id_hash"] or "")
    metadata = {
        "rules": {
            "template_only": True,
            "platform": "qq",
            "active_window": f"{PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}",
            "daily_limit": PROACTIVE_DAILY_LIMIT,
            "min_interval_minutes": PROACTIVE_MIN_INTERVAL_MINUTES,
            "recent_user_message_skip_minutes": PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
            "random_probability": PROACTIVE_RANDOM_PROBABILITY,
        },
        "target_last_seen_at": target_row["created_at"],
        "auto_created_at": _now_iso(),
    }
    return add_proactive_candidate(
        platform="qq",
        target_hash=target_hash,
        target_label=_mask_hash(target_hash),
        message=random.choice(SAFE_TEMPLATES),
        reason="auto v3 fixed template",
        status="pending",
        source="auto",
        metadata_json=json.dumps(metadata, ensure_ascii=False),
    )


def _check_and_send_once() -> dict[str, Any]:
    now = datetime.now()

    if not _within_active_window(now):
        return _skip(f"outside active window: {PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}")

    probability = max(0.0, min(1.0, PROACTIVE_RANDOM_PROBABILITY))
    if random.random() >= probability:
        return _skip("random probability missed")

    sent_count = _today_sent_count()
    if sent_count >= PROACTIVE_DAILY_LIMIT:
        return _skip(f"daily sent limit reached: {PROACTIVE_DAILY_LIMIT}")

    last_sent = _parse_sqlite_datetime(_last_sent_at())
    if last_sent is not None and now - last_sent < timedelta(minutes=PROACTIVE_MIN_INTERVAL_MINUTES):
        return _skip(f"last sent is within {PROACTIVE_MIN_INTERVAL_MINUTES} minutes")

    if _has_recent_user_message():
        return _skip(f"qq user message seen within {PROACTIVE_RECENT_CHAT_SKIP_MINUTES} minutes")

    if _has_pending_qq_candidate():
        return _skip("pending qq candidate exists")

    target_row = _latest_qq_target()
    if target_row is None:
        return _skip("no qq target found in chat_stats")

    target_hash = str(target_row["session_id_hash"] or "")
    if not is_allowed_qq_target(target_hash):
        return _skip("latest qq target is not whitelisted")

    candidate = _create_auto_candidate(target_row)
    try:
        result = send_qq_candidate(candidate_id=candidate["id"], dry_run=False)
    except HTTPException as exc:
        update_proactive_candidate_status(candidate["id"], "failed")
        return {
            "success": False,
            "skipped": False,
            "candidate_id": candidate["id"],
            "error": str(exc.detail),
        }
    except Exception as exc:
        update_proactive_candidate_status(candidate["id"], "failed")
        return {
            "success": False,
            "skipped": False,
            "candidate_id": candidate["id"],
            "error": type(exc).__name__,
        }

    return {
        "success": True,
        "skipped": False,
        "sent": True,
        "candidate_id": candidate["id"],
        "target_label": result.get("target_label"),
    }


async def run_proactive_check_once() -> dict[str, Any]:
    global _last_check_at, _last_result
    _last_check_at = _now_iso()
    _last_result = await asyncio.to_thread(_check_and_send_once)
    return _last_result


async def _scheduler_loop() -> None:
    while True:
        try:
            result = await run_proactive_check_once()
            print("proactive scheduler check:", result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print("proactive scheduler failed:", type(exc).__name__)
        await asyncio.sleep(PROACTIVE_CHECK_INTERVAL_SECONDS)


def start_proactive_scheduler() -> asyncio.Task | None:
    global _scheduler_task
    if not PROACTIVE_ENABLED:
        print("proactive scheduler disabled")
        return None
    if _scheduler_task is not None and not _scheduler_task.done():
        return _scheduler_task
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    print("proactive scheduler started")
    return _scheduler_task


async def stop_proactive_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = None
        return
    _scheduler_task.cancel()
    try:
        await _scheduler_task
    except asyncio.CancelledError:
        pass
    _scheduler_task = None


def get_proactive_scheduler_status() -> dict[str, Any]:
    return {
        "success": True,
        "enabled": PROACTIVE_ENABLED,
        "task_running": _scheduler_task is not None and not _scheduler_task.done(),
        "config": {
            "check_interval_seconds": PROACTIVE_CHECK_INTERVAL_SECONDS,
            "daily_limit": PROACTIVE_DAILY_LIMIT,
            "min_interval_minutes": PROACTIVE_MIN_INTERVAL_MINUTES,
            "recent_chat_skip_minutes": PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
            "active_start": PROACTIVE_ACTIVE_START,
            "active_end": PROACTIVE_ACTIVE_END,
            "random_probability": PROACTIVE_RANDOM_PROBABILITY,
        },
        "qq_allowed_target_count": len(PROACTIVE_QQ_ALLOWED_TARGET_HASHES),
        "today_sent_count": _today_sent_count(),
        "last_sent_at": _last_sent_at(),
        "last_check_at": _last_check_at,
        "last_result": _last_result,
    }
