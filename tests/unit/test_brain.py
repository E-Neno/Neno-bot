"""
Phase 3a 验收测试 — NenoBrain / Fragmenter / InterruptController / MemoryRecall

覆盖:
- brain._llm_judge(): valid JSON, invalid JSON degrade, timeout degrade
- brain._llm_generate(): Gemini success, Gemini fail -> MiMo success, both fail -> None
- fragmenter.split(): energy=20 1 truncated, energy=50 max 3, energy=80 max 5
- interrupt.on_p0_interrupt(): judging cancel_event, generating stop_after_current
- memory_recall.recall(): keyword recall from long_term_memory
- brain.run_cycle(): full pipeline mock, sleeping skip, should_share=false no-op
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.experience_recorder import ExperienceRecorder
from app.services.consciousness.fragmenter import Fragmenter
from app.services.consciousness.interrupt import InterruptController
from app.services.consciousness.memory_recall import MemoryRecall
from app.services.consciousness.event_pool import EventIn
from app.services.consciousness.models import (
    DesireState,
    EnergyState,
    LastInteraction,
    MoodState,
    NenoState,
)
from app.storage import db as db_storage


# ── helpers ──────────────────────────────────────────────────


def _make_test_db_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


def _init_db(data_dir: Path) -> None:
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()


def _make_awake_state() -> NenoState:
    return NenoState(
        energy=EnergyState(value=80.0, status="awake", description="精力还不错"),
        mood=MoodState(
            valence=0.4, arousal=0.5, label="愉悦",
            description="心情还行", baseline_valence=0.3, baseline_arousal=0.5,
        ),
        desire=DesireState(value=65.0),
        last_interaction=LastInteraction(
            user_id="qq:private:test123",
            user_name="测试用户",
            summary="刚才聊了会天",
        ),
    )


def _make_sleeping_state() -> NenoState:
    return NenoState(
        energy=EnergyState(value=10.0, status="sleeping", description="睡着了"),
    )


# ── Fragmenter tests ────────────────────────────────────────


class TestFragmenter:
    def test_split_low_energy(self):
        cfg = ConsciousnessConfig()
        f = Fragmenter(cfg)
        result = f.split("hello|world|foo|bar|baz", 20)
        assert len(result) == 1
        assert len(result[0]) <= 10

    def test_split_mid_energy(self):
        cfg = ConsciousnessConfig()
        f = Fragmenter(cfg)
        result = f.split("a|b|c|d|e|f|g", 50)
        assert len(result) <= 3

    def test_split_high_energy(self):
        cfg = ConsciousnessConfig(max_fragments_per_burst=5)
        f = Fragmenter(cfg)
        result = f.split("a|b|c|d|e|f|g", 80)
        assert len(result) <= 5

    def test_split_removes_empty(self):
        cfg = ConsciousnessConfig()
        f = Fragmenter(cfg)
        result = f.split("a||b|  |c", 80)
        assert result == ["a", "b", "c"]

    def test_typing_delay_in_range(self):
        cfg = ConsciousnessConfig(
            typing_chars_per_second=8.0,
            typing_min_delay=0.8,
            typing_max_delay=4.0,
        )
        f = Fragmenter(cfg)
        delay = f.typing_delay("hello world test")
        assert 0.8 <= delay <= 4.0

    def test_rate_limit_resets_on_new_hour(self):
        cfg = ConsciousnessConfig(max_proactive_per_hour=2)
        f = Fragmenter(cfg)
        assert f.check_rate_limit()
        f.record_sent()
        f.record_sent()
        assert not f.check_rate_limit()
        f._hour_bucket = -1
        assert f.check_rate_limit()


# ── InterruptController tests ───────────────────────────────


class TestInterruptController:
    def test_initial_idle(self):
        ctrl = InterruptController()
        assert ctrl.phase == "idle"
        assert not ctrl.should_cancel_judging
        assert not ctrl.should_stop_after_current

    @pytest.mark.asyncio
    async def test_cancels_judging(self):
        ctrl = InterruptController()
        ctrl.enter("judging")
        await ctrl.on_p0_interrupt()
        assert ctrl.should_cancel_judging
        assert not ctrl.should_stop_after_current

    @pytest.mark.asyncio
    async def test_stops_generating(self):
        ctrl = InterruptController()
        ctrl.enter("generating")
        await ctrl.on_p0_interrupt()
        assert ctrl.should_stop_after_current
        assert not ctrl.should_cancel_judging

    @pytest.mark.asyncio
    async def test_stops_sending_and_pushes_event(self):
        ctrl = InterruptController()
        ctrl.enter("sending")
        mock_pool = AsyncMock()
        await ctrl.on_p0_interrupt(pool=mock_pool)
        assert ctrl.should_stop_after_current
        mock_pool.push.assert_called_once()

    def test_enter_idle_resets(self):
        ctrl = InterruptController()
        ctrl.enter("generating")
        ctrl._stop_after_current = True
        ctrl.enter("idle")
        assert not ctrl.should_stop_after_current

    def test_enter_judging_clears_cancel(self):
        ctrl = InterruptController()
        ctrl._cancel_event.set()
        ctrl.enter("judging")
        assert not ctrl.should_cancel_judging


# ── MemoryRecall tests ──────────────────────────────────────


class TestMemoryRecall:
    @pytest.mark.asyncio
    async def test_recall_keyword_match(self, tmp_path):
        data_dir = _make_test_db_dir(tmp_path)
        _init_db(data_dir)

        recall = MemoryRecall(db=None, config=ConsciousnessConfig(memory_recall_top_k=5))

        await recall.add_memory("用户讨厌下雨天", ["偏好", "天气"], subject="测试用户")
        await recall.add_memory("用户喜欢喝奶茶", ["偏好", "饮食"], subject="测试用户")
        await recall.add_memory("南宁经常下暴雨", ["天气", "南宁"], subject=None)

        results = await recall.recall("下雨天出门", subject="测试用户")
        assert len(results) >= 1
        assert any("下雨" in r for r in results)

    @pytest.mark.asyncio
    async def test_recall_empty_on_no_match(self, tmp_path):
        data_dir = _make_test_db_dir(tmp_path)
        _init_db(data_dir)
        recall = MemoryRecall(db=None, config=ConsciousnessConfig())
        results = await recall.recall("xyzabc123不存在", subject=None)
        assert results == []

    @pytest.mark.asyncio
    async def test_recall_subject_priority(self, tmp_path):
        data_dir = _make_test_db_dir(tmp_path)
        _init_db(data_dir)
        recall = MemoryRecall(db=None, config=ConsciousnessConfig(memory_recall_top_k=3))

        await recall.add_memory("通用记忆", ["标签"], subject=None, salience=1.0)
        await recall.add_memory("匹配用户记忆", ["标签"], subject="测试用户", salience=0.5)

        results = await recall.recall("记忆", subject="测试用户")
        assert len(results) >= 1


# ── NenoBrain judge tests ───────────────────────────────────


class TestNenoBrainJudge:
    @pytest.mark.asyncio
    async def test_judge_valid_json_should_share_true(self):
        from app.services.consciousness.brain import NenoBrain

        cfg = ConsciousnessConfig()
        brain = NenoBrain(
            state_store=AsyncMock(),
            pool=AsyncMock(),
            recall=AsyncMock(),
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=cfg,
        )

        state = _make_awake_state()
        events = [EventIn(
            topic_hash="test_event",
            priority=1,
            content="测试事件",
            tags=["测试"],
            mood_impact=0.3,
        )]

        mock_result = json.dumps({
            "should_share": True,
            "reason": "想聊聊",
            "target_user_id": "qq:private:test123",
            "urgency": "normal",
        })
        with patch("app.services.consciousness.brain._llm_call",
                   new=AsyncMock(return_value=mock_result)):
            result = await brain._llm_judge(state, events, "trace_001")
            assert result["should_share"] is True
            assert result["target_user_id"] == "qq:private:test123"

    @pytest.mark.asyncio
    async def test_judge_valid_json_should_share_false(self):
        from app.services.consciousness.brain import NenoBrain

        cfg = ConsciousnessConfig()
        brain = NenoBrain(
            state_store=AsyncMock(),
            pool=AsyncMock(),
            recall=AsyncMock(),
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=cfg,
        )

        state = _make_awake_state()
        events = [EventIn(topic_hash="test_event", priority=2, content="背景事件")]

        mock_result = json.dumps({
            "should_share": False,
            "reason": None,
            "target_user_id": None,
            "urgency": None,
        })
        with patch("app.services.consciousness.brain._llm_call",
                   new=AsyncMock(return_value=mock_result)):
            result = await brain._llm_judge(state, events, "trace_002")
            assert result["should_share"] is False

    @pytest.mark.asyncio
    async def test_judge_invalid_json_degrade(self):
        from app.services.consciousness.brain import NenoBrain

        cfg = ConsciousnessConfig()
        brain = NenoBrain(
            state_store=AsyncMock(),
            pool=AsyncMock(),
            recall=AsyncMock(),
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=cfg,
        )

        state = _make_awake_state()
        events = [EventIn(topic_hash="test", priority=1, content="测试")]

        with patch("app.services.consciousness.brain._llm_call",
                   new=AsyncMock(return_value="not valid json {{{")):
            result = await brain._llm_judge(state, events, "trace_003")
            assert result is None

    @pytest.mark.asyncio
    async def test_judge_timeout_degrade(self):
        from app.services.consciousness.brain import NenoBrain

        cfg = ConsciousnessConfig(judge_llm_timeout_seconds=0.01)
        brain = NenoBrain(
            state_store=AsyncMock(),
            pool=AsyncMock(),
            recall=AsyncMock(),
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=cfg,
        )

        state = _make_awake_state()
        events = [EventIn(topic_hash="test", priority=1, content="测试")]

        async def slow_response(*args, **kwargs):
            await asyncio.sleep(1.0)
            return "{}"

        with patch("app.services.consciousness.brain._llm_call", new=slow_response):
            result = await brain._llm_judge(state, events, "trace_004")
            assert result is None

    @pytest.mark.asyncio
    async def test_judge_markdown_code_block(self):
        from app.services.consciousness.brain import NenoBrain

        cfg = ConsciousnessConfig()
        brain = NenoBrain(
            state_store=AsyncMock(),
            pool=AsyncMock(),
            recall=AsyncMock(),
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=cfg,
        )

        state = _make_awake_state()
        events = [EventIn(topic_hash="test", priority=1, content="测试")]

        mock_result = '```json\n{"should_share": true, "reason": "test", "target_user_id": null, "urgency": "low"}\n```'
        with patch("app.services.consciousness.brain._llm_call",
                   new=AsyncMock(return_value=mock_result)):
            result = await brain._llm_judge(state, events, "trace_md")
            assert result["should_share"] is True


# ── NenoBrain generate tests ────────────────────────────────


class TestNenoBrainGenerate:
    @pytest.mark.asyncio
    async def test_generate_gemini_success(self):
        from app.services.consciousness.brain import NenoBrain

        cfg = ConsciousnessConfig()
        mock_recall = AsyncMock()
        mock_recall.recall.return_value = ["用户喜欢下雨天"]

        brain = NenoBrain(
            state_store=AsyncMock(),
            pool=AsyncMock(),
            recall=mock_recall,
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=cfg,
        )

        state = _make_awake_state()
        events = [EventIn(topic_hash="rain", priority=1, content="南宁要下暴雨了")]

        with patch("app.services.consciousness.brain._llm_call",
                   new=AsyncMock(return_value="诶 你那边下雨了吗|看天气预报说要下暴雨")):
            result = await brain._llm_generate(state, events, "trace_gen")
            assert result is not None
            assert "下雨" in result

    @pytest.mark.asyncio
    async def test_generate_fallback_on_first_fail(self):
        from app.services.consciousness.brain import NenoBrain

        cfg = ConsciousnessConfig(generate_llm_fallback="mimo-v2.5-pro")
        mock_recall = AsyncMock()
        mock_recall.recall.return_value = []

        brain = NenoBrain(
            state_store=AsyncMock(),
            pool=AsyncMock(),
            recall=mock_recall,
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=cfg,
        )

        state = _make_awake_state()
        events = [EventIn(topic_hash="test", priority=1, content="测试")]

        call_count = [0]

        async def fail_then_succeed(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Gemini failed")
            return "fallback response|second fragment"

        with patch("app.services.consciousness.brain._llm_call",
                   new=fail_then_succeed):
            result = await brain._llm_generate(state, events, "trace_fb")
            assert result is not None
            assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_generate_both_fail(self):
        from app.services.consciousness.brain import NenoBrain

        cfg = ConsciousnessConfig(generate_llm_fallback="mimo-v2.5-pro")
        mock_recall = AsyncMock()
        mock_recall.recall.return_value = []

        brain = NenoBrain(
            state_store=AsyncMock(),
            pool=AsyncMock(),
            recall=mock_recall,
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=cfg,
        )

        state = _make_awake_state()
        events = [EventIn(topic_hash="test", priority=1, content="测试")]

        with patch("app.services.consciousness.brain._llm_call",
                   new=AsyncMock(side_effect=RuntimeError("all fail"))):
            result = await brain._llm_generate(state, events, "trace_none")
            assert result is None


# ── NenoBrain run_cycle tests ───────────────────────────────


class TestNenoBrainRunCycle:
    @pytest.mark.asyncio
    async def test_sleeping_skips(self):
        from app.services.consciousness.brain import NenoBrain

        mock_state_store = AsyncMock()
        mock_state_store.read.return_value = _make_sleeping_state()

        brain = NenoBrain(
            state_store=mock_state_store,
            pool=AsyncMock(),
            recall=AsyncMock(),
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=ConsciousnessConfig(),
        )

        with patch("app.services.consciousness.brain._llm_call") as mock_llm:
            await brain.run_cycle()
            mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_desire_no_p0_skips(self):
        from app.services.consciousness.brain import NenoBrain

        state = _make_awake_state()
        state.desire.value = 10.0

        mock_state_store = AsyncMock()
        mock_state_store.read.return_value = state
        mock_pool = AsyncMock()
        mock_pool.pop_pending.return_value = []

        brain = NenoBrain(
            state_store=mock_state_store,
            pool=mock_pool,
            recall=AsyncMock(),
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=ConsciousnessConfig(),
        )

        with patch("app.services.consciousness.brain._llm_call") as mock_llm:
            await brain.run_cycle()
            mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_full_pipeline_writes_intent(self, tmp_path):
        from app.services.consciousness.brain import NenoBrain

        data_dir = _make_test_db_dir(tmp_path)
        _init_db(data_dir)

        state = _make_awake_state()
        state.desire.value = 80.0

        mock_state_store = AsyncMock()
        mock_state_store.read.return_value = state

        p0_event = EventIn(
            topic_hash="weather_p0",
            priority=0,
            content="南宁暴雨红色预警",
            tags=["天气", "紧急"],
            mood_impact=0.5,
        )
        p1_event = EventIn(
            topic_hash="hot_topic",
            priority=1,
            content="南宁热搜",
            tags=["热搜"],
            mood_impact=0.2,
        )

        mock_pool = AsyncMock()
        mock_pool.pop_pending = AsyncMock()
        mock_pool.pop_pending.side_effect = [
            [p0_event],
            [p1_event],
        ]

        mock_recall = AsyncMock()
        mock_recall.recall.return_value = []

        mock_fragmenter = MagicMock()
        mock_fragmenter.split.return_value = ["诶", "南宁要下暴雨了"]
        mock_fragmenter.check_rate_limit.return_value = True

        brain = NenoBrain(
            state_store=mock_state_store,
            pool=mock_pool,
            recall=mock_recall,
            fragmenter=mock_fragmenter,
            interrupt=InterruptController(),
            config=ConsciousnessConfig(),
        )

        judge_json = json.dumps({
            "should_share": True,
            "reason": "极端天气预警",
            "target_user_id": "qq:private:test123",
            "urgency": "high",
        })
        gen_text = "诶|南宁要下暴雨了|不知道会不会淹水"

        with patch("app.services.consciousness.brain._llm_call",
                   new=AsyncMock(side_effect=[judge_json, gen_text])):
            await brain.run_cycle()

        mock_state_store.submit_mutation.assert_called()
        mock_fragmenter.record_sent.assert_called_once()

    @pytest.mark.asyncio
    async def test_judge_should_not_share_no_intent(self, tmp_path):
        from app.services.consciousness.brain import NenoBrain

        _init_db(_make_test_db_dir(tmp_path))

        state = _make_awake_state()
        state.desire.value = 80.0

        mock_state_store = AsyncMock()
        mock_state_store.read.return_value = state

        p0_event = EventIn(topic_hash="test", priority=0, content="测试事件")

        mock_pool = AsyncMock()
        mock_pool.pop_pending = AsyncMock()
        mock_pool.pop_pending.side_effect = [[p0_event], []]

        mock_fragmenter = MagicMock()

        brain = NenoBrain(
            state_store=mock_state_store,
            pool=mock_pool,
            recall=AsyncMock(),
            fragmenter=mock_fragmenter,
            interrupt=InterruptController(),
            config=ConsciousnessConfig(),
        )

        judge_json = json.dumps({
            "should_share": False,
            "reason": None,
            "target_user_id": None,
            "urgency": None,
        })

        with patch("app.services.consciousness.brain._llm_call",
                   new=AsyncMock(return_value=judge_json)):
            await brain.run_cycle()

        mock_fragmenter.split.assert_not_called()

    @pytest.mark.asyncio
    async def test_judge_should_not_share_records_unspoken_experience(self, tmp_path):
        from app.services.consciousness.brain import NenoBrain

        _init_db(_make_test_db_dir(tmp_path))
        recorder = ExperienceRecorder()

        state = _make_awake_state()
        state.desire.value = 80.0
        mock_state_store = AsyncMock()
        mock_state_store.read.return_value = state

        event = EventIn(topic_hash="test_unspoken", priority=0, content="一件暂时不说的事")
        mock_pool = AsyncMock()
        mock_pool.pop_pending.side_effect = [[event], []]

        brain = NenoBrain(
            state_store=mock_state_store,
            pool=mock_pool,
            recall=AsyncMock(),
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=ConsciousnessConfig(),
            recorder=recorder,
        )

        judge_json = json.dumps({
            "should_share": False,
            "reason": "现在不适合说",
            "target_user_id": None,
            "urgency": "low",
        })

        with patch("app.services.consciousness.brain._llm_call", new=AsyncMock(return_value=judge_json)):
            await brain.run_cycle()

        rows = await recorder.list_recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["source"] == "brain_judge"
        assert rows[0]["kind"] == "unspoken_thought"
        assert rows[0]["expression_status"] == "unspoken"
        assert rows[0]["related_event_hash"] == "test_unspoken"

    @pytest.mark.asyncio
    async def test_judge_true_no_target_records_suppressed(self, tmp_path):
        from app.services.consciousness.brain import NenoBrain

        _init_db(_make_test_db_dir(tmp_path))
        recorder = ExperienceRecorder()

        state = _make_awake_state()
        state.desire.value = 80.0
        state.last_interaction.user_id = None
        mock_state_store = AsyncMock()
        mock_state_store.read.return_value = state

        event = EventIn(topic_hash="test_suppressed", priority=0, content="想说但没有对象")
        mock_pool = AsyncMock()
        mock_pool.pop_pending.side_effect = [[event], []]

        mock_fragmenter = MagicMock()
        mock_fragmenter.check_rate_limit.return_value = True
        mock_fragmenter.split.return_value = ["想说点什么"]

        brain = NenoBrain(
            state_store=mock_state_store,
            pool=mock_pool,
            recall=AsyncMock(),
            fragmenter=mock_fragmenter,
            interrupt=InterruptController(),
            config=ConsciousnessConfig(),
            recorder=recorder,
        )

        judge_json = json.dumps({
            "should_share": True,
            "reason": "想说但没有对象",
            "target_user_id": None,
            "urgency": "normal",
        })

        with patch(
            "app.services.consciousness.brain._llm_call",
            new=AsyncMock(side_effect=[judge_json, "想说点什么"]),
        ):
            await brain.run_cycle()

        rows = await recorder.list_recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["expression_status"] == "suppressed"
        assert rows[0]["related_event_hash"] == "test_suppressed"

    @pytest.mark.asyncio
    async def test_successful_intent_records_pending_expression(self, tmp_path):
        from app.services.consciousness.brain import NenoBrain

        _init_db(_make_test_db_dir(tmp_path))
        recorder = ExperienceRecorder()

        state = _make_awake_state()
        state.desire.value = 80.0
        mock_state_store = AsyncMock()
        mock_state_store.read.return_value = state

        event = EventIn(topic_hash="test_pending", priority=0, content="一件想表达的事")
        mock_pool = AsyncMock()
        mock_pool.pop_pending.side_effect = [[event], []]

        mock_fragmenter = MagicMock()
        mock_fragmenter.check_rate_limit.return_value = True
        mock_fragmenter.split.return_value = ["想说点什么"]

        brain = NenoBrain(
            state_store=mock_state_store,
            pool=mock_pool,
            recall=AsyncMock(),
            fragmenter=mock_fragmenter,
            interrupt=InterruptController(),
            config=ConsciousnessConfig(),
            recorder=recorder,
        )

        judge_json = json.dumps({
            "should_share": True,
            "reason": "想表达",
            "target_user_id": "qq:private:test123",
            "urgency": "normal",
        })

        with patch(
            "app.services.consciousness.brain._llm_call",
            new=AsyncMock(side_effect=[judge_json, "想说点什么"]),
        ):
            await brain.run_cycle()

        rows = await recorder.list_recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["expression_status"] == "pending_expression"
        assert rows[0]["related_event_hash"] == "test_pending"
        assert rows[0]["related_intent_id"] is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("judge_return", ["not valid json {{{", None])
    async def test_judge_none_or_bad_json_records_no_experience(self, tmp_path, judge_return):
        """判断层返回 None / 坏 JSON 降级时，不写 inner_experience_log。"""
        from app.services.consciousness.brain import NenoBrain

        _init_db(_make_test_db_dir(tmp_path))
        recorder = ExperienceRecorder()

        state = _make_awake_state()
        state.desire.value = 80.0
        mock_state_store = AsyncMock()
        mock_state_store.read.return_value = state

        event = EventIn(topic_hash="test_judge_none", priority=0, content="判断层失败的事")
        mock_pool = AsyncMock()
        mock_pool.pop_pending.side_effect = [[event], []]

        mock_fragmenter = MagicMock()

        brain = NenoBrain(
            state_store=mock_state_store,
            pool=mock_pool,
            recall=AsyncMock(),
            fragmenter=mock_fragmenter,
            interrupt=InterruptController(),
            config=ConsciousnessConfig(),
            recorder=recorder,
        )

        # 坏 JSON 与 None 都会让 _llm_judge() 降级为 None
        with patch("app.services.consciousness.brain._llm_call",
                   new=AsyncMock(return_value=judge_return)):
            await brain.run_cycle()

        rows = await recorder.list_recent(limit=10)
        assert rows == []
        mock_fragmenter.split.assert_not_called()

    @pytest.mark.asyncio
    async def test_recorder_failure_does_not_break_cycle(self, tmp_path):
        """recorder.record 抛异常时，brain cycle 不应崩溃。"""
        from app.services.consciousness.brain import NenoBrain

        _init_db(_make_test_db_dir(tmp_path))

        state = _make_awake_state()
        state.desire.value = 80.0
        mock_state_store = AsyncMock()
        mock_state_store.read.return_value = state

        event = EventIn(topic_hash="test_rec_fail", priority=0, content="录入会抛异常的事")
        mock_pool = AsyncMock()
        mock_pool.pop_pending.side_effect = [[event], []]

        failing_recorder = MagicMock()
        failing_recorder.record = AsyncMock(side_effect=RuntimeError("db boom"))

        brain = NenoBrain(
            state_store=mock_state_store,
            pool=mock_pool,
            recall=AsyncMock(),
            fragmenter=MagicMock(),
            interrupt=InterruptController(),
            config=ConsciousnessConfig(),
            recorder=failing_recorder,
        )

        # should_share=False → 进入 _record_experiences，record 抛异常被吞掉
        judge_json = json.dumps({
            "should_share": False,
            "reason": "不说",
            "target_user_id": None,
            "urgency": "low",
        })

        with patch("app.services.consciousness.brain._llm_call",
                   new=AsyncMock(return_value=judge_json)):
            # 不应抛异常逃逸出 run_cycle
            await brain.run_cycle()

        failing_recorder.record.assert_awaited()
