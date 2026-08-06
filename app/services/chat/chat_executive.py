from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from app.services.chat.inner_deliberation import InnerImpulse
from app.services.chat.llm_gateway import request_model_response
from app.services.chat.selection_layer import SelectionDecision
from app.utils.logging_utils import log_event


_VALID_ACTIONS = {"reply_now", "defer", "leave_unanswered"}

_EXECUTIVE_SYSTEM = """你是 Neno 本人的最高决策层，不是文案助手。
你会看到她此刻的状态、关系、记忆、注意力参谋建议，以及互相冲突的私有内心涌念。
这些下层结果都只是建议；回不回、什么时候回、回应什么、以后想做什么，由你最终拍板。

不要生成给对方看的最终原话。只输出一个 JSON：
{
  "action":"reply_now|defer|leave_unanswered",
  "reason":"私有的一句话理由",
  "response_points":["若现在回，真正要表达的具体内容"],
  "max_chars":0到240,
  "max_beats":1到3,
  "inner_reaction":"她没有说出口的具体反应",
  "world_intents":["之后想在生活里做的高层事情"],
  "memory_candidates":["可能值得以后记住的事实"]
}

原则：
- 像人，不等于每条都回，也不等于刻意冷淡；按事情本身和她当下真实反应决定。
- 普通寒暄、嗯、重复追问通常很浅；对方真正需要回应、戳中她或会影响以后时才变深。
- response_points 写内容，不写语气形容词，不替出口层表演自然。
- world_intents 只是她确实想做的事，没有就空数组，禁止为了显得有生活而硬编。
- 只有私有状态明确写着 defer_available=true 才能选择 defer；否则需要回应或明确不回。
- 不要把房间、精力、关系分或系统状态当作要向对方汇报的内容。
- 信息不足时优先给克制的正常回应；任何不确定都不要无故伤害关系。
"""


@dataclass(frozen=True)
class ExecutiveDecision:
    action: str
    reason: str
    response_points: list[str] = field(default_factory=list)
    max_chars: int = 80
    max_beats: int = 1
    inner_reaction: str = ""
    world_intents: list[str] = field(default_factory=list)
    memory_candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def fallback_executive_decision(message: str) -> ExecutiveDecision:
    del message
    return ExecutiveDecision(
        action="reply_now",
        reason="主脑不可用，退回正常回应",
        response_points=["直接回应对方当前这句话，不延伸无关话题"],
        max_chars=80,
        max_beats=1,
    )


def enforce_executive_runtime_capabilities(
    decision: ExecutiveDecision,
    *,
    can_defer: bool,
    fallback_message: str,
) -> ExecutiveDecision:
    if decision.action != "defer" or can_defer:
        return decision
    return fallback_executive_decision(fallback_message)


def _extract_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _string_list(value, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text[:item_limit])
        if len(out) >= limit:
            break
    return out


def parse_executive_decision(raw: str, *, fallback_message: str) -> ExecutiveDecision:
    data = _extract_json(raw)
    if data is None:
        return fallback_executive_decision(fallback_message)

    action = str(data.get("action") or "").strip()
    if action not in _VALID_ACTIONS:
        action = "reply_now"
    reason = str(data.get("reason") or "").strip()[:240]
    response_points = _string_list(data.get("response_points"), limit=5, item_limit=180)
    try:
        max_chars = int(data.get("max_chars", 80))
    except (TypeError, ValueError):
        max_chars = 80
    max_chars = max(0 if action != "reply_now" else 8, min(240, max_chars))
    try:
        max_beats = int(data.get("max_beats", 1))
    except (TypeError, ValueError):
        max_beats = 1
    max_beats = max(1, min(3, max_beats))
    inner_reaction = str(data.get("inner_reaction") or "").strip()[:300]
    world_intents = _string_list(data.get("world_intents"), limit=3, item_limit=180)
    memory_candidates = _string_list(data.get("memory_candidates"), limit=3, item_limit=180)

    if action == "reply_now" and not response_points:
        response_points = ["直接回应对方当前这句话，不延伸无关话题"]
    return ExecutiveDecision(
        action=action,
        reason=reason,
        response_points=response_points,
        max_chars=max_chars,
        max_beats=max_beats,
        inner_reaction=inner_reaction,
        world_intents=world_intents,
        memory_candidates=memory_candidates,
    )


def _build_executive_prompt(
    *,
    message: str,
    batch: list[dict],
    state: dict,
    triage: SelectionDecision,
    impulses: list[InnerImpulse],
) -> str:
    lines = ["【完整但私有的状态】"]
    for key, value in state.items():
        text = str(value or "").strip()
        if text:
            lines.append(f"- {key}: {text}")
    lines.extend(
        [
            "【TRIAGE 参谋建议】",
            json.dumps(
                {
                    "focus": triage.focus,
                    "ignore": triage.ignore,
                    "hooked_by": triage.hooked_by,
                    "should_respond": triage.should_respond,
                    "depth": triage.depth,
                    "emotion": {
                        "hit": triage.emotion_hit,
                        "tone": triage.emotion_tone,
                        "intensity": triage.emotion_intensity,
                    },
                },
                ensure_ascii=False,
            ),
            "【互相独立的私有涌念】",
        ]
    )
    if impulses:
        for impulse in impulses:
            lines.append(json.dumps(asdict(impulse), ensure_ascii=False))
    else:
        lines.append("（浅路或涌念不可用，由你直接判断）")
    lines.append("【刚收到的一波消息】")
    for item in batch:
        lines.append(f"[{item.get('id')}] {str(item.get('content') or '').strip()}")
    lines.append(f"【合并后的当前输入】\n{message}")
    lines.append("现在由你最终拍板。只输出 JSON。")
    return "\n".join(lines)


def decide_chat_turn_sync(
    *,
    message: str,
    batch: list[dict],
    state: dict,
    triage: SelectionDecision,
    impulses: list[InnerImpulse],
    model_name: str,
    current_turn_image_inputs: list[str] | None = None,
    trace_id: str | None = None,
    timeout: int = 60,
    request_client=request_model_response,
) -> ExecutiveDecision:
    try:
        prompt = _build_executive_prompt(
            message=message,
            batch=batch,
            state=state,
            triage=triage,
            impulses=impulses,
        )
        image_inputs = [
            str(value).strip()
            for value in (current_turn_image_inputs or [])
            if str(value or "").strip()
        ]
        user_content: str | list[dict] = prompt
        if image_inputs:
            user_content = [{"type": "text", "text": prompt}]
            user_content.extend(
                {"type": "image_url", "image_url": {"url": value}}
                for value in image_inputs
            )
        raw = request_client(
            model_name=model_name,
            messages=[
                {"role": "system", "content": _EXECUTIVE_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            timeout=int(timeout),
            trace_id=trace_id,
            max_tokens=700,
        )
        return parse_executive_decision(str(raw or ""), fallback_message=message)
    except Exception as exc:  # noqa: BLE001
        log_event(
            "chat",
            "chat_executive_fallback",
            trace_id=trace_id,
            level="warning",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return fallback_executive_decision(message)


def build_output_guidance(decision: ExecutiveDecision) -> str:
    lines = ["【你已经做出的回应决定】"]
    if decision.response_points:
        lines.append("只表达这些内容：")
        lines.extend(f"- {point}" for point in decision.response_points)
    lines.append(f"总长度最多约 {decision.max_chars} 个汉字。")
    lines.append(f"最多 {decision.max_beats} 拍；一拍就是一条自然消息，不要为了拆条而拆条。")
    lines.append("不要主动汇报地点、精力、计划、关系状态或你内部如何权衡。")
    lines.append("直接说最终要说的话，不解释这份决定。")
    return "\n".join(lines)
