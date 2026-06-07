from __future__ import annotations

import asyncio
import json
import logging
import re

from pydantic import BaseModel, Field

from app.config import OPENROUTER_API_KEY, OPENROUTER_URL
from app.llm.openrouter_client import chat_with_openrouter

from .config import ConsciousnessConfig
from .world_model import WorldDef

_log = logging.getLogger(__name__)

_PHASES = ("morning", "afternoon", "evening")

_SYSTEM_PROMPT = """你在为一个独居年轻女性 Neno 规划"今天"的生活。
基于她昨天残留的情绪、未完成的事，以及她家里有的房间和物品，
给出今天 上午/下午/晚上 各一条简短、自然、可执行的生活意图。

只输出 JSON，不要解释，格式：
{"items":[
  {"phase":"morning","intent":"……"},
  {"phase":"afternoon","intent":"……"},
  {"phase":"evening","intent":"……"}
]}"""


class DayPlanItem(BaseModel):
    phase: str
    intent: str
    done: bool = False


class DailyPlan(BaseModel):
    date: str
    items: list[DayPlanItem] = Field(default_factory=list)
    carried_over: list[str] = Field(default_factory=list)


class DailyPlanner:
    def __init__(self, world_def: WorldDef, config: ConsciousnessConfig) -> None:
        self._world_def = world_def
        self._config = config

    async def make_plan(
        self,
        *,
        date: str,
        residue: str,
        carried_over: list[str],
    ) -> DailyPlan:
        carried_over = list(carried_over or [])
        if not self._config.world_planner_enabled:
            return self._mock_plan(date, carried_over)
        try:
            items = await self._llm_plan(residue, carried_over)
            if not items:
                raise ValueError("empty plan from LLM")
            return DailyPlan(date=date, items=items, carried_over=carried_over)
        except Exception as exc:  # noqa: BLE001
            _log.warning("daily plan LLM failed, fallback to mock: %s", exc)
            return self._mock_plan(date, carried_over)

    async def _llm_plan(self, residue: str, carried_over: list[str]) -> list[DayPlanItem]:
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        rooms = "、".join(self._world_def.rooms)
        ctx = [
            f"家里的房间：{rooms}",
            f"昨天的情绪残留：{residue or '无'}",
            f"昨天没做完的事：{('；'.join(carried_over)) or '无'}",
            "请规划今天 上午/下午/晚上 各一条意图，只输出 JSON。",
        ]
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(ctx)},
        ]
        raw = await asyncio.to_thread(
            chat_with_openrouter,
            api_key=OPENROUTER_API_KEY,
            url=OPENROUTER_URL,
            model_name=self._config.world_model,
            messages=messages,
            timeout=int(self._config.world_llm_timeout_seconds),
            trace_id="daily_planner",
        )
        return _parse_items(raw)

    def _mock_plan(self, date: str, carried_over: list[str]) -> DailyPlan:
        items = [
            DayPlanItem(phase="morning", intent="把那本书读一会"),
            DayPlanItem(phase="afternoon", intent="收拾一下屋子"),
            DayPlanItem(phase="evening", intent="早点休息"),
        ]
        return DailyPlan(date=date, items=items, carried_over=carried_over)


def _parse_items(raw: str) -> list[DayPlanItem]:
    if not raw:
        return []
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return []
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    raw_items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(raw_items, list):
        return []
    items: list[DayPlanItem] = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        phase = it.get("phase", "")
        intent = it.get("intent", "")
        if phase in _PHASES and intent:
            items.append(DayPlanItem(phase=phase, intent=intent))
    return items
