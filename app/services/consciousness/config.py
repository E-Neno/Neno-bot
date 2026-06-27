import json
import os

from pydantic import BaseModel, field_validator


def _parse_salience_env() -> dict[str, float]:
    """尝试从 CONSCIOUSNESS_WORLD_SALIENCE 环境变量读取 JSON 覆盖；
    解析失败时返回空 dict，不抛异常。"""
    raw = os.getenv("CONSCIOUSNESS_WORLD_SALIENCE")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): float(val) for k, val in parsed.items()}
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return {}


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
    world_energy_drop_per_tick: float = float(os.getenv("CONSCIOUSNESS_WORLD_ENERGY_DROP_PER_TICK", "0.01"))
    # 时间流速倍率：精力积分的「真实经过时间」乘此倍率。1.0=真实同步（默认）；
    # 调高（如 10）让她活得更快、睡醒周期压缩，便于观察/调试，代价是与现实时钟脱钩。
    world_time_scale: float = float(os.getenv("CONSCIOUSNESS_WORLD_TIME_SCALE", "1.0"))

    # 睡眠
    sleep_hour: int = 1
    wake_hour: int = 8
    sleep_jitter_minutes: int = 30

    # 心跳
    heartbeat_interval_seconds: int = 300

    # Living World（默认关闭）
    reflection_enabled: bool = _env_bool("CONSCIOUSNESS_REFLECTION_ENABLED", False)
    reflection_model_enabled: bool = _env_bool("CONSCIOUSNESS_REFLECTION_MODEL_ENABLED", False)
    expression_gate_enabled: bool = _env_bool("CONSCIOUSNESS_EXPRESSION_GATE_ENABLED", False)
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
    self_context_llm_enabled: bool = _env_bool("CONSCIOUSNESS_SELF_CONTEXT_LLM_ENABLED", False)
    self_context_min_interval: int = int(os.getenv("CONSCIOUSNESS_SELF_CONTEXT_MIN_INTERVAL", "600"))
    self_context_max_interval: int = int(os.getenv("CONSCIOUSNESS_SELF_CONTEXT_MAX_INTERVAL", "10800"))
    self_context_model: str = os.getenv("OPENROUTER_SELF_CONTEXT_MODEL", "openai/gpt-4o-mini")
    self_context_llm_timeout_seconds: float = float(
        os.getenv("CONSCIOUSNESS_SELF_CONTEXT_LLM_TIMEOUT", "20")
    )
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

    # 世界压力触发（第一刀：纯决策引擎，不接 LLM）
    world_pressure_threshold: float = float(os.getenv("CONSCIOUSNESS_WORLD_PRESSURE_THRESHOLD", "100.0"))
    world_wake_min_gap_seconds: float = float(os.getenv("CONSCIOUSNESS_WORLD_WAKE_MIN_GAP", "60.0"))
    world_wake_budget_per_hour: int = int(os.getenv("CONSCIOUSNESS_WORLD_WAKE_BUDGET_PER_HOUR", "12"))
    world_boredom_drip: float = float(os.getenv("CONSCIOUSNESS_WORLD_BOREDOM_DRIP", "1.0"))
    world_salience: dict[str, float] = _parse_salience_env()

    @field_validator("world_salience", mode="before")
    @classmethod
    def _parse_world_salience_env(cls, v: dict | str | None) -> dict:
        """支持从 CONSCIOUSNESS_WORLD_SALIENCE env 传 JSON 覆盖；
        解析失败时回退空 dict，不抛异常。"""
        if isinstance(v, dict) or v is None:
            return v or {}
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return {str(k): float(val) for k, val in parsed.items()}
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        return {}

    # Fragmenter
    max_fragments_per_burst: int = 5
    max_proactive_per_hour: int = 6
    typing_chars_per_second: float = 8.0
    typing_min_delay: float = 0.8
    typing_max_delay: float = 4.0
