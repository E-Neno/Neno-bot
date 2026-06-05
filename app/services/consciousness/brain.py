"""NenoBrain — three-step decision engine: rule filter → LLM judge → LLM generate."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import OPENROUTER_API_KEY, OPENROUTER_URL
from app.llm.openrouter_client import chat_with_openrouter
from app.storage.db import add_debug_event, get_conn

from .config import ConsciousnessConfig
from .desire import DesireModel
from .event_pool import EventPool
from .experience_recorder import ExperienceRecorder, InnerExperienceIn
from .fragmenter import Fragmenter
from .interrupt import InterruptController
from .memory_recall import MemoryRecall
from .models import NenoState, StateMutation, Experience
from .state_store import StateStore

logger = logging.getLogger(__name__)


JUDGE_SYSTEM = """你是 Neno 的内心独白引擎。根据当前状态和事件列表，判断她现在是否想跟人说点什么。

严格输出 JSON，格式：
{
  "should_share": true/false,
  "reason": "一句话理由",
  "target_user_id": "qq:private:xxxxx 或 null",
  "urgency": "high/normal/low"
}

规则：
- should_share=false 时，其余字段可为 null
- target_user_id 从 last_interaction.user_id 取，没有互动过则为 null
- 不要编造数据，只根据输入判断
- P0 事件（极端天气预警）urgency 必须为 high
"""


GENERATE_SYSTEM = """你是 Neno，一个住在南宁的普通女生，20岁左右。
性格：慢热、安静、温柔、有点拘谨、说话直接。
绝对不暴露自己是 AI。

发消息规则：
- 用 | 分隔多条消息，像真人发微信那样分开发
- 每条最多 20 字，语气自然随意，不要正式
- 根据精力值调整：精力低就少说、说短点
- 不是每件事都要大书特书，有时候就随口一句
- 不要说"我想跟你说"这种开场，直接说事

示例：
"诶 你那边下雨了吗|看天气预报说南宁要下暴雨|不知道严不严重"
"刚买了杯奶茶 踩雷了|甜得离谱"
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_api_key() -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return OPENROUTER_API_KEY


async def _llm_call(
    model: str,
    messages: list[dict],
    max_tokens: int,
    timeout: float,
    trace_id: str,
) -> str:
    """Async wrapper around sync chat_with_openrouter."""
    return await asyncio.to_thread(
        chat_with_openrouter,
        api_key=_require_api_key(),
        url=OPENROUTER_URL,
        model_name=model,
        messages=messages,
        timeout=int(timeout),
        trace_id=trace_id,
    )


class NenoBrain:
    """
    Neno 的三步决策引擎。
    消费事件池 → 判断是否表达 → 生成碎片化文案 → 写入 proactive_intent 表。
    不直接发消息，发送由 Phase 3b 的 send_executor.send_brain_intent() 完成。
    """

    def __init__(
        self,
        state_store: StateStore,
        pool: EventPool,
        recall: MemoryRecall,
        fragmenter: Fragmenter,
        interrupt: InterruptController,
        config: ConsciousnessConfig,
        recorder: ExperienceRecorder | None = None,
    ) -> None:
        self._state = state_store
        self._pool = pool
        self._recall = recall
        self._fragmenter = fragmenter
        self._interrupt = interrupt
        self._cfg = config
        self._desire_model = DesireModel(config)
        self._recorder = recorder or ExperienceRecorder()

    async def run_cycle(self) -> None:
        """一次决策周期，由 APScheduler 定期调用（brain_cycle_interval_seconds）。"""
        trace_id = str(uuid.uuid4())[:8]
        state = await self._state.read()

        if state.energy.status == "sleeping":
            return

        now = _utcnow()

        # P0 事件直接进判断，无需等表达欲阈值
        p0_events = await self._pool.pop_pending(priority_le=0)

        # 检查表达欲阈值
        has_desire = self._desire_model.should_express(state.desire, now)

        if not p0_events and not has_desire:
            return

        # 取出 P1/P2 事件
        p12_events = await self._pool.pop_pending(priority_le=2)
        all_events = p0_events + p12_events

        if not all_events:
            return

        # Step 1: 规则过滤
        if self._rule_filter(state, all_events) == "skip":
            logger.debug("[%s] rule_filter: skip", trace_id)
            return

        # Step 2: 判断层
        self._interrupt.enter("judging")
        decision = await self._llm_judge(state, all_events, trace_id)
        if self._interrupt.should_cancel_judging:
            self._interrupt.enter("idle")
            logger.info("[%s] judging cancelled by P0 interrupt", trace_id)
            return
        self._interrupt.enter("idle")

        # decision is None 表示判断层超时 / 坏 JSON / 调用失败的降级。
        # _llm_judge() 已写过 debug warning，这里直接返回，不沉淀 unspoken experience，
        # 避免把"判断失败"误记成"想说但没说"。
        if decision is None:
            return

        if not decision.get("should_share"):
            await self._record_experiences(
                all_events,
                trace_id,
                status="unspoken",
                reason="judge false",
                decision=decision,
            )
            return

        # 确定目标用户。没有 target 时只沉淀为 suppressed，不生成、不发送。
        target_user_id = (
            decision.get("target_user_id")
            or state.last_interaction.user_id
        )

        if not target_user_id:
            logger.info("[%s] no target user, dropping", trace_id)
            await self._record_experiences(
                all_events,
                trace_id,
                status="suppressed",
                reason="no target user",
                decision=decision,
            )
            self._interrupt.enter("idle")
            return

        # Step 3: 生成层
        self._interrupt.enter("generating")
        raw_text = await self._llm_generate(state, all_events, trace_id)
        if not raw_text:
            self._interrupt.enter("idle")
            return

        # 频控检查
        if not self._fragmenter.check_rate_limit():
            logger.info("[%s] rate limit hit, skipping", trace_id)
            self._interrupt.enter("idle")
            return

        # 碎片化切分
        fragments = self._fragmenter.split(raw_text, state.energy.value)
        if not fragments:
            self._interrupt.enter("idle")
            return

        if self._interrupt.should_stop_after_current:
            fragments = fragments[:1]

        # 写入 proactive_intent 表
        intent_id = await self._write_intent(target_user_id, fragments, trace_id)
        await self._record_experiences(
            all_events,
            trace_id,
            status="pending_expression",
            reason="intent queued",
            decision=decision,
            intent_id=intent_id,
        )
        self._fragmenter.record_sent()

        # 清零表达欲
        await self._state.submit_mutation(StateMutation(
            trace_id=trace_id,
            desire_clear=True,
            reason=f"brain expressed: {fragments[0][:20]}",
        ))

        # 标记话题已表达
        for ev in all_events:
            await self._pool.mark_topic_expressed(ev.topic_hash)

        # 追加今日经历
        now_str = _utcnow().strftime("%H:%M")
        for ev in all_events[:2]:
            await self._state.submit_mutation(StateMutation(
                trace_id=trace_id,
                experience=Experience(
                    time=now_str,
                    content=ev.content,
                    topic_hash=ev.topic_hash,
                    mood_impact=ev.mood_impact,
                ),
                reason="brain expressed experience",
            ))

        self._interrupt.enter("idle")
        logger.info(
            "[%s] intent written for %s: %s…",
            trace_id, target_user_id, fragments[0][:20],
        )

    def _rule_filter(self, state: NenoState, events: list) -> str:
        """Step 1 纯规则过滤，0 成本。返回 "skip" 或 "proceed"."""
        if state.energy.status == "sleeping":
            return "skip"
        if all(getattr(ev, "priority", 3) == 3 for ev in events):
            return "skip"
        return "proceed"

    async def _llm_judge(
        self, state: NenoState, events: list, trace_id: str,
    ) -> Optional[dict]:
        """Step 2: DeepSeek 判断层。超时或 JSON 解析失败 → 返回 None."""
        events_text = "\n".join(
            f"- [P{getattr(ev, 'priority', 2)}] {ev.content}" for ev in events
        )
        state_text = (
            f"精力: {state.energy.value:.0f}/100 ({state.energy.description})\n"
            f"情绪: {state.mood.label}（{state.mood.description}）\n"
            f"表达欲: {state.desire.value:.0f}/100\n"
            f"上次互动: {state.last_interaction.summary or '无'}\n"
            f"互动对象: {state.last_interaction.user_id or '无'}"
        )
        user_prompt = f"当前状态：\n{state_text}\n\n待处理事件：\n{events_text}"

        try:
            raw = await asyncio.wait_for(
                _llm_call(
                    model=self._cfg.judge_model,
                    messages=[
                        {"role": "system", "content": JUDGE_SYSTEM},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=200,
                    timeout=self._cfg.judge_llm_timeout_seconds,
                    trace_id=trace_id,
                ),
                timeout=self._cfg.judge_llm_timeout_seconds,
            )
            raw = raw.strip()
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1] if len(parts) > 1 else raw
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("[%s] judge LLM failed: %s", trace_id, e)
            await self._write_debug_event(trace_id, "judge_failed", str(e))
            return None

    async def _llm_generate(
        self, state: NenoState, events: list, trace_id: str,
    ) -> Optional[str]:
        """Step 3: Gemini 生成层，降级到 MiMo。两个模型都失败 → 返回 None."""
        recalled = await self._recall.recall(
            query=" ".join(ev.content for ev in events),
            subject=state.last_interaction.user_name or None,
        )
        mem_text = (
            "\n".join(f"- {m}" for m in recalled) if recalled else "（无相关记忆）"
        )
        events_text = "\n".join(f"- {ev.content}" for ev in events)

        user_prompt = (
            f"精力：{state.energy.value:.0f}/100\n"
            f"情绪：{state.mood.label}\n"
            f"关于对方你记得：\n{mem_text}\n\n"
            f"触发你想说话的事：\n{events_text}\n\n"
            f"现在用 | 分隔多条消息，自然地说："
        )

        models = [self._cfg.generate_model, self._cfg.generate_llm_fallback]
        for model in models:
            if self._interrupt.should_stop_after_current:
                break
            try:
                result = await asyncio.wait_for(
                    _llm_call(
                        model=model,
                        messages=[
                            {"role": "system", "content": GENERATE_SYSTEM},
                            {"role": "user", "content": user_prompt},
                        ],
                        max_tokens=300,
                        timeout=self._cfg.generate_llm_timeout_seconds,
                        trace_id=trace_id,
                    ),
                    timeout=self._cfg.generate_llm_timeout_seconds,
                )
                if result and result.strip():
                    return result.strip()
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning("[%s] generate failed (%s): %s", trace_id, model, e)
                await self._write_debug_event(
                    trace_id, f"generate_failed_{model}", str(e),
                )
                continue
        return None

    async def _write_intent(
        self, user_id: str, fragments: list[str], trace_id: str,
    ) -> int:
        """将碎片化消息写入 proactive_intent 表。Phase 3b 消费。"""
        intent_id = await asyncio.to_thread(
            self._write_intent_sync,
            user_id,
            fragments,
        )
        logger.debug(
            "[%s] wrote %d fragments to proactive_intent", trace_id, len(fragments),
        )
        return intent_id

    def _write_intent_sync(self, user_id: str, fragments: list[str]) -> int:
        with get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO proactive_intent (user_id, fragments, status, created_at) "
                "VALUES (?, ?, 'queued', ?)",
                (user_id, json.dumps(fragments, ensure_ascii=False), _utcnow().isoformat()),
            )
            return int(cursor.lastrowid)

    async def _record_experiences(
        self,
        events: list,
        trace_id: str,
        *,
        status: str,
        reason: str,
        decision: dict | None = None,
        intent_id: int | None = None,
    ) -> None:
        """沉淀 Brain 消费过的事件。失败只写 debug warning，不阻断主流程。"""
        for ev in events[:3]:
            try:
                await self._recorder.record(
                    InnerExperienceIn(
                        trace_id=trace_id,
                        source="brain_judge",
                        kind="unspoken_thought",
                        content=getattr(ev, "content", ""),
                        mood_impact=float(getattr(ev, "mood_impact", 0.0) or 0.0),
                        expression_status=status,
                        related_event_hash=getattr(ev, "topic_hash", None),
                        related_intent_id=intent_id,
                        metadata={
                            "reason": reason,
                            "decision": decision or {},
                            "priority": getattr(ev, "priority", None),
                            "tags": getattr(ev, "tags", []),
                        },
                    )
                )
            except Exception as exc:
                logger.warning("[%s] record brain experience failed: %s", trace_id, exc)
                await self._write_debug_event(
                    trace_id,
                    "experience_record_failed",
                    str(exc),
                )

    async def _write_debug_event(
        self, trace_id: str, event_type: str, detail: str,
    ) -> None:
        """写入 debug_events 表。失败不能影响主流程。"""
        try:
            await asyncio.to_thread(
                add_debug_event,
                trace_id=trace_id,
                module="brain",
                event=event_type,
                level="warning",
                reason=detail[:240],
            )
        except Exception:
            pass
