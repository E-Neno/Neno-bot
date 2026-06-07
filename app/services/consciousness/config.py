import os

from pydantic import BaseModel


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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

    # Living World（默认关闭）
    life_loop_enabled: bool = _env_bool("CONSCIOUSNESS_LIFE_LOOP_ENABLED", False)
    reflection_enabled: bool = _env_bool("CONSCIOUSNESS_REFLECTION_ENABLED", False)
    reflection_model_enabled: bool = _env_bool("CONSCIOUSNESS_REFLECTION_MODEL_ENABLED", False)
    expression_gate_enabled: bool = _env_bool("CONSCIOUSNESS_EXPRESSION_GATE_ENABLED", False)
    life_loop_interval_seconds: int = int(os.getenv("CONSCIOUSNESS_LIFE_LOOP_INTERVAL_SECONDS", "1200"))
    reflection_hour: int = int(os.getenv("CONSCIOUSNESS_REFLECTION_HOUR", "5"))
    reflection_minute: int = int(os.getenv("CONSCIOUSNESS_REFLECTION_MINUTE", "0"))

    # Living World 竖切1（封闭世界）
    world_llm_enabled: bool = _env_bool("CONSCIOUSNESS_WORLD_LLM_ENABLED", False)
    world_planner_enabled: bool = _env_bool("CONSCIOUSNESS_WORLD_PLANNER_ENABLED", False)
    # 常驻世界循环（默认关；开了才在后端注册定时 tick）
    world_loop_enabled: bool = _env_bool("CONSCIOUSNESS_WORLD_LOOP_ENABLED", False)
    world_loop_interval_seconds: int = int(os.getenv("CONSCIOUSNESS_WORLD_LOOP_INTERVAL", "8"))
    world_sim_minutes_per_tick: int = int(os.getenv("CONSCIOUSNESS_WORLD_SIM_MIN_PER_TICK", "30"))
    world_model: str = os.getenv("OPENROUTER_WORLD_MODEL", "openai/gpt-4o-mini")
    world_llm_timeout_seconds: float = float(os.getenv("CONSCIOUSNESS_WORLD_LLM_TIMEOUT", "20"))
    world_kettle_cool_minutes: int = 30
    world_plant_dry_minutes: int = 2880  # 2 天
    world_plant_wilt_minutes: int = 1440  # 再 1 天

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
