from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.consciousness.activity_episode_store import ActivityEpisodeStore
from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.experience_recorder import ExperienceRecorder
from app.services.consciousness.life_loop import LifeLoop
from app.services.consciousness.life_simulation import LifeSimulation
from app.services.consciousness.models import (
    EnergyState,
    LifeResidue,
    StateMutation,
)
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


def _episode_count() -> int:
    row = db_storage.fetch_one(
        "SELECT COUNT(*) AS count FROM life_activity_episodes"
    )
    return int(row["count"])


class _FailingEpisodeStore:
    async def get_active_episode(self):
        raise RuntimeError("episode store unavailable")


class _FailingApplyEpisodeStore:
    def __init__(self, delegate: ActivityEpisodeStore, action: str):
        self._delegate = delegate
        self._action = action

    async def get_active_episode(self):
        return await self._delegate.get_active_episode()

    async def continue_episode(self, *args, **kwargs):
        if self._action == "continue":
            raise RuntimeError("forced continue failure")
        return await self._delegate.continue_episode(*args, **kwargs)

    async def replace_active_episode(self, *args, **kwargs):
        if self._action == "replace":
            raise RuntimeError("forced replacement failure")
        return await self._delegate.replace_active_episode(*args, **kwargs)

    async def start_episode(self, *args, **kwargs):
        return await self._delegate.start_episode(*args, **kwargs)


class _ForbiddenEpisodeStore:
    async def get_active_episode(self):
        raise AssertionError("disabled loop must not access episode store")


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
        assert result["micro_event_preview"] is not None
        assert result["would_record_experience"]["source"] == "life_simulation"
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
async def test_sleeping_run_once_does_not_write_state_episode_or_experience(
    tmp_path: Path,
):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        await store.submit_mutation(
            StateMutation(
                energy=EnergyState(
                    value=20,
                    status="sleeping",
                    description="sleeping",
                )
            )
        )
        await asyncio.sleep(0.2)
        before_state = await store.read()
        before_episodes = _episode_count()
        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
        )

        result = await loop.run_once("trace_sleeping")

        after_state = await store.read()
        assert result["action"] == "skipped_sleeping"
        assert result["micro_event_preview"] is None
        assert await recorder.list_recent() == []
        assert _episode_count() == before_episodes
        assert after_state == before_state
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
        assert rows[0]["source"] == "life_simulation"
        assert rows[0]["kind"] == "episode_started"
        assert rows[0]["metadata"]["life"]["current_activity"] == state.life.current_activity
        assert rows[0]["metadata"]["episode_id"] == state.life.active_episode_id
        assert {
            "daily_intent",
            "place",
            "time_phase",
            "activity_key",
            "space_key",
            "available_objects",
            "decision_action",
        } <= rows[0]["metadata"].keys()
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
        assert state.life.current_activity == "quiet_rest"
        assert state.life.daily_intent == "recover"
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
        assert life.current_activity == "quiet_rest"
        assert life.daily_intent == "recover"
        # 理由要解释“为什么在休息”——引用精力
        assert "energy" in life.activity_reason
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
        assert life.current_activity == "memory_processing"
        assert life.daily_intent == "process_memory"
        assert life.residue.topic in life.activity_reason
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
        low_life = (await low.read()).life
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
        high_life = (await high.read()).life
    finally:
        await high.stop()

    assert low_life.daily_intent != "process_memory"
    assert high_life.daily_intent == "process_memory"
    assert high_life.current_activity == "memory_processing"
    assert low_life.activity_label != high_life.activity_label


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
        assert life.current_activity == "memory_processing"
        assert life.daily_intent == "process_memory"
        assert life.residue.topic in life.activity_reason
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

        preview = plan["would_update_life"]
        assert preview["daily_intent"] == "process_memory"
        assert preview["current_activity"] == "memory_processing"
        assert preview["residue"]["topic"] in preview["activity_reason"]
        assert before_count == after_count
        assert before_rev == after_rev
    finally:
        await store.stop()


# ── C1.3 LifeLoop episode progression ─────────────────────────────────


@pytest.mark.asyncio
async def test_run_once_creates_episode_when_none_active(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        episode_store = ActivityEpisodeStore()
        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=episode_store,
        )

        result = await loop.run_once("trace_episode_create")
        await asyncio.sleep(0.2)

        active = await episode_store.get_active_episode()
        state = await store.read()
        assert result["episode_decision"]["action"] == "create"
        assert active is not None
        assert state.life.active_episode_id == active["id"]
        assert state.life.daily_intent == result["episode_decision"]["intent"]["key"]
        assert state.life.current_activity == active["activity_key"]
        assert state.life.activity_label == active["activity_label"]
        assert state.life.activity_reason == active["reason"]
        assert state.life.continuity_note == active["continuity_note"]
        assert state.life.place == active["place"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_run_once_continues_same_episode_when_conditions_stable(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        episode_store = ActivityEpisodeStore()
        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=episode_store,
        )

        await loop.run_once("trace_episode_first")
        first = await episode_store.get_active_episode()
        result = await loop.run_once("trace_episode_continue")
        second = await episode_store.get_active_episode()

        assert first is not None and second is not None
        assert result["episode_decision"]["action"] == "continue"
        assert second["id"] == first["id"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_run_once_transitions_episode_when_conditions_change(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        episode_store = ActivityEpisodeStore()
        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=episode_store,
        )
        await loop.run_once("trace_before_transition")
        old = await episode_store.get_active_episode()
        await store.submit_mutation(
            StateMutation(
                life_residue=LifeResidue(
                    topic="unfinished memory",
                    mood="quiet",
                    intensity=0.9,
                )
            )
        )
        await asyncio.sleep(0.2)

        result = await loop.run_once("trace_transition")
        rows = await episode_store.list_recent()
        new = await episode_store.get_active_episode()

        assert old is not None and new is not None
        assert result["episode_decision"]["action"] == "transition"
        assert new["activity_key"] == "memory_processing"
        assert new["id"] != old["id"]
        old_row = next(row for row in rows if row["id"] == old["id"])
        assert old_row["status"] == "ended"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_run_once_interrupts_episode_for_low_energy(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        episode_store = ActivityEpisodeStore()
        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=episode_store,
        )
        await loop.run_once("trace_before_interrupt")
        old = await episode_store.get_active_episode()
        await store.submit_mutation(
            StateMutation(
                energy=EnergyState(value=15, status="awake", description="low")
            )
        )
        await asyncio.sleep(0.2)

        result = await loop.run_once("trace_interrupt")
        rows = await episode_store.list_recent()
        new = await episode_store.get_active_episode()

        assert old is not None and new is not None
        assert result["episode_decision"]["action"] == "interrupt"
        assert new["activity_key"] == "quiet_rest"
        old_row = next(row for row in rows if row["id"] == old["id"])
        assert old_row["status"] == "interrupted"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_dry_run_previews_episode_without_writes(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=ActivityEpisodeStore(),
        )
        before_state = await store.read()
        before_experiences = len(await recorder.list_recent())
        before_episodes = _episode_count()

        result = await loop.dry_run("trace_episode_dry")

        after_state = await store.read()
        decision = result["episode_decision"]
        preview = result["would_update_life"]
        assert result["episode_decision"]["action"] == "create"
        assert result["micro_event_preview"] is not None
        assert result["micro_event_preview"]["kind"] == "episode_started"
        assert preview["current_activity"] == decision["activity_key"]
        assert preview["activity_label"] == decision["activity_label"]
        assert preview["activity_reason"] == decision["reason"]
        assert preview["continuity_note"] == decision["continuity_note"]
        assert preview["place"] == decision["space"]["place"]
        assert preview["active_episode_id"] is None
        assert preview["daily_intent"] == decision["intent"]["key"]
        assert _episode_count() == before_episodes
        assert len(await recorder.list_recent()) == before_experiences
        assert after_state.revision == before_state.revision
        assert after_state.life == before_state.life
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_disabled_run_once_does_not_access_episode_store(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        loop = LifeLoop(
            store,
            ExperienceRecorder(),
            ConsciousnessConfig(life_loop_enabled=False),
            simulation=LifeSimulation(),
            episode_store=_ForbiddenEpisodeStore(),
        )

        result = await loop.run_once("trace_disabled_episode")

        assert result["action"] == "disabled"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_episode_store_failure_degrades_without_crashing(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        loop = LifeLoop(
            store,
            ExperienceRecorder(),
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=_FailingEpisodeStore(),
        )

        before_life = (await store.read()).life
        result = await loop.run_once("trace_episode_failure")
        await asyncio.sleep(0.2)

        final_life = (await store.read()).life
        experiences = await ExperienceRecorder().list_recent()
        assert result["success"] is True
        assert result["action"] == "updated"
        assert "episode_error" in result
        assert final_life == before_life
        assert experiences[0]["source"] == "life_loop"
        assert experiences[0]["kind"] == "episode_apply_failed"
        assert "failed" in experiences[0]["content"].lower()
        assert experiences[0]["metadata"]["life"] == final_life.model_dump()
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_transition_failure_keeps_old_episode_and_life_state(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        episode_store = ActivityEpisodeStore()
        initial_loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=episode_store,
        )
        await initial_loop.run_once("trace_transition_initial")
        old_episode = await episode_store.get_active_episode()
        await store.submit_mutation(
            StateMutation(
                life_residue=LifeResidue(
                    topic="failed transition memory",
                    mood="quiet",
                    intensity=0.9,
                )
            )
        )
        await asyncio.sleep(0.2)
        previous_intent = (await store.read()).life.daily_intent

        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=_FailingApplyEpisodeStore(episode_store, "replace"),
        )
        result = await loop.run_once("trace_transition_failure")
        await asyncio.sleep(0.2)

        active = await episode_store.get_active_episode()
        life = (await store.read()).life
        experiences = await recorder.list_recent()
        assert old_episode is not None and active is not None
        assert result["episode_decision"]["action"] == "transition"
        assert "episode_error" in result
        assert active["id"] == old_episode["id"]
        assert life.active_episode_id == active["id"]
        assert life.current_activity == active["activity_key"]
        assert life.activity_label == active["activity_label"]
        assert life.place == active["place"]
        assert life.activity_reason == active["reason"]
        assert life.continuity_note == active["continuity_note"]
        assert life.daily_intent == previous_intent
        assert experiences[0]["metadata"]["life"] == life.model_dump()
        assert experiences[0]["metadata"]["attempted_decision"]["action"] == "transition"
        assert experiences[0]["source"] == "life_loop"
        assert experiences[0]["kind"] == "episode_apply_failed"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_interrupt_failure_keeps_old_episode_and_life_state(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        episode_store = ActivityEpisodeStore()
        initial_loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=episode_store,
        )
        await initial_loop.run_once("trace_interrupt_initial")
        old_episode = await episode_store.get_active_episode()
        await store.submit_mutation(
            StateMutation(
                energy=EnergyState(value=15, status="awake", description="low")
            )
        )
        await asyncio.sleep(0.2)
        previous_intent = (await store.read()).life.daily_intent

        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=_FailingApplyEpisodeStore(episode_store, "replace"),
        )
        result = await loop.run_once("trace_interrupt_failure")
        await asyncio.sleep(0.2)

        active = await episode_store.get_active_episode()
        life = (await store.read()).life
        assert old_episode is not None and active is not None
        assert result["episode_decision"]["action"] == "interrupt"
        assert "episode_error" in result
        assert active["id"] == old_episode["id"]
        assert life.active_episode_id == active["id"]
        assert life.current_activity == active["activity_key"]
        assert life.activity_label == active["activity_label"]
        assert life.place == active["place"]
        assert life.activity_reason == active["reason"]
        assert life.continuity_note == active["continuity_note"]
        assert life.daily_intent == previous_intent
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_continue_failure_keeps_current_episode_state(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        episode_store = ActivityEpisodeStore()
        initial_loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=episode_store,
        )
        await initial_loop.run_once("trace_continue_initial")
        old_episode = await episode_store.get_active_episode()
        previous_intent = (await store.read()).life.daily_intent

        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=_FailingApplyEpisodeStore(episode_store, "continue"),
        )
        result = await loop.run_once("trace_continue_failure")
        await asyncio.sleep(0.2)

        active = await episode_store.get_active_episode()
        life = (await store.read()).life
        assert old_episode is not None and active is not None
        assert result["episode_decision"]["action"] == "continue"
        assert "episode_error" in result
        assert active["id"] == old_episode["id"]
        assert life.active_episode_id == active["id"]
        assert life.current_activity == active["activity_key"]
        assert life.activity_label == active["activity_label"]
        assert life.place == active["place"]
        assert life.activity_reason == active["reason"]
        assert life.continuity_note == active["continuity_note"]
        assert life.daily_intent == previous_intent
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_episode_tick_records_at_most_one_experience(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=ActivityEpisodeStore(),
        )
        before = len(await recorder.list_recent())

        await loop.run_once("trace_single_experience")

        after = len(await recorder.list_recent())
        assert after - before == 1
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_stable_continue_does_not_add_experience(tmp_path: Path):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=ActivityEpisodeStore(),
        )
        await loop.run_once("trace_create_event")
        before = len(await recorder.list_recent())

        result = await loop.run_once("trace_stable_continue")

        after = len(await recorder.list_recent())
        assert result["episode_decision"]["action"] == "continue"
        assert result["experience_id"] is None
        assert after == before
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_life_simulation_experience_is_not_treated_as_unspoken_thought(
    tmp_path: Path,
):
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        loop = LifeLoop(
            store,
            recorder,
            ConsciousnessConfig(life_loop_enabled=True),
            simulation=LifeSimulation(),
            episode_store=ActivityEpisodeStore(),
        )

        await loop.run_once("trace_micro_event")
        await loop.run_once("trace_after_micro_event")
        life = (await store.read()).life

        assert life.mode != "absorbed"
        assert life.current_activity != "carrying_unspoken_thought"
    finally:
        await store.stop()
