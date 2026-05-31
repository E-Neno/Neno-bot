from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import ConsciousnessConfig
from .event_pool import EventPool
from .perception import PerceptionService
from .state_store import StateStore
from .world_engine import WorldEngine


class ConsciousnessEngine:
    """consciousness 层总门面。Phase 2：启动 StateStore + WorldEngine。"""

    def __init__(
        self,
        db: Any,
        scheduler: AsyncIOScheduler,
        config: ConsciousnessConfig | None = None,
    ) -> None:
        self.config = config or ConsciousnessConfig()
        self._db = db
        self._scheduler = scheduler

        self.state_store = StateStore(db, self.config)
        self._perception = PerceptionService(self.config)
        self._pool = EventPool(db, self.config)
        self._world_engine = WorldEngine(
            scheduler, self._perception, self._pool,
            self.state_store, self.config,
        )

    async def start(self) -> None:
        await self.state_store.start()
        self._world_engine.register_jobs()

    async def stop(self) -> None:
        await self.state_store.stop()
