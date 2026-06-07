from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.storage import db as db_storage
from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.state_store import StateStore
from app.services.consciousness.experience_recorder import ExperienceRecorder
from app.services.consciousness.memory_recall import MemoryRecall
from app.services.consciousness.reflection_engine import ReflectionEngine
from app.services.consciousness.activity_episode_store import ActivityEpisodeStore
from app.services.consciousness.world_store import WorldStore
from app.services.consciousness.world_model import load_world_def
from app.services.consciousness.daily_planner import DailyPlanner
from app.services.consciousness.day_cycle import DayCycle


def _init_test_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()


async def _drain(store) -> None:
    """让 StateStore 的单写者协程把队列清空后再读回。

    submit_mutation/read 内部不让出事件循环，若 submit 后立即 stop()，
    writer 可能从未被调度（stop 先置 _started=False），导致 queue.join() 永久阻塞。
    生产代码中 tick 间有其他 await 自然让出；测试里需显式排空。
    """
    for _ in range(200):
        if store._queue.empty():
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)


def _insert_episode(activity_key, label, started_at):
    now = datetime.now(timezone.utc).isoformat()
    db_storage.execute_write(
        """INSERT INTO life_activity_episodes
           (trace_id, activity_key, activity_label, place, time_phase, status,
            started_at, updated_at, ended_at, reason, continuity_note,
            source_residue_json, routine_key, metadata_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("t", activity_key, label, "living_room", "afternoon", "ended",
         started_at, now, now, "", "", "{}", "", "{}"),
    )


def test_phase_of_boundaries():
    dc = DayCycle(ConsciousnessConfig())
    assert dc.phase_of(7) == "morning"
    assert dc.phase_of(13) == "afternoon"
    assert dc.phase_of(19) == "evening"
    assert dc.phase_of(2) == "night"
    assert dc.phase_of(23) == "night"


def test_check_sleep_wake_transitions():
    dc = DayCycle(ConsciousnessConfig())

    class _N:
        class energy:
            value = 10.0
            status = "awake"

    # 夜间 + 低精力 + 醒着 → 入睡
    assert dc.check_sleep_wake(_N, "night", 23) == "fall_asleep"

    class _S:
        class energy:
            value = 90.0
            status = "sleeping"

    # 早晨 + 睡着 → 醒来
    assert dc.check_sleep_wake(_S, "morning", 7) == "wake_up"

    class _A:
        class energy:
            value = 80.0
            status = "awake"

    assert dc.check_sleep_wake(_A, "afternoon", 14) is None


@pytest.mark.asyncio
async def test_on_sleep_sets_sleeping(tmp_path: Path):
    _init_test_db(tmp_path)
    store = StateStore(db=None, config=ConsciousnessConfig())
    await store.start()
    try:
        dc = DayCycle(ConsciousnessConfig())
        await dc.on_sleep(store)
        await _drain(store)
        st = await store.read()
        assert st.energy.status == "sleeping"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_on_wake_reflects_plans_and_carries_over(tmp_path: Path):
    _init_test_db(tmp_path)
    cfg = ConsciousnessConfig(reflection_enabled=True, world_planner_enabled=False)
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        wd = load_world_def()
        world_store = WorldStore(wd)
        planner = DailyPlanner(wd, cfg)
        engine = ReflectionEngine(
            state_store=store,
            recorder=ExperienceRecorder(),
            recall=MemoryRecall(db=None, config=cfg),
            config=cfg,
            episode_store=ActivityEpisodeStore(),
        )

        # 昨天：同一活动出现 2 次 → 触发反思写长期记忆
        yesterday = date(2026, 6, 6)
        y_iso = datetime(2026, 6, 6, 6, 0, tzinfo=timezone(timedelta(hours=8)))
        _insert_episode("reading", "阅读", y_iso.isoformat())
        _insert_episode("reading", "阅读", (y_iso + timedelta(hours=3)).isoformat())

        # 昨天的计划，有一项未完成
        ws = await world_store.read()
        ws.daily_plan = {
            "date": "2026-06-06",
            "items": [
                {"phase": "morning", "intent": "把那本书读完", "done": False},
                {"phase": "evening", "intent": "早点睡", "done": True},
            ],
            "carried_over": [],
        }
        await world_store.write(ws)

        ltm_before = db_storage.fetch_all("SELECT id FROM long_term_memory")
        runs_before = db_storage.fetch_all("SELECT id FROM dream_reflection_runs")

        dc = DayCycle(cfg)
        await dc.on_wake(
            store, engine, world_store, planner,
            today="2026-06-07", yesterday=yesterday,
        )
        await _drain(store)

        # 反思跑过、写了长期记忆
        runs_after = db_storage.fetch_all("SELECT id FROM dream_reflection_runs")
        ltm_after = db_storage.fetch_all("SELECT id FROM long_term_memory")
        assert len(runs_after) == len(runs_before) + 1
        assert len(ltm_after) > len(ltm_before)

        # 新计划生成，未完成项被带过来
        ws2 = await world_store.read()
        assert ws2.daily_plan is not None
        assert ws2.daily_plan["date"] == "2026-06-07"
        assert "把那本书读完" in ws2.daily_plan["carried_over"]

        # 醒来 → 精力恢复 awake
        st = await store.read()
        assert st.energy.status == "awake"
        assert st.energy.value >= 90.0
    finally:
        await store.stop()
