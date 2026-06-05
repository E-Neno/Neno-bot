from __future__ import annotations

import json

import app.storage.db as db_storage


def _get_living_world(client, admin_headers, query: str = ""):
    return client.get(
        f"/debug/consciousness/living-world{query}",
        headers=admin_headers,
    )


def _insert_state() -> None:
    state = {
        "revision": 7,
        "updated_at": "2026-06-05T01:00:00+00:00",
        "life": {
            "mode": "awake",
            "current_activity": "reading",
            "attention": "inner",
            "need": {"rest": 0.2, "connection": 0.7, "novelty": 0.4},
            "residue": {"recent_reflection": "kept a small thought"},
        },
        "energy": {"value": 64.0, "status": "awake"},
        "mood": {"valence": 0.2, "arousal": 0.3, "label": "steady"},
        "desire": {"value": 18.0, "last_express_at": None},
    }
    with db_storage.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO agent_state (id, revision, state_json, updated_at)
            VALUES (1, 7, ?, '2026-06-05T01:00:00+00:00')
            """,
            (json.dumps(state),),
        )


def _insert_experience(
    *,
    trace_id: str = "trace-exp",
    status: str = "unspoken",
    related_event_hash: str = "event-hash",
    related_message_ids: str = "[101, 102]",
    metadata_json: str = '{"origin": "test"}',
    created_at: str = "2026-06-05T01:02:00+00:00",
) -> None:
    with db_storage.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO inner_experience_log (
                trace_id, source, kind, content,
                mood_impact, desire_impact, salience,
                expression_status, related_event_hash,
                related_message_ids, related_intent_id,
                metadata_json, created_at
            )
            VALUES (?, 'brain_judge', 'unspoken_thought', 'kept this inside',
                    0.1, 0.2, 0.8, ?, ?, ?, 42, ?, ?)
            """,
            (trace_id, status, related_event_hash, related_message_ids, metadata_json, created_at),
        )


def _insert_reflection(
    *,
    output_json: str = '{"summary": "quiet reflection"}',
    created_at: str = "2026-06-05T01:03:00+00:00",
) -> None:
    with db_storage.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO dream_reflection_runs (
                trace_id, status, input_summary, output_json,
                model_name, error, created_at, completed_at
            )
            VALUES (
                'trace-reflect', 'completed', 'recent inner events', ?,
                'deterministic', NULL, ?, '2026-06-05T01:04:00+00:00'
            )
            """,
            (output_json, created_at),
        )


def _insert_memory(
    *,
    tags: str = '["reflection", "life"]',
    created_at: str = "2026-06-05T01:05:00+00:00",
) -> None:
    with db_storage.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO long_term_memory (content, tags, subject, salience, created_at)
            VALUES ('remembered a quiet pattern', ?, 'neno', 0.9, ?)
            """,
            (tags, created_at),
        )


def test_living_world_empty_returns_success(client, admin_headers):
    response = _get_living_world(client, admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["state"] is None
    assert data["experiences"] == []
    assert data["reflection_runs"] == []
    assert data["long_term_memory"] == []


def test_living_world_returns_decoded_rows(client, admin_headers):
    _insert_state()
    _insert_experience()
    _insert_reflection()
    _insert_memory()

    response = _get_living_world(client, admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["state"]["revision"] == 7
    assert data["state"]["life"]["mode"] == "awake"
    assert data["state"]["energy"]["value"] == 64.0
    assert data["experiences"][0]["trace_id"] == "trace-exp"
    assert data["experiences"][0]["related_message_ids"] == [101, 102]
    assert data["experiences"][0]["metadata"] == {"origin": "test"}
    assert data["reflection_runs"][0]["output"] == {"summary": "quiet reflection"}
    assert data["long_term_memory"][0]["tags"] == ["reflection", "life"]


def test_living_world_filters_experience_status(client, admin_headers):
    _insert_experience(trace_id="trace-unspoken", status="unspoken")
    _insert_experience(
        trace_id="trace-suppressed",
        status="suppressed",
        related_event_hash="event-hash-suppressed",
        created_at="2026-06-05T01:06:00+00:00",
    )

    response = _get_living_world(client, admin_headers, "?experience_status=suppressed")

    assert response.status_code == 200
    data = response.json()
    assert [item["trace_id"] for item in data["experiences"]] == ["trace-suppressed"]


def test_living_world_bad_json_falls_back(client, admin_headers):
    _insert_experience(related_message_ids="not-json", metadata_json="{bad")
    _insert_reflection(output_json="not-json")
    _insert_memory(tags="{bad")

    response = _get_living_world(client, admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["experiences"][0]["related_message_ids"] == []
    assert data["experiences"][0]["metadata"] == {}
    assert data["reflection_runs"][0]["output"] == {}
    assert data["long_term_memory"][0]["tags"] == []


def test_living_world_requires_admin_token(client):
    response = client.get("/debug/consciousness/living-world")

    assert response.status_code == 403
