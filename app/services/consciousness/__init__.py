from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .brain import NenoBrain
from .config import ConsciousnessConfig
from .event_pool import EventPool
from .fragmenter import Fragmenter
from .interrupt import InterruptController
from .memory_recall import MemoryRecall
from .perception import PerceptionService
from .state_store import StateStore
from .world_engine import WorldEngine


class ConsciousnessEngine:
    """consciousness 层总门面。Phase 3a：启动 StateStore + WorldEngine + NenoBrain。"""

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

        # Phase 3a: Brain components
        self.recall = MemoryRecall(db, self.config)
        self._fragmenter = Fragmenter(self.config)
        self.interrupt = InterruptController()
        self._brain = NenoBrain(
            state_store=self.state_store,
            pool=self._pool,
            recall=self.recall,
            fragmenter=self._fragmenter,
            interrupt=self.interrupt,
            config=self.config,
        )

    async def start(self) -> None:
        await self.state_store.start()
        self._world_engine.register_jobs()

        # Phase 3a: Register brain cycle
        self._scheduler.add_job(
            self._brain.run_cycle,
            "interval",
            seconds=self.config.brain_cycle_interval_seconds,
            id="brain_cycle",
            replace_existing=True,
        )

    async def stop(self) -> None:
        await self.state_store.stop()
