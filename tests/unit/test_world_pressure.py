"""world_pressure 纯函数单元测试。

所有时间用固定 now 时间戳，不依赖 time.time()。
"""
from __future__ import annotations

import pytest

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.world_pressure import (
    PressureState,
    accumulate,
    is_hard,
    on_wake,
    salience_of,
    should_wake,
)


# ── fixtures ─────────────────────────────────────────────────

@pytest.fixture()
def config() -> ConsciousnessConfig:
    return ConsciousnessConfig()


@pytest.fixture()
def state() -> PressureState:
    return PressureState()


# ── 回归：真实 LifeEvent.kind 必须有显著度（曾经词表对不齐=0）──

def test_real_lifeevent_kinds_have_salience(config: ConsciousnessConfig) -> None:
    """world_loop 直接塞 event.kind；这些真实事件必须有非零权重，否则意外永远不驱动唤醒。"""
    for kind in (
        "mishap",
        "message",
        "weather",
        "craving",
        "memory",
        "chore",
        "small_joy",
        "idle_thought",
        "outing",
    ):
        assert salience_of(kind, config) > 0, f"{kind} 显著度为 0，意外会变哑"
    # mishap 必须是 hard（立刻想）
    assert is_hard(["mishap"], config) is True


def test_new_daily_events_have_low_salience(config: ConsciousnessConfig) -> None:
    for kind in ("chore", "small_joy", "idle_thought", "outing"):
        assert 10.0 <= salience_of(kind, config) <= 20.0
        assert is_hard([kind], config) is False


# ── 回归：预算窗口过期后必须解锁（曾经死锁）─────────────────

def test_budget_unlocks_after_hour_window_passes(config: ConsciousnessConfig) -> None:
    """打满预算后，过了 1 小时窗口、即使期间没醒过，也必须能再次唤醒。

    历史 bug：跨小时重置只在 on_wake 里做，而预算又挡住 on_wake → 永久死锁。
    """
    # 构造"本小时已打满预算"的状态：anchor 在 t=0，wakes 已达上限
    full = PressureState(
        value=config.world_pressure_threshold + 50,  # 压力远超阈值
        last_wake_ts=0.0,
        wakes_this_hour=config.world_wake_budget_per_hour,
        hour_anchor=0.0,
    )
    # 同一小时内（且已过 min_gap）→ 被预算挡住
    wake, reason = should_wake(full, config, now=120.0)
    assert wake is False and reason == "budget"

    # 过了 1 小时窗口（now >= 3600）→ 窗口视为重置，应能因 threshold 唤醒
    wake2, reason2 = should_wake(full, config, now=3700.0)
    assert wake2 is True and reason2 == "threshold"


# ── salience_of ──────────────────────────────────────────────

class TestSalienceOf:
    def test_known_kind(self, config: ConsciousnessConfig) -> None:
        assert salience_of("kettle_broken", config) == 50.0
        assert salience_of("message_in", config) == 40.0
        assert salience_of("plant_thirsty", config) == 10.0

    def test_unknown_kind_returns_zero(self, config: ConsciousnessConfig) -> None:
        assert salience_of("alien_landing", config) == 0.0

    def test_config_override(self) -> None:
        cfg = ConsciousnessConfig(world_salience={"kettle_broken": 999.0})
        assert salience_of("kettle_broken", cfg) == 999.0
        # 未被覆盖的仍走默认
        assert salience_of("message_in", cfg) == 40.0

    def test_env_json_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CONSCIOUSNESS_WORLD_SALIENCE env JSON 可覆盖默认值。"""
        import app.services.consciousness.config as cfg_mod
        monkeypatch.setenv(
            "CONSCIOUSNESS_WORLD_SALIENCE",
            '{"kettle_broken": 999, "custom_event": 77}',
        )
        # 重新读取 env
        parsed = cfg_mod._parse_salience_env()
        assert parsed["kettle_broken"] == 999.0
        assert parsed["custom_event"] == 77.0

    def test_env_json_bad_input_no_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非法 JSON 不抛异常，返回空 dict。"""
        import app.services.consciousness.config as cfg_mod
        monkeypatch.setenv("CONSCIOUSNESS_WORLD_SALIENCE", "not json {{{")
        assert cfg_mod._parse_salience_env() == {}


# ── accumulate ───────────────────────────────────────────────

class TestAccumulate:
    def test_boredom_drip_only(self, state: PressureState, config: ConsciousnessConfig) -> None:
        new = accumulate(state, [], config, now=100.0)
        assert new.value == pytest.approx(1.0)  # boredom_drip = 1.0

    def test_events_add_up(self, state: PressureState, config: ConsciousnessConfig) -> None:
        new = accumulate(state, ["action_done", "plant_thirsty"], config, now=100.0)
        # 20 + 10 + 1(drip) = 31
        assert new.value == pytest.approx(31.0)

    def test_does_not_mutate_original(self, state: PressureState, config: ConsciousnessConfig) -> None:
        original_value = state.value
        accumulate(state, ["kettle_broken"], config, now=100.0)
        assert state.value == original_value


# ── should_wake ──────────────────────────────────────────────

class TestShouldWake:
    def test_accumulating_below_threshold(
        self, state: PressureState, config: ConsciousnessConfig
    ) -> None:
        ok, reason = should_wake(state, config, now=100.0)
        assert ok is False
        assert reason == "accumulating"

    def test_threshold_reached(self, config: ConsciousnessConfig) -> None:
        s = PressureState(value=100.0)
        ok, reason = should_wake(s, config, now=100.0)
        assert ok is True
        assert reason == "threshold"

    def test_hard_event_over_threshold_gap(
        self, state: PressureState, config: ConsciousnessConfig
    ) -> None:
        ok, reason = should_wake(state, config, now=100.0, hard_event=True)
        assert ok is True
        assert reason == "hard_event"

    def test_min_gap_blocks_even_with_high_pressure(self, config: ConsciousnessConfig) -> None:
        s = PressureState(value=999.0, last_wake_ts=50.0)
        # now=80 → 距上次 30s < min_gap 60s
        ok, reason = should_wake(s, config, now=80.0)
        assert ok is False
        assert reason == "min_gap"

    def test_min_gap_blocks_hard_event_too(self, config: ConsciousnessConfig) -> None:
        s = PressureState(value=0.0, last_wake_ts=50.0)
        ok, reason = should_wake(s, config, now=80.0, hard_event=True)
        assert ok is False
        assert reason == "min_gap"

    def test_budget_exhausted(self, config: ConsciousnessConfig) -> None:
        s = PressureState(value=999.0, wakes_this_hour=12, hour_anchor=0.0)
        ok, reason = should_wake(s, config, now=100.0)
        assert ok is False
        assert reason == "budget"

    def test_budget_exhausted_blocks_hard_event(self, config: ConsciousnessConfig) -> None:
        s = PressureState(value=0.0, wakes_this_hour=12, hour_anchor=0.0)
        ok, reason = should_wake(s, config, now=100.0, hard_event=True)
        assert ok is False
        assert reason == "budget"

    def test_after_min_gap_pressure_wakes(self, config: ConsciousnessConfig) -> None:
        s = PressureState(value=100.0, last_wake_ts=50.0)
        # now=120 → 距上次 70s >= min_gap 60s
        ok, reason = should_wake(s, config, now=120.0)
        assert ok is True
        assert reason == "threshold"


# ── on_wake ──────────────────────────────────────────────────

class TestOnWake:
    def test_resets_value_and_increments_count(self) -> None:
        s = PressureState(value=88.0, wakes_this_hour=3, hour_anchor=0.0)
        new = on_wake(s, now=100.0)
        assert new.value == 0.0
        assert new.last_wake_ts == 100.0
        assert new.wakes_this_hour == 4

    def test_cross_hour_resets_count(self) -> None:
        s = PressureState(value=50.0, wakes_this_hour=10, hour_anchor=0.0)
        # now=4000 → 距 hour_anchor 4000s >= 3600 → 跨小时
        new = on_wake(s, now=4000.0)
        assert new.wakes_this_hour == 1
        assert new.hour_anchor == 4000.0

    def test_first_wake_sets_anchor(self) -> None:
        s = PressureState(value=10.0, hour_anchor=None)
        new = on_wake(s, now=200.0)
        assert new.hour_anchor == 200.0
        assert new.wakes_this_hour == 1


# ── is_hard ──────────────────────────────────────────────────

class TestIsHard:
    def test_hard_event_detected(self, config: ConsciousnessConfig) -> None:
        assert is_hard(["kettle_broken"], config) is True  # 50 >= 50
        assert is_hard(["message_in"], config) is False    # 40 < 50

    def test_no_hard_event(self, config: ConsciousnessConfig) -> None:
        assert is_hard(["action_done", "plant_thirsty"], config) is False

    def test_mixed_with_hard(self, config: ConsciousnessConfig) -> None:
        assert is_hard(["plant_thirsty", "kettle_broken"], config) is True

    def test_empty_list(self, config: ConsciousnessConfig) -> None:
        assert is_hard([], config) is False


# ── boredom drip 持续累积 ────────────────────────────────────

class TestBoredomDrip:
    def test_monotonic_increase(self, config: ConsciousnessConfig) -> None:
        """多次无事件 tick，value 应单调递增。"""
        s = PressureState()
        values = []
        for i in range(10):
            s = accumulate(s, [], config, now=float(i * 30))
            values.append(s.value)
        # 每次应比上次大
        for a, b in zip(values, values[1:]):
            assert b > a
        # 最终值 = 10 * boredom_drip = 10.0
        assert s.value == pytest.approx(10.0)
