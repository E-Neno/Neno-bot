from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from app.storage import db as db_storage

from .world_model import WorldDef, WorldState, load_world_def, seed_world_state


class WorldStore:
    """读写 life_world_state 单行表。首读返回种子；坏 JSON 降级。"""

    def __init__(self, world_def: WorldDef | None = None) -> None:
        self._world_def = world_def or load_world_def()

    async def read(self) -> WorldState:
        return await asyncio.to_thread(self._read_sync)

    async def write(self, state: WorldState) -> None:
        await asyncio.to_thread(self._write_sync, state)

    def _read_sync(self) -> WorldState:
        row = db_storage.fetch_one(
            "SELECT state_json FROM life_world_state WHERE id = 1"
        )
        if row is None:
            seed = seed_world_state(self._world_def)
            self._write_sync(seed)
            return seed
        try:
            data = json.loads(row["state_json"])
            state = WorldState.model_validate(data)
            if not state.object_states:  # 空也视为需种子
                raise ValueError("empty world state")
            self._backfill_object_states(state)
            return state
        except Exception:
            return seed_world_state(self._world_def)  # 坏 JSON 降级

    def _backfill_object_states(self, state: WorldState) -> None:
        """老世界在 world_def 加了新物品后，持久化状态里缺这些物品的态。
        给"def 里有、没被扔掉、状态缺失"的物品补默认态——否则它们永远是"?"，
        相关事件（如 chore 看 dish_towel==needs_wash）和 drift 都失效。下次 tick 落库。"""
        for name in self._world_def.objects:
            if name in state.removed:
                continue
            if name not in state.object_states:
                state.object_states[name] = self._world_def.default_state(name)

    def _write_sync(self, state: WorldState) -> None:
        state.updated_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(state.model_dump(), ensure_ascii=False)
        db_storage.execute_write(
            """
            INSERT INTO life_world_state (id, state_json, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (payload, state.updated_at),
        )
