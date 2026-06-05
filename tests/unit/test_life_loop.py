from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.experience_recorder import ExperienceRecorder
from app.services.consciousness.life_loop import LifeLoop
from app.services.consciousness.models import EnergyState, LifeResidue, StateMutation
from app.services.consciousness.state_store import StateStore
from app.storage import db as db_storage


def _init_test_db(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()
    return data_dir


def _fresh_store(tmp_path: Path) -> StateStore:
    _init_test_db(tmp_path)
    return StateStore(db=None, config=ConsciousnessConfig())


def test_living_world_flags_default_disabled(monkeypatch):
    for key in [
        "CONSCIOUSNESS_LIFE_LOOP_ENABLED",
        "CONSCIOUSNESS_REFLECTION_ENABLED",
        "CONSCIOUSNESS_REFLECTION_MODEL_ENABLED",
        "CONSCIOUSNESS_EXPRESSION_GATE_ENABLED",
    ]:
        monkeypatch.delenv(key, raising=False)

    cfg = ConsciousnessConfig()

    assert cfg.life_loop_enabled is False
    assert cfg.reflection_enabled is False
    assert cfg.reflection_model_enabled is False
    assert cfg.expression_gate_enabled is False


@pytest.mark.asyncio
async def test_life_loop_dry_run_does_not_write(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        loop = LifeLoop(store, recorder, ConsciousnessConfig())
        before = len(await recorder.list_recent())

        result = await loop.dry_run("trace_life")

        after = len(await recorder.list_recent())
        assert result["success"] is True
        assert result["would_record_experience"]["source"] == "life_loop"
        assert before == after
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_life_loop_disabled_noop(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        cfg = ConsciousnessConfig(life_loop_enabled=False)
        loop = LifeLoop(store, recorder, cfg)

        result = await loop.run_once("trace_life")

        assert result["action"] == "disabled"
        assert await recorder.list_recent() == []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_life_loop_enabled_records_experience_and_updates_state(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        cfg = ConsciousnessConfig(life_loop_enabled=True)
        loop = LifeLoop(store, recorder, cfg)

        result = await loop.run_once("trace_life")
        await asyncio.sleep(0.2)

        rows = await recorder.list_recent()
        state = await store.read()
        assert result["action"] == "updated"
        assert len(rows) == 1
        assert rows[0]["trace_id"] == "trace_life"
        assert rows[0]["source"] == "life_loop"
        assert rows[0]["kind"] == "state_shift"
        assert rows[0]["metadata"]["life"]["current_activity"] == state.life.current_activity
        assert state.life.current_activity in {
            "quiet_observing",
            "thinking_of_user",
            "low_energy_resting",
            "carrying_unspoken_thought",
        }
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_life_loop_low_energy_moves_to_resting(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        await store.submit_mutation(
            StateMutation(
                energy=EnergyState(
                    value=20.0,
                    status="awake",
                    description="低能量",
                )
            )
        )
        await asyncio.sleep(0.2)
        loop = LifeLoop(store, recorder, ConsciousnessConfig(life_loop_enabled=True))

        result = await loop.run_once("trace_low_energy")
        await asyncio.sleep(0.2)

        state = await store.read()
        assert result["action"] == "updated"
        assert state.life.mode == "resting"
        assert state.life.attention == "self"
        assert state.life.current_activity == "low_energy_resting"
    finally:
        await store.stop()


# ── B1.2 LifeLoop 生活化推进 ─────────────────────────────────


@pytest.mark.asyncio
async def test_run_once_writes_living_world_rich_fields(tmp_path: Path):
    """enabled run_once 写入带生活语义的 LifeState 富字段，而非停留在 B1.1 默认值。"""
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        loop = LifeLoop(store, recorder, ConsciousnessConfig(life_loop_enabled=True))

        result = await loop.run_once("trace_rich")
        await asyncio.sleep(0.2)

        state = await store.read()
        life = state.life
        assert result["action"] == "updated"
        # time_phase 必须由时钟推算，不再是模型默认 "unknown"
        assert life.time_phase and life.time_phase != "unknown"
        assert life.place
        # environment / activity_label 必须被循环改写，不再是 B1.1 裸默认
        assert life.environment.summary and life.environment.summary != "安静的房间"
        assert life.activity_label and life.activity_label != "安静观察"
        assert life.activity_reason
        # continuity_note 必须引用上一次状态，不是空字符串
        assert life.continuity_note
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_low_energy_resting_has_life_semantics(tmp_path: Path):
    """low energy/resting 分支也要有合理的 activity_label/activity_reason/environment。"""
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        await store.submit_mutation(
            StateMutation(energy=EnergyState(value=20.0, status="awake", description="低能量"))
        )
        await asyncio.sleep(0.2)
        loop = LifeLoop(store, recorder, ConsciousnessConfig(life_loop_enabled=True))

        await loop.run_once("trace_rest")
        await asyncio.sleep(0.2)

        life = (await store.read()).life
        assert life.mode == "resting"
        assert life.current_activity == "low_energy_resting"
        # 理由要解释“为什么在休息”——引用精力
        assert "精力" in life.activity_reason
        assert life.activity_label and life.activity_label != "安静观察"
        assert life.environment.summary and life.environment.summary != "安静的房间"
        assert life.time_phase and life.time_phase != "unknown"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_continuity_note_references_residue(tmp_path: Path):
    """continuity_note 必须引用 life_residue 的话题，不是空洞占位。"""
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        await store.submit_mutation(
            StateMutation(
                life_residue=LifeResidue(topic="下午没说完的事", mood="soft", intensity=0.4)
            )
        )
        await asyncio.sleep(0.2)
        loop = LifeLoop(store, recorder, ConsciousnessConfig(life_loop_enabled=True))

        await loop.run_once("trace_resi")
        await asyncio.sleep(0.2)

        life = (await store.read()).life
        assert "下午没说完的事" in life.continuity_note
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_continuity_note_references_previous_activity(tmp_path: Path):
    """无 residue 时，continuity_note 引用上一次的 activity_label。"""
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        loop = LifeLoop(store, recorder, ConsciousnessConfig(life_loop_enabled=True))

        await loop.run_once("trace_a")
        await asyncio.sleep(0.2)
        prev_label = (await store.read()).life.activity_label

        await loop.run_once("trace_b")
        await asyncio.sleep(0.2)
        life = (await store.read()).life

        assert prev_label
        assert prev_label in life.continuity_note
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_dry_run_builds_rich_life_without_writing(tmp_path: Path):
    """dry_run 产出富字段计划，但仍只读：不写经历、不推进 revision。"""
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        loop = LifeLoop(store, recorder, ConsciousnessConfig(life_loop_enabled=True))

        before_rev = (await store.read()).revision
        before_count = len(await recorder.list_recent())

        plan = await loop.dry_run("trace_dry")

        after_rev = (await store.read()).revision
        after_count = len(await recorder.list_recent())

        assert plan["would_update_life"]["time_phase"] != "unknown"
        assert plan["would_update_life"]["environment"]["summary"] != "安静的房间"
        assert before_count == after_count
        assert before_rev == after_rev
    finally:
        await store.stop()


# ── B1.3 Reflection residue 影响下一次 LifeLoop ───────────────


@pytest.mark.asyncio
async def test_residue_changes_next_life_progression(tmp_path: Path):
    """高强度 life_residue 改变下一次推进：activity_label/activity_reason/attention 引用 residue。"""
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        await store.submit_mutation(
            StateMutation(
                life_residue=LifeResidue(topic="那场没下完的雨", mood="低落", intensity=0.8)
            )
        )
        await asyncio.sleep(0.2)
        loop = LifeLoop(store, recorder, ConsciousnessConfig(life_loop_enabled=True))

        await loop.run_once("trace_resi_high")
        await asyncio.sleep(0.2)

        life = (await store.read()).life
        assert "那场没下完的雨" in life.activity_label
        assert ("那场没下完的雨" in life.activity_reason) or ("低落" in life.activity_reason)
        assert life.attention == "memory"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_high_intensity_residue_has_stronger_effect(tmp_path: Path):
    """高强度 residue 改变活动标签；低强度只作为 continuity，不改活动标签。"""
    # 低强度（独立 DB）
    (tmp_path / "low").mkdir()
    low = _fresh_store(tmp_path / "low")
    await low.start()
    try:
        await low.submit_mutation(
            StateMutation(life_residue=LifeResidue(topic="同一件小事", mood="平", intensity=0.2))
        )
        await asyncio.sleep(0.2)
        loop_low = LifeLoop(low, ExperienceRecorder(), ConsciousnessConfig(life_loop_enabled=True))
        await loop_low.run_once("t_low")
        await asyncio.sleep(0.2)
        low_label = (await low.read()).life.activity_label
    finally:
        await low.stop()

    # 高强度（独立 DB）
    (tmp_path / "high").mkdir()
    high = _fresh_store(tmp_path / "high")
    await high.start()
    try:
        await high.submit_mutation(
            StateMutation(life_residue=LifeResidue(topic="同一件小事", mood="平", intensity=0.8))
        )
        await asyncio.sleep(0.2)
        loop_high = LifeLoop(high, ExperienceRecorder(), ConsciousnessConfig(life_loop_enabled=True))
        await loop_high.run_once("t_high")
        await asyncio.sleep(0.2)
        high_label = (await high.read()).life.activity_label
    finally:
        await high.stop()

    assert "同一件小事" not in low_label
    assert "同一件小事" in high_label
    assert low_label != high_label


@pytest.mark.asyncio
async def test_residue_effect_survives_self_state_shift(tmp_path: Path):
    """第二轮 tick 时，residue 影响不被 life_loop 自己上一轮 state_shift 的 unspoken 记录盖住。"""
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        await store.submit_mutation(
            StateMutation(
                life_residue=LifeResidue(topic="搁着的那句话", mood="闷", intensity=0.8)
            )
        )
        await asyncio.sleep(0.2)
        loop = LifeLoop(store, recorder, ConsciousnessConfig(life_loop_enabled=True))

        await loop.run_once("t1")
        await asyncio.sleep(0.2)
        await loop.run_once("t2")
        await asyncio.sleep(0.2)

        life = (await store.read()).life
        assert "搁着的那句话" in life.activity_label
        assert life.current_activity != "carrying_unspoken_thought"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_self_state_shift_does_not_force_absorbed(tmp_path: Path):
    """无 residue 时，life_loop 自己上一轮的 state_shift(unspoken) 不应把第二轮强行推进成 absorbed。"""
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        loop = LifeLoop(store, recorder, ConsciousnessConfig(life_loop_enabled=True))

        await loop.run_once("t1")
        await asyncio.sleep(0.2)
        await loop.run_once("t2")
        await asyncio.sleep(0.2)

        life = (await store.read()).life
        assert life.mode != "absorbed"
        assert life.current_activity == "quiet_observing"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_dry_run_previews_residue_effect_without_writing(tmp_path: Path):
    """dry_run 能预览 residue 影响，但不写经历、不推进 revision。"""
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        await store.submit_mutation(
            StateMutation(life_residue=LifeResidue(topic="预览用的事", mood="淡", intensity=0.8))
        )
        await asyncio.sleep(0.2)
        loop = LifeLoop(store, recorder, ConsciousnessConfig(life_loop_enabled=True))

        before_rev = (await store.read()).revision
        before_count = len(await recorder.list_recent())

        plan = await loop.dry_run("t_dry")

        after_rev = (await store.read()).revision
        after_count = len(await recorder.list_recent())

        assert "预览用的事" in plan["would_update_life"]["activity_label"]
        assert before_count == after_count
        assert before_rev == after_rev
    finally:
        await store.stop()
