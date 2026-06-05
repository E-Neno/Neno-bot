# ⛔ PHASE_4.md 已废弃（OBSOLETE）— 仅作历史归档，不可作为执行依据

> **状态：OBSOLETE / DO NOT IMPLEMENT**（2026-06-06 校正）
>
> 本文件是 Phase 4 的**上一代设计**（"梦境 + 主聊天 prompt 注入"路线）。其中多处设计与**当前红线**及新版规格**直接冲突**，禁止再据此实现：
>
> | 本文中的旧设计 | 冲突点 | 结论 |
> |---|---|---|
> | 改 `chat_service.py` 注入动态状态（§1 改动表 / §3 `_inject_consciousness_state`） | 红线：**禁改 `chat_service.py`** | ❌ 作废 |
> | `state_prompt.py` 把状态文本写入 system message 末尾（§2.1 / §3） | 红线：**禁止把 Living World 注入主聊天 prompt** | ❌ 作废 |
> | 召回 Top-5 记忆注入最后一条 user message（§3 `_inject_consciousness_state`） | 同上：禁 prompt 注入 | ❌ 作废 |
> | 把 Phase 4 当作单块"梦境闭环"一次验收 | 导致"地基完成"被误读为"世界引擎完成" | ❌ 作废 |
>
> **唯一执行依据**：`PHASE_4_LIVING_WORLD_SPEC.md`（规格，§0 为权威阶段划分）+ `PHASE_4_IMPL_PLAN.md`（实现计划，§0.0 为权威任务映射）+ `PHASE_4C_LIVING_SIMULATION_PLAN.md`（完整世界引擎核心计划）。
>
> **文档组约束（必须共同保留 / 共同提交）**：本文件与 `PHASE_4_LIVING_WORLD_SPEC.md`、`PHASE_4_IMPL_PLAN.md`、`PHASE_4C_LIVING_SIMULATION_PLAN.md` 构成**一个不可分割的文档组**。后续若提交，四份必须进**同一个 commit**；**禁止只提交 PHASE_4.md** 而让规格 / 实现计划掉队，否则本文件指向的"唯一执行依据"会悬空。
>
> **幸存的思想**：每日梦境总结 + 长期记忆沉淀的**目标**仍然成立，但已**重生为 `ReflectionEngine`**——它只通过 `MemoryRecall.add_memory()` 写 `long_term_memory`、通过 `StateStore.submit_mutation()` 回注状态，**绝不注入主聊天 prompt、绝不碰 `chat_service.py`**。
>
> 以下原文整体保留仅供历史参考，**不要复制其中任何代码片段或文件改动清单**。

---

# PHASE_4（原文 · 历史归档）— 梦境与长期记忆闭环

> **前置**：Phase 1-3 已完成并通过全部验收标准。完整决策链路可用，消息能正常发出，desire 清零正常。
>
> **本阶段目标**：补全记忆固化回路——凌晨梦境总结、长期记忆沉淀、次日召回注入 prompt、动态状态注入 context。完成后 Neno 真正"记得你"，且状态会动态反映在每次对话中。

---

## 1. 本阶段范围

### 新建文件（全部放在 `app/services/consciousness/`）

| 文件 | 职责 |
|------|------|
| `dream.py` | 每日梦境：凌晨 LLM 总结短期记忆 → 沉淀长期 → 清空短期 |
| `state_prompt.py` | 动态状态文本生成器（供 context 注入使用） |

### 改动现有文件（最小化）

| 文件 | 改动内容 | 风险等级 |
|------|----------|----------|
| `app/services/consciousness/world_engine.py` | `_daily_reset_placeholder` 替换为真实 `DreamService` 调用 | 低 |
| `chat_service.py` | 在 `build_context` 之后、发送之前，将动态状态段注入 system message 末尾 | 中 |
| `app/services/consciousness/__init__.py` | 注入 `DreamService`；暴露 `state_prompt` 给 chat_service | 低 |

### 本阶段**禁止碰**的文件

- `session_aggregation_controller.py` — 命门，绝对不改
- `session_submit_controller.py` — 命门，绝对不改
- `context_builder.py` — **不改内部拼接顺序**，只在调用方（chat_service）注入状态文本
- `history_digest.py` — 不碰
- `proactive/` 目录 — Phase 3 已完成，本阶段不再改动

---

## 2. 关键设计决策

### 2.1 context_builder 注入方案（严格遵守 NENO_ARCH.md 第 4 条）

**绝对不改 `context_builder.py` 内部的 list.append 顺序。**

动态状态的注入发生在 `chat_service.py` 中，在 `build_context()` 返回之后：

```
build_context() 返回 messages 列表
    → 找到 role=system 的第一条
    → 在其 content 末尾追加 "\n\n" + state_prompt_text
    → 召回的 Top-5 记忆追加到 memory 段（找 role=user 中的记忆块末尾）
```

这样既注入了动态状态，又零成本保住了 Anthropic prompt cache 前缀稳定性（history_digest 及之后才是缓存大头，system message 结构变化影响最小）。

### 2.2 梦境 LLM 选型与降级

| 场景 | 模型 | 超时 | 降级 |
|------|------|------|------|
| 每日梦境总结 | `mimo-v2.5-pro` | 30s | 跳过本次总结，**不清空短期记忆**（宁可堆积，不丢数据） |
| 长期记忆提取 | `mimo-v2.5-pro` | 20s | 跳过提取，短期记忆照常清空 |

### 2.3 1-Turn Lag 与世界引擎时序隔离（重申）

- 对话链路（memory/relationship 变更）：**严格 1-Turn Lag**，下一轮生效
- 世界引擎状态（energy/mood/desire）：**即时写入 StateStore**，当轮可读
- 梦境沉淀的长期记忆：**次日起效**（梦境在凌晨 3 点跑，次日 8 点醒来后召回）

---

## 3. 接口定义

### `dream.py`

```python
import json
import logging
import uuid
from datetime import datetime, date
from typing import Optional

from app.services.llm_gateway import LLMGateway
from app.storage.database import Database
from .config import ConsciousnessConfig
from .memory_recall import MemoryRecall
from .models import NenoState, StateMutation
from .state_store import StateStore

logger = logging.getLogger(__name__)

DREAM_SUMMARY_SYSTEM = """你是 Neno 的潜意识。现在是凌晨，她快要睡着了，脑海中浮现今天发生的事。

你的任务：
1. 用 2-3 句话，以 Neno 的视角，总结今天印象最深的事（不是流水账，是感受）
2. 从今天的经历中提取值得长期记住的信息，格式如下（JSON 数组）：

[
  {
    "content": "具体事实或印象，一句话",
    "tags": ["标签1", "标签2"],
    "subject": "关于谁（没有则 null）",
    "salience": 0.0到1.0之间的重要度
  }
]

规则：
- 只提取真正值得记住的（salience > 0.5），不重要的直接忽略
- 每次最多提取 5 条
- 输出格式：先输出总结文本，然后输出 ===MEMORIES===，然后输出 JSON 数组
- 示例：
  今天其实挺无聊的，就是下午刷到那条视频笑了挺久，还好有那一下。
  ===MEMORIES===
  [{"content": "用户小明喜欢喝美式咖啡", "tags": ["preference", "coffee", "xiaoming"], "subject": "xiaoming", "salience": 0.8}]
"""

DREAM_NO_MEMORIES_MARKER = "===MEMORIES==="


class DreamService:
    """
    每日梦境服务。
    凌晨 3 点由 APScheduler 触发，总结短期记忆并沉淀到长期记忆。
    失败策略：宁可跳过，不清空数据，不崩溃。
    """

    def __init__(
        self,
        gateway: LLMGateway,
        state_store: StateStore,
        recall: MemoryRecall,
        db: Database,
        config: ConsciousnessConfig,
    ) -> None:
        self._gw = gateway
        self._state = state_store
        self._recall = recall
        self._db = db
        self._cfg = config

    async def run(self) -> None:
        """
        梦境主流程：
        1. 读取今日 today_experiences（短期记忆）
        2. 若为空，直接进入睡眠状态，不调 LLM
        3. 调 MiMo 生成梦境总结 + 提取长期记忆
        4. 写入 long_term_memory 表
        5. 清空 today_experiences
        6. 更新 energy.status = sleeping
        7. 全程异常捕获，写 debug_events
        """
        trace_id = str(uuid.uuid4())[:8]
        logger.info(f"[{trace_id}] dream started")

        state = await self._state.read()
        experiences = state.today_experiences

        if not experiences:
            logger.info(f"[{trace_id}] no experiences today, skip dream LLM")
            await self._enter_sleep(trace_id)
            return

        # 构造今日经历文本
        exp_text = "\n".join(
            f"[{e.time}] {e.content}" for e in experiences
        )

        # 调 MiMo 生成梦境
        summary, memories = await self._run_dream_llm(exp_text, trace_id)

        if memories:
            await self._save_memories(memories, trace_id)

        # 清空短期记忆（无论 LLM 是否成功，都清空——避免无限堆积）
        # 若 LLM 完全失败（summary=None），仍然清空，但不写长期记忆
        await self._clear_today_experiences(trace_id)

        # 记录梦境总结到 debug_events（供观察）
        if summary:
            await self._write_debug_event(trace_id, "dream_summary", summary[:300])

        await self._enter_sleep(trace_id)
        logger.info(f"[{trace_id}] dream completed, saved {len(memories)} memories")

    async def _run_dream_llm(
        self, exp_text: str, trace_id: str
    ) -> tuple[Optional[str], list[dict]]:
        """
        调 MiMo 生成梦境文本并解析长期记忆。
        返回 (summary_text, memories_list)。
        任何失败返回 (None, [])，不 raise。
        """
        try:
            import asyncio
            raw = await asyncio.wait_for(
                self._gw.call(
                    model="mimo-v2.5-pro",
                    messages=[
                        {"role": "system", "content": DREAM_SUMMARY_SYSTEM},
                        {"role": "user", "content": f"今天的经历：\n{exp_text}"},
                    ],
                    max_tokens=800,
                ),
                timeout=30.0,
            )
            return self._parse_dream_output(raw)
        except Exception as e:
            logger.warning(f"[{trace_id}] dream LLM failed: {e}")
            await self._write_debug_event(trace_id, "dream_llm_failed", str(e))
            return None, []

    @staticmethod
    def _parse_dream_output(raw: str) -> tuple[Optional[str], list[dict]]:
        """
        解析 LLM 输出。
        格式：summary文本 + ===MEMORIES=== + JSON数组
        若格式不对，只返回 summary，memories 为空。
        """
        if DREAM_NO_MEMORIES_MARKER not in raw:
            return raw.strip(), []

        parts = raw.split(DREAM_NO_MEMORIES_MARKER, 1)
        summary = parts[0].strip()
        try:
            memories = json.loads(parts[1].strip())
            if not isinstance(memories, list):
                memories = []
        except (json.JSONDecodeError, IndexError):
            memories = []

        # 过滤低 salience
        memories = [m for m in memories if isinstance(m, dict)
                    and m.get("salience", 0) > 0.5]
        return summary, memories[:5]   # 最多 5 条

    async def _save_memories(self, memories: list[dict], trace_id: str) -> None:
        """批量写入 long_term_memory 表"""
        today = date.today().isoformat()
        for m in memories:
            try:
                await self._recall.add_memory(
                    content=m.get("content", ""),
                    tags=m.get("tags", []),
                    subject=m.get("subject"),
                    salience=float(m.get("salience", 0.5)),
                )
            except Exception as e:
                logger.warning(f"[{trace_id}] save memory failed: {e}")

    async def _clear_today_experiences(self, trace_id: str) -> None:
        """通过 StateMutation 清空 today_experiences"""
        from .models import StateMutation
        # 用特殊 mutation 清空（在 state_store._apply_mutation 中处理）
        await self._state.submit_mutation(StateMutation(
            trace_id=trace_id,
            reason="dream: clear today experiences",
            # 约定：experience=None 且 clear_experiences=True 时清空列表
            # 需要在 StateMutation 中新增此字段（见下方 models.py 补充）
        ))

    async def _enter_sleep(self, trace_id: str) -> None:
        """更新 energy.status = sleeping"""
        from .models import StateMutation
        await self._state.submit_mutation(StateMutation(
            trace_id=trace_id,
            reason="dream: enter sleep",
            # 约定：set_sleeping=True（需在 StateMutation 新增此字段）
        ))

    async def _write_debug_event(self, trace_id: str,
                                  event_type: str, detail: str) -> None:
        try:
            await self._db.execute(
                "INSERT INTO debug_events (trace_id, event_type, detail, created_at) "
                "VALUES (?, ?, ?, ?)",
                (trace_id, event_type, detail[:500], datetime.now().isoformat()),
            )
        except Exception:
            pass
```

### `models.py` 补充字段（在 Phase 4 中追加到 StateMutation）

```python
# 在 StateMutation 模型中新增以下字段：

class StateMutation(BaseModel):
    # ... 原有字段保持不变 ...

    # Phase 4 新增
    clear_experiences: bool = False    # 梦境后清空 today_experiences
    set_sleeping: bool = False          # 进入睡眠状态
    set_awake: bool = False             # 醒来（world_engine 早上8点触发）
```

同时在 `state_store._apply_mutation()` 中处理这三个新字段：
```python
if mutation.clear_experiences:
    state.today_experiences = []
if mutation.set_sleeping:
    state.energy.status = "sleeping"
    state.energy.last_sleep_time = now
if mutation.set_awake:
    state.energy.status = "awake"
    state.energy.value = self._cfg.energy_wake_value
    state.energy.last_wake_time = now
    state.desire.value = 10.0   # 刚醒来，表达欲低
```

### `state_prompt.py`

```python
from datetime import datetime
from .models import NenoState
from .desire import DesireModel
from .config import ConsciousnessConfig


class StatePromptBuilder:
    """
    将 NenoState 转换为注入 system prompt 的自然语言文本块。
    供 chat_service.py 在 build_context() 之后调用。

    注入位置：role=system 的 content 末尾（不改 context_builder 内部顺序）。
    """

    def __init__(self, config: ConsciousnessConfig) -> None:
        self._cfg = config
        self._desire = DesireModel(config)

    def build(self, state: NenoState, now: datetime | None = None) -> str:
        """
        生成动态状态文本，供注入到 system prompt 末尾。
        格式设计原则：
        - 简短（< 150 字），不喧宾夺主
        - 数值转自然语言（不直接露出数字）
        - 与 Neno 人设一致（第三人称描述给 LLM 看）
        """
        now = now or datetime.now()
        desire_val = self._desire.current_value(state.desire, now)

        energy_desc = self._energy_to_text(state.energy.value,
                                            state.energy.status)
        mood_desc = state.mood.description or state.mood.label
        desire_desc = self._desire_to_text(desire_val)

        # 今日经历摘要（最近 3 条）
        recent = state.today_experiences[-3:] if state.today_experiences else []
        exp_lines = [f"- {e.content}" for e in recent]
        exp_text = "\n".join(exp_lines) if exp_lines else "- 今天还没发生什么特别的事"

        # 上次互动
        last = state.last_interaction
        last_text = (
            f"上次和{last.user_name}聊天：{last.summary}"
            if last.user_name else "今天还没和用户互动过"
        )

        return (
            f"\n\n---\n"
            f"[Neno 当前状态 · 仅你可见]\n"
            f"精力：{energy_desc}\n"
            f"情绪：{mood_desc}\n"
            f"表达欲：{desire_desc}\n"
            f"今天发生的事：\n{exp_text}\n"
            f"{last_text}\n"
            f"当前时间：{state.world.time_context or self._time_context(now)}\n"
            f"天气：{state.world.weather.text or '未知'}\n"
            f"---"
        )

    @staticmethod
    def _energy_to_text(value: float, status: str) -> str:
        if status == "sleeping":
            return "睡觉中"
        if value >= 80:
            return "挺精神的"
        if value >= 60:
            return "还行，不算累"
        if value >= 40:
            return "有点累了"
        if value >= 20:
            return "很累，不想多说话"
        return "困到不行"

    @staticmethod
    def _desire_to_text(value: float) -> str:
        if value >= 70:
            return "很想找人说说话"
        if value >= 50:
            return "有点想聊聊"
        if value >= 30:
            return "还好，可说可不说"
        return "不太想说话"

    @staticmethod
    def _time_context(now: datetime) -> str:
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        wd = weekdays[now.weekday()]
        h = now.hour
        if 5 <= h < 9:
            period = "早上"
        elif 9 <= h < 12:
            period = "上午"
        elif 12 <= h < 14:
            period = "中午"
        elif 14 <= h < 18:
            period = "下午"
        elif 18 <= h < 21:
            period = "傍晚"
        elif 21 <= h < 24:
            period = "晚上"
        else:
            period = "深夜"
        return f"{wd}{period}{now.strftime('%H:%M')}"
```

### `chat_service.py` 追加（Phase 4 部分，动态状态注入）

```python
# 在 handle_message() 中，build_context() 之后、调用 llm_gateway 之前追加：

async def _inject_consciousness_state(
    self,
    messages: list[dict],
    consciousness_engine,  # ConsciousnessEngine | None
) -> list[dict]:
    """
    将动态状态注入到 system message 末尾。
    召回的 Top-5 记忆注入到最后一条 user message 之前。

    ⚠️ 只修改 content 字符串，不改 messages 列表的顺序和长度。
    ⚠️ 不改 context_builder.py 内部任何逻辑。
    """
    if consciousness_engine is None:
        return messages

    try:
        state = await consciousness_engine.state_store.read()
        prompt_builder = consciousness_engine.state_prompt_builder

        # 1. 动态状态注入到 system message 末尾
        for msg in messages:
            if msg.get("role") == "system":
                state_text = prompt_builder.build(state)
                msg["content"] = msg["content"] + state_text
                break

        # 2. 召回 Top-5 相关记忆，注入到最后一条 user message 之前
        # 取最后一条 user 消息作为召回 query
        user_query = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            ""
        )
        if user_query:
            recalled = await consciousness_engine.recall.recall(
                query=user_query,
                subject=state.last_interaction.user_name or None,
            )
            if recalled:
                mem_text = "（Neno 记得：" + "；".join(recalled) + "）"
                # 插入到最后一条 user message 的 content 开头
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "user":
                        messages[i]["content"] = mem_text + "\n" + messages[i]["content"]
                        break

    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"state inject failed: {e}")
        # 失败时静默，返回原始 messages

    return messages
```

### `world_engine.py` 补充：醒来任务

```python
# 在 register_jobs() 中新增：

self._scheduler.add_job(
    self._wake_up,
    "cron",
    hour=self._cfg.wake_hour, minute=0,
    id="daily_wake",
    replace_existing=True,
)

# 替换 _daily_reset_placeholder：
async def _daily_dream(self) -> None:
    """凌晨 3 点：触发梦境服务（由 ConsciousnessEngine 注入 DreamService）"""
    if self._dream_service:
        await self._dream_service.run()

async def _wake_up(self) -> None:
    """早上 wake_hour 点：醒来，恢复精力"""
    from .models import StateMutation
    import uuid
    trace_id = str(uuid.uuid4())[:8]
    await self._state.submit_mutation(StateMutation(
        trace_id=trace_id,
        set_awake=True,
        reason="daily wake up",
    ))
    logger.info("Neno woke up")
```

### `__init__.py`（Phase 4 最终版本）

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.storage.database import Database
from app.services.llm_gateway import LLMGateway
from .config import ConsciousnessConfig
from .state_store import StateStore
from .perception import PerceptionService
from .event_pool import EventPool
from .world_engine import WorldEngine
from .brain import NenoBrain
from .fragmenter import Fragmenter
from .interrupt import InterruptController
from .memory_recall import MemoryRecall
from .dream import DreamService
from .state_prompt import StatePromptBuilder


class ConsciousnessEngine:
    """consciousness 层总门面，由 main.py lifespan 启停。"""

    def __init__(
        self,
        db: Database,
        scheduler: AsyncIOScheduler,
        gateway: LLMGateway,
        config: ConsciousnessConfig | None = None,
    ) -> None:
        self.config = config or ConsciousnessConfig()

        # 核心组件
        self.state_store = StateStore(db, self.config)
        self._perception = PerceptionService(self.config)
        self._pool = EventPool(db, self.config)
        self.recall = MemoryRecall(db, self.config)
        self._fragmenter = Fragmenter(self.config)
        self.interrupt = InterruptController()
        self.state_prompt_builder = StatePromptBuilder(self.config)

        # 大脑
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

        # 梦境
        self._dream = DreamService(
            gateway=gateway,
            state_store=self.state_store,
            recall=self.recall,
            db=db,
            config=self.config,
        )

        # 世界引擎
        self._world_engine = WorldEngine(
            scheduler=scheduler,
            perception=self._perception,
            pool=self._pool,
            state_store=self.state_store,
            config=self.config,
            dream_service=self._dream,        # Phase 4 注入
        )

        # 大脑消费任务（APScheduler 注册）
        scheduler.add_job(
            self._brain.run_cycle,
            "interval",
            seconds=self.config.brain_cycle_interval_seconds,
            id="brain_cycle",
            replace_existing=True,
        )

    async def start(self) -> None:
        await self.state_store.start()
        self._world_engine.register_jobs()

    async def stop(self) -> None:
        await self.state_store.stop()

    async def feed_user_event(
        self, user_id: str, user_name: str,
        message_summary: str, mood_impact: float = 0.1,
    ) -> None:
        """chat_service 在回复后调用，更新 last_interaction 和情绪。"""
        from .models import StateMutation, LastInteraction
        from datetime import datetime
        await self.state_store.submit_mutation(StateMutation(
            trace_id=f"user_{user_id}_{int(datetime.now().timestamp())}",
            last_interaction=LastInteraction(
                user_id=user_id,
                user_name=user_name,
                time=datetime.now(),
                summary=message_summary[:50],
            ),
            mood_valence_delta=mood_impact,
            reason="user interaction",
        ))
        await self.interrupt.on_p0_interrupt(pool=self._pool)
```

**同时在 `config.py` 新增：**
```python
brain_cycle_interval_seconds: int = 60  # 大脑决策周期（秒）
```

---

## 4. 验收标准（Phase 4 完成的定义）

### 梦境流程
- [ ] 凌晨 3 点 APScheduler 正常触发 `dream.run()`，日志可见
- [ ] `today_experiences` 有内容时，MiMo 生成梦境文本，debug_events 可见 `dream_summary`
- [ ] 长期记忆正确写入 `long_term_memory` 表（salience > 0.5 的才写入）
- [ ] 梦境完成后 `today_experiences` 被清空，`energy.status` 变为 `sleeping`
- [ ] MiMo 调用失败时，**不清空短期记忆**（宁可堆积，不丢数据），日志写入 debug_events
- [ ] 早上 8 点 `set_awake=True` 触发，`energy.value` 恢复到 95，`desire.value` 重置为 10

### 记忆召回
- [ ] `memory_recall.recall("喜欢咖啡", subject="小明")` 返回包含"美式咖啡"的记忆
- [ ] 召回结果正确注入到对话的 user message 中（prefix 形式）
- [ ] 注入后 `context_builder.py` 的 list.append 顺序未被改动（diff 验证）

### 动态状态注入
- [ ] 每次对话，system message 末尾包含 `[Neno 当前状态]` 文本块
- [ ] 精力值 < 30 时，状态文本描述为"困到不行"类似语气
- [ ] `context_builder.py` 内部未被改动（diff 验证）

### 整体闭环
- [ ] 完整闭环测试：手动触发梦境 → 确认记忆写入 → 次日对话 → 确认记忆召回注入 prompt → LLM 回复体现对用户的"记忆"
- [ ] 所有 LLM 调用超时/失败均写入 debug_events，系统不崩溃
- [ ] 2GB 内存压力测试：连续运行 24 小时，内存无明显泄漏（`/debug` 观察）

---

## 5. 给 Claude Code 的执行指令

```
请基于以下文件实现 Phase 4：
- 参考约束：NENO_ARCH.md（必读，禁止改 context_builder 顺序）
- 当前任务：PHASE_4.md（本文件）
- 依赖前提：Phase 1-3 已完成，完整发送链路可用

实现顺序：
1. models.py 追加 StateMutation 的三个新字段（clear_experiences / set_sleeping / set_awake）
2. state_store._apply_mutation() 处理这三个新字段
3. app/services/consciousness/dream.py（完整实现）
4. app/services/consciousness/state_prompt.py（完整实现）
5. app/services/consciousness/__init__.py 最终版本
6. world_engine.py 替换 _daily_reset_placeholder → 真实梦境调用，新增 _wake_up
7. chat_service.py 追加 _inject_consciousness_state()，并在主流程中调用

要求：
- dream.py 的 _parse_dream_output 必须健壮：JSON 解析失败时返回 (summary, []) 不 raise
- dream._clear_today_experiences() 必须在 LLM 成功/失败后都执行（finally 块）
- state_prompt.build() 的输出长度控制在 200 字以内，不喧宾夺主
- chat_service 注入后，用 diff 验证 context_builder.py 零改动
- 实现完成后写端到端测试脚本（test_dream_cycle.py）：
    mock 今日经历 → 触发梦境 → 验证 long_term_memory 表有新记录 → 验证 today_experiences 已清空
- session_aggregation_controller.py 和 session_submit_controller.py 零改动（diff 验证）
```

---

## 附：完整验收检查清单（四阶段总览）

在认为项目完成前，逐条过一遍：

### 架构约束
- [ ] `context_builder.py` list.append 顺序未被改动
- [ ] `session_aggregation_controller.py` 未被改动
- [ ] `session_submit_controller.py` 未被改动
- [ ] `history_digest.py` 未被改动
- [ ] 所有新增代码在 `app/services/consciousness/` 目录内
- [ ] 无第二套并发原语（consciousness 层只用 asyncio，发送命门仍用原 threading）
- [ ] state.json 不存在于文件系统，状态只在 `agent_state` 表（SQLite 单一真相源）

### 功能闭环
- [ ] Phase 1：状态机读写、乐观锁、重启恢复
- [ ] Phase 2：心跳感知、事件去重、随机事件
- [ ] Phase 3：三步决策、碎片发送、P0 打断、频控
- [ ] Phase 4：梦境总结、记忆沉淀、召回注入、动态状态注入

### 健壮性
- [ ] 所有 LLM 超时/失败有降级，写 debug_events，不 raise 到外层
- [ ] 世界引擎 heartbeat 异常被 catch，不让 APScheduler 停止调度
- [ ] 梦境失败不清空短期记忆（宁可堆积）
- [ ] 2GB 内存下 24 小时稳定运行
