from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.storage import db as db_storage


EPISODE_FIELDS = [
    "id",
    "trace_id",
    "activity_key",
    "activity_label",
    "place",
    "time_phase",
    "status",
    "started_at",
    "updated_at",
    "ended_at",
    "reason",
    "continuity_note",
    "source_residue_json",
    "routine_key",
    "metadata_json",
]

SYSTEM_REPLACED_REASON = "system_replaced_by_new_episode"
DEFAULT_TIMEZONE_OFFSET = "+08:00"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_json_dict(raw: Any) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _parse_timezone_offset(value: str) -> timezone:
    parsed = datetime.strptime(value, "%z")
    offset = parsed.utcoffset()
    if offset is None:
        raise ValueError(f"Invalid timezone offset: {value}")
    return timezone(offset)


class ActivityEpisodeStore:
    async def start_episode(
        self,
        *,
        activity_key: str,
        activity_label: str,
        place: str,
        time_phase: str,
        trace_id: str | None = None,
        reason: str = "",
        continuity_note: str = "",
        source_residue: dict[str, Any] | None = None,
        routine_key: str = "",
        metadata: dict[str, Any] | None = None,
        started_at: str | None = None,
    ) -> int:
        return await asyncio.to_thread(
            self._start_episode_sync,
            activity_key=activity_key,
            activity_label=activity_label,
            place=place,
            time_phase=time_phase,
            trace_id=trace_id,
            reason=reason,
            continuity_note=continuity_note,
            source_residue=source_residue,
            routine_key=routine_key,
            metadata=metadata,
            started_at=started_at,
        )

    async def get_active_episode(self) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_active_episode_sync)

    async def continue_episode(
        self,
        episode_id: int,
        *,
        activity_label: str | None = None,
        place: str | None = None,
        time_phase: str | None = None,
        reason: str | None = None,
        continuity_note: str | None = None,
        source_residue: dict[str, Any] | None = None,
        routine_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self._continue_episode_sync,
            episode_id,
            activity_label=activity_label,
            place=place,
            time_phase=time_phase,
            reason=reason,
            continuity_note=continuity_note,
            source_residue=source_residue,
            routine_key=routine_key,
            metadata=metadata,
        )

    async def update_episode(
        self,
        episode_id: int,
        *,
        activity_label: str | None = None,
        place: str | None = None,
        time_phase: str | None = None,
        reason: str | None = None,
        continuity_note: str | None = None,
        source_residue: dict[str, Any] | None = None,
        routine_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return await self.continue_episode(
            episode_id,
            activity_label=activity_label,
            place=place,
            time_phase=time_phase,
            reason=reason,
            continuity_note=continuity_note,
            source_residue=source_residue,
            routine_key=routine_key,
            metadata=metadata,
        )

    async def end_episode(
        self,
        episode_id: int,
        *,
        reason: str | None = None,
        ended_at: str | None = None,
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self._finish_episode_sync,
            episode_id,
            status="ended",
            reason=reason,
            ended_at=ended_at,
        )

    async def interrupt_episode(
        self,
        episode_id: int,
        *,
        reason: str | None = None,
        ended_at: str | None = None,
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self._finish_episode_sync,
            episode_id,
            status="interrupted",
            reason=reason,
            ended_at=ended_at,
        )

    async def replace_active_episode(
        self,
        episode_id: int,
        *,
        previous_status: str,
        activity_key: str,
        activity_label: str,
        place: str,
        time_phase: str,
        trace_id: str | None = None,
        reason: str = "",
        continuity_note: str = "",
        source_residue: dict[str, Any] | None = None,
        routine_key: str = "",
        metadata: dict[str, Any] | None = None,
        replaced_at: str | None = None,
    ) -> int:
        return await asyncio.to_thread(
            self._replace_active_episode_sync,
            episode_id,
            previous_status=previous_status,
            activity_key=activity_key,
            activity_label=activity_label,
            place=place,
            time_phase=time_phase,
            trace_id=trace_id,
            reason=reason,
            continuity_note=continuity_note,
            source_residue=source_residue,
            routine_key=routine_key,
            metadata=metadata,
            replaced_at=replaced_at,
        )

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_recent_sync, limit)

    async def list_for_day(
        self,
        day: date | str,
        timezone_offset: str = DEFAULT_TIMEZONE_OFFSET,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._list_for_day_sync,
            day,
            timezone_offset,
        )

    def _start_episode_sync(
        self,
        *,
        activity_key: str,
        activity_label: str,
        place: str,
        time_phase: str,
        trace_id: str | None,
        reason: str,
        continuity_note: str,
        source_residue: dict[str, Any] | None,
        routine_key: str,
        metadata: dict[str, Any] | None,
        started_at: str | None,
    ) -> int:
        timestamp = started_at or _utcnow_iso()
        with db_storage.get_conn() as conn:
            conn.execute(
                """
                UPDATE life_activity_episodes
                SET status = 'interrupted',
                    ended_at = ?,
                    updated_at = ?,
                    reason = ?
                WHERE status = 'active'
                """,
                (timestamp, timestamp, SYSTEM_REPLACED_REASON),
            )
            cursor = conn.execute(
                """
                INSERT INTO life_activity_episodes (
                    trace_id,
                    activity_key,
                    activity_label,
                    place,
                    time_phase,
                    status,
                    started_at,
                    updated_at,
                    reason,
                    continuity_note,
                    source_residue_json,
                    routine_key,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    activity_key,
                    activity_label,
                    place,
                    time_phase,
                    timestamp,
                    timestamp,
                    reason,
                    continuity_note,
                    json.dumps(source_residue or {}, ensure_ascii=False),
                    routine_key,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def _get_active_episode_sync(self) -> dict[str, Any] | None:
        row = db_storage.fetch_one(
            f"""
            SELECT {", ".join(EPISODE_FIELDS)}
            FROM life_activity_episodes
            WHERE status = 'active'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """
        )
        return self._decode_row(row)

    def _replace_active_episode_sync(
        self,
        episode_id: int,
        *,
        previous_status: str,
        activity_key: str,
        activity_label: str,
        place: str,
        time_phase: str,
        trace_id: str | None,
        reason: str,
        continuity_note: str,
        source_residue: dict[str, Any] | None,
        routine_key: str,
        metadata: dict[str, Any] | None,
        replaced_at: str | None,
    ) -> int:
        if previous_status not in {"ended", "interrupted"}:
            raise ValueError("previous_status must be 'ended' or 'interrupted'")

        timestamp = replaced_at or _utcnow_iso()
        with db_storage.get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE life_activity_episodes
                SET status = ?,
                    ended_at = ?,
                    updated_at = ?,
                    reason = ?
                WHERE id = ? AND status = 'active'
                """,
                (
                    previous_status,
                    timestamp,
                    timestamp,
                    reason,
                    episode_id,
                ),
            )
            if cursor.rowcount <= 0:
                raise RuntimeError("active episode disappeared before replacement")

            inserted = conn.execute(
                """
                INSERT INTO life_activity_episodes (
                    trace_id,
                    activity_key,
                    activity_label,
                    place,
                    time_phase,
                    status,
                    started_at,
                    updated_at,
                    reason,
                    continuity_note,
                    source_residue_json,
                    routine_key,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    activity_key,
                    activity_label,
                    place,
                    time_phase,
                    timestamp,
                    timestamp,
                    reason,
                    continuity_note,
                    json.dumps(source_residue or {}, ensure_ascii=False),
                    routine_key,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            return int(inserted.lastrowid)

    def _continue_episode_sync(
        self,
        episode_id: int,
        *,
        activity_label: str | None,
        place: str | None,
        time_phase: str | None,
        reason: str | None,
        continuity_note: str | None,
        source_residue: dict[str, Any] | None,
        routine_key: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [_utcnow_iso()]
        for column, value in (
            ("activity_label", activity_label),
            ("place", place),
            ("time_phase", time_phase),
            ("reason", reason),
            ("continuity_note", continuity_note),
            ("routine_key", routine_key),
        ):
            if value is not None:
                updates.append(f"{column} = ?")
                params.append(value)
        if source_residue is not None:
            updates.append("source_residue_json = ?")
            params.append(json.dumps(source_residue, ensure_ascii=False))
        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(json.dumps(metadata, ensure_ascii=False))

        params.append(episode_id)
        affected = db_storage.execute_write(
            f"""
            UPDATE life_activity_episodes
            SET {", ".join(updates)}
            WHERE id = ? AND status = 'active'
            """,
            tuple(params),
        )
        if affected <= 0:
            return None
        return self._get_episode_sync(episode_id)

    def _finish_episode_sync(
        self,
        episode_id: int,
        *,
        status: str,
        reason: str | None,
        ended_at: str | None,
    ) -> dict[str, Any] | None:
        timestamp = ended_at or _utcnow_iso()
        if reason is None:
            affected = db_storage.execute_write(
                """
                UPDATE life_activity_episodes
                SET status = ?, ended_at = ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (status, timestamp, timestamp, episode_id),
            )
        else:
            affected = db_storage.execute_write(
                """
                UPDATE life_activity_episodes
                SET status = ?, ended_at = ?, updated_at = ?, reason = ?
                WHERE id = ? AND status = 'active'
                """,
                (status, timestamp, timestamp, reason, episode_id),
            )
        if affected <= 0:
            return None
        return self._get_episode_sync(episode_id)

    def _list_recent_sync(self, limit: int) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 200))
        rows = db_storage.fetch_all(
            f"""
            SELECT {", ".join(EPISODE_FIELDS)}
            FROM life_activity_episodes
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (bounded_limit,),
        )
        return [self._decode_row(row) for row in rows if row is not None]

    def _list_for_day_sync(
        self,
        day: date | str,
        timezone_offset: str,
    ) -> list[dict[str, Any]]:
        target_day = date.fromisoformat(day) if isinstance(day, str) else day
        local_timezone = _parse_timezone_offset(timezone_offset)
        day_start = datetime.combine(target_day, time.min, local_timezone)
        next_day_start = day_start + timedelta(days=1)
        rows = db_storage.fetch_all(
            f"""
            SELECT {", ".join(EPISODE_FIELDS)}
            FROM life_activity_episodes
            WHERE julianday(started_at) >= julianday(?)
              AND julianday(started_at) < julianday(?)
            ORDER BY julianday(started_at) ASC, id ASC
            """,
            (
                day_start.astimezone(timezone.utc).isoformat(),
                next_day_start.astimezone(timezone.utc).isoformat(),
            ),
        )
        return [self._decode_row(row) for row in rows if row is not None]

    def _get_episode_sync(self, episode_id: int) -> dict[str, Any] | None:
        row = db_storage.fetch_one(
            f"""
            SELECT {", ".join(EPISODE_FIELDS)}
            FROM life_activity_episodes
            WHERE id = ?
            LIMIT 1
            """,
            (episode_id,),
        )
        return self._decode_row(row)

    @staticmethod
    def _decode_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = {field: row[field] for field in EPISODE_FIELDS}
        item["source_residue"] = _decode_json_dict(
            item.pop("source_residue_json", None)
        )
        item["metadata"] = _decode_json_dict(item.pop("metadata_json", None))
        return item
