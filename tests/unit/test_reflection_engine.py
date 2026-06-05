from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.experience_recorder import ExperienceRecorder, InnerExperienceIn
from app.services.consciousness.memory_recall import MemoryRecall
from app.services.consciousness.reflection_engine import ReflectionEngine
from app.services.consciousness.state_store import StateStore
from app.storage import db as db_storage


def _init_test_db(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()
    return data_dir


async def _fresh_store(tmp_path: Path) -> StateStore:
    _init_test_db(tmp_path)
    store = StateStore(db=None, config=ConsciousnessConfig())
    await store.start()
    return store


def _make_engine(
    *,
    store: StateStore,
    recorder: ExperienceRecorder | None = None,
    reflection_enabled: bool = True,
    reflection_model_enabled: bool = False,
) -> ReflectionEngine:
    cfg = ConsciousnessConfig(
        reflection_enabled=reflection_enabled,
        reflection_model_enabled=reflection_model_enabled,
    )
    return ReflectionEngine(
        state_store=store,
        recorder=recorder or ExperienceRecorder(),
        recall=MemoryRecall(db=None, config=cfg),
        config=cfg,
    )


@pytest.mark.asyncio
async def test_reflection_disabled_noop(tmp_path: Path):
    store = await _fresh_store(tmp_path)
    try:
        engine = _make_engine(store=store, reflection_enabled=False)

        result = await engine.run_once("trace_reflect")

        assert result["action"] == "disabled"
        rows = db_storage.fetch_all("SELECT id FROM dream_reflection_runs")
        assert rows == []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_reflection_model_disabled_no_llm_call(tmp_path: Path):
    store = await _fresh_store(tmp_path)
    try:
        engine = _make_engine(
            store=store,
            reflection_enabled=True,
            reflection_model_enabled=False,
        )

        with patch("app.services.consciousness.reflection_engine._llm_reflect") as mock_llm:
            result = await engine.run_once("trace_reflect")

        mock_llm.assert_not_called()
        assert result["action"] in {"reflected", "no_experiences"}
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_reflection_no_experiences_writes_skipped_run(tmp_path: Path):
    store = await _fresh_store(tmp_path)
    try:
        engine = _make_engine(store=store, reflection_enabled=True)

        result = await engine.run_once("trace_empty")

        rows = db_storage.fetch_all("SELECT status FROM dream_reflection_runs")
        memories = db_storage.fetch_all("SELECT id FROM long_term_memory")
        assert result["action"] == "no_experiences"
        assert [row["status"] for row in rows] == ["skipped"]
        assert memories == []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_reflection_with_experiences_writes_reflection_run(tmp_path: Path):
    store = await _fresh_store(tmp_path)
    recorder = ExperienceRecorder()
    try:
        await recorder.record(InnerExperienceIn(
            trace_id="t1",
            source="life_loop",
            kind="state_shift",
            content="Neno 安静地整理了一会儿今天的心情",
            salience=0.5,
        ))
        engine = _make_engine(store=store, recorder=recorder, reflection_enabled=True)

        result = await engine.run_once("trace_reflect")

        rows = db_storage.fetch_all(
            "SELECT status, input_summary, output_json FROM dream_reflection_runs"
        )
        assert result["action"] == "reflected"
        assert len(rows) == 1
        assert rows[0]["status"] == "completed"
        assert "Neno 安静地整理" in rows[0]["input_summary"]
        assert rows[0]["output_json"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_reflection_writes_long_term_memory_for_high_salience(tmp_path: Path):
    store = await _fresh_store(tmp_path)
    recorder = ExperienceRecorder()
    try:
        await recorder.record(InnerExperienceIn(
            trace_id="t1",
            source="life_loop",
            kind="state_shift",
            content="Neno 安静地整理了一会儿今天的心情",
            salience=0.8,
        ))
        engine = _make_engine(store=store, recorder=recorder, reflection_enabled=True)

        await engine.run_once("trace_reflect")

        rows = db_storage.fetch_all("SELECT content FROM long_term_memory")
        assert len(rows) >= 1
        assert "Neno 安静地整理" in rows[0]["content"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_reflection_feedback_updates_life_residue(tmp_path: Path):
    store = await _fresh_store(tmp_path)
    recorder = ExperienceRecorder()
    try:
        await recorder.record(InnerExperienceIn(
            trace_id="t1",
            source="life_loop",
            kind="state_shift",
            content="Neno 安静地整理了一会儿今天的心情",
            salience=0.8,
        ))
        engine = _make_engine(store=store, recorder=recorder, reflection_enabled=True)

        await engine.run_once("trace_reflect")
        await asyncio.sleep(0.2)

        state = await store.read()
        assert state.life.residue.topic == "Neno 安静地整理了一会儿今天的心情"
        assert state.life.residue.mood == "reflective"
        assert state.life.residue.intensity > 0.0
    finally:
        await store.stop()
