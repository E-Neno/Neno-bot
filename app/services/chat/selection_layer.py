"""TRIAGE 参谋层：一波消息 → 注意力、深度与情绪建议。

真人感的核心：**取舍 = 真人，无差别全回 = 脚本**。拿到累积的一波消息后，基于「消息内容」+
「她此刻的内部状态（心情/关注点/与对方关系/记忆摘要）」，决定回哪条、忽略哪条、被哪条勾住、
怎么回、是否值得回应。只产出极简 JSON 建议，不产正文，也没有最终沉默权；主脑开启时由
Executive 最终拍板，兼容模式才沿用旧 `should_respond` 行为。一次廉价 LLM 调用压低延迟。

铁律：这一层**绝不能因为自己崩了就让聊天不回**。任何失败/关闭 → `fallback_decision`（退回当前
「全回、综合成一条、回」的行为），下游照常生成回复。
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

from app import config
from app.llm.openrouter_client import chat_with_openrouter
from app.utils.logging_utils import log_event

_VALID_STRATEGY = ("merge", "split", "single")
_VALID_DEPTH = ("silent", "shallow", "deep")

_SYSTEM_PROMPT = """你是一个人的「注意力与取舍」。给你刚收到的一条或一波消息，和你此刻的内部状态，
你要像真人一样**选择性**地决定回应什么——不是有消息就一定回、不是每条都平均用力（那是脚本），
而是结合你现在的状态（在忙什么、累不累、心情、和对方多熟）做出取舍。

只输出一个极简 JSON，**不要回复正文、不要任何解释**：
{"focus":[消息id],"ignore":[消息id],"hooked_by":消息id或null,"reply_strategy":"merge|split|single","should_respond":true或false,"depth":"silent|shallow|deep","emotion":{"hit":true或false,"tone":"具体感受或空字符串","intensity":0到1}}

- 你是参谋，不是最终拍板者。should_respond/depth 都是建议，最终由主脑决定。
- depth：silent=几乎没东西值得说；shallow=普通短回应；deep=真的戳中、复杂、需要权衡或会影响以后。

- should_respond：到底回不回。**这是状态驱动的**——你正专注做某件事、很累、心情差、或对方只是寒暄而你没兴致时，
  **哪怕只有一条消息，也可以这会儿先不回**（过会儿想起来再说，不是没看见）；对方说了要紧/戳到你的事，则倾向回。
- focus：要回的话，重点回哪条/哪几条（最新的 / 最要紧的 / 最戳你的）。只有一条就是它。
- ignore：可以略过的（寒暄、重复、无关紧要）
- hooked_by：有没有某条特别勾住你（惊到 / 感兴趣 / 被冒犯）——**尤其戳到「你活成的自己」里你真在意/喜欢/在学的事**
  （那才是真戳到你，不是泛泛戳到一个人）→ 填它的 id，聚焦它、其余降权；没有就填 null
- reply_strategy：merge（综合成一条）/ split（拆成多条分别回）/ single（只回一条）

同样的消息，你状态不同，取舍就该不同。这是你「活着」而不是脚本的关键。"""


@dataclass
class SelectionDecision:
    focus: list[int]
    ignore: list[int]
    hooked_by: int | None
    reply_strategy: str
    should_respond: bool
    depth: str = "shallow"
    emotion_hit: bool = False
    emotion_tone: str = ""
    emotion_intensity: float = 0.0


def _ids_of(messages: list[dict] | None) -> list[int]:
    out: list[int] = []
    for m in messages or []:
        try:
            out.append(int(m["id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fallback_decision(messages: list[dict] | None) -> SelectionDecision:
    """退回当前行为：全回、综合成一条、回。选择层关闭或任何失败都走这里——绝不因它而不回。"""
    ids = _ids_of(messages)
    return SelectionDecision(
        focus=ids, ignore=[], hooked_by=None, reply_strategy="merge", should_respond=True,
        depth="shallow",
    )


def _coerce_id(value, valid_ids: set[int]) -> int | None:
    try:
        i = int(value)
    except (TypeError, ValueError):
        return None
    return i if i in valid_ids else None


def _extract_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        text = text[start:end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_decision(raw: str, messages: list[dict]) -> SelectionDecision:
    """把 LLM 文本解析成决策；任何非法字段就地纠偏，整体不可解析则退回 fallback。

    - focus/ignore 只保留属于这波消息的合法 id（防 LLM 编 id）；
    - hooked_by 必须是合法 id，否则 None；
    - reply_strategy 不在白名单 → merge；should_respond 非 bool → True（默认回，don't drop）。
    """
    valid_ids = set(_ids_of(messages))
    data = _extract_json(raw)
    if data is None:
        return fallback_decision(messages)

    raw_focus = data.get("focus")
    raw_ignore = data.get("ignore")
    focus = [i for i in (_coerce_id(x, valid_ids) for x in (raw_focus if isinstance(raw_focus, list) else [])) if i is not None]
    ignore = [i for i in (_coerce_id(x, valid_ids) for x in (raw_ignore if isinstance(raw_ignore, list) else [])) if i is not None]
    hooked_by = _coerce_id(data.get("hooked_by"), valid_ids)

    strategy = data.get("reply_strategy")
    if strategy not in _VALID_STRATEGY:
        strategy = "merge"

    should = data.get("should_respond")
    should_respond = should if isinstance(should, bool) else True

    depth = data.get("depth")
    if depth not in _VALID_DEPTH:
        depth = "shallow"

    emotion = data.get("emotion") if isinstance(data.get("emotion"), dict) else {}
    emotion_hit = emotion.get("hit") if isinstance(emotion.get("hit"), bool) else False
    emotion_tone = emotion.get("tone") if isinstance(emotion.get("tone"), str) else ""
    emotion_tone = emotion_tone.strip()[:80]
    try:
        emotion_intensity = float(emotion.get("intensity", 0.0))
    except (TypeError, ValueError):
        emotion_intensity = 0.0
    emotion_intensity = max(0.0, min(1.0, emotion_intensity))

    # 被勾住的那条必然在 focus 里
    if hooked_by is not None and hooked_by not in focus:
        focus.append(hooked_by)
    # 决定要回、却没挑出任何 focus → 兜底聚焦没被忽略的（别要回又没目标）
    if should_respond and not focus:
        focus = [i for i in valid_ids if i not in ignore] or list(valid_ids)

    return SelectionDecision(
        focus=focus, ignore=ignore, hooked_by=hooked_by,
        reply_strategy=strategy, should_respond=should_respond,
        depth=depth, emotion_hit=emotion_hit, emotion_tone=emotion_tone,
        emotion_intensity=emotion_intensity,
    )


def build_selection_prompt(messages: list[dict], state: dict | None) -> str:
    """把「内部状态」和「这波消息」清晰分区给模型。"""
    lines: list[str] = ["【你此刻的内部状态（决定回不回的关键）】"]
    st = state or {}
    if st.get("state"):
        lines.append(f"- 你此刻在哪/在干嘛/累不累/心情/心里挂着啥：{st['state']}")
    if st.get("self"):
        lines.append(f"- 你活成的自己（你在意/喜欢/在学的事）：{st['self']}")
    if st.get("mood"):
        lines.append(f"- 心情：{st['mood']}")
    if st.get("attention"):
        lines.append(f"- 此刻关注/在意：{st['attention']}")
    if st.get("relationship"):
        lines.append(f"- 和对方的关系：{st['relationship']}")
    if st.get("memory"):
        lines.append(f"- 相关记忆：{st['memory']}")
    if len(lines) == 1:
        lines.append("- （暂无特别状态）")
    lines.append("\n【刚收到的一波消息（按先后）】")
    for m in messages or []:
        mid = m.get("id")
        content = str(m.get("content", "")).replace("\n", " ").strip()
        lines.append(f"  [{mid}] {content}")
    lines.append("\n基于你现在的状态，给出取舍和 depth 建议（silent|shallow|deep）。只输出那个 JSON。")
    return "\n".join(lines)


def select_response_sync(
    messages: list[dict],
    state: dict | None,
    *,
    model_name: str,
    api_key: str | None,
    url: str,
    timeout: int = 15,
    trace_id: str | None = None,
    extra_body: dict | None = None,
    llm_client=chat_with_openrouter,
) -> SelectionDecision:
    """一次便宜 LLM 调用得出选择决策（同步；turn_orchestrator 用）。任何异常 → fallback。

    extra_body：厂商特定参数。用 MiMo 时务必传 {"thinking": {"type": "disabled"}} 关深度思考，
    否则它会先烧十几秒思维链（实测 15s → 1.2s）。
    """
    if not messages:
        return fallback_decision(messages)
    try:
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        llm_messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": build_selection_prompt(messages, state)},
        ]
        raw = llm_client(
            api_key=api_key, url=url, model_name=model_name, messages=llm_messages,
            timeout=int(timeout), trace_id=trace_id or "selection_layer", extra_body=extra_body,
        )
        return parse_decision(str(raw or ""), messages)
    except Exception as exc:  # noqa: BLE001 — 选择层崩了绝不能让聊天不回
        log_event(
            "chat", "selection_layer_fallback", trace_id=trace_id,
            level="warning", error_type=type(exc).__name__, error_message=str(exc),
        )
        return fallback_decision(messages)


async def select_response(messages, state, **kwargs) -> SelectionDecision:
    """异步包装（留给异步调用方）。"""
    return await asyncio.to_thread(select_response_sync, messages, state, **kwargs)


def build_selection_guidance(decision: SelectionDecision, messages: list[dict]) -> str:
    """把决策翻成给下游大 LLM 的取舍指导（进回复 prompt 动态区）。should_respond=False 不该走到这里。"""
    by_id = {}
    for m in messages or []:
        try:
            by_id[int(m["id"])] = str(m.get("content", "")).strip()
        except (KeyError, TypeError, ValueError):
            continue

    def snip(i: int) -> str:
        t = by_id.get(i, "")
        return (t[:18] + "…") if len(t) > 18 else t

    lines = ["【这波消息你的取舍（你自己临场的判断，照它来——别无差别全回）】"]
    if decision.focus:
        lines.append("- 重点回应：" + "；".join(f"「{snip(i)}」" for i in decision.focus))
    if decision.ignore:
        lines.append("- 可以略过、不必逐条回：" + "；".join(f"「{snip(i)}」" for i in decision.ignore))
    if decision.hooked_by is not None:
        lines.append(f"- 你被这条勾住了，回应里带点情绪偏向它：「{snip(decision.hooked_by)}」")
    # split 实验门：默认关时，split 降级成 single——别下「拆成几条」的指令（逼出伪多条）。
    effective = decision.reply_strategy
    if effective == "split" and not config.REPLY_SPLIT_ENABLED:
        effective = "single"
    strat = {
        "single": "只挑一条回就好，别面面俱到",
        "merge": "综合起来回成一条",
        "split": "可以拆成几句/几条分别说，自然点（用空行分隔不同条）",
    }.get(effective, "综合起来回成一条")
    lines.append(f"- 回复方式：{strat}")
    return "\n".join(lines)
