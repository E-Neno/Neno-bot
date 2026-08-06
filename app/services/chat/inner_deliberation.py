from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from app.llm.openrouter_client import chat_with_openrouter
from app.utils.logging_utils import log_event


DELIBERATION_LENSES = ("approach", "boundary", "association")

_LENS_INSTRUCTIONS = {
    "approach": "留意想靠近、接住、回应或保护关系的冲动；没有就明确没感觉。",
    "boundary": "留意疲惫、防备、不耐烦、被冒犯或想保持距离的冲动；不要为了显得善良而抹掉它。",
    "association": "留意被勾起的具体联想、好奇、记忆或与她自己有关的兴趣；没有就明确没联想。",
}


@dataclass(frozen=True)
class InnerImpulse:
    lens: str
    drive: str
    reaction: str
    pull: float


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


def parse_impulse(raw: str, *, lens: str) -> InnerImpulse | None:
    data = _extract_json(raw)
    if data is None:
        return None
    drive = str(data.get("drive") or "").strip()[:120]
    reaction = str(data.get("reaction") or "").strip()[:300]
    try:
        pull = float(data.get("pull", 0.0))
    except (TypeError, ValueError):
        pull = 0.0
    pull = max(0.0, min(1.0, pull))
    if not drive and not reaction:
        return None
    return InnerImpulse(lens=lens, drive=drive, reaction=reaction, pull=pull)


def _build_prompt(messages: list[dict], state: dict | None) -> str:
    lines = ["【她此刻知道的状态】"]
    for key, value in (state or {}).items():
        text = str(value or "").strip()
        if text:
            lines.append(f"- {key}: {text}")
    lines.append("【刚收到的消息】")
    for item in messages:
        lines.append(f"[{item.get('id')}] {str(item.get('content') or '').strip()}")
    return "\n".join(lines)


def deliberate_sync(
    *,
    messages: list[dict],
    state: dict | None,
    model_name: str,
    api_key: str | None,
    url: str,
    timeout: int = 8,
    trace_id: str | None = None,
    extra_body: dict | None = None,
    llm_client=chat_with_openrouter,
) -> list[InnerImpulse]:
    if not messages or not api_key:
        return []

    user_prompt = _build_prompt(messages, state)

    def run_lens(lens: str) -> InnerImpulse | None:
        system = "\n".join(
            [
                f"你是 Neno 私有内心的一股独立涌念，lens={lens}。",
                _LENS_INSTRUCTIONS[lens],
                "不要替她作最终决定，不要写给用户看的回复，不要平衡其他立场。",
                '只输出 JSON：{"drive":"这股冲动是什么","reaction":"私有具体反应","pull":0到1}',
            ]
        )
        raw = llm_client(
            api_key=api_key,
            url=url,
            model_name=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            timeout=int(timeout),
            trace_id=trace_id or f"inner_{lens}",
            extra_body=extra_body,
        )
        return parse_impulse(str(raw or ""), lens=lens)

    found: dict[str, InnerImpulse] = {}
    with ThreadPoolExecutor(max_workers=len(DELIBERATION_LENSES)) as pool:
        futures = {pool.submit(run_lens, lens): lens for lens in DELIBERATION_LENSES}
        for future in as_completed(futures):
            lens = futures[future]
            try:
                impulse = future.result()
            except Exception as exc:  # noqa: BLE001
                log_event(
                    "chat",
                    "inner_deliberation_branch_failed",
                    trace_id=trace_id,
                    level="warning",
                    lens=lens,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                continue
            if impulse is not None:
                found[lens] = impulse
    return [found[lens] for lens in DELIBERATION_LENSES if lens in found]
