from pathlib import Path

from app.services.executive_store import (
    list_queued_executive_commands,
    mark_executive_commands_consumed,
    record_executive_command_error,
    record_executive_decision,
)


def _init_db(tmp_path: Path) -> None:
    import app.storage.db as db_storage

    data_dir = tmp_path / "data"
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()


def test_record_decision_queues_each_world_intent_transactionally(tmp_path: Path):
    import app.storage.db as db_storage

    _init_db(tmp_path)
    decision_id = record_executive_decision(
        trace_id="trace-1",
        session_id="session-1",
        trigger_type="chat",
        action="reply_now",
        depth="deep",
        decision={"action": "reply_now", "world_intents": ["去阳台缓一会儿"]},
        world_intents=["去阳台缓一会儿", "把这件事记在心上"],
    )

    decision = db_storage.fetch_one(
        "SELECT action, depth FROM executive_decisions WHERE id = ?",
        (decision_id,),
    )
    commands = list_queued_executive_commands(limit=10)

    assert decision["action"] == "reply_now"
    assert decision["depth"] == "deep"
    assert [item["payload"]["intent"] for item in commands] == [
        "去阳台缓一会儿",
        "把这件事记在心上",
    ]
    assert all(item["decision_id"] == decision_id for item in commands)


def test_command_status_only_changes_when_explicitly_consumed(tmp_path: Path):
    _init_db(tmp_path)
    record_executive_decision(
        trace_id="trace-2",
        session_id="session-2",
        trigger_type="chat",
        action="reply_now",
        depth="shallow",
        decision={"action": "reply_now"},
        world_intents=["去厨房倒杯水"],
    )
    command = list_queued_executive_commands(limit=1)[0]

    record_executive_command_error([command["id"]], "world brain fallback")
    still_queued = list_queued_executive_commands(limit=1)[0]
    assert still_queued["status"] == "queued"
    assert still_queued["error"] == "world brain fallback"

    mark_executive_commands_consumed([command["id"]])
    assert list_queued_executive_commands(limit=10) == []

