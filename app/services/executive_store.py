from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from app.storage import db as db_storage


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _command_ids(values: Sequence[int]) -> list[int]:
    ids: list[int] = []
    for value in values:
        try:
            command_id = int(value)
        except (TypeError, ValueError):
            continue
        if command_id > 0 and command_id not in ids:
            ids.append(command_id)
    return ids


def record_executive_decision(
    *,
    trace_id: str,
    session_id: str,
    trigger_type: str,
    action: str,
    depth: str,
    decision: Mapping[str, Any],
    world_intents: Sequence[str],
) -> int:
    """Append one decision and its world commands in a single transaction."""
    created_at = _utcnow_iso()
    intents = [str(item or "").strip()[:240] for item in world_intents]
    intents = [item for item in intents if item][:3]
    with db_storage.get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO executive_decisions (
                trace_id, session_id, trigger_type, action, depth,
                decision_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(trace_id or ""),
                str(session_id or ""),
                str(trigger_type or "chat"),
                str(action or "reply_now"),
                str(depth or "shallow"),
                json.dumps(dict(decision), ensure_ascii=False),
                created_at,
            ),
        )
        decision_id = int(cursor.lastrowid)
        for intent in intents:
            conn.execute(
                """
                INSERT INTO executive_commands (
                    decision_id, trace_id, session_id, command_type,
                    payload_json, status, created_at
                )
                VALUES (?, ?, ?, 'world_intent', ?, 'queued', ?)
                """,
                (
                    decision_id,
                    str(trace_id or ""),
                    str(session_id or ""),
                    json.dumps({"intent": intent}, ensure_ascii=False),
                    created_at,
                ),
            )
    return decision_id


def list_queued_executive_commands(*, limit: int = 5) -> list[dict[str, Any]]:
    bounded = max(1, min(int(limit), 20))
    rows = db_storage.fetch_all(
        """
        SELECT id, decision_id, trace_id, session_id, command_type,
               payload_json, status, created_at, consumed_at, error
        FROM executive_commands
        WHERE status = 'queued'
        ORDER BY created_at ASC, id ASC
        LIMIT ?
        """,
        (bounded,),
    )
    commands: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        commands.append(
            {
                "id": int(row["id"]),
                "decision_id": int(row["decision_id"]),
                "trace_id": str(row["trace_id"] or ""),
                "session_id": str(row["session_id"] or ""),
                "command_type": str(row["command_type"] or ""),
                "payload": payload if isinstance(payload, dict) else {},
                "status": str(row["status"] or ""),
                "created_at": str(row["created_at"] or ""),
                "consumed_at": row["consumed_at"],
                "error": row["error"],
            }
        )
    return commands


def mark_executive_commands_consumed(command_ids: Sequence[int]) -> None:
    ids = _command_ids(command_ids)
    if not ids:
        return
    placeholders = ", ".join("?" for _ in ids)
    db_storage.execute_write(
        f"""
        UPDATE executive_commands
        SET status = 'consumed', consumed_at = ?, error = NULL
        WHERE status = 'queued' AND id IN ({placeholders})
        """,
        (_utcnow_iso(), *ids),
    )


def record_executive_command_error(command_ids: Sequence[int], error: str) -> None:
    ids = _command_ids(command_ids)
    if not ids:
        return
    placeholders = ", ".join("?" for _ in ids)
    db_storage.execute_write(
        f"""
        UPDATE executive_commands
        SET error = ?
        WHERE status = 'queued' AND id IN ({placeholders})
        """,
        (str(error or "")[:500], *ids),
    )


def mark_executive_commands_failed(command_ids: Sequence[int], error: str) -> None:
    ids = _command_ids(command_ids)
    if not ids:
        return
    placeholders = ", ".join("?" for _ in ids)
    db_storage.execute_write(
        f"""
        UPDATE executive_commands
        SET status = 'failed', error = ?
        WHERE status = 'queued' AND id IN ({placeholders})
        """,
        (str(error or "")[:500], *ids),
    )
