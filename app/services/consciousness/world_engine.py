"""World engine — APScheduler heartbeat coordinating perception → event pool → state updates."""
import json
import logging
import uuid
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.storage.db import add_debug_event

from .config import ConsciousnessConfig
from .event_pool import EventIn, EventPool
from .models import Experience, StateMutation, WorldState
from .perception import PerceptionService
from .random_events import maybe_generate_random_event
from .state_store import StateStore

logger = logging.getLogger(__name__)

EXTREME_WEATHER_KEYWORDS = [
    "暴雨", "台风", "暴雪", "冰雹", "红色预警", "橙色预警",
    "高温红色", "寒潮", "大雾红色", "沙尘暴", "雷电", "龙卷风",
    "storm", "hurricane", "typhoon", "blizzard", "tornado",
    "red alert", "extreme",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorldEngine:
    """世界引擎：APScheduler 驱动的心跳，协调感知→事件生成→状态写入。"""

    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        perception: PerceptionService,
        pool: EventPool,
        state_store: StateStore,
        config: ConsciousnessConfig,
    ) -> None:
        self._scheduler = scheduler
        self._perception = perception
        self._pool = pool
        self._state = state_store
        self._cfg = config

    def register_jobs(self) -> None:
        self._scheduler.add_job(
            self.heartbeat,
            "interval",
            seconds=self._cfg.heartbeat_interval_seconds,
            id="world_engine_heartbeat",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._daily_reset_placeholder,
            "cron",
            hour=3,
            minute=0,
            id="daily_dream",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._expire_events,
            "interval",
            hours=1,
            id="expire_events",
            replace_existing=True,
        )

    async def heartbeat(self) -> None:
        now = _utcnow()
        trace_id = f"heartbeat_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        try:
            state = await self._state.read()

            if state.energy.status == "sleeping":
                logger.debug("heartbeat skipped: sleeping")
                return

            # Check sleep window via config hours as fallback
            if self._is_sleep_hour(now):
                logger.debug("heartbeat skipped: sleep window (config)")
                return

            # ── Parallel: perception + random event ────────────
            world = await self._perception.perceive()

            # Update world perception to state
            await self._state.submit_mutation(StateMutation(
                world=world,
                reason="heartbeat world update",
            ))

            # Extreme weather → P0
            await self._check_extreme_weather(world, now)

            # Random event → P2
            random_event = maybe_generate_random_event(now)
            if random_event is not None:
                pushed = await self._pool.push(random_event)
                if pushed:
                    pulse = random_event.mood_impact * self._cfg.desire_pulse_base
                    await self._state.submit_mutation(StateMutation(
                        desire_pulse=pulse,
                        mood_valence_delta=random_event.mood_impact * 0.3,
                        reason=f"random event: {random_event.content[:30]}",
                    ))

        except Exception:
            logger.exception("heartbeat failed trace_id=%s", trace_id)
            add_debug_event(
                trace_id=trace_id,
                module="world_engine",
                event="heartbeat_crash",
                level="error",
                success=False,
                reason="heartbeat exception caught",
            )

    async def _check_extreme_weather(self, world: WorldState, now: datetime) -> None:
        if world.weather is None:
            return
        if not world.weather.rain:
            return
        text_lower = (world.weather.text or "").lower()
        condition_lower = (world.weather.condition or "").lower()
        combined = f"{text_lower} {condition_lower}"
        is_extreme = any(kw.lower() in combined for kw in EXTREME_WEATHER_KEYWORDS)
        if not is_extreme:
            return

        today = now.strftime("%Y%m%d")
        topic_hash = EventPool.make_hash_structured("weather_extreme", today)
        event = EventIn(
            topic_hash=topic_hash,
            priority=0,
            content=f"天气预警：{world.weather.text}，温度{world.weather.temp}°C",
            tags=["天气", "P0"],
            mood_impact=-0.3,
            source="weather",
        )
        pushed = await self._pool.push(event)
        if pushed:
            logger.info("P0 extreme weather event pushed: %s", world.weather.text)

    async def _daily_reset_placeholder(self) -> None:
        logger.info("daily reset placeholder triggered (Phase 4 will replace)")

    async def _expire_events(self) -> None:
        try:
            count = await self._pool.expire_old_events()
            if count:
                logger.info("expired %d stale events", count)
        except Exception:
            logger.exception("expire_events failed")

    @staticmethod
    def _is_sleep_hour(now: datetime) -> bool:
        h = now.hour
        return h >= 1 and h < 8
