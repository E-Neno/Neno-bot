# PHASE_2 — 感知与事件池

> **前置**：Phase 1 已完成并通过全部验收标准，`agent_state` 表正常读写，`StateStore` 单写者稳定运行。
>
> **本阶段目标**：让世界引擎跑起来，能感知真实世界数据，把事件写进 `event_log` 并正确去重。**本阶段仍不主动发消息，不调生成层 LLM。**

---

## 1. 本阶段范围

### 新建文件（全部放在 `app/services/consciousness/`）

| 文件 | 职责 |
|------|------|
| `perception.py` | 采集天气（wttr.in）、热搜、时间，带 TTL 缓存与失败兜底 |
| `event_pool.py` | 事件入池、topic_hash 分层去重、优先级排序、话题衰减 |
| `world_engine.py` | APScheduler 心跳驱动，每 tick 协调感知→事件生成→状态更新 |
| `random_events.py` | 虚拟随机事件库（日常生活小事），按时间段概率抽取 |

### 改动现有文件

| 文件 | 改动内容 |
|------|----------|
| `app/services/consciousness/__init__.py` | `ConsciousnessEngine.start()` 中启动 `WorldEngine`；`stop()` 中关闭 |

### 本阶段**禁止碰**的文件

- `session_aggregation_controller.py`
- `session_submit_controller.py`
- `context_builder.py`
- `chat_service.py`
- `proactive/` 目录下任何文件
- `brain.py`（Phase 3 才建）
- 任何生成层 LLM 调用（不调 Gemini/MiMo）

---

## 2. 接口定义

### `perception.py`

```python
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
import httpx
from .models import WeatherPerception, WorldPerception, StateMutation
from .config import ConsciousnessConfig

logger = logging.getLogger(__name__)

TTL_WEATHER_MINUTES = 15   # 天气缓存 TTL
TTL_HOT_TOPICS_MINUTES = 10  # 热搜缓存 TTL


class PerceptionService:
    """
    采集真实世界数据。
    所有外部请求设置超时，失败时返回降级占位数据，绝不崩溃。
    成功数据缓存 TTL 分钟，避免高频调用。
    """

    def __init__(self, config: ConsciousnessConfig, location: str = "南宁") -> None:
        self.config = config
        self.location = location
        self._weather_cache: Optional[WeatherPerception] = None
        self._weather_cached_at: Optional[datetime] = None
        self._hot_topics_cache: list[str] = []
        self._hot_topics_cached_at: Optional[datetime] = None

    async def get_weather(self) -> WeatherPerception:
        """
        从 wttr.in 拉取天气。
        - 缓存未过期时直接返回缓存
        - 请求超时(5s)或失败时返回上次缓存；无缓存时返回空占位
        - 失败写 debug_events，不 raise
        """
        ...

    async def get_hot_topics(self) -> list[str]:
        """
        从免费热搜 API 拉取热搜（微博/百度/抖音，按可用性降级）。
        返回最多 5 条标题字符串列表。
        失败时返回上次缓存或空列表。
        """
        ...

    async def perceive(self) -> WorldPerception:
        """
        并行采集所有感知数据，返回 WorldPerception。
        内部用 asyncio.gather，任一失败不影响其他。
        """
        weather, hot_topics = await asyncio.gather(
            self.get_weather(),
            self.get_hot_topics(),
            return_exceptions=True
        )
        # 处理异常返回值，降级为空
        ...

    def build_time_context(self) -> str:
        """
        生成时间上下文描述字符串。
        例："周日下午15:30" / "周三深夜02:10"
        """
        ...
```

### `event_pool.py`

```python
import hashlib
import json
import logging
from datetime import datetime
from typing import Optional
from app.storage.database import Database
from .models import Event, Experience
from .config import ConsciousnessConfig

logger = logging.getLogger(__name__)


class EventPool:
    """
    事件池管理：入池、去重、话题衰减、优先级查询。
    所有持久化走 event_log 表，不在内存中维护全量事件。
    """

    def __init__(self, db: Database, config: ConsciousnessConfig) -> None:
        self._db = db
        self._cfg = config

    # ---- topic_hash 分层生成 ----

    @staticmethod
    def make_hash_structured(event_type: str, date_str: str) -> str:
        """
        结构化事件（天气、节日）的 topic_hash。
        格式：{event_type}_{date_str}
        例：weather_20260531 / holiday_20260601
        """
        return f"{event_type}_{date_str}"

    @staticmethod
    def make_hash_unstructured(content: str) -> str:
        """
        非结构化事件（热搜、随机小事）的 topic_hash。
        做法：提取关键词（去停用词）→ 排序 → MD5 前 8 位
        例："南宁暴雨预警" → hot_a3f2b1c4
        """
        ...

    # ---- 入池与去重 ----

    async def push(self, event: "EventIn") -> bool:
        """
        尝试将事件入池。
        去重规则：
          1. 同 topic_hash 在今日已存在 pending/consumed 事件 → 拒绝入池，返回 False
          2. 该话题在 expressed_topics 中（已说过），且距说过时间 < decay_minutes → 拒绝，返回 False
          3. 否则写入 event_log，返回 True
        """
        ...

    async def pop_pending(self, priority_le: int = 2) -> list["EventIn"]:
        """
        取出优先级 <= priority_le 的 pending 事件（按 priority ASC, created_at ASC）。
        状态改为 consumed。
        """
        ...

    async def mark_topic_expressed(self, topic_hash: str) -> None:
        """
        记录该话题已被表达过，用于话题衰减判断。
        写入一条 status='expressed' 的记录（或更新专用字段）。
        """
        ...

    async def expire_old_events(self) -> int:
        """
        将超过 24 小时的 pending 事件标记为 expired。
        每次心跳调用，防止事件池堆积。
        返回过期事件数量。
        """
        ...


# ---- 事件输入模型 ----

from pydantic import BaseModel, Field
from typing import Literal

class EventIn(BaseModel):
    """入池时的事件描述"""
    topic_hash: str
    priority: Literal[0, 1, 2, 3]          # P0/P1/P2/P3
    content: str
    tags: list[str] = Field(default_factory=list)
    mood_impact: float = 0.0               # 情绪影响（用于 desire 脉冲）
    source: str = ""                        # 来源标识（weather/hot/random）
```

### `random_events.py`

```python
import random
from datetime import datetime
from typing import Optional
from .event_pool import EventIn


# 随机事件库（日常生活小事）
RANDOM_EVENT_POOL = [
    {"content": "路过一只橘猫，盯着我看了好久",         "tags": ["萌宠"], "mood_impact": 0.4},
    {"content": "隔壁在装修，电钻声吵死了",             "tags": ["抱怨"], "mood_impact": -0.2},
    {"content": "买了杯奶茶，踩雷了，甜得发腻",         "tags": ["日常", "抱怨"], "mood_impact": -0.1},
    {"content": "刷到一条超好笑的视频，笑了好久",       "tags": ["开心"], "mood_impact": 0.5},
    {"content": "发现一家新开的小店，看起来不错",       "tags": ["日常"], "mood_impact": 0.2},
    {"content": "突然想起一首很久没听的歌",             "tags": ["怀旧"], "mood_impact": 0.1},
    {"content": "窗外突然开始下雨，没带伞",             "tags": ["天气", "抱怨"], "mood_impact": -0.15},
    {"content": "今天的外卖送得特别快",                 "tags": ["日常", "开心"], "mood_impact": 0.2},
    {"content": "手机没电了差点关机",                   "tags": ["抱怨"], "mood_impact": -0.1},
    {"content": "看到天边有漂亮的晚霞",                 "tags": ["风景", "治愈"], "mood_impact": 0.35},
    {"content": "无意间整理了一下房间，清爽多了",       "tags": ["日常"], "mood_impact": 0.25},
    {"content": "买东西找不到钱包，急死了，后来发现在包里", "tags": ["日常", "抱怨"], "mood_impact": 0.1},
]

# 时间段活跃概率（hour → 触发概率）
HOUR_PROBABILITY = {
    **{h: 0.0  for h in range(1, 8)},    # 凌晨/清晨：不触发
    **{h: 0.3  for h in range(8, 10)},   # 上午初：低
    **{h: 0.5  for h in range(10, 12)},  # 上午：中
    **{h: 0.4  for h in range(12, 14)},  # 午间：中低（可能午休）
    **{h: 0.7  for h in range(14, 18)},  # 下午：高（最活跃）
    **{h: 0.6  for h in range(18, 21)},  # 傍晚：中高
    **{h: 0.4  for h in range(21, 23)},  # 晚间：中低
    0: 0.0,                               # 午夜：不触发
    23: 0.1,
}


def maybe_generate_random_event(now: datetime) -> Optional[EventIn]:
    """
    根据当前时间段概率，随机决定是否生成一条日常小事件。
    返回 EventIn 或 None（大多数 tick 返回 None）。
    """
    prob = HOUR_PROBABILITY.get(now.hour, 0.3)
    if random.random() > prob:
        return None
    chosen = random.choice(RANDOM_EVENT_POOL)
    topic_hash = f"random_{abs(hash(chosen['content'])) % 100000:05d}"
    return EventIn(
        topic_hash=topic_hash,
        priority=2,  # P2：日常小事
        content=chosen["content"],
        tags=chosen["tags"],
        mood_impact=chosen["mood_impact"],
        source="random",
    )
```

### `world_engine.py`

```python
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.storage.database import Database
from .config import ConsciousnessConfig
from .perception import PerceptionService
from .event_pool import EventPool, EventIn
from .random_events import maybe_generate_random_event
from .state_store import StateStore
from .models import StateMutation, WorldPerception

logger = logging.getLogger(__name__)


class WorldEngine:
    """
    世界引擎：APScheduler 驱动的心跳，协调感知→事件生成→状态写入。
    本阶段只做：感知、入池、状态更新（world/energy/mood回归）。
    不调判断层 LLM，不投递主动意图。
    """

    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        perception: PerceptionService,
        pool: EventPool,
        state_store: StateStore,
        config: ConsciousnessConfig,
    ) -> None:
        self._scheduler = scheduler
        self._perception = perception
        self._pool = pool
        self._state = state_store
        self._cfg = config

    def register_jobs(self) -> None:
        """
        向 APScheduler 注册所有定时任务。
        由 ConsciousnessEngine.start() 调用，在 scheduler.start() 之前。
        """
        # 主心跳：每 N 秒一次
        self._scheduler.add_job(
            self.heartbeat,
            "interval",
            seconds=self._cfg.heartbeat_interval_seconds,
            id="world_engine_heartbeat",
            replace_existing=True,
        )
        # 每日梦境：凌晨 3 点（Phase 4 的 DreamService 会覆盖此处）
        # 此处只注册占位，Phase 4 替换实现
        self._scheduler.add_job(
            self._daily_reset_placeholder,
            "cron",
            hour=3, minute=0,
            id="daily_dream",
            replace_existing=True,
        )
        # 过期事件清理：每小时
        self._scheduler.add_job(
            self._expire_events,
            "interval",
            hours=1,
            id="expire_events",
            replace_existing=True,
        )

    async def heartbeat(self) -> None:
        """
        主心跳逻辑：
        1. 检查是否在睡眠期 → 是则跳过感知和随机事件
        2. 并行：采集真实感知 + 生成随机事件
        3. 更新 world perception 到 state
        4. 随机事件尝试入池
        5. 真实数据事件（极端天气等）入池
        6. 情绪向基线回归一步（提交 StateMutation）
        """
        now = datetime.now()
        state = await self._state.read()

        if state.energy.status == "sleeping":
            logger.debug("heartbeat skipped: sleeping")
            return

        # 并行采集
        world = await self._perception.perceive()

        # 更新 world perception
        await self._state.submit_mutation(StateMutation(
            trace_id=f"heartbeat_{now.isoformat()}",
            world=world,
            mood_valence_delta=0,  # 回归由 mood.py 计算
            reason="heartbeat world update",
        ))

        # 检查极端天气 → P0 事件
        await self._check_extreme_weather(world, now)

        # 随机小事 → P2 事件
        random_event = maybe_generate_random_event(now)
        if random_event:
            pushed = await self._pool.push(random_event)
            if pushed:
                # 情绪脉冲
                await self._state.submit_mutation(StateMutation(
                    trace_id=f"random_event_{now.isoformat()}",
                    desire_pulse=random_event.mood_impact * self._cfg.desire_pulse_base,
                    mood_valence_delta=random_event.mood_impact * 0.3,
                    experience=None,  # Phase 3 的 brain 才写 experience
                    reason=f"random event: {random_event.content[:20]}",
                ))

        # 过期事件清理
        await self._pool.expire_old_events()

    async def _check_extreme_weather(
        self, world: WorldPerception, now: datetime
    ) -> None:
        """
        检测极端天气条件（rain=True 且 text 含预警关键词）→ 生成 P0 事件。
        P0 事件不走 desire 阈值，直接触发（Phase 3 的 brain 处理）。
        """
        ...

    async def _daily_reset_placeholder(self) -> None:
        """凌晨占位：Phase 4 由 DreamService 替换"""
        logger.info("daily reset placeholder triggered (Phase 4 will replace)")

    async def _expire_events(self) -> None:
        count = await self._pool.expire_old_events()
        if count:
            logger.info(f"expired {count} stale events")

    def is_sleeping(self, now: datetime) -> bool:
        """
        判断当前时刻是否在睡眠期。
        睡眠：凌晨 sleep_hour 到 wake_hour（含随机抖动，从 state 读取实际时刻）。
        简化版：直接用配置的小时判断。
        """
        h = now.hour
        return h >= self._cfg.sleep_hour or h < self._cfg.wake_hour
```

### `__init__.py`（Phase 2 版本）

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.storage.database import Database
from .config import ConsciousnessConfig
from .state_store import StateStore
from .perception import PerceptionService
from .event_pool import EventPool
from .world_engine import WorldEngine


class ConsciousnessEngine:
    def __init__(self, db: Database, scheduler: AsyncIOScheduler,
                 config: ConsciousnessConfig | None = None) -> None:
        self.config = config or ConsciousnessConfig()
        self._db = db
        self._scheduler = scheduler

        self.state_store = StateStore(db, self.config)
        self._perception = PerceptionService(self.config)
        self._pool = EventPool(db, self.config)
        self._world_engine = WorldEngine(
            scheduler, self._perception, self._pool,
            self.state_store, self.config
        )

    async def start(self) -> None:
        await self.state_store.start()
        self._world_engine.register_jobs()
        # 注意：scheduler 已在 main.py lifespan 中 start，此处不重复 start

    async def stop(self) -> None:
        await self.state_store.stop()
```

---

## 3. 验收标准（Phase 2 完成的定义）

- [ ] APScheduler 心跳每 5 分钟触发，日志可见 `heartbeat` 记录
- [ ] 天气数据成功从 wttr.in 拉取，`agent_state` 中 `world.weather` 字段有真实内容
- [ ] 热搜数据成功拉取（或降级返回空列表），不崩溃
- [ ] 网络请求超时（模拟断网）时，感知返回降级占位数据，heartbeat 正常完成
- [ ] 随机事件按时间段概率触发，深夜（1-7 点）不触发，下午（14-18 点）高频触发
- [ ] 同 topic_hash 事件在今日内只入池一次（重复推送返回 False）
- [ ] 极端天气（rain=True + 预警关键词）生成 P0 事件，写入 event_log
- [ ] 超过 24 小时的 pending 事件被标记为 expired
- [ ] 睡眠期（1:00-8:00）heartbeat 跳过感知，日志可见 `sleeping` 记录
- [ ] 所有外部请求失败均写入 debug_events，携带 trace_id，不影响主流程

**不需要**：任何 LLM 调用、任何消息发送、任何 proactive 改动。

---

## 4. 给 Claude Code 的执行指令

```
请基于以下文件实现 Phase 2：
- 参考约束：NENO_ARCH.md（必读，硬约束）
- 当前任务：PHASE_2.md（本文件）
- 依赖前提：Phase 1 已完成，StateStore 可正常使用

实现顺序：
1. app/services/consciousness/perception.py（含 TTL 缓存和降级）
2. app/services/consciousness/random_events.py（事件库可直接扩展）
3. app/services/consciousness/event_pool.py（去重逻辑务必严格）
4. app/services/consciousness/world_engine.py
5. 更新 app/services/consciousness/__init__.py

要求：
- perception.py 所有外部 HTTP 请求超时设为 5 秒
- event_pool.push() 必须先查库再决定是否入池，不能只靠内存
- world_engine.heartbeat() 内部异常全部 catch，写 debug_events，不让心跳崩溃
- random_events.RANDOM_EVENT_POOL 至少保留现有条目，可新增
- 不接触本任务"禁止碰"列表中的任何文件
- 实现完成后写集成测试（test_world_engine.py），mock 外部 HTTP，验证去重和降级
```
