import json
import random
from typing import Any

from app.config import (
    PROACTIVE_ACTIVE_END,
    PROACTIVE_ACTIVE_START,
    PROACTIVE_DAILY_LIMIT,
    PROACTIVE_MIN_INTERVAL_MINUTES,
    PROACTIVE_MODE,
    PROACTIVE_RANDOM_PROBABILITY,
    PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
)
from app.services.proactive.result_helpers import now_iso
from app.services.proactive_service import SAFE_TEMPLATES, _mask_hash, record_proactive_event
from app.storage.db import add_proactive_candidate
from app.utils.logging_utils import log_event


def create_auto_candidate(target_row: dict[str, Any], trace_id: str | None = None) -> dict:
    target_hash = str(target_row["target_hash"] or "")
    session_id = str(target_row["session_id"] or "").strip()
    metadata = {
        "session_id": session_id,
        "rules": {
            "template_only": True,
            "platform": "qq",
            "active_window": f"{PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}",
            "daily_limit": PROACTIVE_DAILY_LIMIT,
            "min_interval_minutes": PROACTIVE_MIN_INTERVAL_MINUTES,
            "recent_user_message_skip_minutes": PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
            "random_probability": PROACTIVE_RANDOM_PROBABILITY,
            "proactive_mode": PROACTIVE_MODE,
        },
        "target_last_seen_at": target_row["last_seen_at"],
        "auto_created_at": now_iso(),
        "source": "auto_scheduler",
    }
    candidate = add_proactive_candidate(
        platform="qq",
        target_hash=target_hash,
        target_label=str(target_row["target_label"] or _mask_hash(target_hash)),
        message=random.choice(SAFE_TEMPLATES),
        reason="auto v4.6 fixed template",
        status="pending",
        source="auto",
        metadata_json=json.dumps(metadata, ensure_ascii=False),
    )
    record_proactive_event(
        event_type="candidate_generated",
        platform="qq",
        target_label=candidate.get("target_label"),
        candidate_id=candidate["id"],
        action="candidate_generated",
        success=True,
        skipped=False,
        metadata={"source": "auto_scheduler", "proactive_mode": PROACTIVE_MODE},
    )
    log_event(
        "proactive",
        "proactive_candidate_generated",
        trace_id=trace_id,
        candidate_id=candidate.get("id"),
        target_label=candidate.get("target_label"),
        action="candidate_generated",
        success=True,
        skipped=False,
    )
    return candidate
