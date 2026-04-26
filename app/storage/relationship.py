from typing import Any

from app.storage.db import get_conn

RELATIONSHIP_FIELDS = [
    "session_id",
    "stage",
    "conversation_count",
    "familiarity_score",
    "trust_score",
    "emotional_depth_score",
    "boundary_score",
    "created_at",
    "updated_at",
]

UPDATABLE_FIELDS = {
    "stage",
    "conversation_count",
    "familiarity_score",
    "trust_score",
    "emotional_depth_score",
    "boundary_score",
}


def _row_to_dict(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {field: row[field] for field in RELATIONSHIP_FIELDS}


def init_relationship_tables():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS relationship_state (
                session_id TEXT PRIMARY KEY,
                stage INTEGER DEFAULT 0,
                conversation_count INTEGER DEFAULT 0,
                familiarity_score INTEGER DEFAULT 0,
                trust_score INTEGER DEFAULT 0,
                emotional_depth_score INTEGER DEFAULT 0,
                boundary_score INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def get_relationship_state(session_id: str) -> dict[str, Any] | None:
    init_relationship_tables()
    with get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT {", ".join(RELATIONSHIP_FIELDS)}
            FROM relationship_state
            WHERE session_id = ?
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    return _row_to_dict(row)


def ensure_relationship_state(session_id: str) -> dict[str, Any]:
    init_relationship_tables()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO relationship_state (session_id)
            VALUES (?)
            """,
            (session_id,),
        )
        row = conn.execute(
            f"""
            SELECT {", ".join(RELATIONSHIP_FIELDS)}
            FROM relationship_state
            WHERE session_id = ?
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    state = _row_to_dict(row)
    if state is None:
        raise RuntimeError("failed to initialize relationship_state")
    return state


def update_relationship_state(session_id: str, updates: dict) -> dict[str, Any]:
    ensure_relationship_state(session_id)
    cleaned = {
        key: value
        for key, value in updates.items()
        if key in UPDATABLE_FIELDS and value is not None
    }
    if not cleaned:
        return ensure_relationship_state(session_id)

    assignments = [f"{key} = ?" for key in cleaned]
    assignments.append("updated_at = CURRENT_TIMESTAMP")
    params = list(cleaned.values()) + [session_id]

    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE relationship_state
            SET {", ".join(assignments)}
            WHERE session_id = ?
            """,
            tuple(params),
        )
        row = conn.execute(
            f"""
            SELECT {", ".join(RELATIONSHIP_FIELDS)}
            FROM relationship_state
            WHERE session_id = ?
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()

    state = _row_to_dict(row)
    if state is None:
        raise RuntimeError("failed to update relationship_state")
    return state


def update_relationship_state_manual(session_id: str, updates: dict) -> dict[str, Any]:
    return update_relationship_state(session_id, updates)


def reset_relationship_state(session_id: str) -> dict[str, Any]:
    init_relationship_tables()
    with get_conn() as conn:
        conn.execute(
            """
            DELETE FROM relationship_state
            WHERE session_id = ?
            """,
            (session_id,),
        )
        conn.execute(
            """
            INSERT INTO relationship_state (session_id)
            VALUES (?)
            """,
            (session_id,),
        )
        row = conn.execute(
            f"""
            SELECT {", ".join(RELATIONSHIP_FIELDS)}
            FROM relationship_state
            WHERE session_id = ?
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()

    state = _row_to_dict(row)
    if state is None:
        raise RuntimeError("failed to reset relationship_state")
    return state
