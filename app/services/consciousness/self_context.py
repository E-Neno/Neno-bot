from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.config import NENO_SEED, OPENROUTER_API_KEY, OPENROUTER_URL
from app.llm.openrouter_client import chat_with_openrouter
from app.utils.logging_utils import log_event

from .config import ConsciousnessConfig
from .models import NenoState
from .world_model import WorldState

HIGH_RISK_BIOGRAPHY_TERMS = (
    "专业", "大学", "学校", "学院", "家乡", "老家", "父母", "爸妈", "家人",
    "职业", "工作单位", "公司", "毕业", "上学",
)
RAW_INTERNAL_TERMS = ("能量值", "情绪值", "/100", "valence", "energy")

_SYSTEM_PROMPT = """你负责把编号事实压缩成一段给 Neno 自己看的「此刻的你」。
只能压缩或转述输入中明确提供的信息，信息不足就省略。
只描述当下处境、动作、感受和牵挂，不要复述姓名、年龄或气质。
输入里的精力和情绪数值只能帮助你理解状态，输出必须转成自然语言，不得回写数字或内部字段。
不得补专业、学历、学校、家乡、家庭、职业、过去等未提供的身份或传记设定，
也不得根据兴趣、动作或地点做身份推断。
输出 2 到 4 句自然中文，使用第二人称「你」，不要标题、列表或解释。"""


def render_seed_context(seed: dict | None = None) -> str:
    data = seed if seed is not None else NENO_SEED
    if not data:
        return ""
    name = str(data.get("name", "")).strip()
    age = data.get("age")
    temperament = str(data.get("temperament", "")).strip()
    principle = str(data.get("background_principle", "")).strip()
    parts = []
    if name and age not in (None, ""):
        parts.append(f"你叫 {name}，{age} 岁。")
    elif name:
        parts.append(f"你叫 {name}。")
    if temperament:
        parts.append(f"你的气质：{temperament}。")
    if principle:
        parts.append(principle)
    return "".join(parts)


def band_of(valence: float) -> str:
    value = float(valence)
    if value < -0.2:
        return "低"
    if value <= 0.2:
        return "平"
    return "好"


def guard_self_context(output: str, input_facts: str) -> bool:
    for keyword in HIGH_RISK_BIOGRAPHY_TERMS:
        if keyword in output and keyword not in input_facts:
            return False
    if any(char.isdigit() for char in output):
        return False
    for keyword in RAW_INTERNAL_TERMS:
        if keyword in output:
            return False
    return True


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _active_thread_facts(threads: list[dict]) -> list[str]:
    facts = []
    for thread in threads or []:
        if thread.get("resolved"):
            continue
        kind = thread.get("kind")
        if kind in ("loss", "residue") or (
            kind == "goal" and thread.get("carry_count", 0) >= 2
        ):
            topic = str(thread.get("topic", "")).strip()
            if topic:
                facts.append(f"你心里还挂着：{topic}")
    return facts[:3]


def _build_facts(
    ws: WorldState,
    nstate: NenoState,
    self_facts: list[str] | None = None,
) -> tuple[str, str]:
    seed = NENO_SEED or {}
    facts = [
        f"你现在的位置是：{ws.location}",
        f"你刚才或正在做的事是：{(ws.last_tick or {}).get('action', '')}",
        f"你的精力是 {nstate.energy.value:.0f}/100，状态是 {nstate.energy.status}",
        f"你的心情是 {nstate.mood.label}，情绪值是 {nstate.mood.valence:.2f}",
    ]
    recent = [
        str(item.get("action", "")).strip()
        for item in (ws.recent_actions or [])[-3:]
        if str(item.get("action", "")).strip()
    ]
    if recent:
        facts.append("你最近做过：" + "、".join(recent))
    facts.extend(_active_thread_facts(ws.open_threads or []))
    # 自我库（4 号输入）：reflection 从落账经历结晶的归纳偏好，算合法输入事实。
    for fact in (self_facts or [])[:4]:
        text = str(fact).strip()
        if text:
            facts.append(f"关于你自己：{text}")

    numbered = "\n".join(
        f"事实{index}: {fact}" for index, fact in enumerate(facts, start=1) if fact
    )
    principle = str(seed.get("background_principle", "")).strip()
    prompt_facts = numbered
    if principle:
        prompt_facts += f"\n边界要求: {principle}"
    # background_principle 中的高风险词只是禁止扩写，不是身份事实依据。
    return prompt_facts, numbered


async def maybe_update_self_context(
    ws: WorldState,
    nstate: NenoState,
    config: ConsciousnessConfig,
    *,
    trace_id: str | None = None,
    now: datetime | None = None,
    self_facts: list[str] | None = None,
) -> bool:
    """按独立门控组写 self_context；成功时就地更新 ws，失败时保持原值。

    self_facts：自我库（阶段3）结晶的 subject="neno" 归纳偏好，作为只读 4 号输入并入组写。
    """
    if not config.self_context_llm_enabled:
        return False

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    basis = ws.self_context_basis or {}
    previous_time = _parse_timestamp(ws.self_context_updated_at)
    elapsed = (
        float("inf")
        if previous_time is None
        else max(0.0, (current_time - previous_time).total_seconds())
    )
    mood_band = band_of(nstate.mood.valence)
    energy_status = nstate.energy.status
    action = str((ws.last_tick or {}).get("action", "")).strip()

    hard = energy_status != basis.get("energy_status")
    significant = (
        ws.location != basis.get("location")
        or action != basis.get("action")
        or mood_band != basis.get("mood_band")
        or hard
    )
    force = elapsed >= config.self_context_max_interval
    eligible = hard or force or (
        significant and elapsed >= config.self_context_min_interval
    )
    if not eligible:
        return False

    prompt_facts, guard_facts = _build_facts(ws, nstate, self_facts=self_facts)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt_facts},
    ]
    try:
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        raw = await asyncio.to_thread(
            chat_with_openrouter,
            api_key=OPENROUTER_API_KEY,
            url=OPENROUTER_URL,
            model_name=config.self_context_model,
            messages=messages,
            timeout=int(config.self_context_llm_timeout_seconds),
            trace_id=trace_id or "self_context",
        )
        output = str(raw or "").strip()
        if not output:
            raise ValueError("empty self_context output")
        if not guard_self_context(output, guard_facts):
            log_event(
                "consciousness",
                "self_context_guard_rejected",
                trace_id=trace_id,
                level="warning",
            )
            return False
    except Exception as exc:  # noqa: BLE001
        log_event(
            "consciousness",
            "self_context_warning",
            trace_id=trace_id,
            level="warning",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return False

    generated_at = current_time.isoformat()
    ws.self_context = output
    ws.self_context_basis = {
        "location": ws.location,
        "action": action,
        "mood_band": mood_band,
        "energy_status": energy_status,
        "generated_at": generated_at,
    }
    ws.self_context_updated_at = generated_at
    return True
