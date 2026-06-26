from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.storage import db as db_storage


_TZ8 = ZoneInfo("Asia/Shanghai")


def format_world_minutes(value: Any) -> str | None:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _display_date_from_updated_at(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_TZ8)
    return parsed.astimezone(_TZ8).date().isoformat()


def read_world_time_snapshot() -> dict[str, Any] | None:
    """Read the current Living World clock without mutating world state."""
    try:
        row = db_storage.fetch_one(
            "SELECT state_json, updated_at FROM life_world_state WHERE id = 1"
        )
        if row is None:
            return None
        data = json.loads(row["state_json"] or "{}")
    except Exception:
        return None

    last_tick = data.get("last_tick") if isinstance(data, dict) else None
    real_time = ""
    real_date = ""
    if isinstance(last_tick, dict):
        real_time = str(last_tick.get("real_time") or "").strip()
        real_date = str(last_tick.get("real_date") or "").strip()

    sim_minutes = data.get("sim_minutes") if isinstance(data, dict) else None
    display_time = (
        real_time
        if len(real_time) == 5 and real_time[2] == ":"
        else format_world_minutes(sim_minutes)
    )
    if not display_time:
        return None
    display_date = real_date or _display_date_from_updated_at(row["updated_at"])

    snapshot = {
        "display_time": display_time,
        "sim_minutes": sim_minutes,
        "updated_at": row["updated_at"],
        "source": "life_world_state",
    }
    if display_date:
        snapshot["display_date"] = display_date
    return snapshot
