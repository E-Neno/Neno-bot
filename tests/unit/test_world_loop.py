from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from unittest.mock import patch
from datetime import datetime, timezone, timedelta

from app.storage import db as db_storage
from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.state_store import StateStore
from app.services.consciousness.world_store import WorldStore
from app.services.consciousness.world_loop import WorldLoop, build_snapshot
from app.services.consciousness.world_model import load_world_def, seed_world_state


def _init_db(tmp_path: Path) -> None:
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    db_storage.DB_DIR = d
    db_storage.DB_PATH = d / "bot.db"
    db_storage.init_db()


async def _drain(store) -> None:
    for _ in range(200):
        if store._queue.empty():
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)


class _FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, func, trigger, **kw):
        self.jobs.append({"trigger": trigger, **kw})


def test_register_jobs_disabled_does_not_add(tmp_path: Path):
    _init_db(tmp_path)
    store = StateStore(db=None, config=ConsciousnessConfig())
    loop = WorldLoop(store, ConsciousnessConfig(world_loop_enabled=False))
    sched = _FakeScheduler()
    assert loop.register_jobs(sched) is False
    assert sched.jobs == []


def test_register_jobs_enabled_adds_tick(tmp_path: Path):
    _init_db(tmp_path)
    store = StateStore(db=None, config=ConsciousnessConfig())
    loop = WorldLoop(store, ConsciousnessConfig(world_loop_enabled=True))
    sched = _FakeScheduler()
    assert loop.register_jobs(sched) is True
    assert any(j.get("id") == "world_loop_tick" for j in sched.jobs)


def test_build_snapshot_shape():
    wd = load_world_def()
    st = seed_world_state(wd)
    snap = build_snapshot(wd, st, None)
    assert "rooms" in snap and "money" in snap and "plan" in snap
    assert snap["money"] == 120


@pytest.mark.asyncio
async def test_tick_advances_world_and_drops_energy(tmp_path: Path):
    _init_db(tmp_path)
    cfg = ConsciousnessConfig(world_llm_enabled=False)  # mock 决策，不调模型
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        before = await store.read()
        e0 = before.energy.value

        loop = WorldLoop(store, cfg)
        snap = await loop.tick()
        await _drain(store)

        # 快照含关键字段
        assert "rooms" in snap and "last" in snap

        # 世界被推进并落库
        ws = await WorldStore(load_world_def()).read()
        assert ws.sim_minutes > 0
        assert ws.last_tick is not None
        assert ws.last_tick.get("action")

        # 精力下降
        after = await store.read()
        assert after.energy.value < e0
    finally:
        await store.stop()


_TZ8 = timezone(timedelta(hours=8))


@pytest.mark.asyncio
async def test_tick_uses_real_utc8_time(tmp_path: Path):
    """tick 后 sim_minutes 应等于真实 UTC+8 时间的当天分钟数。"""
    _init_db(tmp_path)
    cfg = ConsciousnessConfig(world_llm_enabled=False)
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        # 固定到 14:37 UTC+8
        fake_now = datetime(2026, 6, 8, 14, 37, 0, tzinfo=_TZ8)
        with patch("app.services.consciousness.world_loop.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            loop = WorldLoop(store, cfg)
            snap = await loop.tick()
        await _drain(store)

        ws = await WorldStore(load_world_def()).read()
        assert ws.sim_minutes == 14 * 60 + 37
        assert ws.last_tick["real_time"] == "14:37"
    finally:
        await store.stop()
