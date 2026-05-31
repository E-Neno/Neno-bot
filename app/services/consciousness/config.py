from pydantic import BaseModel


class ConsciousnessConfig(BaseModel):
    """consciousness 模块所有可调参数集中管理"""

    # 表达欲
    desire_linear_rate: float = 2.0
    desire_pulse_base: float = 25.0
    desire_jitter_pct: float = 0.10
    desire_threshold: float = 60.0
    desire_decay_minutes: int = 120

    # 情绪
    mood_regression_rate: float = 0.05
    mood_baseline_valence: float = 0.3
    mood_baseline_arousal: float = 0.5

    # 精力
    energy_wake_value: float = 95.0
    energy_decay_rate: float = 0.04

    # 睡眠
    sleep_hour: int = 1
    wake_hour: int = 8
    sleep_jitter_minutes: int = 30

    # 心跳
    heartbeat_interval_seconds: int = 300

    # 记忆
    today_experiences_max: int = 10
    memory_recall_top_k: int = 5
