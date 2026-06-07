from __future__ import annotations

import asyncio
import json
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.consciousness.activity_episode_store import ActivityEpisodeStore
from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.experience_recorder import ExperienceRecorder, InnerExperienceIn
from app.services.consciousness.memory_recall import MemoryRecall
from app.services.consciousness.reflection_engine import ReflectionEngine
from app.services.consciousness.state_store import StateStore
from app.storage import db as db_storage

_TZ_8 = timezone(timedelta(hours=8))


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


def _make_engine_with_episodes(
    *,
    store: StateStore,
    recorder: ExperienceRecorder | None = None,
    episode_store: ActivityEpisodeStore | None = None,
    reflection_enabled: bool = True,
) -> ReflectionEngine:
    """Make engine wired with optional episode_store (C1.5)."""
    cfg = ConsciousnessConfig(
        reflection_enabled=reflection_enabled,
        reflection_model_enabled=False,
    )
    return ReflectionEngine(
        state_store=store,
        recorder=recorder or ExperienceRecorder(),
        recall=MemoryRecall(db=None, config=cfg),
        config=cfg,
        episode_store=episode_store,
    )


def _insert_episode(
    activity_key: str,
    activity_label: str,
    *,
    place: str = "quiet_room",
    time_phase: str = "afternoon",
    status: str = "ended",
    started_at: str | None = None,
    ended_at: str | None = None,
    routine_key: str = "",
    reason: str = "",
    metadata: dict | None = None,  # Gap 2: allows injecting daily_intent etc.
) -> None:
    """Directly insert a test episode into the DB for unit-test control."""
    now = datetime.now(timezone.utc).isoformat()
    ts_start = started_at or now
    ts_end = ended_at or (now if status != "active" else None)
    with db_storage.get_conn() as conn:
        conn.execute(
            """INSERT INTO life_activity_episodes
               (trace_id, activity_key, activity_label, place, time_phase,
                status, started_at, updated_at, ended_at, reason,
                continuity_note, source_residue_json, routine_key, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "test", activity_key, activity_label, place, time_phase,
                status, ts_start, now, ts_end, reason,
                "", "{}", routine_key,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )


def _insert_experience_with_ts(
    content: str,
    created_at: str,
    *,
    salience: float = 0.5,
    source: str = "life_loop",
    kind: str = "state_shift",
) -> None:
    """Insert an experience with an explicit created_at for boundary testing."""
    with db_storage.get_conn() as conn:
        conn.execute(
            """INSERT INTO inner_experience_log
               (trace_id, source, kind, content, mood_impact, desire_impact,
                salience, expression_status, related_event_hash,
                related_message_ids, related_intent_id, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "test", source, kind, content,
                0.0, 0.0, salience, "unspoken",
                None, "[]", None, "{}", created_at,
            ),
        )


class _FailingEpisodeStore:
    """Stub that always raises, to test graceful degradation."""

    async def list_for_day(self, *args: object, **kwargs: object) -> list:  # noqa: ANN401
        raise RuntimeError("simulated DB failure")


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


# ── C1.5 新增测试 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_c15_timeline_read_chronological_order(tmp_path: Path):
    """Episodes fetched today (UTC+8) must be passed in chronological order."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        _insert_episode("reading", "阅读",   started_at=(now - timedelta(hours=3)).isoformat())
        _insert_episode("walking", "散步",   started_at=(now - timedelta(hours=2)).isoformat())
        _insert_episode("resting", "休息",   started_at=(now - timedelta(hours=1)).isoformat())

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        result = await engine.run_once("trace_c15_order")

        assert result["action"] == "reflected"
        summary: str = result["output"]["summary"]
        # 阅读 (first) should appear before 休息 (last) in the summary
        assert "阅读" in summary
        assert "休息" in summary
        assert summary.index("阅读") < summary.index("休息")
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_summary_includes_first_and_last_activity(tmp_path: Path):
    """Summary must mention the very first and very last episode."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        _insert_episode("morning_read", "晨间阅读", started_at=(now - timedelta(hours=5)).isoformat())
        _insert_episode("evening_rest", "傍晚休息", started_at=(now - timedelta(hours=1)).isoformat())

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        result = await engine.run_once("trace_c15_firstlast")

        assert result["action"] == "reflected"
        summary: str = result["output"]["summary"]
        assert "晨间阅读" in summary, f"first activity missing: {summary!r}"
        assert "傍晚休息" in summary, f"last activity missing: {summary!r}"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_summary_includes_transitions_and_interrupts(tmp_path: Path):
    """Summary must mention interrupt count when ≥1 episodes were interrupted."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        _insert_episode("study",  "学习", status="ended",       started_at=(now - timedelta(hours=4)).isoformat())
        _insert_episode("walk",   "散步", status="interrupted", started_at=(now - timedelta(hours=3)).isoformat())
        _insert_episode("relax",  "放松", status="active",      started_at=(now - timedelta(hours=1)).isoformat())

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        result = await engine.run_once("trace_c15_transit")

        assert result["action"] == "reflected"
        summary: str = result["output"]["summary"]
        # "打断" signals interrupt was summarised
        assert "打断" in summary, f"interrupt not mentioned: {summary!r}"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_summary_includes_main_place(tmp_path: Path):
    """Summary must include the main place(s) from today's episodes."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        _insert_episode("reading", "阅读", place="study_room",
                        started_at=(now - timedelta(hours=2)).isoformat())

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        result = await engine.run_once("trace_c15_place")

        assert result["action"] == "reflected"
        summary: str = result["output"]["summary"]
        assert "study_room" in summary, f"main place missing: {summary!r}"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_microevent_and_episode_influence_residue_topic(tmp_path: Path):
    """High-salience MicroEvent (source=life_simulation) should steer residue.topic."""
    store = await _fresh_store(tmp_path)
    recorder = ExperienceRecorder()
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        _insert_episode("reading", "阅读", started_at=(now - timedelta(hours=2)).isoformat())

        # MicroEvent with high salience – should win residue topic
        await recorder.record(InnerExperienceIn(
            trace_id="t_micro",
            source="life_simulation",
            kind="micro_event",
            content="想起了一首老歌的旋律",
            salience=0.80,
        ))

        engine = _make_engine_with_episodes(store=store, recorder=recorder, episode_store=episode_store)
        await engine.run_once("trace_c15_micro")
        await asyncio.sleep(0.2)

        state = await store.read()
        residue_topic: str = state.life.residue.topic
        assert residue_topic != "", "residue.topic must not be empty"
        assert "老歌" in residue_topic or "阅读" in residue_topic, (
            f"neither MicroEvent nor episode referenced in residue.topic: {residue_topic!r}"
        )
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_repeated_episode_pattern_writes_long_term_memory(tmp_path: Path):
    """Same activity_key appearing 2+ times → long_term_memory entry."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        _insert_episode("reading", "阅读", started_at=(now - timedelta(hours=5)).isoformat())
        _insert_episode("walking", "散步", started_at=(now - timedelta(hours=4)).isoformat())
        _insert_episode("reading", "阅读", started_at=(now - timedelta(hours=3)).isoformat())  # repeated

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        await engine.run_once("trace_c15_repeat")

        rows = db_storage.fetch_all("SELECT content FROM long_term_memory")
        contents = [r["content"] for r in rows]
        assert any("阅读" in c for c in contents), (
            f"repeated pattern not written to LTM: {contents}"
        )
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_single_ordinary_episode_no_long_term_memory(tmp_path: Path):
    """Single, non-repeated episode without interrupt/residue must NOT write LTM."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        _insert_episode("reading", "阅读", status="ended",
                        started_at=(now - timedelta(hours=1)).isoformat())

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        await engine.run_once("trace_c15_single")

        rows = db_storage.fetch_all("SELECT content FROM long_term_memory")
        assert rows == [], f"single ordinary episode must not produce LTM: {rows}"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_episode_store_failure_graceful_degradation(tmp_path: Path):
    """When episode_store.list_for_day raises, fall back to experience-only, no crash."""
    store = await _fresh_store(tmp_path)
    recorder = ExperienceRecorder()
    try:
        await recorder.record(InnerExperienceIn(
            trace_id="t_fallback",
            source="life_loop",
            kind="state_shift",
            content="今天休息了一会儿",
            salience=0.6,
        ))

        engine = _make_engine_with_episodes(
            store=store,
            recorder=recorder,
            episode_store=_FailingEpisodeStore(),  # type: ignore[arg-type]
        )
        result = await engine.run_once("trace_c15_fail")

        assert result["success"] is True
        assert result["action"] in {"reflected", "no_experiences"}
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_no_episode_store_experience_only_compatible(tmp_path: Path):
    """Passing no episode_store must keep existing experience-only flow intact."""
    store = await _fresh_store(tmp_path)
    recorder = ExperienceRecorder()
    try:
        await recorder.record(InnerExperienceIn(
            trace_id="t_exp",
            source="life_loop",
            kind="state_shift",
            content="今天很平静",
            salience=0.5,
        ))

        # episode_store=None → old path
        engine = _make_engine(store=store, recorder=recorder, reflection_enabled=True)
        result = await engine.run_once("trace_c15_noeps")

        assert result["action"] == "reflected"
        assert result["output"]["summary"] != ""
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_wrong_date_episodes_not_consumed(tmp_path: Path):
    """Episodes started 2+ days ago (UTC+8) must not appear in today's reflection."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        # 2 days ago in UTC+8 – guaranteed outside today's window
        two_days_ago = (datetime.now(_TZ_8) - timedelta(days=2)).astimezone(timezone.utc).isoformat()
        _insert_episode("reading", "两天前的阅读", started_at=two_days_ago)

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        result = await engine.run_once("trace_c15_olddate")

        # Old episode must not appear in summary (if any reflection happened at all)
        if result["action"] == "reflected":
            summary: str = result["output"]["summary"]
            assert "两天前的阅读" not in summary, (
                f"stale episode leaked into summary: {summary!r}"
            )
        else:
            assert result["action"] in {"no_experiences", "disabled"}
    finally:
        await store.stop()


# ── C1.5 修正：Problem 1 — UTC+8 口径 ────────────────────────────────────

@pytest.mark.asyncio
async def test_c15_utc8_midnight_boundary_today_is_included(tmp_path: Path):
    """Experience at UTC+8 today 00:01 must be included in today's reflection."""
    store = await _fresh_store(tmp_path)
    try:
        today_utc8 = datetime.now(_TZ_8).date()
        midnight_utc8 = datetime.combine(today_utc8, dt_time.min, _TZ_8)
        # 1 minute past midnight UTC+8 → should be counted as today
        ts_today = (midnight_utc8 + timedelta(minutes=1)).isoformat()
        _insert_experience_with_ts("今天凌晨的活动", ts_today, salience=0.6)

        engine = _make_engine(store=store, recorder=ExperienceRecorder(), reflection_enabled=True)
        result = await engine.run_once("trace_utc8_today")

        assert result["action"] == "reflected", (
            f"experience at UTC+8 today 00:01 was unexpectedly excluded: {result}"
        )
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_utc8_midnight_boundary_yesterday_excluded(tmp_path: Path):
    """Experience at UTC+8 yesterday 23:59 must NOT be included in today's reflection."""
    store = await _fresh_store(tmp_path)
    try:
        today_utc8 = datetime.now(_TZ_8).date()
        midnight_utc8 = datetime.combine(today_utc8, dt_time.min, _TZ_8)
        # 1 minute before midnight UTC+8 → belongs to yesterday
        ts_yesterday = (midnight_utc8 - timedelta(minutes=1)).isoformat()
        _insert_experience_with_ts("昨天深夜的活动", ts_yesterday, salience=0.6)

        engine = _make_engine(store=store, recorder=ExperienceRecorder(), reflection_enabled=True)
        result = await engine.run_once("trace_utc8_yesterday")

        assert result["action"] == "no_experiences", (
            f"experience from UTC+8 yesterday 23:59 should be excluded, got: {result}"
        )
    finally:
        await store.stop()


# ── C1.5 修正：Problem 2 — MicroEvent salience=0.6 优先级 ────────────────

@pytest.mark.asyncio
async def test_c15_medium_salience_microevent_wins_over_episode_label(tmp_path: Path):
    """MicroEvent with salience=0.6 (realistic C1.4 range) must beat plain episode label."""
    store = await _fresh_store(tmp_path)
    recorder = ExperienceRecorder()
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        _insert_episode("reading", "阅读", started_at=(now - timedelta(hours=2)).isoformat())

        # No high-salience (>=0.7) experience; only a medium-salience MicroEvent
        await recorder.record(InnerExperienceIn(
            trace_id="t_micro_med",
            source="life_simulation",
            kind="micro_event",
            content="想到了一件还没做完的事",
            salience=0.60,
        ))

        engine = _make_engine_with_episodes(
            store=store, recorder=recorder, episode_store=episode_store
        )
        await engine.run_once("trace_micro_med")
        await asyncio.sleep(0.2)

        state = await store.read()
        residue_topic: str = state.life.residue.topic
        assert "没做完" in residue_topic, (
            f"MicroEvent (salience=0.6) should win over episode label; "
            f"residue.topic={residue_topic!r}"
        )
    finally:
        await store.stop()


# ── C1.5 修正：Problem 3 — 主场所按频率计算 ─────────────────────────────

@pytest.mark.asyncio
async def test_c15_main_place_by_frequency_not_insertion_order(tmp_path: Path):
    """Main place must be the most frequent, not the first-inserted."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        # study_room appears once (first), quiet_room appears twice → quiet_room wins
        _insert_episode("a", "活动甲", place="study_room",
                        started_at=(now - timedelta(hours=5)).isoformat())
        _insert_episode("b", "活动乙", place="quiet_room",
                        started_at=(now - timedelta(hours=4)).isoformat())
        _insert_episode("c", "活动丙", place="quiet_room",
                        started_at=(now - timedelta(hours=3)).isoformat())

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        result = await engine.run_once("trace_place_freq")

        assert result["action"] == "reflected"
        summary: str = result["output"]["summary"]
        assert "quiet_room" in summary, (
            f"most-frequent place 'quiet_room' not in summary: {summary!r}"
        )
        # study_room should NOT be the declared main place
        # (it may still appear if summarised elsewhere, so we check quiet_room wins)
    finally:
        await store.stop()


# ── C1.5 修正：Problem 4 — transition 数量 + input_summary 含 episode ──

@pytest.mark.asyncio
async def test_c15_summary_includes_transition_count(tmp_path: Path):
    """Summary must mention the number of activity transitions."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        # 3 different activity_keys → 2 transitions (A→B, B→C)
        _insert_episode("activity_a", "活动甲",
                        started_at=(now - timedelta(hours=4)).isoformat())
        _insert_episode("activity_b", "活动乙",
                        started_at=(now - timedelta(hours=3)).isoformat())
        _insert_episode("activity_c", "活动丙",
                        started_at=(now - timedelta(hours=2)).isoformat())

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        result = await engine.run_once("trace_transition_count")

        assert result["action"] == "reflected"
        summary: str = result["output"]["summary"]
        assert "切换" in summary or "转" in summary, (
            f"transition count not in summary: {summary!r}"
        )
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_input_summary_stored_in_db_includes_episode_info(tmp_path: Path):
    """dream_reflection_runs.input_summary must contain episode timeline info."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        _insert_episode("reading", "阅读", place="study_room",
                        started_at=(now - timedelta(hours=2)).isoformat())

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        result = await engine.run_once("trace_input_summary_ep")

        assert result["action"] == "reflected"
        rows = db_storage.fetch_all(
            "SELECT input_summary FROM dream_reflection_runs"
        )
        assert rows, "dream_reflection_runs must have a row"
        stored: str = rows[0]["input_summary"]
        assert "阅读" in stored or "episode" in stored.lower(), (
            f"episode info missing from stored input_summary: {stored!r}"
        )
    finally:
        await store.stop()


# ── Gap 1: 单次反思统一 target_day ───────────────────────────────────────

@pytest.mark.asyncio
async def test_c15_target_day_unified_experiences_and_episodes(tmp_path: Path):
    """Explicit _target_day must make both experiences and episodes use the same day.

    Strategy: inject yesterday's UTC+8 date; insert one experience and one episode
    at a time that is clearly 'yesterday UTC+8'.  run_once must find both and
    return action='reflected'.
    """
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        yesterday_utc8 = datetime.now(_TZ_8).date() - timedelta(days=1)
        # 10:00 UTC+8 yesterday → unambiguously within yesterday's window
        yesterday_10h = datetime.combine(yesterday_utc8, dt_time(10, 0), _TZ_8)
        ts = yesterday_10h.astimezone(timezone.utc).isoformat()

        # Experience recorded at yesterday UTC+8
        _insert_experience_with_ts("昨天上午的回忆", ts, salience=0.6)

        # Episode started at yesterday UTC+8
        _insert_episode("reading", "昨天阅读", started_at=ts)

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        # Pass explicit target_day → both inputs must use it, not datetime.now()
        result = await engine.run_once("trace_targetday", _target_day=yesterday_utc8)

        assert result["action"] == "reflected", (
            f"yesterday's data not found with explicit _target_day: {result}"
        )
        summary: str = result["output"]["summary"]
        assert "昨天阅读" in summary, (
            f"episode not included when _target_day=yesterday: {summary!r}"
        )
    finally:
        await store.stop()


# ── Gap 2: _input_summary 含 daily_intent ────────────────────────────────

@pytest.mark.asyncio
async def test_c15_input_summary_includes_daily_intent(tmp_path: Path):
    """Each episode line in dream_reflection_runs.input_summary must include
    metadata.daily_intent so operators can audit what intent drove the episode."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        _insert_episode(
            "memory_processing", "整理记忆",
            started_at=(now - timedelta(hours=2)).isoformat(),
            metadata={"daily_intent": "process_memory"},
        )

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        result = await engine.run_once("trace_daily_intent")

        assert result["action"] == "reflected"
        rows = db_storage.fetch_all(
            "SELECT input_summary FROM dream_reflection_runs"
        )
        assert rows, "must have a reflection run row"
        stored: str = rows[0]["input_summary"]
        assert "process_memory" in stored, (
            f"daily_intent 'process_memory' missing from input_summary: {stored!r}"
        )
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_c15_input_summary_missing_metadata_no_crash(tmp_path: Path):
    """Episode with empty metadata (no daily_intent) must not crash _input_summary."""
    store = await _fresh_store(tmp_path)
    episode_store = ActivityEpisodeStore()
    try:
        now = datetime.now(timezone.utc)
        # metadata defaults to {} — daily_intent absent
        _insert_episode("reading", "阅读",
                        started_at=(now - timedelta(hours=1)).isoformat())

        engine = _make_engine_with_episodes(store=store, episode_store=episode_store)
        result = await engine.run_once("trace_no_meta_crash")

        assert result["success"] is True, f"crash on missing metadata: {result}"
    finally:
        await store.stop()
