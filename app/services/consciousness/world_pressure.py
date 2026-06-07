"""世界压力触发 — 纯决策引擎（第一刀）

不依赖真实时间（所有时间用 now: float 入参），不调 LLM，不改 DB。
设计文档：docs/living_world_design.md 第 3 节。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.consciousness.config import ConsciousnessConfig

# 默认显著度表（当 config.world_salience 为空时使用）
# 同时覆盖两套词汇：① 真实 LifeEvent.kind（mishap/message/weather/craving/memory）
# ② world_loop 内部合成的触发（phase_change/money_low/plant_thirsty/action_done）
_DEFAULT_SALIENCE: dict[str, float] = {
    # —— 真实生活事件（LifeEvent.kind）——
    "mishap": 50.0,        # 出岔子（水壶摔了等）→ hard，立刻想
    "message": 40.0,       # 来消息
    "craving": 20.0,       # 馋了/想做点什么
    "weather": 15.0,       # 天气变化
    "memory": 10.0,        # 翻起一段回忆
    # —— world_loop 内部合成触发 ——
    "kettle_broken": 50.0,
    "message_in": 40.0,
    "money_low": 30.0,
    "action_done": 20.0,
    "phase_change": 15.0,
    "plant_thirsty": 10.0,
}


def _resolve_salience(config: ConsciousnessConfig) -> dict[str, float]:
    """返回合并后的显著度表：config.world_salience 覆盖默认值。"""
    if config.world_salience:
        return {**_DEFAULT_SALIENCE, **config.world_salience}
    return dict(_DEFAULT_SALIENCE)


# ── 显著度查询 ───────────────────────────────────────────────

def salience_of(kind: str, config: ConsciousnessConfig) -> float:
    """从显著度表取权重；未知 kind 返回 0.0。"""
    return _resolve_salience(config).get(kind, 0.0)


# ── 压力状态 ─────────────────────────────────────────────────

@dataclass
class PressureState:
    """可在内存或 JSON 中持久化的压力状态。"""
    value: float = 0.0
    last_wake_ts: float | None = None
    wakes_this_hour: int = 0
    hour_anchor: float | None = None


# ── 纯函数：累积 ─────────────────────────────────────────────

def accumulate(
    state: PressureState,
    event_kinds: list[str],
    config: ConsciousnessConfig,
    *,
    now: float,
) -> PressureState:
    """每 tick 调用：把本 tick 事件的显著度 + 无聊滴漏加到压力上。

    纯函数，返回新 PressureState，不修改原对象。
    """
    added = sum(salience_of(k, config) for k in event_kinds) + config.world_boredom_drip
    return PressureState(
        value=state.value + added,
        last_wake_ts=state.last_wake_ts,
        wakes_this_hour=state.wakes_this_hour,
        hour_anchor=state.hour_anchor,
    )


# ── 纯函数：判断是否唤醒 ────────────────────────────────────

def should_wake(
    state: PressureState,
    config: ConsciousnessConfig,
    *,
    now: float,
    hard_event: bool = False,
) -> tuple[bool, str]:
    """决定是否唤醒 LLM。返回 (是否唤醒, 原因)。

    规则按优先级顺序执行（不得重排）：

    1. min_gap  — 若 now - last_wake_ts < world_wake_min_gap_seconds → False, "min_gap"
    2. budget   — 若当前小时内 wakes_this_hour >= world_wake_budget_per_hour → False, "budget"
    3. hard_event 为真 → True, "hard_event"
    4. state.value >= world_pressure_threshold → True, "threshold"
    5. 否则 → False, "accumulating"

    hard_event 立刻醒但仍受 min_gap 和 budget 约束（防连发烧钱）。
    """
    # 1. min_gap
    if state.last_wake_ts is not None:
        if now - state.last_wake_ts < config.world_wake_min_gap_seconds:
            return False, "min_gap"

    # 2. budget（按真实小时窗口；窗口过期即视为已重置，避免"打满后永久死锁"）
    window_expired = state.hour_anchor is None or (now - state.hour_anchor) >= 3600
    effective_wakes = 0 if window_expired else state.wakes_this_hour
    if effective_wakes >= config.world_wake_budget_per_hour:
        return False, "budget"

    # 3. hard_event
    if hard_event:
        return True, "hard_event"

    # 4. threshold
    if state.value >= config.world_pressure_threshold:
        return True, "threshold"

    # 5. accumulating
    return False, "accumulating"


# ── 纯函数：唤醒后处理 ──────────────────────────────────────

def on_wake(state: PressureState, *, now: float) -> PressureState:
    """唤醒后调用：value 清零，更新 last_wake_ts，处理跨小时重置。

    纯函数，返回新 PressureState。
    """
    # 跨小时：若 hour_anchor 为 None 或已过 3600 秒 → 重置计数
    if state.hour_anchor is None or now - state.hour_anchor >= 3600:
        new_hour_anchor = now
        new_wakes_this_hour = 1
    else:
        new_hour_anchor = state.hour_anchor
        new_wakes_this_hour = state.wakes_this_hour + 1

    return PressureState(
        value=0.0,
        last_wake_ts=now,
        wakes_this_hour=new_wakes_this_hour,
        hour_anchor=new_hour_anchor,
    )


# ── 辅助：判断是否 hard event ────────────────────────────────

def is_hard(event_kinds: list[str], config: ConsciousnessConfig) -> bool:
    """任一 kind 的显著度 >= 50 即为 hard event。"""
    return any(salience_of(k, config) >= 50.0 for k in event_kinds)
