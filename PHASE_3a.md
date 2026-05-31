# PHASE_3a — 大脑决策与生成

> **前置**：Phase 1（状态地基）和 Phase 2（感知与事件池）已完成并通过全部验收标准。
>
> **本阶段目标**：实现 NenoBrain 的三步决策链路——规则过滤 → DeepSeek 判断 → Gemini 生成碎片化文案。产出到"fragments 列表写入 proactive_intent 表"为止。**本阶段不真实发消息，不调用 neno-bridge，不碰 send_executor.py。**
>
> ⚠️ **重要架构纠正（必读）**：
> - `SessionSubmitController` 与本阶段完全无关，**禁止使用**。它只用于用户 chat 消息的串行化（platform.py → submit_platform_chat_turn），proactive 和 brain 链路完全不走它。
> - 发送链路在 Phase 3b 处理，本阶段只管"决策 → 生成 → 写 proactive_intent 表"。

---

## 1. 本阶段范围

### 新建文件（全部放在 `app/services/consciousness/`）

| 文件 | 职责 |
|------|------|
| `brain.py` | NenoBrain 三步决策编排：规则过滤 → DeepSeek JSON 判断 → Gemini 生成文案 |
| `fragmenter.py` | 文案碎片化切分（按 `\|` 分割）+ 打字延迟计算 + 单位时间频控 |
| `interrupt.py` | InterruptController 三态状态机（judging/generating/sending） |
| `memory_recall.py` | 长期记忆关键词召回（Top-K，为生成层提供上下文） |

### 改动现有文件（最小化）

| 文件 | 改动内容 | 风险等级 |
|------|----------|----------|
| `app/services/consciousness/config.py` | 新增 brain 相关配置字段 | 低 |
| `app/services/consciousness/models.py` | StateMutation 新增 `clear_experiences` 字段（为 Phase 4 预留） | 低 |
| `app/services/consciousness/__init__.py` | ConsciousnessEngine 接入 NenoBrain，注册 brain_cycle 调度任务 | 低 |

### 本阶段**禁止碰**的文件

- `session_submit_controller.py` — 与 brain 链路无关，绝对不碰
- `session_aggregation_controller.py` — 同上
- `context_builder.py` — Phase 4 才注入动态状态，本阶段不碰
- `chat_service.py` — Phase 3b 才改，本阶段不碰
- `send_executor.py` — Phase 3b 才新增函数，本阶段不碰
- `proactive/runner.py` — Phase 3b 才对接，本阶段不碰
- `proactive/rules.py` — Phase 3b 才复用漏斗，本阶段不碰

---

## 2. 架构背景（必读，防止错误设计）

### 2.1 proactive 真实发送链路（已考古确认）

```
proactive/runner.py
  check_and_send_once()           ← 漏斗入口
    ├─ hard_cooldown_active()     ← 硬冷却检查
    ├─ failure_pause_active()     ← 失败熔断检查
    ├─ within_active_window()     ← 活跃时间窗口
    ├─ today_sent_count()         ← 日发送上限
    ├─ has_recent_user_message()  ← 近期用户消息检查
    └─ [通过后] send_executor.auto_send_real()
         └─ send_executor.send_proactive_candidate()
              └─ _send_qq_candidate()
                   ├─ _post_neno_bridge_send_qq()  ← HTTP POST 到 neno-bridge
                   └─ _save_proactive_context()    ← add_message() 写 messages 表
```

### 2.2 本阶段 brain 的产出边界

```
WorldEngine heartbeat
  → EventPool.pop_pending()        ← 取出待处理事件
  → NenoBrain.run_cycle()
      ├─ Step1: _rule_filter()     ← 0成本规则过滤
      ├─ Step2: _llm_judge()       ← DeepSeek V4-Pro，强制 JSON
      └─ Step3: _llm_generate()    ← Gemini 3.1 Pro，生成文案
  → Fragmenter.split()             ← 按 | 切分碎片
  → INSERT proactive_intent        ← 写表，等 Phase 3b 消费
  ← 本阶段在此停止，不调用发送
```

### 2.3 并发模型（简化版）

由于 proactive 是"独立线程内的同步函数"而非 asyncio 协程，**Phase 3 不存在 asyncio↔threading 跨范式死锁风险**。brain 是纯 asyncio 协程，写 proactive_intent 表（SQLite WAL）是 aiosqlite 异步操作，两者完全解耦。

---

## 3. config.py 新增字段

```python
# 在 ConsciousnessConfig 中新增：

# Brain 决策
brain_cycle_interval_seconds: int = 60     # 大脑决策周期（秒）
judge_llm_timeout_seconds: float = 8.0     # 判断层超时
generate_llm_timeout_seconds: float = 15.0 # 生成层超时
generate_llm_fallback: str = "mimo-v2.5-pro" # 生成层降级模型

# Fragmenter
max_fragments_per_burst: int = 5           # 单次最多碎片条数
max_proactive_per_hour: int = 6            # 每小时主动消息上限
typing_chars_per_second: float = 8.0       # 模拟打字速度
typing_min_delay: float = 0.8              # 最短打字延迟（秒）
typing_max_delay: float = 4.0              # 最长打字延迟（秒）

# 记忆召回
memory_recall_top_k: int = 5              # 每次召回长期记忆条数
```

---

## 4. 接口定义

### `memory_recall.py`

```python
import logging
from app.storage.database import Database
from .config import ConsciousnessConfig

logger = logging.getLogger(__name__)


class MemoryRecall:
    """
    长期记忆关键词召回。
    数据量小时用关键词匹配，无需向量库。
    接口预留 embedding 扩展点，将来可无痛替换。
    """

    def __init__(self, db: Database, config: ConsciousnessConfig) -> None:
        self._db = db
        self._cfg = config

    async def recall(self, query: str, subject: str | None = None) -> list[str]:
        """
        根据 query 关键词从 long_term_memory 表召回 Top-K 条记忆。
        匹配逻辑：
          1. 若 subject 不为空，优先匹配 subject 字段
          2. 对 content 和 tags 做关键词分词匹配
          3. 按 salience DESC 排序，取前 cfg.memory_recall_top_k 条
          4. 返回 content 字符串列表（供直接注入 prompt）
        失败时返回 []，不 raise。
        """
        ...

    async def add_memory(self, content: str, tags: list[str],
                         subject: str | None, salience: float = 0.5) -> int:
        """写入一条长期记忆，返回 id。Phase 4 梦境服务使用。"""
        ...

    async def update_salience(self, memory_id: int, delta: float) -> None:
        """调整记忆重要度（梦境沉淀时用）"""
        ...
```

### `interrupt.py`

```python
import asyncio
import logging
from typing import Literal

logger = logging.getLogger(__name__)

Phase = Literal["idle", "judging", "generating", "sending"]


class InterruptController:
    """
    三态打断规则状态机。
    - idle      → 无事发生
    - judging   → DeepSeek 判断中（P0 到达可无损取消）
    - generating→ Gemini 生成中（P0 到达：发完当前条，不追加）
    - sending   → 碎片发送中（P0 到达：剩余丢弃，"被打断"入事件池）

    全程 asyncio，无 threading 锁，无死锁风险。
    """

    def __init__(self) -> None:
        self._phase: Phase = "idle"
        self._cancel_event = asyncio.Event()
        self._stop_after_current = False

    @property
    def phase(self) -> Phase:
        return self._phase

    def enter(self, phase: Phase) -> None:
        self._phase = phase
        if phase == "judging":
            self._cancel_event.clear()
        if phase == "idle":
            self._stop_after_current = False

    async def on_p0_interrupt(self, pool=None) -> None:
        """P0 用户消息到达时调用"""
        if self._phase == "judging":
            self._cancel_event.set()
            logger.info("interrupt: cancelled judging")
        elif self._phase in ("generating", "sending"):
            self._stop_after_current = True
            logger.info(f"interrupt: stop_after_current set in {self._phase}")
            if self._phase == "sending" and pool is not None:
                from .event_pool import EventIn
                await pool.push(EventIn(
                    topic_hash="system_interrupted",
                    priority=2,
                    content="说话说到一半被用户打断了",
                    tags=["系统", "打断"],
                    mood_impact=-0.05,
                    source="system",
                ))

    @property
    def should_cancel_judging(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def should_stop_after_current(self) -> bool:
        return self._stop_after_current
```

### `fragmenter.py`

```python
import random
import logging
from datetime import datetime
from .config import ConsciousnessConfig

logger = logging.getLogger(__name__)


class Fragmenter:
    """
    文案碎片化切分 + 打字延迟 + 单位时间频控。
    LLM 输出用 | 分隔多条消息。
    """

    def __init__(self, config: ConsciousnessConfig) -> None:
        self._cfg = config
        self._sent_count_this_hour: int = 0
        self._hour_bucket: int = -1

    def split(self, raw_text: str, energy: float) -> list[str]:
        """
        按 | 切分，并按精力过滤数量和长度。
        - energy < 30：最多 1 条，截断到 10 字
        - energy < 60：最多 3 条
        - energy >= 60：最多 max_fragments_per_burst 条
        """
        parts = [p.strip() for p in raw_text.split("|") if p.strip()]
        if energy < 30:
            parts = parts[:1]
            if parts:
                parts[0] = parts[0][:10]
        elif energy < 60:
            parts = parts[:3]
        else:
            parts = parts[:self._cfg.max_fragments_per_burst]
        return parts

    def typing_delay(self, text: str) -> float:
        """
        打字延迟 = 字数 / chars_per_second + 随机抖动（±20%）
        夹紧到 [min_delay, max_delay]
        """
        base = len(text) / self._cfg.typing_chars_per_second
        jitter = base * random.uniform(-0.2, 0.2)
        return max(self._cfg.typing_min_delay,
                   min(self._cfg.typing_max_delay, base + jitter))

    def check_rate_limit(self) -> bool:
        """每小时频控，返回 True 表示允许"""
        now_hour = datetime.now().hour
        if now_hour != self._hour_bucket:
            self._hour_bucket = now_hour
            self._sent_count_this_hour = 0
        return self._sent_count_this_hour < self._cfg.max_proactive_per_hour

    def record_sent(self) -> None:
        self._sent_count_this_hour += 1
```

### `brain.py`

```python
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.services.llm_gateway import LLMGateway
from app.storage.database import Database
from .config import ConsciousnessConfig
from .desire import DesireModel
from .event_pool import EventPool, EventIn
from .fragmenter import Fragmenter
from .interrupt import InterruptController
from .memory_recall import MemoryRecall
from .models import NenoState, StateMutation, Experience
from .state_store import StateStore

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# Step 2 判断层 System Prompt
# ──────────────────────────────────────────
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

# ──────────────────────────────────────────
# Step 3 生成层 System Prompt
# ──────────────────────────────────────────
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


class NenoBrain:
    """
    Neno 的三步决策引擎。
    消费事件池 → 判断是否表达 → 生成碎片化文案 → 写入 proactive_intent 表。
    不直接发消息，发送由 Phase 3b 的 send_executor.send_brain_intent() 完成。
    """

    def __init__(
        self,
        gateway: LLMGateway,
        state_store: StateStore,
        pool: EventPool,
        recall: MemoryRecall,
        fragmenter: Fragmenter,
        interrupt: InterruptController,
        db: Database,
        config: ConsciousnessConfig,
    ) -> None:
        self._gw = gateway
        self._state = state_store
        self._pool = pool
        self._recall = recall
        self._fragmenter = fragmenter
        self._interrupt = interrupt
        self._db = db
        self._cfg = config
        self._desire_model = DesireModel(config)

    async def run_cycle(self) -> None:
        """
        一次决策周期，由 APScheduler 定期调用（brain_cycle_interval_seconds）。
        """
        trace_id = str(uuid.uuid4())[:8]
        state = await self._state.read()

        if state.energy.status == "sleeping":
            return

        now = datetime.now()

        # P0 事件（极端天气等）直接进判断，无需等表达欲阈值
        p0_events = await self._pool.pop_pending(priority_le=0)

        # 检查表达欲阈值
        desire_val = self._desire_model.current_value(state.desire, now)
        has_desire = self._desire_model.should_express(state.desire, now)

        if not p0_events and not has_desire:
            return

        # 取出 P1/P2 事件
        p12_events = await self._pool.pop_pending(priority_le=2)
        all_events = p0_events + p12_events

        if not all_events:
            return

        # Step 1: 规则过滤（0 成本）
        if self._rule_filter(state, all_events) == "skip":
            logger.debug(f"[{trace_id}] rule_filter: skip")
            return

        # Step 2: 判断层（DeepSeek V4-Pro，强制 JSON）
        self._interrupt.enter("judging")
        decision = await self._llm_judge(state, all_events, trace_id)
        if self._interrupt.should_cancel_judging:
            self._interrupt.enter("idle")
            logger.info(f"[{trace_id}] judging cancelled by P0 interrupt")
            return
        self._interrupt.enter("idle")

        if not decision or not decision.get("should_share"):
            return

        # Step 3: 生成层（Gemini 3.1 Pro → MiMo 降级）
        self._interrupt.enter("generating")
        raw_text = await self._llm_generate(state, all_events, trace_id)
        if not raw_text:
            self._interrupt.enter("idle")
            return

        # 频控检查
        if not self._fragmenter.check_rate_limit():
            logger.info(f"[{trace_id}] rate limit hit, skipping")
            self._interrupt.enter("idle")
            return

        # 碎片化切分
        fragments = self._fragmenter.split(raw_text, state.energy.value)
        if not fragments:
            self._interrupt.enter("idle")
            return

        if self._interrupt.should_stop_after_current:
            fragments = fragments[:1]

        # 确定目标用户
        target_user_id = (
            decision.get("target_user_id")
            or state.last_interaction.user_id
            or None
        )

        if not target_user_id:
            logger.info(f"[{trace_id}] no target user, dropping")
            self._interrupt.enter("idle")
            return

        # 写入 proactive_intent 表（Phase 3b 的 send_brain_intent 消费）
        await self._write_intent(target_user_id, fragments, trace_id)
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
        for ev in all_events[:2]:  # 最多记录前两个触发事件
            await self._state.submit_mutation(StateMutation(
                trace_id=trace_id,
                experience=Experience(
                    time=now.strftime("%H:%M"),
                    content=ev.content,
                    topic_hash=ev.topic_hash,
                    mood_impact=ev.mood_impact,
                ),
                reason="brain expressed experience",
            ))

        self._interrupt.enter("idle")
        logger.info(f"[{trace_id}] intent written for {target_user_id}: {fragments[0][:20]}…")

    def _rule_filter(self, state: NenoState, events: list) -> str:
        """
        Step 1 纯规则过滤，0 成本。
        返回 "skip" 或 "proceed"。
        规则：
        - 在睡眠中 → skip（外层已过滤，此处双重保险）
        - 最近 5 分钟已写过 proactive_intent → skip（防抖）
        - 所有事件都是 P3（纯背景信息）→ skip
        """
        if state.energy.status == "sleeping":
            return "skip"
        if all(getattr(ev, "priority", 3) == 3 for ev in events):
            return "skip"
        return "proceed"

    async def _llm_judge(
        self, state: NenoState, events: list, trace_id: str
    ) -> Optional[dict]:
        """
        Step 2: DeepSeek V4-Pro 判断层。
        超时(judge_llm_timeout_seconds)或 JSON 解析失败 → 返回 None（降级：不打扰）。
        失败写 debug_events，不 raise。
        """
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
                self._gw.call(
                    model="deepseek-v4-pro",
                    messages=[
                        {"role": "system", "content": JUDGE_SYSTEM},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=200,
                ),
                timeout=self._cfg.judge_llm_timeout_seconds,
            )
            # 兼容 markdown 代码块包裹
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except Exception as e:
            logger.warning(f"[{trace_id}] judge LLM failed: {e}")
            await self._write_debug_event(trace_id, "judge_failed", str(e))
            return None

    async def _llm_generate(
        self, state: NenoState, events: list, trace_id: str
    ) -> Optional[str]:
        """
        Step 3: Gemini 3.1 Pro 生成层，降级到 MiMo-V2.5-Pro。
        两个模型都失败 → 返回 None（放弃本次，不发半成品）。
        """
        # 召回相关长期记忆
        recalled = await self._recall.recall(
            query=" ".join(ev.content for ev in events),
            subject=state.last_interaction.user_name or None,
        )
        mem_text = "\n".join(f"- {m}" for m in recalled) if recalled else "（无相关记忆）"
        events_text = "\n".join(f"- {ev.content}" for ev in events)

        user_prompt = (
            f"精力：{state.energy.value:.0f}/100\n"
            f"情绪：{state.mood.label}\n"
            f"关于对方你记得：\n{mem_text}\n\n"
            f"触发你想说话的事：\n{events_text}\n\n"
            f"现在用 | 分隔多条消息，自然地说："
        )

        for model in ["gemini-3.1-pro", self._cfg.generate_llm_fallback]:
            if self._interrupt.should_stop_after_current:
                break
            try:
                result = await asyncio.wait_for(
                    self._gw.call(
                        model=model,
                        messages=[
                            {"role": "system", "content": GENERATE_SYSTEM},
                            {"role": "user", "content": user_prompt},
                        ],
                        max_tokens=300,
                    ),
                    timeout=self._cfg.generate_llm_timeout_seconds,
                )
                if result and result.strip():
                    return result.strip()
            except Exception as e:
                logger.warning(f"[{trace_id}] generate failed ({model}): {e}")
                await self._write_debug_event(trace_id, f"generate_failed_{model}", str(e))
                continue
        return None

    async def _write_intent(
        self, user_id: str, fragments: list[str], trace_id: str
    ) -> None:
        """
        将碎片化消息写入 proactive_intent 表。
        由 Phase 3b 的 send_executor.send_brain_intent() 消费后发送。
        """
        import json as _json
        await self._db.execute(
            "INSERT INTO proactive_intent (user_id, fragments, status, created_at) "
            "VALUES (?, ?, 'queued', ?)",
            (user_id, _json.dumps(fragments, ensure_ascii=False), datetime.now().isoformat()),
        )

    async def _write_debug_event(
        self, trace_id: str, event_type: str, detail: str
    ) -> None:
        """写入 debug_events 表，遵守 NENO_ARCH 第 8 条（所有行为携带 trace_id）"""
        try:
            await self._db.execute(
                "INSERT INTO debug_events (trace_id, event_type, detail, created_at) "
                "VALUES (?, ?, ?, ?)",
                (trace_id, event_type, detail[:500], datetime.now().isoformat()),
            )
        except Exception:
            pass  # debug 写入失败不能影响主流程
```

---

## 5. `__init__.py` 更新（Phase 3a 版本）

```python
# 在 ConsciousnessEngine.__init__() 中新增：

from .brain import NenoBrain
from .fragmenter import Fragmenter
from .interrupt import InterruptController
from .memory_recall import MemoryRecall

# 在 __init__ 中初始化：
self.recall = MemoryRecall(db, self.config)
self._fragmenter = Fragmenter(self.config)
self.interrupt = InterruptController()
self._brain = NenoBrain(
    gateway=gateway,
    state_store=self.state_store,
    pool=self._pool,
    recall=self.recall,
    fragmenter=self._fragmenter,
    interrupt=self.interrupt,
    db=db,
    config=self.config,
)

# 在 start() 中注册 brain_cycle：
scheduler.add_job(
    self._brain.run_cycle,
    "interval",
    seconds=self.config.brain_cycle_interval_seconds,
    id="brain_cycle",
    replace_existing=True,
)
```

---

## 6. 验收标准（Phase 3a 完成的定义）

### 必须全部通过才能进入 Phase 3b

- [ ] `brain._llm_judge()` 单元测试：mock DeepSeek 返回合法 JSON → should_share=True/False 正确；返回非法 JSON → 降级返回 None，写 debug_events
- [ ] `brain._llm_judge()` 超时测试：mock 延迟超过 8s → 返回 None，不 raise
- [ ] `brain._llm_generate()` 单元测试：mock Gemini 失败 → 降级到 MiMo；MiMo 也失败 → 返回 None
- [ ] `fragmenter.split()` 测试：energy=20 时只返回 1 条截断消息；energy=50 返回最多 3 条；energy=80 返回最多 5 条
- [ ] `interrupt.on_p0_interrupt()` 测试：judging 阶段设置 cancel_event；generating 阶段设置 stop_after_current
- [ ] `memory_recall.recall()` 测试：能从 long_term_memory 表按关键词召回，subject 匹配优先
- [ ] `brain.run_cycle()` 完整链路冒烟（单元级，全部 mock）：
  - 插入 1 条 P1 事件，表达欲超阈值 → proactive_intent 表出现 queued 记录
  - 判断层返回 should_share=false → proactive_intent 无新记录
  - 睡眠状态 → run_cycle 直接返回，不调任何 LLM
- [ ] `desire_clear=True` 后，StateStore 中 desire.value 正确清零
- [ ] 所有 LLM 调用超时/失败均写入 debug_events，携带 trace_id，不崩溃

### diff 红线（Phase 3a）

以下文件 diff **必须为空**：
- `session_submit_controller.py`
- `session_aggregation_controller.py`
- `context_builder.py`
- `chat_service.py`
- `send_executor.py`
- `proactive/runner.py`
- `proactive/rules.py`

---

## 7. 给 Claude Code 的执行指令

```
请读取以下文件，然后按本文件第 7 节的指令实现 Phase 3a：

必读文件（全部）：
1. NENO_ARCHITECTURE.md（架构约束）
2. CLAUDE.md（系统硬约束）
3. PHASE_3a.md（本文件）
4. PROACTIVE_ARCHAEOLOGY.md（考古结论——proactive真实发送链路，必读）

重要前提：
- Phase 1（StateStore/DesireModel/MoodModel）和 Phase 2（WorldEngine/EventPool）已完成
- SessionSubmitController 与本阶段完全无关，禁止使用
- 本阶段不真实发消息，只写 proactive_intent 表
- 所有 LLM 调用必须用 asyncio.wait_for 控制超时
- 失败走 debug_events，不 raise 到外层

实现顺序：
1. config.py 追加新字段
2. memory_recall.py（完整实现，不留 ...）
3. interrupt.py（完整实现）
4. fragmenter.py（完整实现）
5. brain.py（完整实现，_write_intent 写 proactive_intent 表）
6. __init__.py 更新（接入 brain，注册 brain_cycle 调度）

完成后写测试：tests/unit/test_brain.py
覆盖：judge 降级、generate 降级、fragmenter split 三档精力、interrupt 三态、run_cycle 完整链路（全 mock）

验收：运行 pytest tests/unit/test_brain.py 全绿后，用 git diff 确认"diff 红线"文件零改动。
```
