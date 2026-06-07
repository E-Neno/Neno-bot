from __future__ import annotations

import logging
from datetime import date

from .config import ConsciousnessConfig
from .daily_planner import DailyPlanner
from .models import StateMutation
from .state_store import StateStore
from .world_store import WorldStore

_log = logging.getLogger(__name__)

SLEEP_ENERGY_THRESHOLD = 20.0  # 夜间精力低于此值则入睡


class DayCycle:
    """时段判定 + 睡眠/醒来/跨天结算。

    on_wake 复用 ReflectionEngine（沉淀昨天 → 长期记忆）与 DailyPlanner（生成今日计划），
    并把昨天未完成的计划项跨天带过来。
    """

    def __init__(self, config: ConsciousnessConfig) -> None:
        self._cfg = config

    # ── 时段 ──────────────────────────────────────────────────────────────
    def phase_of(self, hour: int) -> str:
        if 5 <= hour < 11:
            return "morning"
        if 11 <= hour < 17:
            return "afternoon"
        if 17 <= hour < 22:
            return "evening"
        return "night"

    def check_sleep_wake(self, nstate, phase: str, hour: int) -> str | None:
        status = nstate.energy.status
        value = nstate.energy.value
        if phase == "night" and status == "awake" and value < SLEEP_ENERGY_THRESHOLD:
            return "fall_asleep"
        if phase == "morning" and status == "sleeping":
            return "wake_up"
        return None

    # ── 睡眠 / 醒来 ───────────────────────────────────────────────────────
    async def on_sleep(self, state_store: StateStore) -> None:
        nstate = await state_store.read()
        energy = nstate.energy.model_copy(deep=True)
        energy.status = "sleeping"
        energy.description = "睡着了"
        await state_store.submit_mutation(
            StateMutation(energy=energy, reason="day_cycle: fall asleep")
        )

    async def on_wake(
        self,
        state_store: StateStore,
        reflection_engine,
        world_store: WorldStore,
        daily_planner: DailyPlanner,
        *,
        today: str,
        yesterday: date,
    ) -> None:
        # 1. 反思昨天 → 沉淀长期记忆（复用 C1.5 ReflectionEngine）
        try:
            await reflection_engine.run_once(trace_id="wake", _target_day=yesterday)
        except Exception as exc:  # noqa: BLE001
            _log.warning("on_wake reflection failed: %s", exc)

        # 2. 昨天未完成的计划项 → 跨天带过来
        ws = await world_store.read()
        carried: list[str] = []
        if ws.daily_plan and isinstance(ws.daily_plan.get("items"), list):
            carried = [
                it.get("intent", "")
                for it in ws.daily_plan["items"]
                if not it.get("done") and it.get("intent")
            ]

        # 3. 生成今日计划（含昨天残留情绪）
        nstate = await state_store.read()
        residue = nstate.life.residue.topic if nstate.life and nstate.life.residue else ""
        plan = await daily_planner.make_plan(
            date=today, residue=residue, carried_over=carried
        )
        ws.daily_plan = plan.model_dump()
        await world_store.write(ws)

        # 4. 精力恢复，醒来
        energy = nstate.energy.model_copy(deep=True)
        energy.status = "awake"
        energy.value = self._cfg.energy_wake_value
        energy.description = "睡醒了，精力还不错"
        await state_store.submit_mutation(
            StateMutation(energy=energy, reason="day_cycle: wake up")
        )
