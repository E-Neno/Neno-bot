import hashlib
from typing import Any

from app.config import CHAT_MODEL_NAME, HISTORY_LIMIT, MEMORY_LIMIT, MEMORY_MODEL_NAME
from app.storage.db import execute_write, fetch_all, fetch_one
from app.utils.logging_utils import log_event


def short_hash(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def record_chat_stat(
    *,
    source: str,
    platform: str,
    session_id: str,
    message: str | None,
    reply: str | None,
    success: bool,
    latency_ms: int,
    error_type: str | None = None,
    model: str | None = None,
) -> None:
    try:
        execute_write(
            """
            INSERT INTO chat_stats (
                source,
                platform,
                session_id,
                session_id_hash,
                message_len,
                reply_len,
                success,
                latency_ms,
                error_type,
                model
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                platform,
                session_id,
                short_hash(session_id),
                len(message or ""),
                len(reply or ""),
                1 if success else 0,
                latency_ms,
                (error_type or "")[:80] or None,
                model or CHAT_MODEL_NAME,
            ),
        )
    except Exception as exc:
        log_event(
            "stats",
            "stats_write_failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )


def get_stats_summary() -> dict[str, Any]:
    counts = fetch_one(
        """
        SELECT
            COUNT(CASE WHEN date(created_at, 'localtime') = date('now', 'localtime') THEN 1 END) AS today_messages,
            COUNT(CASE WHEN created_at >= datetime('now', '-24 hours') THEN 1 END) AS last_24h_messages,
            COUNT(CASE WHEN created_at >= datetime('now', '-24 hours') AND success = 0 THEN 1 END) AS last_24h_errors,
            ROUND(AVG(CASE WHEN created_at >= datetime('now', '-24 hours') THEN latency_ms END)) AS avg_latency_ms_24h,
            MAX(created_at) AS last_message_at,
            MAX(CASE WHEN platform = 'qq' THEN created_at END) AS last_qq_message_at,
            COUNT(CASE WHEN platform = 'qq' AND created_at >= datetime('now', '-10 minutes') THEN 1 END) AS recent_qq_messages_10m
        FROM chat_stats
        """
    )
    platform_rows = fetch_all(
        """
        SELECT platform, COUNT(*) AS count
        FROM chat_stats
        WHERE created_at >= datetime('now', '-24 hours')
        GROUP BY platform
        ORDER BY count DESC, platform ASC
        """
    )

    return {
        "today_messages": int(counts["today_messages"] or 0) if counts else 0,
        "last_24h_messages": int(counts["last_24h_messages"] or 0) if counts else 0,
        "last_24h_errors": int(counts["last_24h_errors"] or 0) if counts else 0,
        "avg_latency_ms_24h": int(counts["avg_latency_ms_24h"] or 0) if counts else 0,
        "last_message_at": counts["last_message_at"] if counts else None,
        "last_qq_message_at": counts["last_qq_message_at"] if counts else None,
        "platform_counts_24h": {
            (row["platform"] or "unknown"): int(row["count"] or 0)
            for row in platform_rows
        },
        "current_model": CHAT_MODEL_NAME,
        "memory_model": MEMORY_MODEL_NAME,
        "history_limit": HISTORY_LIMIT,
        "memory_limit": MEMORY_LIMIT,
        "backend_ok": True,
        "openclaw_gateway_maybe_online": bool(counts["recent_qq_messages_10m"] or 0) if counts else False,
    }
