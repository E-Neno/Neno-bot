from typing import Any

from fastapi import HTTPException

from app.config import (
    PROACTIVE_AUTO_SEND_MAX_PER_DAY,
    PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET,
)
from app.services.proactive.result_helpers import (
    generated_pending_result,
    now_iso,
    update_candidate_metadata,
)
from app.services.proactive.rules import today_auto_sent_count
from app.services.proactive_service import (
    is_allowed_qq_target,
    record_proactive_event,
    send_qq_candidate,
)
from app.storage.db import update_proactive_candidate_status
from app.utils.logging_utils import log_event


def record_auto_send_error(candidate_id: int, action: str, error: str) -> None:
    update_candidate_metadata(
        candidate_id,
        {
            "auto_send_error": (error or "auto send failed")[:160],
            "auto_send_failed_at": now_iso(),
            "auto_send_action": action,
        },
    )


def candidate_can_auto_send(candidate: dict, target_row: dict[str, Any]) -> tuple[bool, str | None]:
    if candidate.get("platform") != "qq":
        return False, "auto send only supports qq"
    if candidate.get("status") != "pending":
        return False, "candidate is not pending"
    if int(target_row.get("is_allowed") or 0) != 1:
        return False, "target is not allowed"
    if PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET and not is_allowed_qq_target(str(candidate.get("target_hash") or "")):
        return False, "target is not allowed"
    auto_sent_today = today_auto_sent_count()
    if auto_sent_today >= PROACTIVE_AUTO_SEND_MAX_PER_DAY:
        return False, f"auto send max per day reached: {PROACTIVE_AUTO_SEND_MAX_PER_DAY}"
    return True, None


def auto_send_dry_run(
    candidate: dict,
    *,
    event_source: str = "auto",
    trace_id: str | None = None,
) -> dict[str, Any]:
    try:
        send_qq_candidate(
            candidate_id=candidate["id"],
            dry_run=True,
            event_source=event_source,
            trace_id=trace_id,
        )
    except HTTPException as exc:
        record_auto_send_error(candidate["id"], "auto_send_dry_run_failed", str(exc.detail))
        record_proactive_event(
            event_type="auto_send_dry_run",
            platform="qq",
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_dry_run_failed",
            success=False,
            skipped=False,
            reason=str(exc.detail),
        )
        log_event(
            "proactive",
            "proactive_dry_run_failed",
            trace_id=trace_id,
            candidate_id=candidate.get("id"),
            target_label=candidate.get("target_label"),
            action="auto_send_dry_run_failed",
            dry_run=True,
            success=False,
            reason=str(exc.detail),
        )
        return {
            "success": False,
            "skipped": False,
            "action": "auto_send_dry_run_failed",
            "candidate_id": candidate["id"],
            "error": str(exc.detail),
        }
    except Exception as exc:
        record_auto_send_error(candidate["id"], "auto_send_dry_run_failed", type(exc).__name__)
        record_proactive_event(
            event_type="auto_send_dry_run",
            platform="qq",
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_dry_run_failed",
            success=False,
            skipped=False,
            reason=type(exc).__name__,
        )
        log_event(
            "proactive",
            "proactive_dry_run_failed",
            trace_id=trace_id,
            candidate_id=candidate.get("id"),
            target_label=candidate.get("target_label"),
            action="auto_send_dry_run_failed",
            dry_run=True,
            success=False,
            reason=type(exc).__name__,
        )
        return {
            "success": False,
            "skipped": False,
            "action": "auto_send_dry_run_failed",
            "candidate_id": candidate["id"],
            "error": type(exc).__name__,
        }

    update_candidate_metadata(
        candidate["id"],
        {
            "auto_send_dry_run": True,
            "auto_send_dry_run_at": now_iso(),
            "auto_send_action": "auto_send_dry_run_ok",
        },
    )
    record_proactive_event(
        event_type="auto_send_dry_run",
        platform="qq",
        target_label=candidate.get("target_label"),
        candidate_id=candidate["id"],
        action="auto_send_dry_run_ok",
        success=True,
        skipped=False,
    )
    log_event(
        "proactive",
        "proactive_dry_run_ok",
        trace_id=trace_id,
        candidate_id=candidate.get("id"),
        target_label=candidate.get("target_label"),
        action="auto_send_dry_run_ok",
        dry_run=True,
        success=True,
    )
    return {
        "success": True,
        "skipped": False,
        "action": "auto_send_dry_run_ok",
        "candidate_id": candidate["id"],
        "target_label": candidate.get("target_label"),
    }


def auto_send_real(
    candidate: dict,
    target_row: dict[str, Any],
    trace_id: str | None = None,
) -> dict[str, Any]:
    can_send, blocked_reason = candidate_can_auto_send(candidate, target_row)
    if not can_send:
        update_candidate_metadata(
            candidate["id"],
            {
                "auto_send_blocked": True,
                "auto_send_blocked_at": now_iso(),
                "auto_send_blocked_reason": blocked_reason,
            },
        )
        return generated_pending_result(candidate, blocked_reason)

    try:
        send_qq_candidate(
            candidate_id=candidate["id"],
            dry_run=False,
            event_source="auto",
            trace_id=trace_id,
        )
    except HTTPException as exc:
        record_auto_send_error(candidate["id"], "auto_send_failed", str(exc.detail))
        update_proactive_candidate_status(candidate["id"], "failed")
        record_proactive_event(
            event_type="auto_send_failed",
            platform="qq",
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_failed",
            success=False,
            skipped=False,
            reason=str(exc.detail),
        )
        log_event(
            "proactive",
            "proactive_auto_failed",
            trace_id=trace_id,
            candidate_id=candidate.get("id"),
            target_label=candidate.get("target_label"),
            action="auto_send_failed",
            dry_run=False,
            auto_send=True,
            success=False,
            reason=str(exc.detail),
        )
        return {
            "success": False,
            "skipped": False,
            "action": "auto_send_failed",
            "candidate_id": candidate["id"],
            "error": str(exc.detail),
        }
    except Exception as exc:
        record_auto_send_error(candidate["id"], "auto_send_failed", type(exc).__name__)
        update_proactive_candidate_status(candidate["id"], "failed")
        record_proactive_event(
            event_type="auto_send_failed",
            platform="qq",
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_failed",
            success=False,
            skipped=False,
            reason=type(exc).__name__,
        )
        log_event(
            "proactive",
            "proactive_auto_failed",
            trace_id=trace_id,
            candidate_id=candidate.get("id"),
            target_label=candidate.get("target_label"),
            action="auto_send_failed",
            dry_run=False,
            auto_send=True,
            success=False,
            reason=type(exc).__name__,
        )
        return {
            "success": False,
            "skipped": False,
            "action": "auto_send_failed",
            "candidate_id": candidate["id"],
            "error": type(exc).__name__,
        }

    update_candidate_metadata(
        candidate["id"],
        {
            "auto_sent": True,
            "auto_sent_at": now_iso(),
            "auto_send_action": "auto_sent",
        },
    )
    record_proactive_event(
        event_type="auto_sent",
        platform="qq",
        target_label=candidate.get("target_label"),
        candidate_id=candidate["id"],
        action="auto_sent",
        success=True,
        skipped=False,
    )
    log_event(
        "proactive",
        "proactive_auto_sent",
        trace_id=trace_id,
        candidate_id=candidate.get("id"),
        target_label=candidate.get("target_label"),
        action="auto_sent",
        dry_run=False,
        auto_send=True,
        success=True,
    )
    return {
        "success": True,
        "skipped": False,
        "sent": True,
        "action": "auto_sent",
        "candidate_id": candidate["id"],
        "target_label": candidate.get("target_label"),
    }
