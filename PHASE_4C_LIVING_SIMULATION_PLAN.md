# Phase 4c Living Simulation Core 实现计划

> **目标：** 把 Phase 4b 的模板状态机升级为可连续运行、可重放、可反思的完整世界引擎核心。实现必须遵守单机 SQLite 约束，但目标不再后移到 Phase 5 或 Phase 6；Phase 5 只在本计划验收后处理“用户消息进入世界引擎”。

## 1. 成功定义

完成后，Neno 不再只是刷新一个 `LifeState` 模板，而是拥有当天的生活线：

- 一段生活以 `ActivityEpisode` 表示，包含开始、持续、结束、转移、被打断。
- 虚拟生活由 `VirtualSpace`、`DailyIntent`、`Routine` 和 `MicroEvent` 共同驱动。
- `MicroEvent` 必须从当前 episode / 空间 / 需求 / 记忆余波 / 时间段派生，不能是随机事件列表。
- Debug 面板能重放“今天怎么活过”，不是只展示“此刻状态”。
- ReflectionEngine 整理生活线，并通过 `life_residue` / `long_term_memory` 改变下一天状态。
- 默认不真实调用模型、不真实发送、不改主聊天入口、不改 prompt、不碰红线文件。

## 2. 数据模型

保持单机 SQLite，不引入 Redis / Kafka / Celery / Postgres。优先新增一张表：

```sql
CREATE TABLE IF NOT EXISTS life_activity_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT,
    activity_key TEXT NOT NULL,
    activity_label TEXT NOT NULL,
    place TEXT NOT NULL,
    time_phase TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ended_at TEXT,
    reason TEXT NOT NULL DEFAULT '',
    continuity_note TEXT NOT NULL DEFAULT '',
    source_residue_json TEXT NOT NULL DEFAULT '{}',
    routine_key TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

新增 Pydantic 模型（建议放 `app/services/consciousness/models.py`）：

- `ActivityEpisode`：对应一段生活片段。
- `VirtualSpace`：命名场景和可用物品，不做地图。
- `DailyIntent`：当天生活倾向，例如 `recover` / `observe` / `organize` / `seek_connection` / `process_memory`。
- `MicroEvent`：episode 推进中产生的内在小事件。

`LifeState` 保持现有字段，新增可选引用：

- `active_episode_id: int | None = None`
- `daily_intent: str = ""`

旧 JSON 必须自动补默认。

## 3. 实现任务

### C1.1 Episode 存储层

文件：

- `app/storage/db.py`
- `app/services/consciousness/episode_store.py`
- `tests/unit/test_episode_store.py`

验收：

- 表可创建。
- 可创建 active episode。
- 可更新 episode。
- 可结束 episode。
- 可列出今天 episode timeline。
- 坏 JSON 容错，不 500。

### C1.2 Simulation 模型与决策器

文件：

- `app/services/consciousness/models.py`
- `app/services/consciousness/life_simulation.py`
- `tests/unit/test_life_simulation.py`

验收：

- `DailyIntent` 由 energy / need / residue / time_phase 确定性生成。
- `VirtualSpace` 按 activity 选择合理 place / object。
- `ActivityEpisode` 不是单点状态：同一 episode 多次 tick 会延续，满足条件才转移。
- 高强度 residue 优先驱动 `process_memory`，低强度 residue 只影响 continuity。

### C1.3 LifeLoop 接入 episode 推进

文件：

- `app/services/consciousness/life_loop.py`
- `tests/unit/test_life_loop.py`

验收：

- `run_once()` 会创建或推进 active episode。
- 低能量可打断当前 episode 并转为休息。
- 强 residue 可把 episode 转为记忆处理。
- 每次 tick 最多写一条 `state_shift` 或 `micro_event`，避免随机事件泛滥。
- disabled / dry-run 语义不变。

### C1.4 MicroEvent 沉淀

文件：

- `app/services/consciousness/life_simulation.py`
- `app/services/consciousness/life_loop.py`
- `tests/unit/test_life_simulation.py`
- `tests/unit/test_life_loop.py`

验收：

- MicroEvent 内容来自当前 episode、space、intent、residue。
- MicroEvent 写入 `inner_experience_log`，`source="life_simulation"`。
- MicroEvent metadata 包含 `episode_id`、`daily_intent`、`place`、`time_phase`。
- 不把 life_loop 自己的低显著状态变动误当“未说出口的想法”。

### C1.5 Reflection 读取生活线

文件：

- `app/services/consciousness/reflection_engine.py`
- `tests/unit/test_reflection_engine.py`

验收：

- ReflectionEngine 输入包含当天 episode timeline。
- deterministic 反思能总结“今天怎么活过”，不是只列事件。
- 反思输出的 `life_residue.topic` 能引用 episode / micro event。
- `long_term_memory` 可沉淀生活倾向，例如“夜里容易反复想起未处理的事”。

### C1.6 Debug endpoint 与 UI timeline

文件：

- `app/routers/debug.py`
- `app/static/js/consciousness.js`
- `app/static/js/layout.js`
- `tests/integration/test_consciousness_living_world_debug.py`

验收：

- `/debug/consciousness/living-world` 返回 `episodes` timeline。
- `?dry_run=true` 返回下一轮 episode 预览，不写 DB。
- UI 展示“今天生活线”：每段活动的时间、地点、原因、状态、结束原因。
- 空 timeline 有中文空态。
- 仍要求 admin token。

### C1.7 全量验收与提交边界

验证命令：

```bash
pytest tests/unit/test_episode_store.py \
       tests/unit/test_life_simulation.py \
       tests/unit/test_life_loop.py \
       tests/unit/test_reflection_engine.py \
       tests/integration/test_consciousness_living_world_debug.py -v

pytest tests/unit/test_brain.py tests/unit/test_state_store.py tests/unit/test_experience_recorder.py -v

node --check app/static/js/consciousness.js
node --check app/static/js/layout.js

git diff --name-only -- \
  app/services/session_submit_controller.py \
  app/services/session_aggregation_controller.py \
  app/services/chat/context_builder.py \
  app/services/chat_service.py \
  app/services/proactive/rules.py \
  app/services/chat/history_digest.py
```

验收结果必须证明：

- 红线文件 diff 为空。
- 默认配置不真实调用模型、不真实发送、不注册新发送链路。
- 新增表只服务生活模拟，不替代 `inner_experience_log`。
- Phase 5 仍未启动。

## 4. 非目标

- 不做 3D / 地图导航 / 多智能体社会。
- 不接被动消息入口。
- 不实现 ExpressionGate。
- 不新增发送链路。
- 不把 Living World 注入主聊天 prompt。
- 不引入外部队列或新数据库。
