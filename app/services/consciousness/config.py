import os

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

    # Brain 决策
    brain_cycle_interval_seconds: int = 60
    judge_llm_timeout_seconds: float = 8.0
    generate_llm_timeout_seconds: float = 15.0
    generate_llm_fallback: str = "mimo-v2.5-pro"

    # LLM 模型（从 env 读取，兼容现有 OPENROUTER 风格）
    judge_model: str = os.getenv("CONSCIOUSNESS_JUDGE_MODEL", "deepseek/deepseek-v4-pro")
    generate_model: str = os.getenv("CONSCIOUSNESS_GENERATE_MODEL", "anthropic/claude-opus-4.8")
    dream_model: str = os.getenv("CONSCIOUSNESS_DREAM_MODEL", "mimo-v2.5-pro")

    # Fragmenter
    max_fragments_per_burst: int = 5
    max_proactive_per_hour: int = 6
    typing_chars_per_second: float = 8.0
    typing_min_delay: float = 0.8
    typing_max_delay: float = 4.0
