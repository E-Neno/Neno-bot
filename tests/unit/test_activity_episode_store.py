from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.storage import db as db_storage


def _init_test_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()


def _store():
    from app.services.consciousness.activity_episode_store import ActivityEpisodeStore

    return ActivityEpisodeStore()


async def _start_episode(store, **overrides):
    values = {
        "trace_id": "trace-episode",
        "activity_key": "quiet_reading",
        "activity_label": "安静读书",
        "place": "home_desk",
        "time_phase": "evening",
        "reason": "想把注意力收回来",
        "continuity_note": "接着下午没读完的部分",
        "source_residue": {"topic": "unfinished_book", "intensity": 0.6},
        "routine_key": "evening_reading",
        "metadata": {"book": "The Dispossessed", "page": 42},
        "started_at": "2026-06-06T10:00:00+00:00",
    }
    values.update(overrides)
    return await store.start_episode(**values)


def test_life_activity_episodes_table_and_indexes_exist(tmp_path: Path):
    _init_test_db(tmp_path)

    table = db_storage.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='life_activity_episodes'"
    )
    assert table is not None

    columns = {
        row["name"]
        for row in db_storage.fetch_all("PRAGMA table_info(life_activity_episodes)")
    }
    assert {
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
    } <= columns

    indexes = {
        row["name"]
        for row in db_storage.fetch_all("PRAGMA index_list(life_activity_episodes)")
    }
    assert "idx_life_episode_status_updated" in indexes
    assert "idx_life_episode_started" in indexes


@pytest.mark.asyncio
async def test_start_episode_and_get_active_roundtrip_json(tmp_path: Path):
    _init_test_db(tmp_path)
    store = _store()

    episode_id = await _start_episode(store)
    active = await store.get_active_episode()

    assert active is not None
    assert active["id"] == episode_id
    assert active["status"] == "active"
    assert active["activity_key"] == "quiet_reading"
    assert active["source_residue"] == {
        "topic": "unfinished_book",
        "intensity": 0.6,
    }
    assert active["metadata"] == {
        "book": "The Dispossessed",
        "page": 42,
    }


@pytest.mark.asyncio
async def test_start_episode_interrupts_existing_active_episode(tmp_path: Path):
    _init_test_db(tmp_path)
    store = _store()
    first_id = await _start_episode(
        store,
        activity_key="morning_walk",
        started_at="2026-06-06T01:00:00+00:00",
    )

    second_id = await _start_episode(
        store,
        activity_key="desk_work",
        started_at="2026-06-06T02:00:00+00:00",
    )

    rows = await store.list_recent()
    first = next(row for row in rows if row["id"] == first_id)
    active_rows = [row for row in rows if row["status"] == "active"]
    assert first["status"] == "interrupted"
    assert first["ended_at"] == "2026-06-06T02:00:00+00:00"
    assert first["updated_at"] == "2026-06-06T02:00:00+00:00"
    assert first["reason"] == "system_replaced_by_new_episode"
    assert [row["id"] for row in active_rows] == [second_id]


@pytest.mark.asyncio
async def test_get_active_episode_returns_none_when_missing(tmp_path: Path):
    _init_test_db(tmp_path)

    assert await _store().get_active_episode() is None


@pytest.mark.asyncio
async def test_continue_episode_updates_active_episode(tmp_path: Path):
    _init_test_db(tmp_path)
    store = _store()
    episode_id = await _start_episode(store)

    updated = await store.continue_episode(
        episode_id,
        place="window_seat",
        time_phase="late_evening",
        continuity_note="读完一章后继续整理标记",
        source_residue={"topic": "unfinished_book", "intensity": 0.3},
        metadata={"book": "The Dispossessed", "page": 58},
    )

    assert updated is not None
    assert updated["id"] == episode_id
    assert updated["status"] == "active"
    assert updated["place"] == "window_seat"
    assert updated["time_phase"] == "late_evening"
    assert updated["continuity_note"] == "读完一章后继续整理标记"
    assert updated["source_residue"]["intensity"] == 0.3
    assert updated["metadata"]["page"] == 58


@pytest.mark.asyncio
async def test_update_episode_updates_active_episode(tmp_path: Path):
    _init_test_db(tmp_path)
    store = _store()
    episode_id = await _start_episode(store)

    updated = await store.update_episode(
        episode_id,
        activity_label="读完后整理摘记",
        reason="阅读自然过渡到整理",
    )

    assert updated is not None
    assert updated["activity_label"] == "读完后整理摘记"
    assert updated["reason"] == "阅读自然过渡到整理"


@pytest.mark.asyncio
async def test_end_episode_clears_active_episode(tmp_path: Path):
    _init_test_db(tmp_path)
    store = _store()
    episode_id = await _start_episode(store)

    ended = await store.end_episode(
        episode_id,
        reason="读完计划中的章节",
        ended_at="2026-06-06T11:00:00+00:00",
    )

    assert ended is not None
    assert ended["status"] == "ended"
    assert ended["reason"] == "读完计划中的章节"
    assert ended["ended_at"] == "2026-06-06T11:00:00+00:00"
    assert await store.get_active_episode() is None
    assert await store.continue_episode(episode_id, place="bed") is None


@pytest.mark.asyncio
async def test_interrupt_episode_records_interruption(tmp_path: Path):
    _init_test_db(tmp_path)
    store = _store()
    episode_id = await _start_episode(store)

    interrupted = await store.interrupt_episode(
        episode_id,
        reason="能量下降，需要休息",
        ended_at="2026-06-06T10:30:00+00:00",
    )

    assert interrupted is not None
    assert interrupted["status"] == "interrupted"
    assert interrupted["reason"] == "能量下降，需要休息"
    assert interrupted["ended_at"] == "2026-06-06T10:30:00+00:00"
    assert await store.get_active_episode() is None


@pytest.mark.asyncio
async def test_replace_active_episode_ends_old_and_creates_new_atomically(
    tmp_path: Path,
):
    _init_test_db(tmp_path)
    store = _store()
    old_id = await _start_episode(store)

    new_id = await store.replace_active_episode(
        old_id,
        previous_status="ended",
        trace_id="trace-transition",
        activity_key="memory_processing",
        activity_label="Process a lingering memory",
        place="window_desk",
        time_phase="evening",
        reason="target activity changed",
        continuity_note="continue with the unfinished memory",
        metadata={"decision_action": "transition"},
        replaced_at="2026-06-06T10:30:00+00:00",
    )

    rows = await store.list_recent()
    old = next(row for row in rows if row["id"] == old_id)
    active = await store.get_active_episode()
    assert active is not None
    assert new_id == active["id"]
    assert old["status"] == "ended"
    assert old["ended_at"] == "2026-06-06T10:30:00+00:00"
    assert active["activity_key"] == "memory_processing"
    assert active["metadata"]["decision_action"] == "transition"


@pytest.mark.asyncio
async def test_replace_active_episode_interrupts_old_and_creates_new_atomically(
    tmp_path: Path,
):
    _init_test_db(tmp_path)
    store = _store()
    old_id = await _start_episode(store)

    new_id = await store.replace_active_episode(
        old_id,
        previous_status="interrupted",
        trace_id="trace-interrupt",
        activity_key="quiet_rest",
        activity_label="Rest quietly",
        place="rest_corner",
        time_phase="evening",
        reason="recovery takes priority",
        continuity_note="pause the previous activity",
        metadata={"decision_action": "interrupt"},
        replaced_at="2026-06-06T10:45:00+00:00",
    )

    rows = await store.list_recent()
    old = next(row for row in rows if row["id"] == old_id)
    active = await store.get_active_episode()
    assert active is not None
    assert new_id == active["id"]
    assert old["status"] == "interrupted"
    assert old["ended_at"] == "2026-06-06T10:45:00+00:00"
    assert active["activity_key"] == "quiet_rest"
    assert active["place"] == "rest_corner"


@pytest.mark.asyncio
async def test_replace_active_episode_rolls_back_when_insert_fails(tmp_path: Path):
    _init_test_db(tmp_path)
    store = _store()
    old_id = await _start_episode(store)
    with db_storage.get_conn() as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_replacement_insert
            BEFORE INSERT ON life_activity_episodes
            WHEN NEW.activity_key = 'force_insert_failure'
            BEGIN
                SELECT RAISE(ABORT, 'forced insert failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced insert failure"):
        await store.replace_active_episode(
            old_id,
            previous_status="ended",
            activity_key="force_insert_failure",
            activity_label="Should not persist",
            place="nowhere",
            time_phase="evening",
            reason="force rollback",
            replaced_at="2026-06-06T11:00:00+00:00",
        )

    active = await store.get_active_episode()
    rows = await store.list_recent()
    assert active is not None
    assert active["id"] == old_id
    assert active["status"] == "active"
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_list_recent_episodes_orders_newest_first_and_limits(tmp_path: Path):
    _init_test_db(tmp_path)
    store = _store()

    first_id = await _start_episode(
        store,
        activity_key="morning_walk",
        activity_label="晨间散步",
        started_at="2026-06-06T01:00:00+00:00",
    )
    await store.end_episode(first_id, ended_at="2026-06-06T01:30:00+00:00")
    second_id = await _start_episode(
        store,
        activity_key="desk_work",
        activity_label="桌前整理",
        started_at="2026-06-06T03:00:00+00:00",
    )
    await store.end_episode(second_id, ended_at="2026-06-06T04:00:00+00:00")
    third_id = await _start_episode(
        store,
        activity_key="quiet_rest",
        activity_label="安静休息",
        started_at="2026-06-06T05:00:00+00:00",
    )

    rows = await store.list_recent(limit=2)

    assert [row["id"] for row in rows] == [third_id, second_id]


@pytest.mark.asyncio
async def test_list_for_day_excludes_episodes_outside_utc_plus_8_day(tmp_path: Path):
    _init_test_db(tmp_path)
    store = _store()
    before_id = await _start_episode(
        store,
        activity_key="before_day",
        started_at="2026-06-05T15:59:59+00:00",
    )
    inside_id = await _start_episode(
        store,
        activity_key="inside_day",
        started_at="2026-06-05T16:00:00+00:00",
    )
    after_id = await _start_episode(
        store,
        activity_key="after_day",
        started_at="2026-06-06T16:00:00+00:00",
    )

    rows = await store.list_for_day("2026-06-06")

    assert [row["id"] for row in rows] == [inside_id]
    assert before_id not in [row["id"] for row in rows]
    assert after_id not in [row["id"] for row in rows]


@pytest.mark.asyncio
async def test_list_for_day_orders_timeline_oldest_first(tmp_path: Path):
    _init_test_db(tmp_path)
    store = _store()
    later_id = await _start_episode(
        store,
        activity_key="later",
        started_at="2026-06-06T09:00:00+00:00",
    )
    earlier_id = await _start_episode(
        store,
        activity_key="earlier",
        started_at="2026-06-06T01:00:00+00:00",
    )

    rows = await store.list_for_day("2026-06-06", timezone_offset="+08:00")

    assert [row["id"] for row in rows] == [earlier_id, later_id]


@pytest.mark.asyncio
async def test_list_for_day_returns_empty_list_when_no_episodes(tmp_path: Path):
    _init_test_db(tmp_path)

    assert await _store().list_for_day("2026-06-06") == []


@pytest.mark.asyncio
async def test_bad_json_decodes_to_empty_objects(tmp_path: Path):
    _init_test_db(tmp_path)
    with db_storage.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO life_activity_episodes (
                trace_id, activity_key, activity_label, place, time_phase,
                status, started_at, updated_at, source_residue_json, metadata_json
            )
            VALUES (
                'bad-json', 'idle', '停一停', 'home', 'night',
                'active', '2026-06-06T06:00:00+00:00',
                '2026-06-06T06:00:00+00:00', '{bad', 'not-json'
            )
            """
        )

    active = await _store().get_active_episode()

    assert active is not None
    assert active["source_residue"] == {}
    assert active["metadata"] == {}
