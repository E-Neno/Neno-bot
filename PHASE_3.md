# PHASE_3 — 大脑决策与发送

> **前置**：Phase 1 和 Phase 2 已完成并通过全部验收标准。StateStore 稳定运行，世界引擎心跳正常，事件池去重可用。
>
> **本阶段目标**：打通完整决策链路——事件池 → 三步判断 → 碎片化文案 → 经由 SessionSubmitController 命门真实发送。**首次真实发消息，务必先在白名单单用户灰度测试。**
>
> ⚠️ **本阶段涉及现有命门模块，改动前必须重读 NENO_ARCH.md 第 9、10 条。**

---

## 0. 你需要在开始前补充的信息

**在执行本阶段前，请将以下内容填入此文件对应位置，或直接追加到 NENO_ARCH.md：**

```
# 需要补充：SessionSubmitController 的真实接口

# 问题1：世界引擎投递主动意图时，调用 SessionSubmitController 的哪个方法？
# 答：_______________

# 问题2：proactive/engine.py 目前如何触发消息发送？用什么参数？
# 答：_______________

# 问题3：硬冷却期检查在 proactive/rules.py 的哪个方法？
# 答：_______________
```

**在拿到上述答案之前，brain.py 中的 `_deliver_to_proactive()` 方法留 stub，不要假设接口。**

---

## 1. 本阶段范围

### 新建文件（全部放在 `app/services/consciousness/`）

| 文件 | 职责 |
|------|------|
| `brain.py` | 三步决策编排（规则过滤 → 判断层 LLM → 生成层 LLM） |
| `fragmenter.py` | 文案碎片化切分 + 打字延迟计算 + 单位时间频控 |
| `interrupt.py` | 三态打断规则状态机（酝酿/生成/已发送） |
| `memory_recall.py` | 长期记忆关键词召回（Top-K，为生成层提供上下文） |

### 改动现有文件（最小化）

| 文件 | 改动内容 | 风险等级 |
|------|----------|----------|
| `proactive/engine.py` | 新增 `consume_world_intent()` 方法，消费 `proactive_intent` 表中的 queued 意图；原有模板逻辑**保留不删** | 中 |
| `chat_service.py` | 在回复生成完成后，调用 `consciousness_engine.feed_user_event()` 更新 last_interaction 和情绪；原有逻辑不变 | 低 |
| `llm_gateway.py` | 新增三个模型 key 的路由配置（deepseek-v4-pro / gemini-3.1-pro / mimo-v2.5-pro）；不改 `call()` 签名 | 低 |
| `app/services/consciousness/__init__.py` | 启动 brain 的消费循环；注册 proactive 消费任务 | 低 |
| `main.py` | lifespan 中将 `ConsciousnessEngine` 实例注入 app.state；`chat_service` 从 app.state 读取 | 低 |

### 本阶段**禁止碰**的文件

- `session_aggregation_controller.py` — 绝对命门，不改
- `session_submit_controller.py` — 绝对命门，不改
- `context_builder.py` — Phase 4 的动态状态注入会改，本阶段不碰
- `history_digest.py` — 不碰
- `proactive/rules.py` — 只读（调用其硬冷却检查），不改逻辑

---

## 2. 关键架构决策（必须遵守）

### 2.1 并发隔离：asyncio 与 threading 不交叉持锁

```
世界引擎（asyncio）
    ↓ 写 proactive_intent 表（SQLite，WAL）
proactive/engine.py 消费循环（asyncio）
    ↓ 读 proactive_intent 表
    ↓ 调用 SessionSubmitController（threading.RLock）← 唯一命门
    ↓ 发送
```

**consciousness 层不直接持有 SessionSubmitController 的锁。**
所有发送路径都经由 `proactive/engine.py` 的现有接口，由它去调命门。
世界引擎和命门之间通过 SQLite 表（`proactive_intent`）解耦，不共享内存队列。

### 2.2 LLM 分工

| 步骤 | 模型 key | 输出格式 | 超时 | 降级策略 |
|------|----------|----------|------|----------|
| Step 2 判断层 | `deepseek-v4-pro` | 强制 JSON | 8s | 返回 `{"should_share": false}` |
| Step 3 生成层 | `gemini-3.1-pro` | 纯文本（含 `\|` 分隔符） | 15s | 降级到 `mimo-v2.5-pro`；再失败则放弃 |
| 每日梦境（Phase 4） | `mimo-v2.5-pro` | 纯文本 | 30s | 跳过，不清空短期记忆 |

### 2.3 context_builder 注入方案（不改拼接顺序）

动态状态注入位置：**SYSTEM_PROMPT 之后、history_digest 之前**（作为独立稳定段）。
召回记忆注入位置：**并入既有 memory 段末尾**。

```python
# context_builder.py 中，在现有 build_context 末尾追加（不改原有顺序）：
# 由 consciousness 层调用者在调用 build_context 之后、send 之前注入
# 具体：在 chat_service.py 中，build_context 返回的 messages 列表里
# 找到 role=system 的那条，在其 content 末尾 append 动态状态文本块
```

**不允许在 context_builder.py 内部修改任何 list.append 顺序。**

---

## 3. 接口定义

### `memory_recall.py`

```python
import logging
from app.storage.database import Database
from .config import ConsciousnessConfig

logger = logging.getLogger(__name__)


class MemoryRecall:
    """
    长期记忆关键词召回。
    数据量小时（<1000条）用关键词匹配，无需向量库。
    接口预留 embedding 扩展点，将来无痛替换。
    """

    def __init__(self, db: Database, config: ConsciousnessConfig) -> None:
        self._db = db
        self._cfg = config

    async def recall(self, query: str, subject: str | None = None) -> list[str]:
        """
        根据 query 关键词从 long_term_memory 表召回 Top-K 条记忆。
        匹配逻辑：
          1. 若 subject 不为空，优先匹配 subject 字段
          2. 对 content 和 tags 做关键词分词匹配（jieba 分词或简单分割）
          3. 按 salience DESC 排序，取前 cfg.memory_recall_top_k 条
          4. 返回 content 字符串列表（供直接注入 prompt）
        """
        ...

    async def add_memory(self, content: str, tags: list[str],
                         subject: str | None, salience: float = 0.5) -> int:
        """写入一条长期记忆，返回 id"""
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
from datetime import datetime

logger = logging.getLogger(__name__)

Phase = Literal["idle", "judging", "generating", "sending"]


class InterruptController:
    """
    三态打断规则状态机。
    - idle      → 无事发生
    - judging   → 便宜 LLM 判断中（P0 到达可无损取消）
    - generating→ 主力 LLM 生成文案中（P0 到达：发完当前条，不追加）
    - sending   → 碎片消息发送中（P0 到达：剩余丢弃，"被打断"作为事件入池）

    线程安全：所有操作在同一 asyncio 事件循环内，无需 threading 锁。
    """

    def __init__(self) -> None:
        self._phase: Phase = "idle"
        self._cancel_event = asyncio.Event()   # judging 阶段取消信号
        self._stop_after_current = False        # generating 阶段：发完即停

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
        """
        P0 用户消息到达时调用。
        - judging  → 设置 cancel_event，让判断协程自行退出
        - generating → 设置 stop_after_current=True
        - sending  → 设置 stop_after_current=True；将"被打断"推入事件池
        - idle     → 无操作
        """
        if self._phase == "judging":
            self._cancel_event.set()
            logger.info("interrupt: cancelled judging phase")
        elif self._phase in ("generating", "sending"):
            self._stop_after_current = True
            logger.info(f"interrupt: stop_after_current set in {self._phase}")
            if self._phase == "sending" and pool is not None:
                # 被打断作为事件喂给状态机
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
import asyncio
import logging
import time
from .config import ConsciousnessConfig

logger = logging.getLogger(__name__)

MAX_FRAGMENTS_PER_BURST = 5     # 单次发送最多碎片条数
MIN_DELAY_SECONDS = 0.8         # 最短打字延迟
MAX_DELAY_SECONDS = 4.0         # 最长打字延迟
CHARS_PER_SECOND = 8            # 模拟打字速度


class Fragmenter:
    """
    文案碎片化切分 + 打字延迟 + 单位时间频控。
    碎片分隔符：LLM 输出中用 | 分隔多条消息。
    """

    def __init__(self, config: ConsciousnessConfig) -> None:
        self._cfg = config
        self._sent_count_this_hour: int = 0
        self._hour_bucket: int = -1   # 当前小时标记，用于重置计数

    def split(self, raw_text: str, energy: float) -> list[str]:
        """
        将 LLM 原始输出按 | 切分，并按精力过滤。
        - energy < 30：最多保留 1 条，且强制短（截断到 10 字）
        - energy < 60：最多保留 3 条
        - energy >= 60：最多 MAX_FRAGMENTS_PER_BURST 条
        去掉空白碎片，去掉前后空格。
        """
        parts = [p.strip() for p in raw_text.split("|") if p.strip()]
        if energy < 30:
            parts = parts[:1]
            if parts:
                parts[0] = parts[0][:10]
        elif energy < 60:
            parts = parts[:3]
        else:
            parts = parts[:MAX_FRAGMENTS_PER_BURST]
        return parts

    def typing_delay(self, text: str) -> float:
        """
        计算打字延迟（秒）。
        公式：字数 / CHARS_PER_SECOND + 随机抖动（±20%）
        夹紧到 [MIN_DELAY, MAX_DELAY]。
        """
        import random
        base = len(text) / CHARS_PER_SECOND
        jitter = base * random.uniform(-0.2, 0.2)
        return max(MIN_DELAY_SECONDS, min(MAX_DELAY_SECONDS, base + jitter))

    def check_rate_limit(self) -> bool:
        """
        单位时间（小时）频控：最多发 N 条主动消息。
        N 由 config.max_proactive_per_hour 控制（默认 6）。
        返回 True 表示允许发送，False 表示超频。
        """
        now_hour = __import__("datetime").datetime.now().hour
        if now_hour != self._hour_bucket:
            self._hour_bucket = now_hour
            self._sent_count_this_hour = 0
        limit = getattr(self._cfg, "max_proactive_per_hour", 6)
        return self._sent_count_this_hour < limit

    def record_sent(self) -> None:
        self._sent_count_this_hour += 1
```

**同时在 `config.py` 中新增字段：**
```python
max_proactive_per_hour: int = 6   # 每小时主动发消息上限（防刷屏）
```

### `brain.py`

```python
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

# ---- Step 2 判断层 Prompt ----
JUDGE_SYSTEM = """你是 Neno 的内心独白引擎。根据给定的状态和事件列表，判断她现在是否想跟人说点什么。

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
"""

# ---- Step 3 生成层 Prompt ----
GENERATE_SYSTEM = """你是 Neno，一个住在南宁的普通女生，20岁左右。
性格：慢热、安静、温柔、有点拘谨、说话直接。
绝对不暴露自己是 AI。

发消息规则：
- 用 | 分隔多条消息，像真人发微信那样分开发
- 消息要短，每条最多 20 字
- 语气自然随意，不要正式
- 根据精力值调整：精力低就少说、说短点
- 不是每件事都要说，有时候就随口一句

示例格式：
"诶 你那边下雨了吗|看天气预报说南宁要下暴雨|不知道严不严重"
"""


class NenoBrain:
    """
    Neno 的三步决策引擎。
    消费事件 → 判断是否表达 → 生成文案 → 投递到 proactive_intent 表。
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
        一次决策周期，由 APScheduler 或专用消费协程定期调用。
        1. 读当前状态
        2. 检查 P0 事件（立刻处理）
        3. 检查表达欲阈值 → 批量取 P1/P2 事件
        4. Step1 规则过滤
        5. Step2 判断层
        6. Step3 生成并投递
        """
        trace_id = str(uuid.uuid4())[:8]
        state = await self._state.read()

        # 检查睡眠
        if state.energy.status == "sleeping":
            return

        # P0：极端天气等，直接进判断
        p0_events = await self._pool.pop_pending(priority_le=0)

        # 表达欲阈值检查
        now = datetime.now()
        desire_val = self._desire_model.current_value(state.desire, now)
        has_desire = self._desire_model.should_express(state.desire, now)

        pending_events = p0_events
        if has_desire or p0_events:
            p12_events = await self._pool.pop_pending(priority_le=2)
            pending_events = p0_events + p12_events

        if not pending_events:
            return

        # Step 1: 规则过滤
        verdict = self._rule_filter(state, pending_events)
        if verdict == "skip":
            return

        # Step 2: 判断层（DeepSeek，强制 JSON）
        self._interrupt.enter("judging")
        decision = await self._llm_judge(state, pending_events, trace_id)
        if self._interrupt.should_cancel_judging:
            self._interrupt.enter("idle")
            logger.info(f"[{trace_id}] judging cancelled by P0 interrupt")
            return
        self._interrupt.enter("idle")

        if not decision or not decision.get("should_share"):
            return

        # Step 3: 生成层（Gemini → MiMo 降级）
        self._interrupt.enter("generating")
        raw_text = await self._llm_generate(state, pending_events, decision, trace_id)
        if not raw_text:
            self._interrupt.enter("idle")
            return

        # 碎片化切分 + 频控
        if not self._fragmenter.check_rate_limit():
            logger.info(f"[{trace_id}] rate limit hit, skipping")
            self._interrupt.enter("idle")
            return

        fragments = self._fragmenter.split(raw_text, state.energy.value)
        if not fragments:
            self._interrupt.enter("idle")
            return

        if self._interrupt.should_stop_after_current:
            fragments = fragments[:1]   # 发完当前这条即停

        # 写入 proactive_intent 表（由 proactive/engine 消费发送）
        target_user = decision.get("target_user_id") or \
                      (state.last_interaction.user_id or None)
        if target_user:
            await self._deliver_to_proactive(target_user, fragments, trace_id)
            self._fragmenter.record_sent()

            # 清零表达欲
            await self._state.submit_mutation(StateMutation(
                trace_id=trace_id,
                desire_clear=True,
                reason=f"expressed: {fragments[0][:15]}",
            ))
            # 标记话题已说过
            for ev in pending_events:
                await self._pool.mark_topic_expressed(ev.topic_hash)

        self._interrupt.enter("idle")

    def _rule_filter(self, state: NenoState, events: list) -> str:
        """
        Step 1 纯规则过滤，0 成本。
        返回 "skip" 或 "proceed"。
        规则：
        - 睡眠期 → skip（已在外层过滤，此处双重保险）
        - 最近 5 分钟已发过消息 → skip
        - 所有事件都是已表达过的话题 → skip
        """
        ...

    async def _llm_judge(self, state: NenoState, events: list,
                         trace_id: str) -> Optional[dict]:
        """
        Step 2：调 deepseek-v4-pro 判断是否表达。
        - 超时(8s) 或 JSON 解析失败 → 返回 None（降级：不打扰）
        - 失败写 debug_events，携带 trace_id
        """
        events_text = "\n".join(f"- [{e.priority}] {e.content}" for e in events)
        state_text = (
            f"精力: {state.energy.value:.0f}/100 ({state.energy.description})\n"
            f"情绪: {state.mood.label}（{state.mood.description}）\n"
            f"表达欲: {state.desire.value:.0f}/100\n"
            f"上次互动: {state.last_interaction.summary or '无'}"
        )
        user_prompt = f"当前状态：\n{state_text}\n\n待处理事件：\n{events_text}"

        try:
            raw = await self._gw.call(
                model="deepseek-v4-pro",
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM},
                    {"role": "user",   "content": user_prompt},
                ],
                max_tokens=200,
            )
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"[{trace_id}] judge LLM failed: {e}")
            await self._write_debug_event(trace_id, "judge_failed", str(e))
            return None

    async def _llm_generate(self, state: NenoState, events: list,
                             decision: dict, trace_id: str) -> Optional[str]:
        """
        Step 3：调 gemini-3.1-pro 生成碎片化文案。
        降级链：gemini-3.1-pro → mimo-v2.5-pro → None（放弃）
        """
        recalled = await self._recall.recall(
            query=" ".join(e.content for e in events),
            subject=state.last_interaction.user_name or None,
        )
        mem_text = "\n".join(f"- {m}" for m in recalled) if recalled else "（无相关记忆）"

        events_text = "\n".join(f"- {e.content}" for e in events)
        user_prompt = (
            f"精力：{state.energy.value:.0f}/100\n"
            f"情绪：{state.mood.label}\n"
            f"相关记忆：\n{mem_text}\n\n"
            f"今天发生的事：\n{events_text}\n\n"
            f"现在想跟对方说点什么，用 | 分隔多条消息："
        )

        for model in ["gemini-3.1-pro", "mimo-v2.5-pro"]:
            if self._interrupt.should_stop_after_current:
                break
            try:
                result = await self._gw.call(
                    model=model,
                    messages=[
                        {"role": "system", "content": GENERATE_SYSTEM},
                        {"role": "user",   "content": user_prompt},
                    ],
                    max_tokens=300,
                )
                if result and result.strip():
                    return result
            except Exception as e:
                logger.warning(f"[{trace_id}] generate failed ({model}): {e}")
                await self._write_debug_event(trace_id, f"generate_failed_{model}", str(e))
                continue
        return None

    async def _deliver_to_proactive(self, user_id: str,
                                    fragments: list[str], trace_id: str) -> None:
        """
        将碎片化消息写入 proactive_intent 表。
        由 proactive/engine.consume_world_intent() 消费后经 SessionSubmitController 发送。

        ⚠️ 此处不直接调用 SessionSubmitController，保持 asyncio/threading 隔离。
        """
        import json as _json
        from datetime import datetime as _dt
        await self._db.execute(
            """INSERT INTO proactive_intent (user_id, fragments, status, created_at)
               VALUES (?, ?, 'queued', ?)""",
            (user_id, _json.dumps(fragments, ensure_ascii=False), _dt.now().isoformat()),
        )
        logger.info(f"[{trace_id}] intent queued for {user_id}: {fragments[0][:20]}…")

    async def _write_debug_event(self, trace_id: str,
                                  event_type: str, detail: str) -> None:
        """写入 debug_events 表，遵守 NENO_ARCH.md 第 8 条"""
        try:
            from datetime import datetime as _dt
            await self._db.execute(
                """INSERT INTO debug_events (trace_id, event_type, detail, created_at)
                   VALUES (?, ?, ?, ?)""",
                (trace_id, event_type, detail[:500], _dt.now().isoformat()),
            )
        except Exception:
            pass  # debug 写入失败不能影响主流程
```

### `proactive/engine.py` 改造（新增方法，不删原有逻辑）

```python
# 在现有 ProactiveEngine 类中新增以下方法，其余代码保持不变：

async def consume_world_intent(self) -> None:
    """
    消费 proactive_intent 表中 status='queued' 的意图，
    经由现有硬冷却/日上限规则漏斗后，调用现有发送机制（命门）发出。

    ⚠️ 发送调用方式与现有 maybe_send_proactive 保持完全一致，
       不引入新的发送路径，只是消息来源从"模板"变为"表中取"。
    """
    import json as _json
    # 取第一条 queued 意图
    row = await self._db.fetchone(
        "SELECT id, user_id, fragments FROM proactive_intent "
        "WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
    )
    if not row:
        return

    intent_id, user_id, fragments_json = row
    fragments: list[str] = _json.loads(fragments_json)

    # 复用现有规则漏斗（硬冷却、日上限）
    # TODO: 将 user_id 代入现有 rules.py 的冷却检查方法（补充真实签名后填写）
    allowed = await self._check_rules(user_id)
    if not allowed:
        await self._db.execute(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?", (intent_id,)
        )
        return

    # 逐条发送（打字延迟由 Fragmenter 计算，此处用 asyncio.sleep 模拟）
    import asyncio
    from app.services.consciousness.fragmenter import Fragmenter
    frag = Fragmenter(self._config)
    try:
        for i, text in enumerate(fragments):
            if i > 0:
                delay = frag.typing_delay(text)
                await asyncio.sleep(delay)
            # TODO: 替换为现有发送调用（补充真实签名后填写）
            await self._send_message(user_id, text)

        await self._db.execute(
            "UPDATE proactive_intent SET status='sent' WHERE id=?", (intent_id,)
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"consume_world_intent failed: {e}")
        await self._db.execute(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?", (intent_id,)
        )
```

### `chat_service.py` 改造（尾部追加，不改现有逻辑）

```python
# 在 handle_message() 返回回复文本之后，追加：

async def _notify_consciousness(
    self, user_id: str, user_name: str,
    message: str, reply: str,
    consciousness_engine,  # ConsciousnessEngine | None
) -> None:
    """
    通知 consciousness 层本次用户交互。
    在回复已发送后异步调用，不阻塞主流程。
    """
    if consciousness_engine is None:
        return
    try:
        from app.services.consciousness.models import StateMutation, LastInteraction
        from datetime import datetime
        await consciousness_engine.state_store.submit_mutation(StateMutation(
            trace_id=f"chat_{user_id}_{int(datetime.now().timestamp())}",
            last_interaction=LastInteraction(
                user_id=user_id,
                user_name=user_name,
                time=datetime.now(),
                summary=message[:50],  # 截取前50字作为摘要
            ),
            mood_valence_delta=0.1,   # 有人说话情绪微涨
            reason="user interaction",
        ))
        # P0 打断：如果世界引擎正在酝酿，通知打断
        await consciousness_engine.interrupt.on_p0_interrupt(
            pool=consciousness_engine._pool
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"consciousness notify failed: {e}")
```

---

## 4. 验收标准（Phase 3 完成的定义）

**灰度测试顺序：先在白名单单用户测试，确认无误再开放。**

- [ ] `llm_gateway.py` 新增三个模型 key，调用 test 接口返回正常
- [ ] `brain._llm_judge()` 单元测试：mock DeepSeek 返回合法/非法 JSON，验证降级逻辑
- [ ] `brain._llm_generate()` 单元测试：mock Gemini 失败，验证降级到 MiMo
- [ ] 完整链路冒烟（单用户白名单）：
  - 手动插入一条 P1 事件到 event_log
  - 等待 brain.run_cycle() 触发
  - 确认 proactive_intent 表出现 queued 记录
  - 确认消息通过 neno-bridge 实际发出
  - 确认 agent_state 中 desire 已清零
- [ ] P0 打断测试：judging 阶段发用户消息，确认主动消息被取消
- [ ] 硬冷却测试：短时间内连续触发，确认频控生效（只发 ≤ max_proactive_per_hour 条）
- [ ] 所有 LLM 调用失败均写入 debug_events，不崩溃
- [ ] `context_builder.py` 的 list.append 顺序未被改动（diff 验证）
- [ ] `session_aggregation_controller.py` 和 `session_submit_controller.py` 未被改动（diff 验证）

---

## 5. 给 Claude Code 的执行指令

```
请基于以下文件实现 Phase 3：
- 参考约束：NENO_ARCH.md（必读，命门模块绝对不改）
- 当前任务：PHASE_3.md（本文件）
- 依赖前提：Phase 1 和 Phase 2 已完成

⚠️ 开始前先确认：
1. SessionSubmitController 的真实发送方法签名已补充到 NENO_ARCH.md
2. proactive/engine.py 的现有发送调用方式已确认

实现顺序：
1. llm_gateway.py 新增三个模型 key（最低风险，先做）
2. app/services/consciousness/memory_recall.py
3. app/services/consciousness/interrupt.py
4. app/services/consciousness/fragmenter.py（含 config.py 新增字段）
5. app/services/consciousness/brain.py
6. proactive/engine.py 新增 consume_world_intent()（不删原有逻辑）
7. chat_service.py 追加 _notify_consciousness()

要求：
- brain.py 的 LLM 调用必须有超时控制（用 asyncio.wait_for）
- 所有异常写 debug_events，携带 trace_id，不 raise 到外层
- proactive/engine.py 改动后用 diff 确认原有 maybe_send_proactive 逻辑完整保留
- 完成后写灰度测试脚本（test_brain_cycle.py），可手动触发单次 run_cycle
- context_builder.py 不允许修改（diff 验证为空改动）
```
