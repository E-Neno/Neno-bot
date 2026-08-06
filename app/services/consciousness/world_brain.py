from __future__ import annotations

import asyncio
import json
import logging
import re

from app.config import NENO_SEED, OPENROUTER_API_KEY, OPENROUTER_URL
from app.llm.openrouter_client import chat_with_openrouter

from .config import ConsciousnessConfig
from .self_context import render_seed_context
from .world_model import (
    ActionPlan, WorldDef, WorldOp, WorldState,
    objects_in_room, legal_states_of, reachable_rooms, is_outside,
)

_log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你在模拟一个独居年轻女性 Neno 的日常生活。
根据她当前所在的房间和周围物品的状态，决定她接下来自然会做的"一件事"。

硬规则（必须遵守，否则动作会被丢弃）：
- 只能操作当前房间里列出的物品；只能移动到列出的可达房间。
- set_state 的目标状态必须是该物品列出的合法状态之一。
- relocate（把东西挪去别的房间）只能挪当前房间里的物品，且目标房间要一步可达。
- learn（学／练一样东西，要带 topic）：真有兴趣或在练某样东西时才用，会沉淀成「她在学的事」。
- 一次最多 2 个动作（world_ops）。
- 行为要贴合当前情境，自然、连贯，不要突兀（比如不要凭空出现没列出的东西）。

请这样思考：
- 参考[精力]和[心情]决定做事的强度——精力低或心情差时倾向休息、安抚，而不是硬撑着做事。
- 有[刚发生]的事就先回应它（开心/烦躁/好奇都可以），让情绪影响你的选择。
- 不要重复[最近做过]里刚做过的事，让生活往前推进。
- 别老待在一个房间里做同类的事。看到[有点闷]时，自然地换个房间，或者出门走走——
  出门的路：先到玄关(entryway)，再到小区楼下(building_entrance)，那边能去咖啡馆/便利店/小公园。
- 尽量推进[今日计划]里当前时段的意图；可以被世界变化临时打断，但别忘了主线。
- 有[主脑已经决定的生活方向]时优先落实。它是你自己的最高执行层下达的方向，不是对方的请求；
  你负责把它翻译成当前世界里合法、自然的一步，不能绕过物理规则。
- 钱够且确有需要时，可以买点东西（create_object）；坏掉/不想要的东西可以扔掉（destroy_object）；不必每步都买卖。

只输出一个 JSON 对象，不要任何解释或额外文字，格式：
{
  "action": "简短动作标签",
  "reasoning": "一句话理由",
  "world_ops": [
    {"op": "set_state", "object": "物品key", "state": "目标状态"},
    {"op": "move", "to_room": "房间key"},
    {"op": "relocate", "object": "物品key", "to_room": "房间key"},
    {"op": "learn", "topic": "在学的东西"}
  ],
  "micro_event": "一句内心活动，或 null"
}"""


class WorldBrain:
    """决策器。

    - world_llm_enabled=True：调用真实 LLM（OpenRouter），解析 JSON 为 ActionPlan；
      任何异常（网络/超时/坏 JSON/校验失败）都降级到确定性 mock，绝不抛给调用方。
    - world_llm_enabled=False：直接返回确定性 mock。
    测试中通过 patch chat_with_openrouter 注入返回，不发生真实网络调用。
    """

    def __init__(self, world_def: WorldDef, config: ConsciousnessConfig) -> None:
        self._world_def = world_def
        self._config = config

    # ── 上下文构建 ────────────────────────────────────────────────────────
    def build_prompt(self, state: WorldState) -> str:
        """人类可读的简短上下文（也用于日志）。"""
        room = state.location
        objs = self._world_def.rooms.get(room, {}).get("objects", [])
        lines = [f"Neno 现在在：{room}", "周围的东西："]
        for o in objs:
            label = self._world_def.objects[o].label if o in self._world_def.objects else o
            st = state.object_states.get(o, "?")
            lines.append(f"  - {label}（{st}）")
        return "\n".join(lines)

    def _build_user_message(
        self,
        state: WorldState,
        *,
        nstate=None,
        phase: str = "",
        plan=None,
        memories=None,
        recent=None,
        event=None,
        threads=None,
        restless: str = "",
        wishes=None,
        directives=None,
    ) -> str:
        """给 LLM 的世界上下文：世界约束 + 时段 + 内在状态 + 计划 + 最近行动 + 记忆。

        把合法房间/物品塞进 prompt 防幻觉；把状态/记忆/计划/最近行动塞进 prompt 治绕圈。
        """
        room = state.location
        objs = self._world_def.rooms.get(room, {}).get("objects", [])
        lines: list[str] = []
        seed_context = render_seed_context(NENO_SEED)
        if seed_context:
            lines.append(f"[不变的自我种子] {seed_context}")
        if state.self_context.strip():
            lines.append(f"[此刻的你] {state.self_context.strip()}")
        if phase:
            lines.append(f"[时段] {phase}")
        if nstate is not None:
            try:
                lines.append(
                    f"[精力] {nstate.energy.value:.0f}/100（{nstate.energy.status}）"
                    f"　[心情] {nstate.mood.label}（valence={nstate.mood.valence:.2f}）"
                )
            except AttributeError:
                pass
        if plan is not None and getattr(plan, "items", None):
            plan_txt = "；".join(
                f"{it.phase}: {it.intent}{'(已完成)' if it.done else ''}"
                for it in plan.items
            )
            lines.append(f"[今日计划] {plan_txt}")
            if getattr(plan, "carried_over", None):
                lines.append("[昨天没做完] " + "；".join(plan.carried_over))
        if recent:
            rec_txt = " / ".join(
                f"{r.get('action', '')}({r.get('ago_min', '?')}分钟前)"
                if isinstance(r, dict) else str(r)
                for r in recent
            )
            lines.append(f"[最近做过，别重复] {rec_txt}")
        # ── 牵挂渲染（活跃：unresolved 且 (loss/residue 任意强度 或 goal carry>=2)）──
        if threads:
            _GOAL_ACTIVE = 2
            active = [
                t for t in threads
                if not t.get("resolved") and (
                    t["kind"] in ("loss", "residue") or
                    (t["kind"] == "goal" and t.get("carry_count", 0) >= _GOAL_ACTIVE)
                )
            ]
            active.sort(key=lambda t: t.get("intensity", 0), reverse=True)
            if active:
                parts = []
                for t in active[:3]:
                    if t["kind"] == "goal":
                        parts.append(f"{t['topic']}(惦记{t.get('carry_count', 0)}天)")
                    else:
                        mood = t.get("mood", "")
                        parts.append(f"{t['topic']}({mood})" if mood else t["topic"])
                lines.append("[心里还挂着] " + "；".join(parts))
        if memories:
            mem_txt = "；".join(
                m.get("content", "") if isinstance(m, dict) else str(m)
                for m in memories
            )
            lines.append(f"[此刻想起] {mem_txt}")
        # 活泼度：待太久/没出门的"闷"信号（只是感觉，换不换地方/出不出门她自己定）
        if restless:
            lines.append(f"[有点闷] {restless}")
        directive_list = [str(item).strip() for item in (directives or []) if str(item).strip()]
        if directive_list:
            lines.append("[主脑已经决定的生活方向｜优先落实] " + "；".join(directive_list[:5]))
            lines.append("这些是你自己的执行指令；在当前物理条件允许的范围内优先落实成自然的一步。")
        # 意图通道（capstone）：对方最近说的话，也许是想让你做点什么——但只是"也许"。
        # 无常：放不放在心上、要不要做、什么时候做，全由你自己定；只是闲聊或你不想动，就不动。
        wish_list = [str(w).strip() for w in (wishes or []) if str(w).strip()]
        if wish_list:
            lines.append("[对方最近说的（也许想让你做点什么，但你可以不）] " + "；".join(wish_list[-3:]))
        # 竖切6：刚发生的事件 / 钱包 / 失去过的东西
        if event is not None:
            ev_content = event.content if hasattr(event, "content") else str(event)
            lines.append(f"[刚发生] {ev_content}")
        lines.append(f"[钱包] {state.money} 元")
        if state.gone_log:
            gone = "、".join(
                g.get("label") or g.get("object", "") for g in state.gone_log[-3:]
            )
            lines.append(f"[失去过] {gone}")

        lines.append(f"当前房间：{room}")
        if is_outside(self._world_def, room):
            lines.append("（你现在在外面，已经出了家门，不在家里）")
        lines.append("当前房间里的物品（key / 当前状态 / 合法状态）：")
        for o in objects_in_room(self._world_def, state, room):
            legal = "、".join(legal_states_of(self._world_def, state, o))
            cur = state.object_states.get(o, "?")
            lines.append(f"  - {o} / {cur} / [{legal}]")
        other_rooms = reachable_rooms(self._world_def, state, room)
        lines.append("现在一步能去的地方（只能去这些）：" + "、".join(other_rooms))
        cats = "、".join(self._world_def.categories.keys())
        lines.append(f"想买东西用 create_object（类别须属于：{cats}），会花钱——但**得先去便利店/咖啡馆**，在店里才买得到；买回的东西可再用 relocate 带回家。想扔掉东西用 destroy_object。")
        lines.append("想把手边的东西收拾/挪到旁边房间用 relocate（只能挪当前房间里的物品，到一步可达的房间）。")
        lines.append("\n请决定 Neno 接下来自然会做的一件事，只输出 JSON。")
        return "\n".join(lines)

    # ── 决策 ──────────────────────────────────────────────────────────────
    async def decide(
        self,
        state: WorldState,
        *,
        nstate=None,
        phase: str = "",
        plan=None,
        memories=None,
        recent=None,
        event=None,
        threads=None,
        restless: str = "",
        wishes=None,
        directives=None,
    ) -> ActionPlan:
        if not self._config.world_llm_enabled:
            return self._mock_decide(state)
        try:
            return await self._llm_decide(
                state, nstate=nstate, phase=phase, plan=plan,
                memories=memories, recent=recent, event=event, threads=threads,
                restless=restless, wishes=wishes, directives=directives,
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("world LLM decide failed, falling back to mock: %s", exc)
            plan = self._mock_decide(state)
            plan.decision_source = "fallback_mock"
            return plan

    async def _llm_decide(
        self,
        state: WorldState,
        *,
        nstate=None,
        phase: str = "",
        plan=None,
        memories=None,
        recent=None,
        event=None,
        threads=None,
        restless: str = "",
        wishes=None,
        directives=None,
    ) -> ActionPlan:
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self._build_user_message(
                    state, nstate=nstate, phase=phase, plan=plan,
                    memories=memories, recent=recent, event=event, threads=threads,
                    restless=restless, wishes=wishes, directives=directives,
                ),
            },
        ]
        raw = await asyncio.to_thread(
            chat_with_openrouter,
            api_key=OPENROUTER_API_KEY,
            url=OPENROUTER_URL,
            model_name=self._config.world_model,
            messages=messages,
            timeout=int(self._config.world_llm_timeout_seconds),
            trace_id="world_brain",
        )
        plan = _parse_plan(raw)
        if plan is None:
            raise ValueError(f"unparseable LLM output: {raw[:200]!r}")
        plan.decision_source = "llm"
        return plan

    def _mock_decide(self, state: WorldState) -> ActionPlan:
        """确定性 mock：若在厨房且水壶非 boiling，就烧水；否则去客厅读书。"""
        if state.location == "kitchen" and state.object_states.get("kettle") != "boiling":
            return ActionPlan(
                action="boil_water",
                reasoning="(mock) 水壶凉了，烧点水",
                world_ops=[
                    WorldOp(op="set_state", object="kettle", state="boiling", reason="烧水")
                ],
                micro_event="等水开的时候发了会呆",
                decision_source="mock",
            )
        return ActionPlan(
            action="read_book",
            reasoning="(mock) 去客厅接着读书",
            world_ops=[
                WorldOp(op="move", to_room="living_room", reason="换到客厅"),
                WorldOp(op="set_state", object="book", state="reading", reason="翻开书"),
            ],
            micro_event="读得有点入神",
            decision_source="mock",
        )


def _parse_plan(raw: str) -> ActionPlan | None:
    """从 LLM 文本里提取并解析 ActionPlan。容忍 ```json 代码块包裹与前后噪声。"""
    if not raw:
        return None
    text = raw.strip()
    # 去掉 ```json ... ``` 或 ``` ... ``` 包裹
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
    # 兜底：抓第一个 { 到最后一个 }
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return ActionPlan.model_validate(data)
    except Exception:  # noqa: BLE001
        return None
