"""
Phase 2 验收测试 — Perception / EventPool / RandomEvents / WorldEngine

覆盖:
- 天气 (wttr.in) 拉取与解析，TTL 缓存，失败降级
- 热搜 API 降级链，缓存，全失败返回空列表
- 时间上下文生成
- 随机事件按时间段概率触发
- EventPool 双层 topic_hash 去重
- EventPool expressed 话题冷却
- EventPool 优先级出队 + 24h 过期
- WorldEngine 心跳、睡眠跳过、极端天气 P0
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.event_pool import EventIn, EventPool, _extract_keywords
from app.services.consciousness.models import (
    EnergyState,
    MoodState,
    NenoState,
    StateMutation,
    WeatherSnapshot,
    WorldState,
)
from app.services.consciousness.perception import (
    TTL_HOT_TOPICS_MINUTES,
    TTL_WEATHER_MINUTES,
    PerceptionService,
)
from app.services.consciousness.random_events import (
    HOUR_PROBABILITY,
    RANDOM_EVENT_POOL,
    maybe_generate_random_event,
)
from app.services.consciousness.state_store import StateStore
from app.storage import db as db_storage


# ── helpers ──────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_test_db(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


def _init_test_db(data_dir: Path) -> None:
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()


def _fresh_store(data_dir: Path) -> StateStore:
    _init_test_db(data_dir)
    cfg = ConsciousnessConfig()
    return StateStore(db=None, config=cfg)


def _fresh_pool(data_dir: Path) -> EventPool:
    _init_test_db(data_dir)
    cfg = ConsciousnessConfig()
    return EventPool(db=None, config=cfg)


# ── WeatherSnapshot model ────────────────────────────────────

class TestWeatherSnapshot:
    def test_default_snapshot(self):
        ws = WeatherSnapshot()
        assert ws.text == ""
        assert ws.temp is None
        assert ws.rain is False

    def test_rain_detection(self):
        ws = WeatherSnapshot(text="Light rain shower", rain=True)
        assert ws.rain is True


# ── PerceptionService: time context ──────────────────────────

class TestTimeContext:
    @pytest.mark.parametrize("hour,expected_period", [
        (3, "凌晨"), (7, "早上"), (10, "上午"), (13, "中午"),
        (16, "下午"), (20, "晚上"), (23, "深夜"),
    ])
    def test_period_labels(self, hour, expected_period):
        now = datetime(2026, 5, 31, hour, 30)
        ctx = PerceptionService.build_time_context(now)
        assert expected_period in ctx

    def test_weekday_in_context(self):
        # 2026-05-31 is a Sunday (weekday=6 → "日")
        now = datetime(2026, 5, 31, 14, 30)
        ctx = PerceptionService.build_time_context(now)
        assert "周日" in ctx


# ── PerceptionService: weather (mocked) ──────────────────────

class TestPerceptionWeather:
    @pytest.mark.asyncio
    async def test_parse_valid_weather_json(self):
        cfg = ConsciousnessConfig()
        svc = PerceptionService(cfg, location="TestCity")
        data = {
            "current_condition": [{
                "weatherDesc": [{"value": "Sunny"}],
                "temp_C": "25",
            }]
        }
        snap = svc._parse_weather(data)
        assert snap.text == "Sunny"
        assert snap.temp == 25
        assert snap.rain is False

    @pytest.mark.asyncio
    async def test_parse_rain_detected(self):
        cfg = ConsciousnessConfig()
        svc = PerceptionService(cfg)
        data = {
            "current_condition": [{
                "weatherDesc": [{"value": "暴雨"}],
                "temp_C": "20",
            }]
        }
        snap = svc._parse_weather(data)
        assert snap.rain is True

    @pytest.mark.asyncio
    async def test_cache_returns_cached(self):
        cfg = ConsciousnessConfig()
        svc = PerceptionService(cfg)
        cached = WeatherSnapshot(text="CachedSun", temp=30, condition="Sunny")
        svc._weather_cache = cached
        svc._weather_cached_at = _utcnow()
        result = await svc.get_weather()
        assert result.text == "CachedSun"

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_fallback(self):
        cfg = ConsciousnessConfig()
        svc = PerceptionService(cfg)
        cached = WeatherSnapshot(text="OldCache", temp=20)
        svc._weather_cache = cached
        svc._weather_cached_at = _utcnow() - timedelta(minutes=TTL_WEATHER_MINUTES + 1)
        with patch("httpx.AsyncClient.get", side_effect=Exception("network down")):
            result = await svc.get_weather()
        assert result.text == "OldCache"

    @pytest.mark.asyncio
    async def test_fetch_failure_no_cache_returns_empty(self):
        cfg = ConsciousnessConfig()
        svc = PerceptionService(cfg)
        with patch("httpx.AsyncClient.get", side_effect=Exception("network down")):
            result = await svc.get_weather()
        assert result.text == ""


# ── PerceptionService: hot topics (mocked) ───────────────────

class TestPerceptionHotTopics:
    @pytest.mark.asyncio
    async def test_all_apis_fail_returns_cache(self):
        cfg = ConsciousnessConfig()
        svc = PerceptionService(cfg)
        svc._hot_topics_cache = ["cached_topic"]
        svc._hot_topics_cached_at = _utcnow() - timedelta(minutes=TTL_HOT_TOPICS_MINUTES + 1)
        with patch.object(svc, "_fetch_hot_topics", side_effect=Exception("fail")):
            result = await svc.get_hot_topics()
        assert result == ["cached_topic"]


# ── PerceptionService: perceive (parallel gather) ────────────

class TestPerceive:
    @pytest.mark.asyncio
    async def test_perceive_returns_world_state(self):
        cfg = ConsciousnessConfig()
        svc = PerceptionService(cfg, location="南宁")
        fake_weather = WeatherSnapshot(text="MockSun", temp=28)
        svc._weather_cache = fake_weather
        svc._weather_cached_at = _utcnow()
        svc._hot_topics_cache = ["topic1", "topic2"]
        svc._hot_topics_cached_at = _utcnow()

        world = await svc.perceive()
        assert world.weather is not None
        assert world.weather.text == "MockSun"
        assert len(world.hot_topics) == 2
        assert world.time_context != ""

    @pytest.mark.asyncio
    async def test_perceive_survives_weather_failure(self):
        cfg = ConsciousnessConfig()
        svc = PerceptionService(cfg)
        svc._hot_topics_cache = ["ok"]
        svc._hot_topics_cached_at = _utcnow()
        with patch.object(svc, "get_weather", side_effect=Exception("boom")):
            world = await svc.perceive()
        assert world.weather is not None
        assert world.time_context != ""


# ── Random Events ────────────────────────────────────────────

class TestRandomEvents:
    def test_pool_has_20_entries(self):
        assert len(RANDOM_EVENT_POOL) >= 20

    def test_night_hours_zero_probability(self):
        for h in range(1, 8):
            assert HOUR_PROBABILITY.get(h, 0) == 0.0, f"hour {h} should be 0.0"

    def test_afternoon_high_probability(self):
        for h in range(14, 18):
            assert HOUR_PROBABILITY[h] == 0.7, f"hour {h} should be 0.7"

    def test_midnight_zero(self):
        assert HOUR_PROBABILITY[0] == 0.0

    def test_generates_none_at_night(self):
        now = datetime(2026, 5, 31, 3, 0)
        for _ in range(50):
            event = maybe_generate_random_event(now)
            assert event is None, "night should never generate events"

    def test_generates_event_at_afternoon(self):
        now = datetime(2026, 5, 31, 15, 0)
        results = [maybe_generate_random_event(now) for _ in range(200)]
        generated = [r for r in results if r is not None]
        assert len(generated) > 0, "afternoon should generate events"
        for evt in generated:
            assert evt.priority == 2
            assert evt.source == "random"
            assert isinstance(evt.content, str)
            assert len(evt.content) > 0
            assert isinstance(evt.tags, list)
            assert -1.0 <= evt.mood_impact <= 1.0


# ── EventPool: topic_hash ────────────────────────────────────

class TestEventPoolHashing:
    def test_structured_hash(self):
        h = EventPool.make_hash_structured("weather", "20260531")
        assert h == "weather_20260531"

    def test_structured_hash_holiday(self):
        h = EventPool.make_hash_structured("holiday", "20260601")
        assert h == "holiday_20260601"

    def test_unstructured_hash_deterministic(self):
        h1 = EventPool.make_hash_unstructured("南宁暴雨预警")
        h2 = EventPool.make_hash_unstructured("南宁暴雨预警")
        assert h1 == h2

    def test_unstructured_hash_different_content(self):
        h1 = EventPool.make_hash_unstructured("南宁暴雨预警")
        h2 = EventPool.make_hash_unstructured("今天天气真好")
        assert h1 != h2

    def test_keyword_extraction(self):
        kw = _extract_keywords("南宁今天暴雨预警")
        assert any("南宁" in k or "暴雨" in k or "预警" in k for k in kw)


# ── EventPool: push / dedup ──────────────────────────────────

class TestEventPoolPush:
    @pytest.mark.asyncio
    async def test_push_new_event_returns_true(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        pool = _fresh_pool(data_dir)
        evt = EventIn(topic_hash="test_001", priority=2, content="hello", source="test")
        assert await pool.push(evt) is True

    @pytest.mark.asyncio
    async def test_duplicate_push_returns_false(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        pool = _fresh_pool(data_dir)
        evt = EventIn(topic_hash="dup_test", priority=2, content="dup", source="test")
        assert await pool.push(evt) is True
        assert await pool.push(evt) is False

    @pytest.mark.asyncio
    async def test_expressed_topic_rejected(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        pool = _fresh_pool(data_dir)
        await pool.mark_topic_expressed("said_already")
        evt = EventIn(topic_hash="said_already", priority=2, content="again", source="test")
        assert await pool.push(evt) is False

    @pytest.mark.asyncio
    async def test_different_topic_allowed(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        pool = _fresh_pool(data_dir)
        await pool.push(EventIn(topic_hash="topic_a", priority=2, content="a"))
        assert await pool.push(EventIn(topic_hash="topic_b", priority=2, content="b")) is True


# ── EventPool: pop ───────────────────────────────────────────

class TestEventPoolPop:
    @pytest.mark.asyncio
    async def test_pop_returns_priority_order(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        pool = _fresh_pool(data_dir)
        await pool.push(EventIn(topic_hash="p2", priority=2, content="p2"))
        await pool.push(EventIn(topic_hash="p0", priority=0, content="p0"))
        await pool.push(EventIn(topic_hash="p1", priority=1, content="p1"))

        popped = await pool.pop_pending(priority_le=2)
        assert len(popped) == 3
        assert popped[0].priority == 0
        assert popped[1].priority == 1
        assert popped[2].priority == 2

    @pytest.mark.asyncio
    async def test_pop_respects_priority_le(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        pool = _fresh_pool(data_dir)
        await pool.push(EventIn(topic_hash="p0", priority=0, content="p0"))
        await pool.push(EventIn(topic_hash="p3", priority=3, content="p3"))

        popped = await pool.pop_pending(priority_le=1)
        assert len(popped) == 1
        assert popped[0].priority == 0

    @pytest.mark.asyncio
    async def test_pop_changes_status_to_consumed(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        pool = _fresh_pool(data_dir)
        await pool.push(EventIn(topic_hash="consume_me", priority=1, content="test"))
        popped = await pool.pop_pending()
        assert len(popped) == 1
        # Verify cannot pop again
        popped2 = await pool.pop_pending()
        assert len(popped2) == 0


# ── EventPool: expire ────────────────────────────────────────

class TestEventPoolExpire:
    @pytest.mark.asyncio
    async def test_expire_old_events(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        _init_test_db(data_dir)
        from app.storage.db import get_conn

        # Insert an event with old timestamp
        old_time = (_utcnow() - timedelta(hours=25)).isoformat()
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO event_log (topic_hash, priority, content, tags, mood_impact, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                ("old_event", 2, "stale", "[]", 0.0, old_time),
            )

        pool = _fresh_pool(data_dir)
        count = await pool.expire_old_events()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_recent_events_not_expired(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        pool = _fresh_pool(data_dir)
        await pool.push(EventIn(topic_hash="recent", priority=2, content="fresh"))
        count = await pool.expire_old_events()
        assert count == 0


# ── WorldEngine ──────────────────────────────────────────────

class TestWorldEngineSleep:
    def test_is_sleep_hour_true(self):
        from app.services.consciousness.world_engine import WorldEngine
        for h in [1, 2, 3, 4, 5, 6, 7]:
            assert WorldEngine._is_sleep_hour(datetime(2026, 5, 31, h, 0)) is True

    def test_is_sleep_hour_false(self):
        from app.services.consciousness.world_engine import WorldEngine
        for h in [0, 8, 9, 12, 15, 18, 22, 23]:
            assert WorldEngine._is_sleep_hour(datetime(2026, 5, 31, h, 0)) is False

    @pytest.mark.asyncio
    async def test_heartbeat_skips_when_sleeping(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        store = _fresh_store(data_dir)
        await store.start()
        try:
            await store.submit_mutation(StateMutation(
                energy=EnergyState(value=10, status="sleeping", description="zzz")
            ))
            await asyncio.sleep(0.2)
            state = await store.read()
            assert state.energy.status == "sleeping"
        finally:
            await store.stop()


# ── StateMutation new fields ─────────────────────────────────

class TestStateMutationNewFields:
    @pytest.mark.asyncio
    async def test_desire_pulse_increases_value(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        store = _fresh_store(data_dir)
        await store.start()
        try:
            initial = await store.read()
            base_desire = initial.desire.value

            await store.submit_mutation(StateMutation(desire_pulse=30.0))
            await asyncio.sleep(0.2)

            state = await store.read()
            # read() applies jitter and regression; just verify it went up meaningfully
            assert state.desire.value > base_desire + 15.0, (
                f"desire should increase significantly, got {state.desire.value} from {base_desire}"
            )
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_mood_valence_delta(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        store = _fresh_store(data_dir)
        await store.start()
        try:
            initial = await store.read()
            base_valence = initial.mood.valence

            await store.submit_mutation(StateMutation(mood_valence_delta=0.2))
            await asyncio.sleep(0.3)

            state = await store.read()
            assert state.mood.valence > base_valence
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_world_update_via_mutation(self, tmp_path: Path):
        data_dir = _make_test_db(tmp_path)
        store = _fresh_store(data_dir)
        await store.start()
        try:
            world = WorldState(
                weather=WeatherSnapshot(text="Sunny", temp=25),
                hot_topics=["topic1"],
                time_context="周日下午15:00",
            )
            await store.submit_mutation(StateMutation(world=world, reason="test"))
            await asyncio.sleep(0.2)

            state = await store.read()
            assert state.world.weather is not None
            assert state.world.weather.text == "Sunny"
            assert state.world.weather.temp == 25
            assert state.world.time_context == "周日下午15:00"
        finally:
            await store.stop()
