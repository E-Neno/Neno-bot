"""精力的真实时间积分模型（纯函数，好测）。

把精力从「每 tick 量化掉一点」改成「按真实经过的时间积分」：醒着掉电、睡着回血，
速率受 活动 / 心情 / 昼夜 调制。单个 tick 自对账，不依赖 24/7 连续 tick——
两拍之间隔多久就结算多久，停机/坏时钟用 cap 兜住，不产生尖刺。

睡 / 醒的转换由阈值在 day_cycle.check_sleep_wake 判定，本模块只负责"值"怎么变。
"""
from __future__ import annotations

from .models import EnergyState

# ── 调参常量（第一刀用代码常量，仿 SLEEP_ENERGY_THRESHOLD；第二步可提升为 env）──
ENERGY_BASE_DRAIN_PER_MIN = 0.078   # 活动=1.0 时 ~16h 把 95→20
ENERGY_RECOVER_PER_MIN = 0.15       # ~8h 把 20→90
ELAPSED_CAP_MIN = 720.0             # 单次结算最多算 12h，防停机/坏时钟尖刺
WAKE_ENERGY_THRESHOLD = 90.0        # 睡到此值自然醒（SLEEP_ENERGY_THRESHOLD 在 day_cycle）

# 动作关键词 → 体力消耗倾向
_TIRE_KEYS = ("整理", "收拾", "打扫", "做饭", "烧水", "浇花", "出门", "搬", "洗", "运动", "买")
_REST_KEYS = ("发呆", "休息", "歇", "睡", "读", "听", "看书", "看")


def _elapsed_min(prev_ts: float | None, now: float) -> float:
    """上次结算到现在的分钟数，clamp 到 [0, ELAPSED_CAP_MIN]。prev_ts 为空(冷启动)→0。"""
    if not prev_ts:
        return 0.0
    return max(0.0, min((now - prev_ts) / 60.0, ELAPSED_CAP_MIN))


def activity_mult(action: str) -> float:
    """费神动作更耗电，静养动作省电。费神优先（避免"看着做饭"被判静养）。"""
    a = action or ""
    if any(k in a for k in _TIRE_KEYS):
        return 1.4
    if any(k in a for k in _REST_KEYS):
        return 0.6
    return 1.0


def mood_mult(valence: float) -> float:
    """心情差更累，心情好省力。"""
    if valence < 0.0:
        return 1.2
    if valence > 0.5:
        return 0.9
    return 1.0


def circadian_mult(hour8: int) -> float:
    """软锚：深夜更困、午后微困；不刚性，只把就寝拉向夜里防相位漂移。"""
    if 23 <= hour8 or hour8 < 5:
        return 1.3
    if 12 <= hour8 < 15:
        return 1.05
    return 1.0


def step_energy(
    energy: EnergyState,
    *,
    status: str,
    action: str,
    valence: float,
    hour8: int,
    now: float,
    time_scale: float = 1.0,
) -> EnergyState:
    """按真实经过时间结算精力，返回新的 EnergyState（不改入参，clamp 到 0..100）。

    status="sleeping" → 回血；否则按 基础速率 × 活动 × 心情 × 昼夜 掉电。
    无论睡醒都盖上 updated_real_ts=now（下次结算的锚点）。
    time_scale>1.0 把经过时间放大（观察/调试加速；1.0=真实同步）。
    """
    new = energy.model_copy(deep=True)
    dt = _elapsed_min(energy.updated_real_ts, now) * max(0.0, time_scale)
    if status == "sleeping":
        new.value = min(100.0, energy.value + ENERGY_RECOVER_PER_MIN * dt)
    else:
        drain = (
            ENERGY_BASE_DRAIN_PER_MIN * dt
            * activity_mult(action) * mood_mult(valence) * circadian_mult(hour8)
        )
        new.value = max(0.0, energy.value - drain)
    new.updated_real_ts = now
    return new
