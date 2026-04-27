import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

DB_DIR = Path("data")
DB_PATH = DB_DIR / "bot.db"


@contextmanager
def get_conn():
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def fetch_all(query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(query, tuple(params)).fetchall()


def fetch_one(query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(query, tuple(params)).fetchone()


def execute_write(query: str, params: Iterable[Any] = ()) -> int:
    with get_conn() as conn:
        cursor = conn.execute(query, tuple(params))
        return cursor.rowcount


def rows_to_dicts(rows: list[sqlite3.Row], fields: list[str]) -> list[dict]:
    return [{field: row[field] for field in fields} for row in rows]


def row_to_dict(row: sqlite3.Row | None, fields: list[str]) -> dict | None:
    if row is None:
        return None
    return {field: row[field] for field in fields}


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                memory_type TEXT DEFAULT 'general',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                source TEXT,
                platform TEXT,
                session_id TEXT,
                session_id_hash TEXT,
                message_len INTEGER,
                reply_len INTEGER,
                success INTEGER,
                latency_ms INTEGER,
                error_type TEXT,
                model TEXT
            )
            """
        )
        chat_stats_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(chat_stats)").fetchall()
        }
        if "session_id" not in chat_stats_columns:
            conn.execute("ALTER TABLE chat_stats ADD COLUMN session_id TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS proactive_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                platform TEXT,
                target_hash TEXT,
                target_label TEXT,
                message TEXT,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                source TEXT DEFAULT 'manual',
                metadata_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS proactive_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                session_id TEXT NOT NULL,
                target_hash TEXT NOT NULL,
                target_label TEXT NOT NULL,
                is_allowed INTEGER DEFAULT 0,
                last_seen_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(platform, session_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS proactive_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT,
                platform TEXT,
                target_label TEXT,
                candidate_id INTEGER,
                action TEXT,
                success INTEGER,
                skipped INTEGER,
                reason TEXT,
                metadata_json TEXT
            )
            """
        )


def add_message(session_id: str, role: str, content: str):
    execute_write(
        """
        INSERT INTO messages (session_id, role, content)
        VALUES (?, ?, ?)
        """,
        (session_id, role, content),
    )


def list_messages(session_id: str, limit: int, fields: list[str]) -> list[dict]:
    rows = fetch_all(
        f"""
        SELECT {", ".join(fields)}
        FROM messages
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (session_id, limit),
    )
    return rows_to_dicts(list(reversed(rows)), fields)


def get_recent_messages(session_id: str, limit: int = 8):
    return list_messages(session_id, limit, ["role", "content", "created_at"])


def get_session_messages(session_id: str, limit: int = 50):
    return list_messages(session_id, limit, ["id", "role", "content", "created_at"])


def add_memory(content: str, memory_type: str = "general"):
    execute_write(
        """
        INSERT INTO memories (content, memory_type)
        VALUES (?, ?)
        """,
        (content, memory_type),
    )


def list_memories(where_clause: str = "", params: Iterable[Any] = (), limit: int | None = None) -> list[dict]:
    fields = ["id", "content", "memory_type", "created_at", "is_active"]
    query = f"""
        SELECT {", ".join(fields)}
        FROM memories
        {where_clause}
        ORDER BY id DESC
    """
    if limit is not None:
        query += "\nLIMIT ?"
        params = tuple(params) + (limit,)

    rows = fetch_all(query, params)
    items = rows_to_dicts(rows, fields)
    return list(reversed(items)) if limit is not None else items


def get_active_memories(limit: int = 5):
    memories = list_memories("WHERE is_active = 1", (), limit=limit)
    return [
        {
            "id": item["id"],
            "content": item["content"],
            "memory_type": item["memory_type"],
            "created_at": item["created_at"],
        }
        for item in memories
    ]


def get_all_memories():
    return list_memories()


def get_memories_by_status(is_active: int):
    return list_memories("WHERE is_active = ?", (is_active,))


def get_memory_by_id(memory_id: int) -> dict | None:
    fields = ["id", "content", "memory_type", "created_at", "is_active"]
    row = fetch_one(
        f"""
        SELECT {", ".join(fields)}
        FROM memories
        WHERE id = ?
        LIMIT 1
        """,
        (memory_id,),
    )
    return row_to_dict(row, fields)


def update_memory(memory_id: int, content: str, memory_type: str):
    affected = execute_write(
        """
        UPDATE memories
        SET content = ?, memory_type = ?
        WHERE id = ?
        """,
        (content, memory_type, memory_id),
    )
    if affected <= 0:
        return None
    return get_memory_by_id(memory_id)


def delete_memory(memory_id: int) -> bool:
    affected = execute_write(
        """
        DELETE FROM memories
        WHERE id = ?
        """,
        (memory_id,),
    )
    return affected > 0


def set_memory_active(memory_id: int, is_active: bool) -> bool:
    affected = execute_write(
        "UPDATE memories SET is_active = ? WHERE id = ?",
        (1 if is_active else 0, memory_id),
    )
    return affected > 0


def memory_exists(content: str) -> bool:
    row = fetch_one(
        """
        SELECT 1 FROM memories
        WHERE content = ? AND is_active = 1
        LIMIT 1
        """,
        (content,),
    )
    return row is not None


def clear_session_messages(session_id: str) -> int:
    return execute_write(
        """
        DELETE FROM messages
        WHERE session_id = ?
        """,
        (session_id,),
    )


def get_sessions():
    rows = fetch_all(
        """
        SELECT
            session_id,
            COUNT(*) AS message_count,
            MAX(created_at) AS last_message_at
        FROM messages
        GROUP BY session_id
        ORDER BY last_message_at DESC
        """
    )
    return rows_to_dicts(rows, ["session_id", "message_count", "last_message_at"])


def upsert_proactive_target(
    *,
    platform: str,
    session_id: str,
    target_hash: str,
    target_label: str,
    is_allowed: bool,
    last_seen_at: str,
) -> dict:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO proactive_targets (
                platform,
                session_id,
                target_hash,
                target_label,
                is_allowed,
                last_seen_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(platform, session_id) DO UPDATE SET
                target_hash = excluded.target_hash,
                target_label = excluded.target_label,
                is_allowed = excluded.is_allowed,
                last_seen_at = excluded.last_seen_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                platform,
                session_id,
                target_hash,
                target_label,
                1 if is_allowed else 0,
                last_seen_at,
            ),
        )

    target = get_proactive_target_by_session(platform, session_id)
    if target is None:
        raise RuntimeError("proactive target upsert failed")
    return target


def _proactive_target_fields() -> list[str]:
    return [
        "id",
        "platform",
        "session_id",
        "target_hash",
        "target_label",
        "is_allowed",
        "last_seen_at",
        "created_at",
        "updated_at",
    ]


def get_proactive_target_by_session(platform: str, session_id: str) -> dict | None:
    fields = _proactive_target_fields()
    row = fetch_one(
        f"""
        SELECT {", ".join(fields)}
        FROM proactive_targets
        WHERE platform = ?
          AND session_id = ?
        LIMIT 1
        """,
        (platform, session_id),
    )
    return row_to_dict(row, fields)


def list_proactive_targets(limit: int = 20) -> list[dict]:
    fields = _proactive_target_fields()
    rows = fetch_all(
        f"""
        SELECT {", ".join(fields)}
        FROM proactive_targets
        ORDER BY last_seen_at DESC, updated_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return rows_to_dicts(rows, fields)


def get_latest_allowed_proactive_target(platform: str) -> dict | None:
    fields = _proactive_target_fields()
    row = fetch_one(
        f"""
        SELECT {", ".join(fields)}
        FROM proactive_targets
        WHERE platform = ?
          AND is_allowed = 1
          AND session_id != ''
          AND target_hash != ''
        ORDER BY last_seen_at DESC, updated_at DESC, id DESC
        LIMIT 1
        """,
        (platform,),
    )
    return row_to_dict(row, fields)


def add_proactive_event(
    *,
    event_type: str,
    platform: str | None = None,
    target_label: str | None = None,
    candidate_id: int | None = None,
    action: str | None = None,
    success: bool | None = None,
    skipped: bool | None = None,
    reason: str | None = None,
    metadata_json: str = "{}",
) -> dict:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO proactive_events (
                event_type,
                platform,
                target_label,
                candidate_id,
                action,
                success,
                skipped,
                reason,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                platform,
                target_label,
                candidate_id,
                action,
                None if success is None else 1 if success else 0,
                None if skipped is None else 1 if skipped else 0,
                reason,
                metadata_json,
            ),
        )
        event_id = cursor.lastrowid

    event = get_proactive_event(event_id)
    if event is None:
        raise RuntimeError("proactive event insert failed")
    return event


def _proactive_event_fields() -> list[str]:
    return [
        "id",
        "created_at",
        "event_type",
        "platform",
        "target_label",
        "candidate_id",
        "action",
        "success",
        "skipped",
        "reason",
        "metadata_json",
    ]


def get_proactive_event(event_id: int) -> dict | None:
    fields = _proactive_event_fields()
    row = fetch_one(
        f"""
        SELECT {", ".join(fields)}
        FROM proactive_events
        WHERE id = ?
        LIMIT 1
        """,
        (event_id,),
    )
    return row_to_dict(row, fields)


def list_proactive_events(limit: int = 50, event_type: str | None = None) -> list[dict]:
    fields = _proactive_event_fields()
    bounded_limit = max(1, min(int(limit), 200))
    where = ""
    params: tuple[Any, ...]
    if event_type:
        where = "WHERE event_type = ?"
        params = (event_type, bounded_limit)
    else:
        params = (bounded_limit,)
    rows = fetch_all(
        f"""
        SELECT {", ".join(fields)}
        FROM proactive_events
        {where}
        ORDER BY id DESC
        LIMIT ?
        """,
        params,
    )
    return rows_to_dicts(rows, fields)


def add_proactive_candidate(
    *,
    platform: str,
    target_hash: str,
    target_label: str,
    message: str,
    reason: str,
    status: str = "pending",
    source: str = "manual",
    metadata_json: str = "{}",
) -> dict:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO proactive_candidates (
                platform,
                target_hash,
                target_label,
                message,
                reason,
                status,
                source,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                platform,
                target_hash,
                target_label,
                message,
                reason,
                status,
                source,
                metadata_json,
            ),
        )
        candidate_id = cursor.lastrowid

    candidate = get_proactive_candidate(candidate_id)
    if candidate is None:
        raise RuntimeError("proactive candidate insert failed")
    return candidate


def get_proactive_candidate(candidate_id: int) -> dict | None:
    fields = [
        "id",
        "created_at",
        "platform",
        "target_hash",
        "target_label",
        "message",
        "reason",
        "status",
        "source",
        "metadata_json",
    ]
    row = fetch_one(
        f"""
        SELECT {", ".join(fields)}
        FROM proactive_candidates
        WHERE id = ?
        LIMIT 1
        """,
        (candidate_id,),
    )
    return row_to_dict(row, fields)


def list_proactive_candidates(limit: int = 20) -> list[dict]:
    fields = [
        "id",
        "created_at",
        "platform",
        "target_hash",
        "target_label",
        "message",
        "reason",
        "status",
        "source",
        "metadata_json",
    ]
    rows = fetch_all(
        f"""
        SELECT {", ".join(fields)}
        FROM proactive_candidates
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return rows_to_dicts(rows, fields)


def update_proactive_candidate_status(candidate_id: int, status: str) -> dict | None:
    affected = execute_write(
        """
        UPDATE proactive_candidates
        SET status = ?
        WHERE id = ?
        """,
        (status, candidate_id),
    )
    if affected <= 0:
        return None
    return get_proactive_candidate(candidate_id)


def update_proactive_candidate_metadata(candidate_id: int, metadata_json: str) -> dict | None:
    affected = execute_write(
        """
        UPDATE proactive_candidates
        SET metadata_json = ?
        WHERE id = ?
        """,
        (metadata_json, candidate_id),
    )
    if affected <= 0:
        return None
    return get_proactive_candidate(candidate_id)
