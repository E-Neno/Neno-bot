import random
from datetime import datetime, timedelta

from .config import ConsciousnessConfig
from .models import DesireState


class DesireModel:
    """表达欲实时推算模型 — 线性增长 + 随机抖动"""

    def __init__(self, config: ConsciousnessConfig) -> None:
        self.cfg = config

    def current_value(self, state: DesireState, now: datetime) -> float:
        """实时推算当前表达欲（不写库，只计算）"""
        base = state.value

        # 线性增长：按分钟累计
        last_express = state.last_express_at
        if isinstance(last_express, str):
            last_express = datetime.fromisoformat(last_express)
        if last_express is not None:
            elapsed_minutes = (now - last_express).total_seconds() / 60.0
            base += self.cfg.desire_linear_rate * elapsed_minutes

        # 随机抖动
        jitter = base * self.cfg.desire_jitter_pct * random.uniform(-1.0, 1.0)
        base += jitter

        return max(0.0, min(100.0, base))

    def apply_pulse(self, base_impact: float) -> float:
        """根据事件 mood_impact 计算注入脉冲量"""
        if base_impact <= 0:
            return 0.0
        return self.cfg.desire_pulse_base * base_impact

    def should_express(self, state: DesireState, now: datetime) -> bool:
        """是否达到分享阈值，且距上次分享超过 decay_duration"""
        current = self.current_value(state, now)
        if current < self.cfg.desire_threshold:
            return False
        last_express = state.last_express_at
        if isinstance(last_express, str):
            last_express = datetime.fromisoformat(last_express)
        if last_express is not None:
            decay_minutes = getattr(state, "decay_duration_minutes", self.cfg.desire_decay_minutes)
            decay_cutoff = now - timedelta(minutes=decay_minutes)
            if last_express > decay_cutoff:
                return False
        return True
