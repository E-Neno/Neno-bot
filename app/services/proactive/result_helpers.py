import json
from datetime import datetime
from typing import Any, Callable

from app.config import PROACTIVE_MODE
from app.services.proactive_service import record_proactive_event
from app.storage.db import get_proactive_candidate, update_proactive_candidate_metadata
from app.utils.logging_utils import log_event


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_sqlite_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_candidate_metadata(candidate: dict | None) -> dict[str, Any]:
    if not candidate:
        return {}
    raw = candidate.get("metadata_json") or "{}"
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def update_candidate_metadata(candidate_id: int, updates: dict[str, Any]) -> dict | None:
    candidate = get_proactive_candidate(candidate_id)
    metadata = load_candidate_metadata(candidate)
    metadata.update(updates)
    return update_proactive_candidate_metadata(
        candidate_id,
        json.dumps(metadata, ensure_ascii=False),
    )


def rule(name: str, ok: bool | None, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "detail": detail,
    }


def skip_result(
    reason: str,
    checks: list[dict[str, Any]] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    record_proactive_event(
        event_type="rule_skipped",
        platform="qq",
        action="skipped",
        success=True,
        skipped=True,
        reason=reason,
        metadata={"proactive_mode": PROACTIVE_MODE},
    )
    log_event(
        "proactive",
        "proactive_rule_skipped",
        trace_id=trace_id,
        action="skipped",
        reason=reason,
        success=True,
        skipped=True,
        proactive_mode=PROACTIVE_MODE,
    )
    return {
        "success": True,
        "skipped": True,
        "reason": reason,
        "action": "skipped",
        "proactive_mode": PROACTIVE_MODE,
        "checks": checks or [],
    }


def observed_result(checks: list[dict[str, Any]], trace_id: str | None = None) -> dict[str, Any]:
    failed = next((check for check in checks if check["ok"] is False), None)
    can_send = failed is None
    reason = "observe would pass" if can_send else str(failed["detail"])
    record_proactive_event(
        event_type="scheduler_observed",
        platform="qq",
        action="observed",
        success=True,
        skipped=not can_send,
        reason=reason,
        metadata={"proactive_mode": PROACTIVE_MODE, "would_pass": can_send},
    )
    log_event(
        "proactive",
        "proactive_observed",
        trace_id=trace_id,
        action="observed",
        success=True,
        skipped=not can_send,
        reason=reason,
        proactive_mode=PROACTIVE_MODE,
    )
    return {
        "success": True,
        "skipped": not can_send,
        "action": "observed",
        "reason": reason,
        "would_pass": can_send,
        "proactive_mode": PROACTIVE_MODE,
        "checks": checks,
    }


def generated_pending_result(candidate: dict, reason: str | None = None) -> dict[str, Any]:
    result = {
        "success": True,
        "skipped": False,
        "action": "generated_pending",
        "generated_pending": True,
        "candidate_id": candidate["id"],
        "target_label": candidate.get("target_label"),
    }
    if reason:
        result["reason"] = reason
    return result


def with_explained_reason(
    result: dict[str, Any] | None,
    explain_reason: Callable[[str | None], str],
) -> dict[str, Any] | None:
    if result is None:
        return None
    normalized = dict(result)
    if "reason" in normalized:
        normalized["reason"] = explain_reason(str(normalized.get("reason") or ""))
    if "error" in normalized and "reason" not in normalized:
        normalized["reason"] = explain_reason(str(normalized.get("error") or "发送失败"))
    return normalized


def normalize_manual_run_result(
    result: dict[str, Any],
    *,
    dry_run_only: bool,
    explain_reason: Callable[[str | None], str],
) -> dict[str, Any]:
    if result.get("action") == "observed":
        action = "observed"
    elif result.get("skipped"):
        action = "skipped"
    elif result.get("success") is not True:
        action = "failed"
    elif result.get("action") in {"auto_send_dry_run_ok", "manual_send_dry_run"} or result.get("dry_run"):
        action = "dry_run_ok"
    elif result.get("action") == "auto_sent" and dry_run_only:
        action = "dry_run_ok"
    else:
        action = "generated_pending"

    return {
        "success": result.get("success") is True,
        "action": action,
        "reason": explain_reason(
            str(result.get("reason") or result.get("error") or result.get("action") or "")
        ),
        "candidate_id": result.get("candidate_id"),
        "dry_run_only": dry_run_only,
        "proactive_mode": result.get("proactive_mode") or PROACTIVE_MODE,
        "would_pass": result.get("would_pass"),
        "checks": result.get("checks") or [],
    }
