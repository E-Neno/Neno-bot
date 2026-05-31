# PHASE_1 — 状态地基

> **前置**：先读 `NENO.md`，所有硬约束（命门模块、SQLite 单一真相源、禁改 context_builder 顺序）在本阶段同样适用。
>
> **本阶段目标**：把 AgentState 状态机跑起来。不接 LLM、不接发送、不碰 proactive、不碰 SessionSubmitController。纯状态机，风险最低，可独立验收。

---

## 1. 本阶段范围

### 新建文件（全部放在 `app/services/consciousness/`）

| 文件 | 职责 |
|------|------|
| `__init__.py` | 暴露 `ConsciousnessEngine` 门面（本阶段只 stub，不启动任何调度） |
| `models.py` | 所有 Pydantic 数据模型（NenoState、StateMutation、Event 等） |
| `desire.py` | 表达欲实时推算（线性 + 脉冲 + 抖动） |
| `mood.py` | 二维情绪（valence/arousal）更新与基线回归 |
| `state_store.py` | 状态单写者队列 + 乐观锁 + SQLite 持久化 |
| `config.py` | ConsciousnessConfig（所有魔法数字集中管理） |

### 改动现有文件

| 文件 | 改动内容 |
|------|----------|
| `storage/database.py` | 新增 4 张表的建表语句（见下方 DDL）；用 `IF NOT EXISTS`，不影响现有表 |
| `models/schemas.py` | 引入 `NenoState`（`from app.services.consciousness.models import NenoState`） |

### 本阶段**禁止碰**的文件

- `session_aggregation_controller.py`
- `session_submit_controller.py`
- `context_builder.py`
- `chat_service.py`
- `proactive/` 目录下任何文件
- `llm_gateway.py`（本阶段不调 LLM）

---

## 2. 数据库 DDL（加入 `storage/database.py` 的初始化函数）

```sql
-- 状态：单行，JSON 存全量 state，revision 做乐观锁
CREATE TABLE IF NOT EXISTS agent_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    revision    INTEGER NOT NULL DEFAULT 0,
    state_json  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

-- 事件池
CREATE TABLE IF NOT EXISTS event_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_hash  TEXT    NOT NULL,
    priority    INTEGER NOT NULL,           -- 0=P0 / 1=P1 / 2=P2 / 3=P3
    content     TEXT    NOT NULL,
    tags        TEXT,                        -- JSON 数组
    mood_impact REAL    DEFAULT 0.0,
    status      TEXT    DEFAULT 'pending',   -- pending / consumed / expired
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_topic  ON event_log(topic_hash, created_at);
CREATE INDEX IF NOT EXISTS idx_event_status ON event_log(status, priority);

-- 长期记忆（结构化）
CREATE TABLE IF NOT EXISTS long_term_memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content    TEXT NOT NULL,
    tags       TEXT,                         -- JSON 数组，召回用
    subject    TEXT,                         -- 关于谁
    salience   REAL DEFAULT 0.5,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mem_subject ON long_term_memory(subject, salience);

-- 主动意图队列（世界引擎 → proactive 的汇流缓冲）
CREATE TABLE IF NOT EXISTS proactive_intent (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    fragments  TEXT NOT NULL,               -- JSON 数组，碎片化消息
    status     TEXT DEFAULT 'queued',        -- queued / sent / interrupted / dropped
    created_at TEXT NOT NULL
);
```

---

## 3. 接口定义

### `config.py`

```python
from pydantic import BaseModel

class ConsciousnessConfig(BaseModel):
    # 表达欲
    desire_linear_rate: float = 2.0        # 每分钟基础增长点数
    desire_pulse_base: float = 25.0        # 高情绪事件脉冲基数
    desire_jitter_pct: float = 0.10        # ±10% 随机抖动
    desire_threshold: float = 60.0         # 触发分享的阈值
    desire_decay_minutes: int = 120        # 分享后 N 分钟内不再轻易触发

    # 情绪
    mood_regression_rate: float = 0.05    # 每分钟向基线回归速率
    mood_baseline_valence: float = 0.3
    mood_baseline_arousal: float = 0.5

    # 精力
    energy_wake_value: float = 95.0
    energy_decay_rate: float = 0.04        # 每分钟衰减点数（清醒时）

    # 睡眠
    sleep_hour: int = 1                    # 凌晨几点入睡
    wake_hour: int = 8                     # 几点醒来
    sleep_jitter_minutes: int = 30         # ±N 分钟随机

    # 心跳
    heartbeat_interval_seconds: int = 300  # 世界引擎 tick 间隔（Phase 2 用）

    # 记忆
    today_experiences_max: int = 10        # 短期经历最多保留条数
    memory_recall_top_k: int = 5           # 每次召回的长期记忆条数
```

### `models.py`

```python
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class EnergyState(BaseModel):
    value: float = Field(ge=0, le=100)
    status: Literal["awake", "sleeping"] = "awake"
    description: str = ""
    last_wake_time: Optional[datetime] = None
    last_sleep_time: Optional[datetime] = None


class MoodState(BaseModel):
    valence: float = Field(ge=-1, le=1, default=0.3)   # 愉悦度
    arousal: float = Field(ge=0,  le=1, default=0.5)   # 唤醒度
    label: str = "平静"
    description: str = ""
    baseline_valence: float = 0.3
    baseline_arousal: float = 0.5
    last_updated: datetime = Field(default_factory=datetime.now)


class DesireState(BaseModel):
    value: float = Field(ge=0, le=100, default=10.0)
    last_express_at: Optional[datetime] = None
    last_express_topic_hash: Optional[str] = None
    # 脉冲注入列表（待消费），格式：{"amount": float, "injected_at": datetime}
    pending_pulses: list[dict] = Field(default_factory=list)


class WeatherPerception(BaseModel):
    text: str = ""
    temp: Optional[float] = None
    condition: str = ""
    rain: bool = False
    fetched_at: Optional[datetime] = None


class WorldPerception(BaseModel):
    weather: WeatherPerception = Field(default_factory=WeatherPerception)
    hot_topics: list[str] = Field(default_factory=list)
    time_context: str = ""
    last_perception_at: Optional[datetime] = None


class Experience(BaseModel):
    time: str                              # "HH:MM"
    content: str
    topic_hash: str
    mood_impact: float = 0.0


class LastInteraction(BaseModel):
    user_id: str = ""
    user_name: str = ""
    time: Optional[datetime] = None
    summary: str = ""


class NenoState(BaseModel):
    """AgentState 单行 JSON 的 Python 表示"""
    version: int = 2
    revision: int = 0
    updated_at: datetime = Field(default_factory=datetime.now)

    energy: EnergyState = Field(default_factory=EnergyState)
    mood: MoodState = Field(default_factory=MoodState)
    desire: DesireState = Field(default_factory=DesireState)
    world: WorldPerception = Field(default_factory=WorldPerception)
    today_experiences: list[Experience] = Field(default_factory=list)
    last_interaction: LastInteraction = Field(default_factory=LastInteraction)

    # 长期记忆在 long_term_memory 表，此处只存召回结果（不持久化）
    recalled_memories: list[str] = Field(default_factory=list, exclude=True)


class StateMutation(BaseModel):
    """描述一次状态变更，由单写者队列消费"""
    trace_id: str
    energy_delta: Optional[float] = None
    mood_valence_delta: Optional[float] = None
    mood_arousal_delta: Optional[float] = None
    desire_pulse: Optional[float] = None        # 脉冲注入量
    desire_clear: bool = False                   # 分享后清零
    experience: Optional[Experience] = None      # 追加今日经历
    last_interaction: Optional[LastInteraction] = None
    world: Optional[WorldPerception] = None
    reason: str = ""                             # 调试用
```

### `desire.py`

```python
import random
from datetime import datetime
from .models import DesireState
from .config import ConsciousnessConfig


class DesireModel:
    def __init__(self, config: ConsciousnessConfig) -> None:
        self.cfg = config

    def current_value(self, state: DesireState, now: datetime) -> float:
        """
        实时推算当前表达欲（不写库，只计算）。
        公式：持久化值 + 线性增长 + 待消费脉冲 + 随机抖动
        """
        ...

    def apply_pulse(self, base_impact: float) -> float:
        """根据事件 mood_impact 计算注入脉冲量"""
        ...

    def should_express(self, state: DesireState, now: datetime) -> bool:
        """是否达到分享阈值，且距上次分享超过 decay_duration"""
        ...

    def clear_mutation(self) -> dict:
        """生成"分享后清零"的 mutation 字段"""
        return {"desire_clear": True}
```

### `mood.py`

```python
from datetime import datetime
from .models import MoodState
from .config import ConsciousnessConfig


class MoodModel:
    def __init__(self, config: ConsciousnessConfig) -> None:
        self.cfg = config

    def apply_event(self, state: MoodState, valence_delta: float,
                    arousal_delta: float, now: datetime) -> tuple[float, float]:
        """应用事件影响，返回 (new_valence, new_arousal)，夹紧到合法范围"""
        ...

    def regress_to_baseline(self, state: MoodState, now: datetime) -> tuple[float, float]:
        """
        向基线回归一步（每次 tick 调用）。
        速率：cfg.mood_regression_rate × 距 last_updated 的分钟数
        """
        ...

    def to_label(self, valence: float, arousal: float) -> tuple[str, str]:
        """
        将二维情绪映射为 (label, description)，供 LLM 读取。
        例：valence>0.5 & arousal>0.5 → ("开心", "状态不错，有点兴奋")
        """
        ...
```

### `state_store.py`

```python
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional
from app.storage.database import Database
from .models import NenoState, StateMutation
from .config import ConsciousnessConfig
from .desire import DesireModel
from .mood import MoodModel

logger = logging.getLogger(__name__)

MAX_RETRY = 3  # 乐观锁冲突最大重试次数


class StateStore:
    """
    AgentState 单写者。所有状态变更必须经此类，不允许外部直接写 agent_state 表。

    并发模型：
    - 读：任意协程可直接调用 read()，无锁（SQLite WAL 保证一致读）
    - 写：外部调用 submit_mutation()，入 asyncio.Queue；
           单一 _writer_loop 协程串行消费，乐观锁 revision 校验后落库
    - 与 SessionSubmitController（threading 锁）的隔离：
           本类只管状态写，不参与消息发送；发送由 proactive/engine 经由命门完成
    """

    def __init__(self, db: Database, config: ConsciousnessConfig) -> None:
        self._db = db
        self._cfg = config
        self._desire = DesireModel(config)
        self._mood = MoodModel(config)
        self._queue: asyncio.Queue[StateMutation] = asyncio.Queue()
        self._writer_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """启动单写者协程，由 ConsciousnessEngine.start() 调用"""
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def stop(self) -> None:
        """优雅停止：等待队列清空后取消写者协程"""
        await self._queue.join()
        if self._writer_task:
            self._writer_task.cancel()

    async def read(self) -> NenoState:
        """
        从 SQLite 读取当前状态，并实时推算 desire/mood 的当前值。
        返回的 NenoState 包含推算后的值，不直接写库。
        """
        ...

    async def submit_mutation(self, mutation: StateMutation) -> None:
        """提交状态变更请求，异步入队，不阻塞调用方"""
        await self._queue.put(mutation)

    async def _writer_loop(self) -> None:
        """
        单写者主循环。
        1. 从队列取 mutation
        2. 读当前 revision
        3. 应用 mutation 计算新 state
        4. UPDATE WHERE revision = old_revision
        5. 若 revision 不匹配（并发写），重试最多 MAX_RETRY 次
        6. 失败写入 debug_events，不崩溃
        """
        ...

    async def _apply_mutation(self, state: NenoState,
                               mutation: StateMutation,
                               now: datetime) -> NenoState:
        """将 StateMutation 应用到 NenoState，返回新状态（纯函数，不写库）"""
        ...

    async def _ensure_row_exists(self) -> None:
        """首次启动时若 agent_state 表为空，插入默认状态行"""
        ...
```

### `__init__.py`（Phase 1 版本，stub）

```python
from .state_store import StateStore
from .config import ConsciousnessConfig
from .models import NenoState

class ConsciousnessEngine:
    """
    consciousness 层总门面。
    Phase 1：只启动 StateStore，不启动世界引擎和调度器。
    """
    def __init__(self, db, config: ConsciousnessConfig | None = None) -> None:
        self.config = config or ConsciousnessConfig()
        self.state_store = StateStore(db, self.config)

    async def start(self) -> None:
        await self.state_store.start()

    async def stop(self) -> None:
        await self.state_store.stop()
```

---

## 4. 验收标准（Phase 1 完成的定义）

以下全部通过才算 Phase 1 完成，可进入 Phase 2：

- [ ] `storage/database.py` 跑通，4 张新表创建成功，不影响现有表
- [ ] `NenoState` 默认值可序列化为合法 JSON，并能从 JSON 反序列化
- [ ] `StateStore.start()` 启动后，`read()` 返回默认状态（revision=0）
- [ ] 服务重启后，`read()` 从 SQLite 正确恢复上次的状态（而非重置为默认）
- [ ] 并发写测试：同时 submit 10 条 mutation，最终 revision=10，无数据丢失
- [ ] 乐观锁冲突时自动重试，最终一致，日志可见冲突次数
- [ ] `DesireModel.current_value()` 在时间推进后返回递增值（含抖动）
- [ ] `MoodModel.regress_to_baseline()` 在无事件时向基线收敛

**不需要**：任何 LLM 调用、任何消息发送、任何外部 API 请求。

---

## 5. 给 Claude Code 的执行指令

```
请基于以下文件实现 Phase 1：
- 参考约束：NENO_ARCH.md（必读，硬约束）
- 当前任务：PHASE_1.md（本文件）

实现顺序：
1. storage/database.py 加建表语句
2. app/services/consciousness/config.py
3. app/services/consciousness/models.py
4. app/services/consciousness/desire.py
5. app/services/consciousness/mood.py
6. app/services/consciousness/state_store.py
7. app/services/consciousness/__init__.py

要求：
- 每个文件写完整实现，不要留 pass 或 ...
- state_store._writer_loop 必须实现乐观锁重试逻辑
- 所有异常捕获后写入 debug_events 表，携带 trace_id，不 raise
- 不接触本任务"禁止碰"列表中的任何文件
- 实现完成后，为 state_store 写 pytest 测试（test_state_store.py）覆盖并发写和乐观锁场景
```
