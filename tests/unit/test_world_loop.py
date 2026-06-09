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


import time


# ── Fake brain（替身，记录 decide 调用次数）──

class _FakeBrain:
    """记录 decide() 被调用的次数，返回固定结果。"""

    def __init__(self):
        self.call_count = 0

    async def decide(self, *args, **kwargs):
        self.call_count += 1
        from types import SimpleNamespace
        return SimpleNamespace(
            action="test_action", reasoning="test_reason",
            micro_event="test_micro", world_ops=[],
        )


@pytest.mark.asyncio
async def test_pressure_gate_low_pressure_uses_routine(tmp_path: Path):
    """压力未到阈值且非 hard -> brain 未被调用（走 routine），pressure 累积上升。"""
    _init_db(tmp_path)
    cfg = ConsciousnessConfig(
        world_llm_enabled=True,
        world_pressure_threshold=99999.0,
        world_boredom_drip=1.0,
    )
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        brain = _FakeBrain()
        loop = WorldLoop(store, cfg)
        loop._brain = brain
        snap = await loop.tick()
        await _drain(store)

        assert brain.call_count == 0
        ws = await WorldStore(load_world_def()).read()
        assert ws.pressure_value > 0
        assert ws.last_tick.get("wake") is False
        assert ws.last_tick.get("wake_reason") == "accumulating"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pressure_gate_threshold_triggers_brain(tmp_path: Path):
    """压力到阈值 -> brain 被调用恰好 1 次，pressure 被清零。"""
    _init_db(tmp_path)
    cfg = ConsciousnessConfig(
        world_llm_enabled=True,
        world_pressure_threshold=0.1,
        world_boredom_drip=1.0,
        world_wake_min_gap_seconds=0.0,
    )
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        brain = _FakeBrain()
        loop = WorldLoop(store, cfg)
        loop._brain = brain
        snap = await loop.tick()
        await _drain(store)

        assert brain.call_count == 1
        ws = await WorldStore(load_world_def()).read()
        assert ws.pressure_value == 0.0
        assert ws.last_tick.get("wake") is True
        assert ws.last_tick.get("wake_reason") == "threshold"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pressure_gate_min_gap_blocks_second_wake(tmp_path: Path):
    """min_gap 内连续两 tick -> 第二次不调 brain。"""
    _init_db(tmp_path)
    cfg = ConsciousnessConfig(
        world_llm_enabled=True,
        world_pressure_threshold=0.1,
        world_boredom_drip=1.0,
        world_wake_min_gap_seconds=9999.0,
    )
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        brain = _FakeBrain()
        loop = WorldLoop(store, cfg)
        loop._brain = brain

        await loop.tick()
        await _drain(store)
        assert brain.call_count == 1

        await loop.tick()
        await _drain(store)
        assert brain.call_count == 1
        ws = await WorldStore(load_world_def()).read()
        assert ws.last_tick.get("wake_reason") == "min_gap"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pressure_gate_llm_disabled_never_calls_brain(tmp_path: Path):
    """world_llm_enabled=False 时，无论压力多高，brain 永不被调用。"""
    _init_db(tmp_path)
    cfg = ConsciousnessConfig(
        world_llm_enabled=False,
        world_pressure_threshold=0.0,
        world_boredom_drip=999.0,
    )
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        brain = _FakeBrain()
        loop = WorldLoop(store, cfg)
        loop._brain = brain

        await loop.tick()
        await _drain(store)

        assert brain.call_count == 0
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pressure_state_roundtrip(tmp_path: Path):
    """tick 后 WorldStore 读回的 ws 含 pressure_* 字段，值正确。"""
    _init_db(tmp_path)
    cfg = ConsciousnessConfig(
        world_llm_enabled=True,
        world_pressure_threshold=99999.0,
        world_boredom_drip=5.0,
    )
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        brain = _FakeBrain()
        loop = WorldLoop(store, cfg)
        loop._brain = brain
        await loop.tick()
        await _drain(store)

        ws = await WorldStore(load_world_def()).read()
        assert ws.pressure_value > 0.0
        assert ws.pressure_wakes_this_hour == 0
        assert ws.pressure_hour_anchor is None
        assert "pressure" in ws.last_tick
        assert "wake" in ws.last_tick
        assert "wake_reason" in ws.last_tick
    finally:
        await store.stop()


# ── ① 滑行接续测试 ──

@pytest.mark.asyncio
async def test_glide_continues_reading_action(tmp_path: Path):
    """LLM 开、未唤醒、last_tick.action="读书" → 滑行：action 仍为"读书"，brain 未调用。"""
    _init_db(tmp_path)
    cfg = ConsciousnessConfig(
        world_llm_enabled=True,
        world_pressure_threshold=99999.0,
        world_boredom_drip=1.0,
    )
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        # 预设 last_tick = "读书"（模拟上一拍 LLM 真想选了读书）
        wstore = WorldStore(load_world_def())
        ws = await wstore.read()
        ws.last_tick = {
            "action": "读书", "reasoning": "沉浸在书里", "drift": [],
            "ops": [], "micro": None, "event": None, "sleeping": False,
            "phase": "下午", "real_time": "14:00",
            "wake": True, "wake_reason": "threshold", "pressure": 0.0,
        }
        await wstore.write(ws)

        brain = _FakeBrain()
        loop = WorldLoop(store, cfg)
        loop._world_store = wstore
        loop._brain = brain

        snap = await loop.tick()
        await _drain(store)

        assert snap["last"]["action"] == "读书"
        assert brain.call_count == 0  # 没调 LLM
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_glide_falls_back_on_transient_action(tmp_path: Path):
    """LLM 开、未唤醒、last_tick.action="去厨房"（瞬态）→ 回退 routine_decide。"""
    _init_db(tmp_path)
    cfg = ConsciousnessConfig(
        world_llm_enabled=True,
        world_pressure_threshold=99999.0,
        world_boredom_drip=1.0,
    )
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        wstore = WorldStore(load_world_def())
        ws = await wstore.read()
        # 放到厨房，让 routine_decide 走厨房分支（烧水/去客厅）
        ws.location = "kitchen"
        ws.last_tick = {
            "action": "去厨房", "reasoning": "想喝点热的", "drift": [],
            "ops": [], "micro": None, "event": None, "sleeping": False,
            "phase": "上午", "real_time": "09:00",
            "wake": False, "wake_reason": "accumulating", "pressure": 0.0,
        }
        await wstore.write(ws)

        brain = _FakeBrain()
        loop = WorldLoop(store, cfg)
        loop._world_store = wstore
        loop._brain = brain

        # 固定到 14:00 UTC+8 避免 sleep/wake 转换干扰
        fake_now = datetime(2026, 6, 8, 14, 0, 0, tzinfo=_TZ8)
        with patch("app.services.consciousness.world_loop.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            snap = await loop.tick()
        await _drain(store)

        # 去厨房是瞬态 → 回退 routine_decide → 在厨房会选"烧水"或"去客厅"
        assert snap["last"]["action"] in {"烧水", "去客厅"}
        assert brain.call_count == 0
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_llm_disabled_still_uses_routine_every_tick(tmp_path: Path):
    """world_llm_enabled=False → 每拍 routine_decide，回归测试（行为不变）。"""
    _init_db(tmp_path)
    cfg = ConsciousnessConfig(world_llm_enabled=False)
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        brain = _FakeBrain()
        loop = WorldLoop(store, cfg)
        loop._brain = brain

        snap1 = await loop.tick()
        await _drain(store)
        snap2 = await loop.tick()
        await _drain(store)

        # LLM 关 → brain 永不被调用
        assert brain.call_count == 0
        # 每拍都有 action（routine_decide 总会返回一个）
        assert snap1["last"]["action"]
        assert snap2["last"]["action"]
    finally:
        await store.stop()


# ── ② 精力重调测试 ──

@pytest.mark.asyncio
async def test_energy_uses_config_drop_per_tick(tmp_path: Path):
    """tick 后精力下降量 == cfg.world_energy_drop_per_tick（不再是硬编码 3.0）。"""
    _init_db(tmp_path)
    custom_drop = 0.07
    cfg = ConsciousnessConfig(
        world_llm_enabled=False,
        world_energy_drop_per_tick=custom_drop,
    )
    store = StateStore(db=None, config=cfg)
    await store.start()
    try:
        before = await store.read()
        e0 = before.energy.value

        loop = WorldLoop(store, cfg)
        await loop.tick()
        await _drain(store)

        after = await store.read()
        actual_drop = e0 - after.energy.value
        assert abs(actual_drop - custom_drop) < 0.001, f"expected drop={custom_drop}, got {actual_drop}"
    finally:
        await store.stop()
