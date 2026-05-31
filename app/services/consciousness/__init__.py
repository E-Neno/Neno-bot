from .config import ConsciousnessConfig
from .models import NenoState
from .state_store import StateStore


class ConsciousnessEngine:
    """
    consciousness 层总门面。
    Phase 1：只启动 StateStore，不启动世界引擎和调度器。
    """

    def __init__(self, db, config: ConsciousnessConfig | None = None) -> None:
        self.config = config or ConsciousnessConfig()
        self.state_store = StateStore(db, self.config)

    async def start(self) -> None:
        await self.state_store.start()

    async def stop(self) -> None:
        await self.state_store.stop()
