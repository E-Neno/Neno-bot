from __future__ import annotations

import logging
import time
from datetime import date

from .config import ConsciousnessConfig
from .daily_planner import DailyPlanner
from .energy_dynamics import WAKE_ENERGY_THRESHOLD
from .models import StateMutation
from .state_store import StateStore
from .world_model import find_goal_thread, find_thread, make_thread
from .world_store import WorldStore
from app.utils.logging_utils import log_event

_log = logging.getLogger(__name__)

SLEEP_ENERGY_THRESHOLD = 20.0  # 精力低于此值则自然入睡（涌现，不再看时段）

# ── 牵挂常量（第一刀，第二刀提升为 env）───────────────────────────────────
THREAD_DECAY = 0.6           # 每日衰减乘数
THREAD_DROP_BELOW = 0.1      # 低于此强度自动下线
RESIDUE_BIRTH_MIN = 0.4      # 残留强度 ≥ 此值才升格为牵挂
# 对账：reflection 的 residue 常态 ≈ 0.45（micro_event salience），空日子回落到默认 0.3。
# 阈值取 0.4 → 有真实经历的日子留下余波牵挂，平淡的日子不留，避免丙路径长期哑火。
GOAL_ACTIVE_CARRY = 2        # carry_count ≥ 此值才算"活跃牵挂"
GOAL_BIRTH_INTENSITY = 0.3   # 新 goal 牵挂初始强度


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

    def check_sleep_wake(self, nstate) -> str | None:
        """睡/醒只看精力阈值（涌现作息），不再受时段闸门约束。

        累了就睡（昼夜调制让多落在夜里）、睡够就醒（回血到 WAKE_ENERGY_THRESHOLD）；
        不规律但有界、单 tick 自对账。旧的 phase/hour 刚性闸门已删除。
        """
        status = nstate.energy.status
        value = nstate.energy.value
        if status == "awake" and value < SLEEP_ENERGY_THRESHOLD:
            return "fall_asleep"
        if status == "sleeping" and value >= WAKE_ENERGY_THRESHOLD:
            return "wake_up"
        return None

    # ── 睡眠 / 醒来 ───────────────────────────────────────────────────────
    async def on_sleep(self, state_store: StateStore) -> None:
        nstate = await state_store.read()
        energy = nstate.energy.model_copy(deep=True)
        energy.status = "sleeping"
        energy.description = "睡着了"
        energy.updated_real_ts = time.time()  # 切睡眠时重置积分锚点，下拍按睡眠回血
        log_event("consciousness", "fell_asleep", energy=round(nstate.energy.value, 1))
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

        # 3. 读残留情绪（完整 LifeResidue，用于牵挂 + 计划）
        nstate = await state_store.read()
        residue_obj = nstate.life.residue if nstate.life and nstate.life.residue else None
        residue = residue_obj.topic if residue_obj else ""

        # 3b. 牵挂维护：衰减 → goal 升格 → residue 牵挂 → 下线
        today_str = yesterday.isoformat()  # 真实日期
        threads = list(ws.open_threads or [])
        # 先衰减
        for t in threads:
            t["intensity"] = round(t["intensity"] * THREAD_DECAY, 4)
            t["last_touch_day"] = today_str
        # goal 升格：已有 → carry_count+1, intensity+0.2；没有 → 新建
        for intent in carried:
            existing = find_goal_thread(threads, intent)
            if existing:
                existing["carry_count"] = existing.get("carry_count", 0) + 1
                existing["intensity"] = min(1.0, round(existing["intensity"] + 0.2, 4))
                existing["last_touch_day"] = today_str
            else:
                threads.append(make_thread(
                    "goal", intent, day=today_str, intensity=GOAL_BIRTH_INTENSITY,
                ))
                threads[-1]["carry_count"] = 1
        # residue 牵挂：强度 ≥ 阈值才升格
        if residue_obj and residue_obj.intensity >= RESIDUE_BIRTH_MIN and residue:
            tid = f"residue:{residue}"
            existing = find_thread(threads, tid)
            if existing:
                existing["intensity"] = residue_obj.intensity
                existing["mood"] = residue_obj.mood
                existing["last_touch_day"] = today_str
            else:
                threads.append(make_thread(
                    "residue", residue, day=today_str,
                    intensity=residue_obj.intensity, mood=residue_obj.mood,
                ))
        # 下线：resolved 或强度过低
        threads = [t for t in threads if not t.get("resolved") and t["intensity"] >= THREAD_DROP_BELOW]
        ws.open_threads = threads
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
        energy.updated_real_ts = time.time()  # 切清醒时重置积分锚点，下拍按活动掉电
        log_event("consciousness", "woke_up", day=today, carried=len(carried))
        await state_store.submit_mutation(
            StateMutation(energy=energy, reason="day_cycle: wake up")
        )
