from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.storage import db as db_storage


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


class InnerExperienceIn(BaseModel):
    trace_id: str
    source: str
    kind: str
    content: str
    mood_impact: float = 0.0
    desire_impact: float = 0.0
    salience: float = 0.5
    expression_status: str = "unspoken"
    related_event_hash: str | None = None
    related_message_ids: list[int] = Field(default_factory=list)
    related_intent_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("salience", mode="after")
    @classmethod
    def _clamp_salience(cls, value: float) -> float:
        return _clamp(value, 0.0, 1.0)


class ExperienceRecorder:
    async def record(self, exp: InnerExperienceIn) -> int | None:
        return await asyncio.to_thread(self._record_sync, exp)

    async def list_recent(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_recent_sync, limit, status)

    async def mark_expression_status(
        self,
        experience_id: int | None,
        status: str,
        intent_id: int | None = None,
    ) -> None:
        if experience_id is None:
            return
        await asyncio.to_thread(self._mark_expression_status_sync, experience_id, status, intent_id)

    def _record_sync(self, exp: InnerExperienceIn) -> int | None:
        created_at = _utcnow_iso()
        try:
            with db_storage.get_conn() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO inner_experience_log (
                        trace_id,
                        source,
                        kind,
                        content,
                        mood_impact,
                        desire_impact,
                        salience,
                        expression_status,
                        related_event_hash,
                        related_message_ids,
                        related_intent_id,
                        metadata_json,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        exp.trace_id,
                        exp.source,
                        exp.kind,
                        exp.content,
                        exp.mood_impact,
                        exp.desire_impact,
                        exp.salience,
                        exp.expression_status,
                        exp.related_event_hash,
                        json.dumps(exp.related_message_ids, ensure_ascii=False),
                        exp.related_intent_id,
                        json.dumps(exp.metadata, ensure_ascii=False),
                        created_at,
                    ),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return self._find_duplicate_id(exp, created_at)

    def _find_duplicate_id(self, exp: InnerExperienceIn, created_at: str) -> int | None:
        if not exp.related_event_hash:
            return None

        row = db_storage.fetch_one(
            """
            SELECT id
            FROM inner_experience_log
            WHERE source = ?
              AND kind = ?
              AND related_event_hash = ?
              AND date(created_at) = date(?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (exp.source, exp.kind, exp.related_event_hash, created_at),
        )
        return None if row is None else int(row["id"])

    def _list_recent_sync(self, limit: int, status: str | None) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 200))
        fields = [
            "id",
            "trace_id",
            "source",
            "kind",
            "content",
            "mood_impact",
            "desire_impact",
            "salience",
            "expression_status",
            "related_event_hash",
            "related_message_ids",
            "related_intent_id",
            "metadata_json",
            "created_at",
        ]
        if status:
            rows = db_storage.fetch_all(
                f"""
                SELECT {", ".join(fields)}
                FROM inner_experience_log
                WHERE expression_status = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (status, bounded_limit),
            )
        else:
            rows = db_storage.fetch_all(
                f"""
                SELECT {", ".join(fields)}
                FROM inner_experience_log
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (bounded_limit,),
            )

        return [self._decode_row(row, fields) for row in rows]

    def _mark_expression_status_sync(
        self,
        experience_id: int,
        status: str,
        intent_id: int | None,
    ) -> None:
        db_storage.execute_write(
            """
            UPDATE inner_experience_log
            SET expression_status = ?,
                related_intent_id = ?
            WHERE id = ?
            """,
            (status, intent_id, experience_id),
        )

    def _decode_row(self, row: sqlite3.Row, fields: list[str]) -> dict[str, Any]:
        item = {field: row[field] for field in fields}
        item["related_message_ids"] = _decode_json_list(item.pop("related_message_ids", None))
        item["metadata"] = _decode_json_dict(item.pop("metadata_json", None))
        return item


def _decode_json_list(raw: Any) -> list[Any]:
    if raw in (None, ""):
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _decode_json_dict(raw: Any) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
