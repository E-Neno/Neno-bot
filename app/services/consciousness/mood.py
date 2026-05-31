from datetime import datetime

from .config import ConsciousnessConfig
from .models import MoodState


class MoodModel:
    """二维情绪模型 — valence/arousal 更新与基线回归"""

    def __init__(self, config: ConsciousnessConfig) -> None:
        self.cfg = config

    def apply_event(
        self,
        state: MoodState,
        valence_delta: float,
        arousal_delta: float,
        now: datetime,
    ) -> tuple[float, float]:
        """应用事件影响，返回 (new_valence, new_arousal)，夹紧到合法范围"""
        new_valence = max(-1.0, min(1.0, state.valence + valence_delta))
        new_arousal = max(0.0, min(1.0, state.arousal + arousal_delta))
        return new_valence, new_arousal

    def regress_to_baseline(self, state: MoodState) -> tuple[float, float]:
        """向基线回归一步（每次 tick 调用）"""
        rate = self.cfg.mood_regression_rate
        new_valence = _regress_toward(state.valence, state.baseline_valence, rate)
        new_arousal = _regress_toward(state.arousal, state.baseline_arousal, rate)
        return new_valence, new_arousal

    def to_label(self, valence: float, arousal: float) -> tuple[str, str]:
        """将二维情绪映射为 (label, description)"""
        if arousal < 0.3:
            if valence > 0.3:
                return "放松", "心里没什么事，很松弛"
            elif valence < -0.2:
                return "低落", "没什么精神，有点消沉"
            else:
                return "平静", "不咸不淡，放空状态"
        elif arousal < 0.7:
            if valence > 0.5:
                return "开心", "状态不错，有点兴奋"
            elif valence > 0.1:
                return "愉悦", "心情还行，比较轻松"
            elif valence < -0.4:
                return "烦躁", "心里有点毛躁"
            elif valence < -0.1:
                return "不安", "隐隐感觉不太对"
            else:
                return "清醒", "脑子转得动，不悲不喜"
        else:
            if valence > 0.5:
                return "兴奋", "上头了，话可能变多"
            elif valence > 0.0:
                return "激动", "有点坐不住"
            elif valence < -0.5:
                return "愤怒", "气炸了，但不会直接炸"
            elif valence < -0.1:
                return "焦虑", "心里七上八下"
            else:
                return "警觉", "高度专注，眼睛瞪得像铜铃"


def _regress_toward(current: float, target: float, rate: float) -> float:
    """按 rate 向 target 回归一步"""
    diff = target - current
    step = rate * abs(diff)
    if abs(diff) <= step:
        return target
    return current + step if diff > 0 else current - step
