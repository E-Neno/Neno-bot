import json
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.security import require_admin_token
from app.storage.db import list_debug_events

router = APIRouter(prefix="/debug", tags=["debug"])


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _sanitize_debug_event(event: dict) -> dict:
    return {
        "id": event.get("id"),
        "created_at": event.get("created_at"),
        "trace_id": event.get("trace_id"),
        "module": event.get("module"),
        "event": event.get("event"),
        "level": event.get("level") or "info",
        "success": None if event.get("success") is None else bool(event.get("success")),
        "skipped": None if event.get("skipped") is None else bool(event.get("skipped")),
        "action": event.get("action"),
        "reason": event.get("reason"),
        "target_label": event.get("target_label"),
        "candidate_id": event.get("candidate_id"),
        "metadata": _parse_metadata(event.get("metadata_json")),
    }


def _build_summary(events: list[dict]) -> dict:
    return {
        "total_returned": len(events),
        "latest_event_at": events[0]["created_at"] if events else None,
        "error_count": sum(
            1
            for event in events
            if event.get("level") == "error" or event.get("success") is False
        ),
        "proactive_count": sum(1 for event in events if event.get("module") == "proactive"),
        "platform_count": sum(1 for event in events if event.get("module") == "platform"),
        "chat_count": sum(1 for event in events if event.get("module") == "chat"),
        "openrouter_count": sum(1 for event in events if event.get("module") == "openrouter"),
    }


@router.get("/events", dependencies=[Depends(require_admin_token)])
def debug_events(
    limit: int = Query(default=100, ge=1, le=300),
    module: str | None = Query(default=None, max_length=64),
    event: str | None = Query(default=None, max_length=128),
    trace_id: str | None = Query(default=None, max_length=64),
    level: str | None = Query(default=None, max_length=32),
):
    raw_events = list_debug_events(
        limit=limit,
        module=module,
        event=event,
        trace_id=trace_id,
        level=level,
    )
    events = [_sanitize_debug_event(item) for item in raw_events]
    return {
        "success": True,
        "events": events,
        "summary": _build_summary(events),
    }
