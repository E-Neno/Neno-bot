from __future__ import annotations

from pathlib import Path

import pytest

from app.services.consciousness.experience_recorder import (
    ExperienceRecorder,
    InnerExperienceIn,
)
from app.storage import db as db_storage


def _init_test_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()


def test_inner_experience_and_reflection_tables_exist(tmp_path: Path):
    _init_test_db(tmp_path)

    row = db_storage.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='inner_experience_log'"
    )
    assert row is not None

    row = db_storage.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dream_reflection_runs'"
    )
    assert row is not None

    columns = {
        row["name"]
        for row in db_storage.fetch_all("PRAGMA table_info(inner_experience_log)")
    }
    assert "related_message_ids" in columns
    assert "metadata_json" in columns


@pytest.mark.asyncio
async def test_record_and_list_recent(tmp_path: Path):
    _init_test_db(tmp_path)
    recorder = ExperienceRecorder()

    exp_id = await recorder.record(InnerExperienceIn(
        trace_id="t1",
        source="brain_judge",
        kind="unspoken_thought",
        content="暂时没说出口的想法",
        related_event_hash="evt1",
    ))

    assert exp_id is not None
    rows = await recorder.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["id"] == exp_id
    assert rows[0]["content"] == "暂时没说出口的想法"
    assert rows[0]["expression_status"] == "unspoken"


@pytest.mark.asyncio
async def test_record_dedupes_same_event_same_day(tmp_path: Path):
    _init_test_db(tmp_path)
    recorder = ExperienceRecorder()
    exp = InnerExperienceIn(
        trace_id="t1",
        source="brain_judge",
        kind="unspoken_thought",
        content="same",
        related_event_hash="evt_dup",
    )

    first = await recorder.record(exp)
    second = await recorder.record(exp)

    rows = await recorder.list_recent(limit=10)
    assert first is not None
    assert second in (None, first)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_mark_expression_status(tmp_path: Path):
    _init_test_db(tmp_path)
    recorder = ExperienceRecorder()
    exp_id = await recorder.record(InnerExperienceIn(
        trace_id="t1",
        source="life_loop",
        kind="impulse",
        content="想说点什么",
    ))

    await recorder.mark_expression_status(exp_id, "pending_expression", intent_id=12)
    rows = await recorder.list_recent(limit=10)

    assert rows[0]["expression_status"] == "pending_expression"
    assert rows[0]["related_intent_id"] == 12


@pytest.mark.asyncio
async def test_record_user_message_batch_metadata(tmp_path: Path):
    _init_test_db(tmp_path)
    recorder = ExperienceRecorder()

    exp_id = await recorder.record(InnerExperienceIn(
        trace_id="t_batch",
        source="user_interaction",
        kind="message_batch",
        content="用户连续发来 3 条消息",
        related_message_ids=[101, 102, 103],
        metadata={
            "tempo": "rapid_burst",
            "message_types": ["text", "text", "text"],
            "user_message_batch": {
                "source_count": 3,
                "aggregated_text": "三条消息的合并文本",
            },
        },
    ))

    rows = await recorder.list_recent(limit=10)
    assert exp_id is not None
    assert rows[0]["related_message_ids"] == [101, 102, 103]
    assert rows[0]["metadata"]["tempo"] == "rapid_burst"
    assert rows[0]["metadata"]["user_message_batch"]["source_count"] == 3


@pytest.mark.asyncio
async def test_list_recent_filters_status_and_orders_newest_first(tmp_path: Path):
    _init_test_db(tmp_path)
    recorder = ExperienceRecorder()

    first = await recorder.record(InnerExperienceIn(
        trace_id="t1",
        source="life_loop",
        kind="state_shift",
        content="older",
        expression_status="suppressed",
    ))
    second = await recorder.record(InnerExperienceIn(
        trace_id="t2",
        source="life_loop",
        kind="state_shift",
        content="newer",
        expression_status="unspoken",
    ))

    rows = await recorder.list_recent(limit=10, status="unspoken")
    assert [row["id"] for row in rows] == [second]
    assert rows[0]["content"] == "newer"

    all_rows = await recorder.list_recent(limit=10)
    assert [row["id"] for row in all_rows] == [second, first]


@pytest.mark.asyncio
async def test_record_clamps_salience(tmp_path: Path):
    _init_test_db(tmp_path)
    recorder = ExperienceRecorder()

    await recorder.record(InnerExperienceIn(
        trace_id="t1",
        source="life_loop",
        kind="state_shift",
        content="salient",
        salience=4.2,
    ))

    rows = await recorder.list_recent(limit=10)
    assert rows[0]["salience"] == 1.0
