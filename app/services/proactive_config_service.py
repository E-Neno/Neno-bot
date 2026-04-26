import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.schemas import ProactiveConfigUpdateRequest
from app.utils.env_writer import update_env_file

PROACTIVE_CONFIG_KEYS = [
    "PROACTIVE_ENABLED",
    "PROACTIVE_CHECK_INTERVAL_SECONDS",
    "PROACTIVE_DAILY_LIMIT",
    "PROACTIVE_MIN_INTERVAL_MINUTES",
    "PROACTIVE_RECENT_CHAT_SKIP_MINUTES",
    "PROACTIVE_ACTIVE_START",
    "PROACTIVE_ACTIVE_END",
    "PROACTIVE_RANDOM_PROBABILITY",
    "PROACTIVE_QQ_ALLOWED_TARGET_HASHES",
    "NENO_BRIDGE_SEND_QQ_URL",
]

DEFAULT_PROACTIVE_CONFIG = {
    "PROACTIVE_ENABLED": "false",
    "PROACTIVE_CHECK_INTERVAL_SECONDS": "600",
    "PROACTIVE_DAILY_LIMIT": "2",
    "PROACTIVE_MIN_INTERVAL_MINUTES": "240",
    "PROACTIVE_RECENT_CHAT_SKIP_MINUTES": "45",
    "PROACTIVE_ACTIVE_START": "10:30",
    "PROACTIVE_ACTIVE_END": "23:30",
    "PROACTIVE_RANDOM_PROBABILITY": "0.25",
    "PROACTIVE_QQ_ALLOWED_TARGET_HASHES": "",
    "NENO_BRIDGE_SEND_QQ_URL": "http://127.0.0.1:18793/proactive/send-qq",
}

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
HASH_LIST_RE = re.compile(r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$")


def _env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def _read_allowed_env_values() -> dict[str, str]:
    values = dict(DEFAULT_PROACTIVE_CONFIG)
    path = _env_path()
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in values:
            values[key] = value.strip()
    return values


def _mask_value(value: str) -> str:
    text = value.strip()
    if len(text) <= 8:
        return text
    return f"{text[:4]}...{text[-4:]}"


def _mask_hashes(raw: str) -> list[str]:
    return [_mask_value(item) for item in raw.split(",") if item.strip()]


def get_proactive_config() -> dict[str, Any]:
    values = _read_allowed_env_values()
    allowed_hashes = values["PROACTIVE_QQ_ALLOWED_TARGET_HASHES"]
    return {
        "success": True,
        "config": {
            "PROACTIVE_ENABLED": values["PROACTIVE_ENABLED"],
            "PROACTIVE_CHECK_INTERVAL_SECONDS": values["PROACTIVE_CHECK_INTERVAL_SECONDS"],
            "PROACTIVE_DAILY_LIMIT": values["PROACTIVE_DAILY_LIMIT"],
            "PROACTIVE_MIN_INTERVAL_MINUTES": values["PROACTIVE_MIN_INTERVAL_MINUTES"],
            "PROACTIVE_RECENT_CHAT_SKIP_MINUTES": values["PROACTIVE_RECENT_CHAT_SKIP_MINUTES"],
            "PROACTIVE_ACTIVE_START": values["PROACTIVE_ACTIVE_START"],
            "PROACTIVE_ACTIVE_END": values["PROACTIVE_ACTIVE_END"],
            "PROACTIVE_RANDOM_PROBABILITY": values["PROACTIVE_RANDOM_PROBABILITY"],
            "PROACTIVE_QQ_ALLOWED_TARGET_HASHES_EMPTY": not bool(allowed_hashes.strip()),
            "PROACTIVE_QQ_ALLOWED_TARGET_HASHES_LABELS": _mask_hashes(allowed_hashes),
            "NENO_BRIDGE_SEND_QQ_URL": values["NENO_BRIDGE_SEND_QQ_URL"],
        },
    }


def _validate_time(name: str, value: str) -> str:
    text = value.strip()
    if not TIME_RE.match(text):
        raise HTTPException(status_code=400, detail=f"{name} must be HH:MM")
    return text


def _validate_int(name: str, value: int, minimum: int, maximum: int) -> str:
    if not minimum <= value <= maximum:
        raise HTTPException(status_code=400, detail=f"{name} must be between {minimum} and {maximum}")
    return str(value)


def _validate_probability(value: float) -> str:
    if not 0 <= value <= 1:
        raise HTTPException(status_code=400, detail="PROACTIVE_RANDOM_PROBABILITY must be between 0 and 1")
    return str(value)


def _validate_hashes(value: str) -> str:
    text = ",".join(item.strip() for item in value.split(",") if item.strip())
    if not text:
        return ""
    if not HASH_LIST_RE.match(text):
        raise HTTPException(
            status_code=400,
            detail="PROACTIVE_QQ_ALLOWED_TARGET_HASHES must be empty or comma-separated hashes",
        )
    return text


def _validate_bridge_url(value: str) -> str:
    text = value.strip()
    if not text.startswith("http://127.0.0.1:"):
        raise HTTPException(
            status_code=400,
            detail="NENO_BRIDGE_SEND_QQ_URL must start with http://127.0.0.1:",
        )
    return text


def update_proactive_config(req: ProactiveConfigUpdateRequest) -> dict[str, Any]:
    payload = req.dict(exclude_unset=True)
    updates: dict[str, str] = {}

    if "PROACTIVE_ENABLED" in payload:
        updates["PROACTIVE_ENABLED"] = "true" if payload["PROACTIVE_ENABLED"] else "false"
    if "PROACTIVE_CHECK_INTERVAL_SECONDS" in payload:
        updates["PROACTIVE_CHECK_INTERVAL_SECONDS"] = _validate_int(
            "PROACTIVE_CHECK_INTERVAL_SECONDS",
            payload["PROACTIVE_CHECK_INTERVAL_SECONDS"],
            30,
            86400,
        )
    if "PROACTIVE_DAILY_LIMIT" in payload:
        updates["PROACTIVE_DAILY_LIMIT"] = _validate_int(
            "PROACTIVE_DAILY_LIMIT",
            payload["PROACTIVE_DAILY_LIMIT"],
            0,
            10,
        )
    if "PROACTIVE_MIN_INTERVAL_MINUTES" in payload:
        updates["PROACTIVE_MIN_INTERVAL_MINUTES"] = _validate_int(
            "PROACTIVE_MIN_INTERVAL_MINUTES",
            payload["PROACTIVE_MIN_INTERVAL_MINUTES"],
            1,
            1440,
        )
    if "PROACTIVE_RECENT_CHAT_SKIP_MINUTES" in payload:
        updates["PROACTIVE_RECENT_CHAT_SKIP_MINUTES"] = _validate_int(
            "PROACTIVE_RECENT_CHAT_SKIP_MINUTES",
            payload["PROACTIVE_RECENT_CHAT_SKIP_MINUTES"],
            0,
            1440,
        )
    if "PROACTIVE_ACTIVE_START" in payload:
        updates["PROACTIVE_ACTIVE_START"] = _validate_time(
            "PROACTIVE_ACTIVE_START",
            payload["PROACTIVE_ACTIVE_START"],
        )
    if "PROACTIVE_ACTIVE_END" in payload:
        updates["PROACTIVE_ACTIVE_END"] = _validate_time(
            "PROACTIVE_ACTIVE_END",
            payload["PROACTIVE_ACTIVE_END"],
        )
    if "PROACTIVE_RANDOM_PROBABILITY" in payload:
        updates["PROACTIVE_RANDOM_PROBABILITY"] = _validate_probability(
            payload["PROACTIVE_RANDOM_PROBABILITY"]
        )
    if "PROACTIVE_QQ_ALLOWED_TARGET_HASHES" in payload:
        updates["PROACTIVE_QQ_ALLOWED_TARGET_HASHES"] = _validate_hashes(
            payload["PROACTIVE_QQ_ALLOWED_TARGET_HASHES"]
        )
    if "NENO_BRIDGE_SEND_QQ_URL" in payload:
        updates["NENO_BRIDGE_SEND_QQ_URL"] = _validate_bridge_url(payload["NENO_BRIDGE_SEND_QQ_URL"])

    if not updates:
        raise HTTPException(status_code=400, detail="no proactive config fields provided")

    try:
        update_env_file(updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    masked_updates = {
        key: (_mask_hashes(value) if key == "PROACTIVE_QQ_ALLOWED_TARGET_HASHES" else value)
        for key, value in updates.items()
    }
    return {
        "success": True,
        "requires_restart": True,
        "message": "config saved, restart emotion-bot to apply changes",
        "updated": masked_updates,
    }
