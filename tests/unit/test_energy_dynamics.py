from __future__ import annotations

from app.services.consciousness.energy_dynamics import (
    ELAPSED_CAP_MIN,
    ENERGY_BASE_DRAIN_PER_MIN,
    ENERGY_RECOVER_PER_MIN,
    activity_mult,
    circadian_mult,
    mood_mult,
    step_energy,
)
from app.services.consciousness.models import EnergyState


def test_step_energy_drains_awake():
    """awake、dt=60min、活动=1.0、valence=0.3(中性)、hour=10 → 按基础速率掉电。"""
    now = 10_000.0
    e = EnergyState(value=80.0, status="awake", updated_real_ts=now - 3600.0)
    out = step_energy(e, status="awake", action="随便走走", valence=0.3, hour8=10, now=now)
    # activity=1.0(无关键词), mood=1.0(0<=valence<=0.5), circadian=1.0(白天)
    expected = 80.0 - ENERGY_BASE_DRAIN_PER_MIN * 60.0
    assert abs(out.value - expected) < 0.01
    assert out.updated_real_ts == now


def test_step_energy_recovers_sleeping():
    """sleeping、dt=60min → 按回升速率回血，不超 100。"""
    now = 10_000.0
    e = EnergyState(value=20.0, status="sleeping", updated_real_ts=now - 3600.0)
    out = step_energy(e, status="sleeping", action="睡觉", valence=0.0, hour8=3, now=now)
    expected = 20.0 + ENERGY_RECOVER_PER_MIN * 60.0
    assert abs(out.value - expected) < 0.01


def test_step_energy_clamps():
    now = 10_000.0
    # 掉到 0 不破
    low = EnergyState(value=1.0, status="awake", updated_real_ts=now - 36000.0)
    assert step_energy(low, status="awake", action="", valence=0.0, hour8=10, now=now).value == 0.0
    # 回升不超 100
    high = EnergyState(value=99.0, status="sleeping", updated_real_ts=now - 36000.0)
    assert step_energy(high, status="sleeping", action="", valence=0.0, hour8=3, now=now).value == 100.0


def test_activity_mult():
    assert activity_mult("整理床铺") > 1.0   # 费神
    assert activity_mult("出门买菜") > 1.0
    assert activity_mult("发呆休息") < 1.0    # 静养
    assert activity_mult("读完一章") < 1.0
    assert activity_mult("随便走走") == 1.0   # 中性
    assert activity_mult("") == 1.0


def test_mood_mult():
    assert mood_mult(-0.3) > 1.0   # 心情差更累
    assert mood_mult(0.8) < 1.0    # 心情好省力
    assert mood_mult(0.3) == 1.0   # 中性


def test_circadian_mult():
    assert circadian_mult(23) > 1.0   # 深夜更困
    assert circadian_mult(2) > 1.0
    assert circadian_mult(13) > 1.0   # 午后微困
    assert circadian_mult(10) == 1.0  # 白天正常


def test_elapsed_cap():
    """updated_real_ts 距今 24h → 只算 ELAPSED_CAP_MIN(12h)，不尖刺。"""
    now = 100_000.0
    e = EnergyState(value=95.0, status="awake", updated_real_ts=now - 24 * 3600.0)
    out = step_energy(e, status="awake", action="", valence=0.3, hour8=10, now=now)
    drained = 95.0 - out.value
    max_possible = ENERGY_BASE_DRAIN_PER_MIN * ELAPSED_CAP_MIN
    assert abs(drained - max_possible) < 0.01


def test_first_tick_no_drain():
    """updated_real_ts=None → dt=0 → 精力不变（防冷启动尖刺），但盖上时间戳。"""
    now = 10_000.0
    e = EnergyState(value=80.0, status="awake", updated_real_ts=None)
    out = step_energy(e, status="awake", action="整理床铺", valence=-0.5, hour8=23, now=now)
    assert out.value == 80.0
    assert out.updated_real_ts == now
