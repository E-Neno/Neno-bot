"""
Phase 1 验收测试 — StateStore / DesireModel / MoodModel

覆盖:
- 4 张新表创建成功，不影响现有表
- NenoState 默认值 JSON 序列化/反序列化
- StateStore 读写与持久化恢复
- 并发写：10 条 mutation → revision=10，无数据丢失
- 乐观锁冲突重试，最终一致
- DesireModel 线性增长 + 抖动
- MoodModel 基线回归
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.desire import DesireModel
from app.services.consciousness.models import (
    DesireState,
    EnergyState,
    Experience,
    LifeResidue,
    LifeState,
    MoodState,
    NenoState,
    StateMutation,
    WorldState,
)
from app.services.consciousness.mood import MoodModel
from app.storage import db as db_storage


# ── helpers ──────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_test_db_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


def _init_db(data_dir: Path) -> None:
    """初始化完整数据库（含 consciousness 4 张表）"""
    import app.storage.db as db_storage

    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()


def _fresh_state_store(data_dir: Path) -> "FreshStore":
    """创建全新的 StateStore 并绑定到独立 DB"""
    from app.services.consciousness.state_store import StateStore

    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()

    cfg = ConsciousnessConfig()
    store = StateStore(db=None, config=cfg)
    return FreshStore(store, cfg)


class FreshStore:
    """Holder to avoid re-monkeypatching every time."""

    def __init__(self, store, cfg: ConsciousnessConfig) -> None:
        self.store = store
        self.cfg = cfg


# ── NenoState 序列化 ─────────────────────────────────────────


class TestNenoStateSerialization:
    def test_default_state_roundtrip(self):
        """NenoState 默认值可序列化为合法 JSON，并能从 JSON 反序列化"""
        state = NenoState()
        js = state.model_dump_json()
        assert isinstance(js, str)
        data = json.loads(js)
        assert data["version"] == 2
        assert data["revision"] == 0

        restored = NenoState.model_validate_json(js)
        assert restored.version == 2
        assert restored.revision == 0
        assert restored.energy.value == 80.0
        assert restored.mood.valence == 0.3
        assert restored.mood.arousal == 0.5
        assert restored.desire.value == 0.0

    def test_modified_state_roundtrip(self):
        """修改后的状态可正确序列化/反序列化"""
        state = NenoState()
        state.energy.value = 50.0
        state.mood.valence = -0.5
        state.desire.value = 30.0

        js = state.model_dump_json()
        restored = NenoState.model_validate_json(js)
        assert restored.energy.value == 50.0
        assert restored.mood.valence == -0.5
        assert restored.desire.value == 30.0


def test_old_state_json_gets_default_life():
    old = {
        "version": 2,
        "revision": 0,
        "updated_at": None,
        "energy": {"value": 80.0, "status": "awake", "description": "ok"},
        "mood": {
            "valence": 0.3,
            "arousal": 0.5,
            "label": "平静",
            "description": "ok",
            "baseline_valence": 0.3,
            "baseline_arousal": 0.5,
        },
        "desire": {"value": 0.0, "last_express_at": None, "decay_duration_minutes": 120},
        "world": {"weather": None, "hot_topics": [], "time_context": "", "last_perception_at": None},
        "last_interaction": {"user_id": None, "user_name": None, "summary": None, "at_time": None},
        "today_experiences": [],
    }

    state = NenoState.model_validate(old)

    assert state.life.mode == "idle"
    assert state.life.current_activity == "quiet_observing"


# ── 数据库建表 ───────────────────────────────────────────────


class TestNewTables:
    def test_all_four_tables_exist(self, tmp_path: Path):
        """4 张新表创建成功，不影响现有表"""
        data_dir = _make_test_db_dir(tmp_path)
        _init_db(data_dir)

        row = db_storage.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_state'"
        )
        assert row is not None

        row = db_storage.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='event_log'"
        )
        assert row is not None

        row = db_storage.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='long_term_memory'"
        )
        assert row is not None

        row = db_storage.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='proactive_intent'"
        )
        assert row is not None

    def test_existing_tables_still_work(self, tmp_path: Path):
        """现有表（messages, memories, debug_events 等）不受影响"""
        data_dir = _make_test_db_dir(tmp_path)
        _init_db(data_dir)

        msg_id = db_storage.add_message("s1", "user", "hello", trace_id="t1")
        assert msg_id > 0

        db_storage.add_memory("test memory", "general")
        memories = db_storage.get_active_memories()
        assert len(memories) >= 1

        eid = db_storage.add_debug_event(
            trace_id="t1", module="test", event="smoke", level="info"
        )
        assert eid > 0


# ── StateStore 读写与持久化 ──────────────────────────────────


class TestStateStoreBasic:
    @pytest.mark.asyncio
    async def test_start_and_read_default_state(self, tmp_path: Path):
        """StateStore.start() 后 read() 返回默认状态（revision=0）"""
        data_dir = _make_test_db_dir(tmp_path)
        fs = _fresh_state_store(data_dir)

        await fs.store.start()
        try:
            state = await fs.store.read()
            assert state.revision == 0
            assert state.version == 2
            assert state.energy.value == 80.0
        finally:
            await fs.store.stop()

    @pytest.mark.asyncio
    async def test_persistence_across_restart(self, tmp_path: Path):
        """服务重启后 read() 从 SQLite 正确恢复上次的状态"""
        data_dir = _make_test_db_dir(tmp_path)

        # 第一轮：写入
        fs1 = _fresh_state_store(data_dir)
        await fs1.store.start()
        mutation = StateMutation(energy=EnergyState(value=42.0))
        await fs1.store.submit_mutation(mutation)
        await asyncio.sleep(0.2)
        await fs1.store.stop()

        # 第二轮：重建 StateStore，验证恢复
        fs2 = _fresh_state_store(data_dir)
        await fs2.store.start()
        try:
            state = await fs2.store.read()
            assert state.energy.value == 42.0
            assert state.revision >= 1
        finally:
            await fs2.store.stop()

    @pytest.mark.asyncio
    async def test_submit_mutation_updates_state(self, tmp_path: Path):
        """单条 mutation 正确更新状态"""
        data_dir = _make_test_db_dir(tmp_path)
        fs = _fresh_state_store(data_dir)

        await fs.store.start()
        try:
            mutation = StateMutation(
                energy=EnergyState(value=90.0, status="awake", description="精力充沛"),
                mood=MoodState(valence=0.8, arousal=0.7),
            )
            await fs.store.submit_mutation(mutation)
            await asyncio.sleep(0.2)

            state = await fs.store.read()
            assert state.energy.value == 90.0
            assert state.energy.description == "精力充沛"
            # read() applies mood regression toward baseline, so exact values drift
            assert 0.7 <= state.mood.valence <= 0.8
            assert 0.65 <= state.mood.arousal <= 0.7
            assert state.revision >= 1
        finally:
            await fs.store.stop()

    @pytest.mark.asyncio
    async def test_submit_mutation_updates_life_state(self, tmp_path: Path):
        """life mutation 只能通过 StateStore 单写者持久化"""
        data_dir = _make_test_db_dir(tmp_path)
        fs = _fresh_state_store(data_dir)

        await fs.store.start()
        try:
            await fs.store.submit_mutation(
                StateMutation(
                    life=LifeState(
                        mode="absorbed",
                        attention="memory",
                        current_activity="carrying_unspoken_thought",
                    ),
                    life_residue=LifeResidue(topic="未说出口的话", mood="soft", intensity=0.4),
                )
            )
            await asyncio.sleep(0.2)

            state = await fs.store.read()
            assert state.life.mode == "absorbed"
            assert state.life.attention == "memory"
            assert state.life.current_activity == "carrying_unspoken_thought"
            assert state.life.residue.topic == "未说出口的话"
            assert state.life.residue.intensity == 0.4
        finally:
            await fs.store.stop()


# ── 并发写 / 乐观锁 ─────────────────────────────────────────


class TestConcurrentWrites:
    @pytest.mark.asyncio
    async def test_concurrent_submit_10_mutations(self, tmp_path: Path):
        """并发 submit 10 条 mutation，最终 revision=10，无数据丢失"""
        data_dir = _make_test_db_dir(tmp_path)
        fs = _fresh_state_store(data_dir)

        await fs.store.start()
        try:
            async def submit_one(i: int) -> None:
                await fs.store.submit_mutation(
                    StateMutation(
                        energy=EnergyState(value=float(i + 1)),
                        mood=MoodState(valence=0.1 * i, arousal=0.1 * i),
                    )
                )

            tasks = [asyncio.create_task(submit_one(i)) for i in range(10)]
            await asyncio.gather(*tasks)
            await asyncio.sleep(0.5)

            state = await fs.store.read()
            assert state.revision == 10, f"expected revision=10, got {state.revision}"
        finally:
            await fs.store.stop()

    @pytest.mark.asyncio
    async def test_optimistic_lock_retry_logged(self, tmp_path: Path, caplog):
        """乐观锁冲突时自动重试，日志可见冲突次数"""
        data_dir = _make_test_db_dir(tmp_path)
        fs = _fresh_state_store(data_dir)

        await fs.store.start()
        try:
            caplog.set_level(logging.WARNING, logger="app.services.consciousness.state_store")

            async def submit_one(i: int) -> None:
                await fs.store.submit_mutation(
                    StateMutation(energy=EnergyState(value=float(50 + i)))
                )

            tasks = [asyncio.create_task(submit_one(i)) for i in range(20)]
            await asyncio.gather(*tasks)
            await asyncio.sleep(1.0)

            state = await fs.store.read()
            assert state.revision == 20, f"expected revision=20, got {state.revision}"

            conflict_logs = [
                r.message for r in caplog.records
                if "optimistic lock conflict" in r.message
            ]
            if conflict_logs:
                assert any("attempt=1" in msg or "attempt=2" in msg or "attempt=3" in msg
                          for msg in conflict_logs)
        finally:
            await fs.store.stop()


# ── DesireModel ──────────────────────────────────────────────


class TestDesireModel:
    def test_current_value_increases_over_time(self):
        """时间推进后 current_value 返回递增值"""
        cfg = ConsciousnessConfig(desire_linear_rate=2.0, desire_jitter_pct=0.0)
        model = DesireModel(cfg)

        now = _utcnow()
        past = (now - timedelta(minutes=10)).isoformat()
        state = DesireState(value=10.0, last_express_at=past)

        val_now = model.current_value(state, now)

        future = now + timedelta(minutes=30)
        state_future = DesireState(value=10.0, last_express_at=past)
        val_future = model.current_value(state_future, future)

        assert val_future > val_now
        expected_growth = cfg.desire_linear_rate * 30
        assert val_future == pytest.approx(10.0 + expected_growth + cfg.desire_linear_rate * 10, abs=1.0)

    def test_current_value_includes_jitter(self):
        """抖动开启时值有变化"""
        cfg = ConsciousnessConfig(desire_linear_rate=2.0, desire_jitter_pct=0.10)
        model = DesireModel(cfg)
        state = DesireState(value=10.0)
        now = _utcnow()

        values = {model.current_value(state, now) for _ in range(20)}
        assert len(values) > 1, "jitter should produce variation"

    def test_current_value_clamped(self):
        """表达欲不超过 [0, 100]"""
        cfg = ConsciousnessConfig(desire_linear_rate=2.0, desire_jitter_pct=0.0)
        model = DesireModel(cfg)

        low_state = DesireState(value=0.0, last_express_at=None)
        assert model.current_value(low_state, _utcnow()) >= 0.0

        high_state = DesireState(value=200.0, last_express_at=None)
        assert model.current_value(high_state, _utcnow()) <= 100.0

    def test_should_express_respects_threshold_and_decay(self):
        """低于阈值不触发，decay 期内不触发"""
        cfg = ConsciousnessConfig(desire_threshold=60.0, desire_decay_minutes=120)
        model = DesireModel(cfg)
        now = _utcnow()

        low_state = DesireState(value=5.0, last_express_at=None)
        assert model.should_express(low_state, now) is False

        high_state = DesireState(value=80.0, last_express_at=(now - timedelta(minutes=10)).isoformat())
        assert model.should_express(high_state, now) is False

        old_state = DesireState(value=80.0, last_express_at=(now - timedelta(minutes=200)).isoformat())
        assert model.should_express(old_state, now) is True

    def test_apply_pulse(self):
        """正 mood_impact 产生脉冲，非正值返回 0"""
        cfg = ConsciousnessConfig(desire_pulse_base=25.0)
        model = DesireModel(cfg)

        assert model.apply_pulse(0.5) == 12.5
        assert model.apply_pulse(0.0) == 0.0
        assert model.apply_pulse(-0.3) == 0.0


# ── MoodModel ────────────────────────────────────────────────


class TestMoodModel:
    def test_apply_event_clamps(self):
        """apply_event 夹紧到合法范围"""
        cfg = ConsciousnessConfig()
        model = MoodModel(cfg)
        state = MoodState(valence=0.9, arousal=0.9)
        now = _utcnow()

        nv, na = model.apply_event(state, 0.5, 0.5, now)
        assert nv == 1.0
        assert na == 1.0

        nv, na = model.apply_event(state, -2.0, -2.0, now)
        assert nv == -1.0
        assert na == 0.0

    def test_regress_to_baseline_converges(self):
        """无事件时向基线逐步收敛"""
        cfg = ConsciousnessConfig(mood_regression_rate=0.1)
        model = MoodModel(cfg)
        state = MoodState(
            valence=0.9,
            arousal=0.1,
            baseline_valence=0.3,
            baseline_arousal=0.5,
        )

        # 多次回归后应靠近基线
        for _ in range(30):
            nv, na = model.regress_to_baseline(state)
            state.valence = nv
            state.arousal = na

        assert state.valence == pytest.approx(0.3, abs=0.1)
        assert state.arousal == pytest.approx(0.5, abs=0.1)

    def test_to_label_coverage(self):
        """to_label 对典型值返回合理标签"""
        cfg = ConsciousnessConfig()
        model = MoodModel(cfg)

        test_cases = [
            (0.3, 0.1, "平静"),
            (0.6, 0.2, "放松"),
            (-0.5, 0.2, "低落"),
            (0.8, 0.5, "开心"),
            (0.3, 0.5, "愉悦"),
            (-0.7, 0.5, "烦躁"),
            (-0.2, 0.5, "不安"),
            (0.0, 0.5, "清醒"),
            (0.8, 0.9, "兴奋"),
            (0.2, 0.9, "激动"),
            (-0.8, 0.9, "愤怒"),
            (-0.3, 0.9, "焦虑"),
            (0.0, 0.9, "警觉"),
        ]
        for valence, arousal, expected_label in test_cases:
            label, desc = model.to_label(valence, arousal)
            assert label == expected_label, f"({valence}, {arousal}) → {label}, expected {expected_label}"
            assert isinstance(desc, str)
            assert len(desc) > 0


# ── 集成：StateStore + 经验追加 ──────────────────────────────


class TestStateStoreExperiences:
    @pytest.mark.asyncio
    async def test_append_experience_respects_max(self, tmp_path: Path):
        """今日经历追加并限制最大条数"""
        data_dir = _make_test_db_dir(tmp_path)
        fs = _fresh_state_store(data_dir)
        fs.cfg.today_experiences_max = 3

        await fs.store.start()
        try:
            for i in range(5):
                mutation = StateMutation(
                    today_experiences_append=Experience(
                        time=f"1{i}:00",
                        content=f"event {i}",
                        topic_hash=f"topic_{i}",
                    )
                )
                await fs.store.submit_mutation(mutation)
            await asyncio.sleep(0.3)

            state = await fs.store.read()
            assert len(state.today_experiences) == 3
            assert state.today_experiences[-1].content == "event 4"
        finally:
            await fs.store.stop()

    @pytest.mark.asyncio
    async def test_clear_experiences(self, tmp_path: Path):
        """today_experiences_clear 清空列表"""
        data_dir = _make_test_db_dir(tmp_path)
        fs = _fresh_state_store(data_dir)

        await fs.store.start()
        try:
            await fs.store.submit_mutation(
                StateMutation(
                    today_experiences_append=Experience(
                        time="10:00", content="test", topic_hash="t1"
                    )
                )
            )
            await asyncio.sleep(0.2)
            state = await fs.store.read()
            assert len(state.today_experiences) == 1

            await fs.store.submit_mutation(StateMutation(today_experiences_clear=True))
            await asyncio.sleep(0.2)
            state = await fs.store.read()
            assert len(state.today_experiences) == 0
        finally:
            await fs.store.stop()


# ── B1.1 Living World Model 富字段 ───────────────────────────


class TestLivingWorldModelB11:
    """Phase 4b 任务 B1.1：LifeState Living World 富字段 + 旧 JSON 兼容 + roundtrip。"""

    def test_default_life_has_living_world_semantics(self):
        """默认 LifeState 必须带人能理解的生活语义默认值，而非占位。"""
        life = NenoState().life
        assert life.place == "quiet_room"
        assert life.time_phase == "unknown"
        assert life.environment.summary == "安静的房间"
        assert life.activity_label == "安静观察"
        assert life.activity_reason == "没有新的外部刺激，维持低强度观察"
        assert life.continuity_note == ""

    def test_old_life_json_without_rich_fields_gets_defaults(self):
        """旧 life JSON（只有 4a 字段，无富字段）读取时自动补 B1.1 默认值。"""
        old = {
            "version": 2,
            "revision": 5,
            "updated_at": None,
            "energy": {"value": 80.0, "status": "awake", "description": "ok"},
            "mood": {
                "valence": 0.3, "arousal": 0.5, "label": "平静", "description": "ok",
                "baseline_valence": 0.3, "baseline_arousal": 0.5,
            },
            "desire": {"value": 0.0, "last_express_at": None, "decay_duration_minutes": 120},
            "world": {"weather": None, "hot_topics": [], "time_context": "", "last_perception_at": None},
            "last_interaction": {"user_id": None, "user_name": None, "summary": None, "at_time": None},
            "life": {
                "mode": "absorbed",
                "attention": "memory",
                "need": {"connection": 0.0, "novelty": 0.0, "quiet": 0.0, "order": 0.0},
                "current_activity": "carrying_unspoken_thought",
                "last_transition_at": None,
                "residue": {"topic": "旧事", "mood": "soft", "intensity": 0.4},
            },
            "today_experiences": [],
        }

        state = NenoState.model_validate(old)

        # 旧字段必须保留
        assert state.life.mode == "absorbed"
        assert state.life.current_activity == "carrying_unspoken_thought"
        assert state.life.residue.topic == "旧事"
        # 富字段必须自动补默认
        assert state.life.place == "quiet_room"
        assert state.life.time_phase == "unknown"
        assert state.life.environment.summary == "安静的房间"
        assert state.life.activity_label == "安静观察"
        assert state.life.activity_reason == "没有新的外部刺激，维持低强度观察"
        assert state.life.continuity_note == ""

    def test_life_rich_fields_json_roundtrip(self):
        """富字段经 model_dump_json / model_validate_json 完整 roundtrip。"""
        from app.services.consciousness.models import LifeEnvironment

        state = NenoState()
        state.life.place = "out"
        state.life.time_phase = "afternoon"
        state.life.environment = LifeEnvironment(summary="外面有点吵")
        state.life.activity_label = "出门买奶茶"
        state.life.activity_reason = "想换个心情"
        state.life.continuity_note = "上午写代码写累了"

        restored = NenoState.model_validate_json(state.model_dump_json())

        assert restored.life.place == "out"
        assert restored.life.time_phase == "afternoon"
        assert restored.life.environment.summary == "外面有点吵"
        assert restored.life.activity_label == "出门买奶茶"
        assert restored.life.activity_reason == "想换个心情"
        assert restored.life.continuity_note == "上午写代码写累了"

    @pytest.mark.asyncio
    async def test_life_rich_fields_roundtrip_through_store(self, tmp_path: Path):
        """StateMutation(life=...) 持久化后富字段必须 roundtrip。"""
        from app.services.consciousness.models import LifeEnvironment

        data_dir = _make_test_db_dir(tmp_path)
        fs = _fresh_state_store(data_dir)

        await fs.store.start()
        try:
            await fs.store.submit_mutation(
                StateMutation(
                    life=LifeState(
                        place="home_desk",
                        time_phase="late_night",
                        environment=LifeEnvironment(summary="安静，窗外有雨"),
                        activity_label="整理今天的心情",
                        activity_reason="白天那条暴雨预警一直没说出口",
                        continuity_note="接着下午没说完的那件事",
                    )
                )
            )
            await asyncio.sleep(0.2)

            state = await fs.store.read()
            assert state.life.place == "home_desk"
            assert state.life.time_phase == "late_night"
            assert state.life.environment.summary == "安静，窗外有雨"
            assert state.life.activity_label == "整理今天的心情"
            assert state.life.activity_reason == "白天那条暴雨预警一直没说出口"
            assert state.life.continuity_note == "接着下午没说完的那件事"
        finally:
            await fs.store.stop()
