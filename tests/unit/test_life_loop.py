from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.experience_recorder import ExperienceRecorder
from app.services.consciousness.life_loop import LifeLoop
from app.services.consciousness.models import EnergyState, StateMutation
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
