# Phase 4 Living World 实现计划

> **面向 AI 代理的工作说明：** 实施本计划前先阅读 `NENO.md`、`NENO_ARCHITECTURE.md`、`PHASE_4_LIVING_WORLD_SPEC.md`。实现时使用 `test-driven-development`，每个任务先写失败测试，再写最小实现。需要逐步提交时，每个任务完成且验证通过后再 commit。

**目标：** 把 Neno 从“事件驱动主动消息机器人”推进成有连续虚拟生活、会沉淀经历、会通过反思影响长期状态的单体智能体。

**架构：** 保持单机 SQLite。新增 Living World 层：`LifeState` 记录生活状态，`ExperienceRecorder` 持久化内在经历，`LifeLoop` 推进生活，`ReflectionEngine` 低频整理长期记忆。Phase 4 先完成生活模拟核心，ExpressionGate 顺延为可选表达层，只能把生活外溢写入既有 `proactive_intent`。Phase 4 预留 `UserMessageBatch` 和 `ExpressionPlan`，但不重构被动聊天入口。

**技术栈：** Python、FastAPI、APScheduler、SQLite、Pydantic、pytest。真实模型调用、真实发送、生活循环、反思、表达闸门默认通过 env 关闭。

---

> **状态提醒（2026-06-07）：** 本文是历史实现计划，不再是代码现状的权威来源。
> 世界引擎已经超过下述 4c/C1 规划并接入应用。当前架构、运行方式、缺口和
> 下一步以 `docs/living-world.md` 与 `PHASE_4_PROGRESS.md` 为准。

## 0.0 阶段状态与任务映射（2026-06-06 历史校正）

> **Phase 4a / 4b 已验收 ≠ Phase 4 完成。** 本节是任务 → 阶段的权威映射；§6 验收标准与本节对齐。
> 阶段定义见 `PHASE_4_LIVING_WORLD_SPEC.md` §0。

| 任务 | 内容 | 归属阶段 | 状态 |
|---|---|---|---|
| 任务 1 | DB 表 + LifeState 模型 + StateStore | **Phase 4a** | ✅ 已验收 |
| 任务 2 | ExperienceRecorder | **Phase 4a** | ✅ 已验收 |
| 任务 3 | 配置开关（默认全关） | **Phase 4a** | ✅ 已验收 |
| 任务 4 | LifeLoop（最小脉冲） | **Phase 4a** | ✅ 已验收 |
| 任务 5 | Brain 未表达经历沉淀 | **Phase 4a** | ✅ 已验收 |
| 任务 6 | ReflectionEngine（反思 + long_term 回写 + 回注） | **Phase 4a** | ✅ 已验收 |
| 任务 8（只读部分） | Living World debug endpoint | **Phase 4a** | ✅ 已验收 |
| **任务 B1** | **Living World Model（富字段）+ 生活化 LifeLoop + residue 回灌 + 生活验收面板** | **Phase 4b** | ✅ 已验收（MVP 状态机） |
| **任务 C1（新增）** | **Living Simulation Core：ActivityEpisode + VirtualSpace + Routine + MicroEvent + timeline replay** | **Phase 4c** | 历史状态：当时待做；当前已实现并被新世界层扩展 |
| 任务 7 | ExpressionGate | **Phase 4d（可选）** | ⏳ 未做 / 非 4c 必需 |
| —— | 被动消息进世界引擎 | **Phase 5** | ⛔ 暂停（等 4c 验收） |

> ⚠️ 本计划原文"任务 1–8 一条龙"会让人误以为跑完即 Phase 4 完成。实际跑完任务 1–6 + 任务 8 只读 = **Phase 4a 地基**；任务 B1 = **Phase 4b Living World MVP**。完整世界引擎核心必须继续做 **Phase 4c / 任务 C1**。

---

## 0. 红线与默认策略

禁止修改以下文件：

- `app/services/session_submit_controller.py`
- `app/services/session_aggregation_controller.py`
- `app/services/chat/context_builder.py`
- `app/services/chat_service.py`
- `app/services/proactive/rules.py`
- `app/services/chat/history_digest.py`

禁止行为：

- 不引入 Redis、Kafka、Celery、PostgreSQL、独立向量库。
- 不让 proactive 走 `SessionSubmitController`。
- 不直接调用微信 bridge。
- 不新增第二套发送链路。
- 不把 Living World 注入主聊天 prompt。
- 不让用户消息在 Phase 4 先经过世界引擎再决定回复。
- 不改变被动聊天接口的 `reply: str` 返回结构。
- 不让 Reflection 默认真实调用模型。

实现默认值：

```env
CONSCIOUSNESS_LIFE_LOOP_ENABLED=false
CONSCIOUSNESS_REFLECTION_ENABLED=false
CONSCIOUSNESS_REFLECTION_MODEL_ENABLED=false
CONSCIOUSNESS_EXPRESSION_GATE_ENABLED=false
CONSCIOUSNESS_LIFE_LOOP_INTERVAL_SECONDS=1200
CONSCIOUSNESS_REFLECTION_HOUR=5
CONSCIOUSNESS_REFLECTION_MINUTE=0
```

验收必须证明：默认配置不会真实调用模型，不会真实发送。

## 1. 文件结构（按阶段 · 以 §0.0 为权威）

### Phase 4a — 已完成 / 已验收（仅列实际已存在的文件与测试）

**已新增的源码：**

- `app/services/consciousness/experience_recorder.py` — InnerExperience 写入 / 查询 / 去重 / 状态标记 / 批次 metadata。
- `app/services/consciousness/life_loop.py` — LifeLoop 最小脉冲：dry-run / disabled no-op / 最小状态推进。
- `app/services/consciousness/reflection_engine.py` — 反思 run + 写 `long_term_memory` + StateStore 回注。

**已修改的源码：**

- `app/storage/db.py` — 新增 `inner_experience_log` / `dream_reflection_runs` 表与索引。
- `app/services/consciousness/models.py` — `NeedState` / `LifeResidue` / `LifeState`；`NenoState.life`；`StateMutation.life` / `life_residue`（旧 JSON 兼容）。
- `app/services/consciousness/state_store.py` — `_apply_mutation()` 支持 life / life_residue。
- `app/services/consciousness/config.py` — Living World env 开关，默认全关。
- `app/services/consciousness/brain.py` — 接入 `ExperienceRecorder`；judge false / 无 target / 写 intent 后沉淀经历；不改发送链路。
- `app/services/consciousness/__init__.py` — 构造新服务，仅 env enabled 时注册 job。
- `app/services/consciousness/world_engine.py` — 保留 `daily_dream` job id，placeholder 委托 ReflectionEngine 或 no-op。
- `app/routers/debug.py` — 新增 `/debug/consciousness/living/*` 只读 + dry-run endpoint。

**已存在的测试：**

- `tests/unit/test_experience_recorder.py`
- `tests/unit/test_life_loop.py`
- `tests/unit/test_reflection_engine.py`
- `tests/unit/test_brain.py`（含未表达经历沉淀用例）
- `tests/unit/test_state_store.py`（含 LifeState 旧 JSON 兼容用例）
- `tests/integration/test_consciousness_living_world_debug.py`（Living World debug endpoint）

> ⚠️ 旧版本文中列过的 `tests/unit/test_living_debug.py` **不存在**——Living World debug 的实际测试是上面那条 integration 测试，不要再引用不存在的 unit 文件。

### Phase 4b — 已完成 / 已验收（Living World MVP，按 §4 任务 B1.1–B1.5 落地）

- `app/services/consciousness/models.py` — `LifeState` 富字段 `place` / `time_phase` / `environment` / `activity_label` / `activity_reason` / `continuity_note`（B1.1）。
- `app/services/consciousness/life_loop.py` — 生活化推进（B1.2）；读取 residue 影响推进并过滤自身 state_shift（B1.3）。
- `app/routers/debug.py` — Living World endpoint schema 扩展富字段和只读 dry-run 预览（B1.4）。
- `app/static/js/consciousness.js`、`app/static/js/layout.js` — 生活验收面板（B1.5）。
- 测试：已扩充 `tests/unit/test_state_store.py` / `tests/unit/test_life_loop.py` / `tests/integration/test_consciousness_living_world_debug.py`。

### Phase 4c — 待实现（完整世界引擎核心）

- 新计划：`PHASE_4C_LIVING_SIMULATION_PLAN.md`。
- 预期源码：在 `app/services/consciousness/` 下新增生活模拟模型 / episode 推进 / micro event 生成模块，具体以 Phase 4c 计划为准。
- 预期测试：新增或扩充 `tests/unit/test_life_simulation.py`、`tests/unit/test_life_loop.py`、`tests/unit/test_reflection_engine.py`、`tests/integration/test_consciousness_living_world_debug.py`。

### Phase 4d — 可选（4c 验收后再考虑，不进 4c）

- `app/services/consciousness/expression_gate.py` — 从 LifeState + InnerExperience 生成 ExpressionPlan，仅写 `proactive_intent`（不发送）。
- 测试：`tests/unit/test_expression_gate.py`（**尚不存在**，4d 才创建；不得放进 4b / 4c 验证）。

### Phase 5 — 暂停

- 无新增文件；仅在 schema / 语义层保留 `UserMessageBatch` / `ExpressionPlan` / `delivery` / `tempo` 预留。须等 4c 验收后启动。

## 2. 数据结构

### 2.1 LifeState JSON

在 `models.py` 中新增：

```python
class NeedState(BaseModel):
    connection: float = 0.0
    novelty: float = 0.0
    quiet: float = 0.0
    order: float = 0.0


class LifeResidue(BaseModel):
    topic: str = ""
    mood: str = ""
    intensity: float = 0.0


class LifeState(BaseModel):
    mode: str = "idle"
    attention: str = "ambient"
    need: NeedState = Field(default_factory=NeedState)
    current_activity: str = "quiet_observing"
    last_transition_at: Optional[str] = None
    residue: LifeResidue = Field(default_factory=LifeResidue)
```

在 `NenoState` 增加：

```python
life: LifeState = Field(default_factory=LifeState)
```

在 `StateMutation` 增加：

```python
life: Optional[LifeState] = None
life_residue: Optional[LifeResidue] = None
```

兼容要求：

- `NenoState.model_validate_json()` 读取旧 `state_json` 时必须自动补默认 `life`。
- `StateStore.read()` 对旧状态不得抛异常。
- 所有数值写入时 clamp 到合法范围。

### 2.2 InnerExperience 表

在 `app/storage/db.py:init_db()` 的 consciousness tables 区域增加：

```sql
CREATE TABLE IF NOT EXISTS inner_experience_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    mood_impact REAL DEFAULT 0.0,
    desire_impact REAL DEFAULT 0.0,
    salience REAL DEFAULT 0.5,
    expression_status TEXT DEFAULT 'unspoken',
    related_event_hash TEXT,
    related_message_ids TEXT,
    related_intent_id INTEGER,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);
```

索引：

```sql
CREATE INDEX IF NOT EXISTS idx_inner_exp_created
ON inner_experience_log(created_at);

CREATE INDEX IF NOT EXISTS idx_inner_exp_status
ON inner_experience_log(expression_status, created_at);

CREATE INDEX IF NOT EXISTS idx_inner_exp_source
ON inner_experience_log(source, kind);

CREATE UNIQUE INDEX IF NOT EXISTS idx_inner_exp_dedupe
ON inner_experience_log(source, kind, related_event_hash, date(created_at))
WHERE related_event_hash IS NOT NULL;
```

`related_message_ids` 存 JSON list，例如 `[101, 102, 103]`。

`metadata_json` 存 JSON object，用于保存：

- `user_message_batch`
- `tempo`
- `message_types`
- `expression_plan`
- debug trace 信息

### 2.3 Reflection Run 表

```sql
CREATE TABLE IF NOT EXISTS dream_reflection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    input_summary TEXT NOT NULL,
    output_json TEXT,
    model_name TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
```

索引：

```sql
CREATE INDEX IF NOT EXISTS idx_reflection_created
ON dream_reflection_runs(created_at);

CREATE INDEX IF NOT EXISTS idx_reflection_status
ON dream_reflection_runs(status, created_at);
```

## 3. JSON Schema

### 3.1 InnerExperience 输入

```json
{
  "trace_id": "string",
  "source": "life_loop|event_pool|brain_judge|reflection|user_residue",
  "kind": "observation|impulse|memory_echo|state_shift|unspoken_thought",
  "content": "string",
  "mood_impact": 0.0,
  "desire_impact": 0.0,
  "salience": 0.5,
  "expression_status": "unspoken|pending_expression|expressed|suppressed|expired",
  "related_event_hash": "string|null",
  "related_message_ids": [101, 102],
  "related_intent_id": 1,
  "metadata": {
    "tempo": "rapid_burst",
    "message_types": ["text", "text"],
    "expression_plan": null
  }
}
```

### 3.2 UserMessageBatch 预留输入

Phase 4 只把它保存进 `metadata_json`，Phase 5 才把它作为回复前决策输入。

```json
{
  "batch_id": "wx:private:xxx#batch-12",
  "session_id": "wx:private:xxx",
  "source_count": 3,
  "tempo": "rapid_burst",
  "messages": [
    {
      "message_id": 101,
      "arrival_seq": 1,
      "trace_id": "t1",
      "message_type": "text",
      "content": "第一句",
      "received_at": "2026-06-05T00:00:00"
    }
  ],
  "aggregated_text": "当前给 run_chat_turn 的合并文本"
}
```

### 3.3 LifeLoop dry-run 输出

```json
{
  "success": true,
  "enabled": false,
  "would_update_life": {
    "mode": "idle",
    "attention": "ambient",
    "current_activity": "quiet_observing"
  },
  "would_record_experience": {
    "source": "life_loop",
    "kind": "state_shift",
    "content": "Neno quiet_observing"
  },
  "would_mutate_state": {
    "mood_valence_delta": 0.0,
    "desire_pulse": 0.0
  }
}
```

### 3.4 Reflection 输出

```json
{
  "summary": "string",
  "memories": [
    {
      "content": "string",
      "tags": ["life"],
      "subject": "",
      "salience": 0.5
    }
  ],
  "state_feedback": {
    "mood_valence_delta": 0.0,
    "desire_pulse": 0.0,
    "life_residue": {
      "topic": "",
      "mood": "",
      "intensity": 0.0
    }
  }
}
```

### 3.5 ExpressionPlan 输出

```json
{
  "mode": "reply_now",
  "fragments": ["第一句", "第二句"],
  "timing": {
    "style": "immediate",
    "delays_seconds": [0, 2]
  },
  "reason": "user_directly_addressed_neno",
  "source_experience_ids": [1, 2],
  "delivery": "passive_response"
}
```

`delivery` 取值：

- `passive_response`：被动聊天返回；Phase 4 不拆多条，只保留计划。
- `proactive_intent`：主动消息；Phase 4C 可写 `proactive_intent.fragments`。
- `absorb_only`：只沉淀。
- `delayed_outbound`：真正延迟外发；Phase 5C 才允许实现。

### 3.6 ExpressionGate 输出

```json
{
  "speak_now": false,
  "reason": "connection_need_low",
  "candidate_experience_ids": [],
  "target_user_id": null,
  "urgency": "low",
  "expression_plan": null
}
```

## 4. 实现任务

### 任务 1：数据库表与模型地基

**文件：**

- 修改：`app/storage/db.py`
- 修改：`app/services/consciousness/models.py`
- 修改：`app/services/consciousness/state_store.py`
- 测试：`tests/unit/test_state_store.py`
- 测试：`tests/unit/test_experience_recorder.py`

**步骤：**

- [ ] **步骤 1：写失败测试，验证新表存在**

在 `tests/unit/test_experience_recorder.py` 增加：

```python
def test_inner_experience_and_reflection_tables_exist(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()

    row = db_storage.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='inner_experience_log'"
    )
    assert row is not None

    row = db_storage.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dream_reflection_runs'"
    )
    assert row is not None

    columns = {
        row["name"]
        for row in db_storage.fetch_all("PRAGMA table_info(inner_experience_log)")
    }
    assert "related_message_ids" in columns
    assert "metadata_json" in columns
```

运行：

```bash
pytest tests/unit/test_experience_recorder.py::test_inner_experience_and_reflection_tables_exist -v
```

预期：失败，表不存在。

- [ ] **步骤 2：在 `db.py` 增加两张表和索引**

按第 2 节 SQL 增加 `CREATE TABLE IF NOT EXISTS` 和 `CREATE INDEX IF NOT EXISTS`。

- [ ] **步骤 3：运行建表测试**

```bash
pytest tests/unit/test_experience_recorder.py::test_inner_experience_and_reflection_tables_exist -v
```

预期：通过。

- [ ] **步骤 4：写失败测试，验证旧 `state_json` 自动补 LifeState**

在 `tests/unit/test_state_store.py` 增加：

```python
def test_old_state_json_gets_default_life():
    old = {
        "version": 2,
        "revision": 0,
        "updated_at": None,
        "energy": {"value": 80.0, "status": "awake", "description": "ok"},
        "mood": {
            "valence": 0.3,
            "arousal": 0.5,
            "label": "平静",
            "description": "ok",
            "baseline_valence": 0.3,
            "baseline_arousal": 0.5
        },
        "desire": {"value": 0.0, "last_express_at": None, "decay_duration_minutes": 120},
        "world": {"weather": None, "hot_topics": [], "time_context": "", "last_perception_at": None},
        "last_interaction": {"user_id": None, "user_name": None, "summary": None, "at_time": None},
        "today_experiences": []
    }

    state = NenoState.model_validate(old)
    assert state.life.mode == "idle"
    assert state.life.current_activity == "quiet_observing"
```

运行：

```bash
pytest tests/unit/test_state_store.py::TestNenoStateSerialization::test_default_state_roundtrip tests/unit/test_state_store.py::test_old_state_json_gets_default_life -v
```

预期：新增测试失败或 import 缺失。

- [ ] **步骤 5：新增 LifeState 模型和 StateMutation 字段**

按第 2.1 节修改 `models.py`。

- [ ] **步骤 6：支持 StateStore life 写入**

在 `StateStore._apply_mutation()` 中增加：

```python
if mutation.life is not None:
    state.life = mutation.life

if mutation.life_residue is not None:
    state.life.residue = mutation.life_residue
```

- [ ] **步骤 7：运行 StateStore 回归**

```bash
pytest tests/unit/test_state_store.py -v
```

预期：通过。

### 任务 2：ExperienceRecorder

**文件：**

- 创建：`app/services/consciousness/experience_recorder.py`
- 测试：`tests/unit/test_experience_recorder.py`

**接口：**

```python
from pydantic import BaseModel, Field


class InnerExperienceIn(BaseModel):
    trace_id: str
    source: str
    kind: str
    content: str
    mood_impact: float = 0.0
    desire_impact: float = 0.0
    salience: float = 0.5
    expression_status: str = "unspoken"
    related_event_hash: str | None = None
    related_message_ids: list[int] = Field(default_factory=list)
    related_intent_id: int | None = None
    metadata: dict = Field(default_factory=dict)


class ExperienceRecorder:
    async def record(self, exp: InnerExperienceIn) -> int | None: ...
    async def list_recent(self, limit: int = 50, status: str | None = None) -> list[dict]: ...
    async def mark_expression_status(self, experience_id: int, status: str, intent_id: int | None = None) -> None: ...
```

**步骤：**

- [ ] **步骤 1：写失败测试，验证 record/list_recent**

```python
@pytest.mark.asyncio
async def test_record_and_list_recent(tmp_path):
    _init_test_db(tmp_path)
    recorder = ExperienceRecorder()

    exp_id = await recorder.record(InnerExperienceIn(
        trace_id="t1",
        source="brain_judge",
        kind="unspoken_thought",
        content="暂时没说出口的想法",
        related_event_hash="evt1",
    ))

    assert exp_id is not None
    rows = await recorder.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["content"] == "暂时没说出口的想法"
```

- [ ] **步骤 2：实现最小 recorder**

实现要求：

- 所有写入用 `asyncio.to_thread()` 包裹 `execute_write` 或 `get_conn()`。
- `record()` 捕获唯一索引冲突，返回已有记录 id 或 `None`，不得抛到主流程。
- `list_recent()` 按 `created_at DESC, id DESC` 返回。
- `salience` clamp 到 `[0, 1]`。
- `related_message_ids` 和 `metadata` 用 JSON 持久化，查询时解码回 Python 对象。

- [ ] **步骤 3：写失败测试，验证去重**

```python
@pytest.mark.asyncio
async def test_record_dedupes_same_event_same_day(tmp_path):
    _init_test_db(tmp_path)
    recorder = ExperienceRecorder()
    exp = InnerExperienceIn(
        trace_id="t1",
        source="brain_judge",
        kind="unspoken_thought",
        content="same",
        related_event_hash="evt_dup",
    )

    first = await recorder.record(exp)
    second = await recorder.record(exp)

    rows = await recorder.list_recent(limit=10)
    assert first is not None
    assert second in (None, first)
    assert len(rows) == 1
```

- [ ] **步骤 4：写失败测试，验证状态标记**

```python
@pytest.mark.asyncio
async def test_mark_expression_status(tmp_path):
    _init_test_db(tmp_path)
    recorder = ExperienceRecorder()
    exp_id = await recorder.record(InnerExperienceIn(
        trace_id="t1", source="life_loop", kind="impulse", content="想说点什么"
    ))

    await recorder.mark_expression_status(exp_id, "pending_expression", intent_id=12)
    rows = await recorder.list_recent(limit=10)

    assert rows[0]["expression_status"] == "pending_expression"
    assert rows[0]["related_intent_id"] == 12
```

- [ ] **步骤 5：写失败测试，验证用户消息批次 metadata roundtrip**

```python
@pytest.mark.asyncio
async def test_record_user_message_batch_metadata(tmp_path):
    _init_test_db(tmp_path)
    recorder = ExperienceRecorder()

    exp_id = await recorder.record(InnerExperienceIn(
        trace_id="t_batch",
        source="user_interaction",
        kind="message_batch",
        content="用户连续发来 3 条消息",
        related_message_ids=[101, 102, 103],
        metadata={
            "tempo": "rapid_burst",
            "message_types": ["text", "text", "text"],
            "user_message_batch": {
                "source_count": 3,
                "aggregated_text": "三条消息的合并文本"
            }
        },
    ))

    rows = await recorder.list_recent(limit=10)
    assert exp_id is not None
    assert rows[0]["related_message_ids"] == [101, 102, 103]
    assert rows[0]["metadata"]["tempo"] == "rapid_burst"
```

- [ ] **步骤 6：运行 recorder 测试**

```bash
pytest tests/unit/test_experience_recorder.py -v
```

预期：通过。

### 任务 3：配置开关

**文件：**

- 修改：`app/services/consciousness/config.py`
- 测试：`tests/unit/test_life_loop.py`
- 测试：`tests/unit/test_reflection_engine.py`
- 测试：`tests/unit/test_expression_gate.py`

**步骤：**

- [ ] **步骤 1：写失败测试，验证默认关闭**

```python
def test_living_world_flags_default_disabled(monkeypatch):
    for key in [
        "CONSCIOUSNESS_LIFE_LOOP_ENABLED",
        "CONSCIOUSNESS_REFLECTION_ENABLED",
        "CONSCIOUSNESS_REFLECTION_MODEL_ENABLED",
        "CONSCIOUSNESS_EXPRESSION_GATE_ENABLED",
    ]:
        monkeypatch.delenv(key, raising=False)

    cfg = ConsciousnessConfig()
    assert cfg.life_loop_enabled is False
    assert cfg.reflection_enabled is False
    assert cfg.reflection_model_enabled is False
    assert cfg.expression_gate_enabled is False
```

- [ ] **步骤 2：实现 env 解析**

在 `config.py` 增加：

```python
def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
```

新增字段：

```python
life_loop_enabled: bool = _env_bool("CONSCIOUSNESS_LIFE_LOOP_ENABLED", False)
reflection_enabled: bool = _env_bool("CONSCIOUSNESS_REFLECTION_ENABLED", False)
reflection_model_enabled: bool = _env_bool("CONSCIOUSNESS_REFLECTION_MODEL_ENABLED", False)
expression_gate_enabled: bool = _env_bool("CONSCIOUSNESS_EXPRESSION_GATE_ENABLED", False)
life_loop_interval_seconds: int = int(os.getenv("CONSCIOUSNESS_LIFE_LOOP_INTERVAL_SECONDS", "1200"))
reflection_hour: int = int(os.getenv("CONSCIOUSNESS_REFLECTION_HOUR", "5"))
reflection_minute: int = int(os.getenv("CONSCIOUSNESS_REFLECTION_MINUTE", "0"))
```

- [ ] **步骤 3：运行配置测试**

```bash
pytest tests/unit/test_life_loop.py::test_living_world_flags_default_disabled -v
```

预期：通过。

### 任务 4：LifeLoop 生活循环

**文件：**

- 创建：`app/services/consciousness/life_loop.py`
- 修改：`app/services/consciousness/__init__.py`
- 测试：`tests/unit/test_life_loop.py`

**接口：**

```python
class LifeLoop:
    def __init__(self, state_store: StateStore, recorder: ExperienceRecorder, config: ConsciousnessConfig) -> None: ...
    async def dry_run(self, trace_id: str | None = None) -> dict: ...
    async def run_once(self, trace_id: str | None = None) -> dict: ...
```

**生活状态规则：**

- energy sleeping：不推进，返回 `skipped_sleeping`。
- energy < 30：`mode=resting`，`attention=self`，`current_activity=low_energy_resting`。
- desire >= threshold 且最近有 user：`mode=seeking_connection`，`attention=user`，`current_activity=thinking_of_user`。
- 最近 6 小时有 unspoken experience：`mode=absorbed`，`attention=memory`，`current_activity=carrying_unspoken_thought`。
- 其他情况：`mode=idle`，`attention=ambient`，`current_activity=quiet_observing`。

**步骤：**

- [ ] **步骤 1：写失败测试，dry-run 不写 DB**

```python
@pytest.mark.asyncio
async def test_life_loop_dry_run_does_not_write(tmp_path):
    _init_test_db(tmp_path)
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        loop = LifeLoop(store, recorder, ConsciousnessConfig())
        before = len(await recorder.list_recent())
        result = await loop.dry_run("trace_life")
        after = len(await recorder.list_recent())
        assert result["success"] is True
        assert before == after
    finally:
        await store.stop()
```

- [ ] **步骤 2：实现 dry-run**

实现只读 state 和 recent experiences，返回计划结果，不写 DB。

- [ ] **步骤 3：写失败测试，disabled run_once no-op**

```python
@pytest.mark.asyncio
async def test_life_loop_disabled_noop(tmp_path):
    _init_test_db(tmp_path)
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        cfg = ConsciousnessConfig(life_loop_enabled=False)
        loop = LifeLoop(store, recorder, cfg)
        result = await loop.run_once("trace_life")
        assert result["action"] == "disabled"
        assert await recorder.list_recent() == []
    finally:
        await store.stop()
```

- [ ] **步骤 4：写失败测试，enabled 写状态和 experience**

```python
@pytest.mark.asyncio
async def test_life_loop_enabled_records_experience_and_updates_state(tmp_path):
    _init_test_db(tmp_path)
    store = _fresh_store(tmp_path)
    await store.start()
    try:
        recorder = ExperienceRecorder()
        cfg = ConsciousnessConfig(life_loop_enabled=True)
        loop = LifeLoop(store, recorder, cfg)

        result = await loop.run_once("trace_life")
        await asyncio.sleep(0.2)

        rows = await recorder.list_recent()
        state = await store.read()
        assert result["action"] == "updated"
        assert len(rows) == 1
        assert state.life.current_activity in {
            "quiet_observing",
            "thinking_of_user",
            "low_energy_resting",
            "carrying_unspoken_thought",
        }
    finally:
        await store.stop()
```

- [ ] **步骤 5：实现 run_once**

实现要求：

- disabled 返回 no-op。
- enabled 时先调用 dry-run 生成决定。
- 写 `inner_experience_log`。
- 通过 `StateStore.submit_mutation()` 写 `life`、`mood_valence_delta`、`desire_pulse`。
- 捕获异常并写 debug event，不影响 scheduler。

- [ ] **步骤 6：在 `ConsciousnessEngine.start()` 注册 job**

只在 `self.config.life_loop_enabled` 为 true 时注册：

```python
self._scheduler.add_job(
    self._life_loop.run_once,
    "interval",
    seconds=self.config.life_loop_interval_seconds,
    id="life_loop",
    replace_existing=True,
)
```

- [ ] **步骤 7：运行测试**

```bash
pytest tests/unit/test_life_loop.py tests/unit/test_state_store.py -v
```

预期：通过。

### 任务 5：Brain 未表达经历沉淀

**文件：**

- 修改：`app/services/consciousness/brain.py`
- 修改：`app/services/consciousness/__init__.py`
- 测试：`tests/unit/test_brain.py`
- 测试：`tests/unit/test_experience_recorder.py`

**步骤：**

- [ ] **步骤 1：写失败测试，judge false 写 unspoken experience**

在 `tests/unit/test_brain.py` 的 `TestNenoBrainRunCycle` 增加：

```python
@pytest.mark.asyncio
async def test_judge_should_not_share_records_unspoken_experience(tmp_path):
    _init_db(_make_test_db_dir(tmp_path))
    recorder = ExperienceRecorder()

    state = _make_awake_state()
    state.desire.value = 80.0
    mock_state_store = AsyncMock()
    mock_state_store.read.return_value = state

    event = EventIn(topic_hash="test_unspoken", priority=0, content="一件暂时不说的事")
    mock_pool = AsyncMock()
    mock_pool.pop_pending.side_effect = [[event], []]

    brain = NenoBrain(
        state_store=mock_state_store,
        pool=mock_pool,
        recall=AsyncMock(),
        fragmenter=MagicMock(),
        interrupt=InterruptController(),
        config=ConsciousnessConfig(),
        recorder=recorder,
    )

    judge_json = json.dumps({
        "should_share": False,
        "reason": "现在不适合说",
        "target_user_id": None,
        "urgency": "low",
    })

    with patch("app.services.consciousness.brain._llm_call", new=AsyncMock(return_value=judge_json)):
        await brain.run_cycle()

    rows = await recorder.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["expression_status"] == "unspoken"
    assert rows[0]["related_event_hash"] == "test_unspoken"
```

- [ ] **步骤 2：修改 NenoBrain 构造函数**

新增可选参数：

```python
recorder: ExperienceRecorder | None = None
```

如果未传入，内部创建 `ExperienceRecorder()`，保证旧测试可少改。

- [ ] **步骤 3：在 judge false 分支记录经历**

在：

```python
if not decision or not decision.get("should_share"):
    return
```

之前记录：

```python
await self._record_unspoken(all_events, trace_id, reason="judge false")
```

要求：

- 记录 `source="brain_judge"`。
- 记录 `kind="unspoken_thought"`。
- `expression_status="unspoken"`。
- 每个 event 最多记录前 3 条，防止一次写太多。
- recorder 失败只写 warning debug，不阻断 brain。

- [ ] **步骤 4：写失败测试，无 target 时记录 suppressed**

```python
@pytest.mark.asyncio
async def test_judge_true_no_target_records_suppressed(tmp_path):
    ...
    judge_json = json.dumps({
        "should_share": True,
        "reason": "想说但没有对象",
        "target_user_id": None,
        "urgency": "normal",
    })
    ...
    assert rows[0]["expression_status"] == "suppressed"
```

- [ ] **步骤 5：成功写 intent 后记录 pending_expression**

修改 `_write_intent()` 返回 `intent_id`。

实现方式：

- 不能再只用 `execute_write()`，需要用 `get_conn()` 拿 `cursor.lastrowid`。
- 保持 SQL 仍写 `proactive_intent`，不触碰发送链路。
- 成功后记录 `expression_status="pending_expression"`，`related_intent_id=intent_id`。

- [ ] **步骤 6：运行 brain 测试**

```bash
pytest tests/unit/test_brain.py tests/unit/test_experience_recorder.py -v
```

预期：通过。

### 任务 6：ReflectionEngine 反思与长期记忆闭环

**文件：**

- 创建：`app/services/consciousness/reflection_engine.py`
- 修改：`app/services/consciousness/__init__.py`
- 修改：`app/services/consciousness/world_engine.py`
- 测试：`tests/unit/test_reflection_engine.py`

**接口：**

```python
class ReflectionEngine:
    def __init__(
        self,
        state_store: StateStore,
        recorder: ExperienceRecorder,
        recall: MemoryRecall,
        config: ConsciousnessConfig,
    ) -> None: ...

    async def dry_run(self, trace_id: str | None = None) -> dict: ...
    async def run_once(self, trace_id: str | None = None) -> dict: ...
```

**步骤：**

- [ ] **步骤 1：写失败测试，disabled no-op**

```python
@pytest.mark.asyncio
async def test_reflection_disabled_noop(tmp_path):
    _init_test_db(tmp_path)
    engine = _make_reflection_engine(tmp_path, reflection_enabled=False)
    result = await engine.run_once("trace_reflect")
    assert result["action"] == "disabled"
```

- [ ] **步骤 2：写失败测试，model disabled 使用 deterministic 输出**

```python
@pytest.mark.asyncio
async def test_reflection_model_disabled_no_llm_call(tmp_path):
    _init_test_db(tmp_path)
    engine = _make_reflection_engine(
        tmp_path,
        reflection_enabled=True,
        reflection_model_enabled=False,
    )

    with patch("app.services.consciousness.reflection_engine._llm_reflect") as mock_llm:
        result = await engine.run_once("trace_reflect")
        mock_llm.assert_not_called()
        assert result["action"] in {"reflected", "no_experiences"}
```

- [ ] **步骤 3：实现 reflection run 写入**

实现要求：

- 从 `ExperienceRecorder.list_recent()` 读取当天 experiences。
- 无 experiences 时写一条 `dream_reflection_runs.status='skipped'` 或返回 `no_experiences`，不写 long_term_memory。
- 有 experiences 时创建 `input_summary`，先写 run 表。
- `reflection_model_enabled=false` 时用 deterministic 输出：
  - summary 由最近 3 条 experience 拼接。
  - memories 最多 2 条。
  - feedback 小幅度，`mood_valence_delta` 在 `[-0.05, 0.05]`。
- `reflection_model_enabled=true` 时再调用模型；本阶段实现可以保留调用函数但测试中必须 mock。

- [ ] **步骤 4：写失败测试，写入 long_term_memory**

```python
@pytest.mark.asyncio
async def test_reflection_writes_long_term_memory(tmp_path):
    _init_test_db(tmp_path)
    recorder = ExperienceRecorder()
    await recorder.record(InnerExperienceIn(
        trace_id="t1",
        source="life_loop",
        kind="state_shift",
        content="Neno 安静地整理了一会儿今天的心情",
        salience=0.8,
    ))

    engine = _make_reflection_engine(tmp_path, recorder=recorder, reflection_enabled=True)
    await engine.run_once("trace_reflect")

    rows = db_storage.fetch_all("SELECT content FROM long_term_memory")
    assert len(rows) >= 1
```

- [ ] **步骤 5：写失败测试，通过 StateStore 回注 residue**

```python
@pytest.mark.asyncio
async def test_reflection_feedback_updates_life_residue(tmp_path):
    ...
    await engine.run_once("trace_reflect")
    await asyncio.sleep(0.2)
    state = await store.read()
    assert state.life.residue.intensity >= 0.0
```

- [ ] **步骤 6：注册 reflection job**

在 `ConsciousnessEngine.start()` 中，仅当 `reflection_enabled` true 时注册：

```python
self._scheduler.add_job(
    self._reflection.run_once,
    "cron",
    hour=self.config.reflection_hour,
    minute=self.config.reflection_minute,
    id="daily_dream",
    replace_existing=True,
)
```

如果保留 `WorldEngine.register_jobs()` 内的 `daily_dream`，必须避免两个同 id job 竞争。推荐实现方式：

- `WorldEngine.register_jobs()` 接收 `enable_daily_dream_placeholder: bool = True`。
- `ConsciousnessEngine` 在启用 ReflectionEngine 时传 false。
- 未启用 ReflectionEngine 时保留 placeholder。

- [ ] **步骤 7：运行 reflection 测试**

```bash
pytest tests/unit/test_reflection_engine.py tests/unit/test_world_engine.py -v
```

预期：通过。

### 任务 B1（Phase 4b · 已完成 · Living World MVP）：Living World Model 与生活化推进

> **Phase 4b 已完成并通过验证。** 它是可观测生活状态机 MVP，不等同于完整世界引擎。完整世界引擎核心见任务 C1。
> **红线（每个子任务都沿用 §0）：** 不碰 `chat_service.py` / `context_builder.py` / 发送链路；不注入主聊天 prompt；不引入新基础设施；默认不真实调用模型、不真实发送。

#### B1.1 LifeState 富字段模型与旧 JSON 兼容（已完成）

- **文件：** `app/services/consciousness/models.py`、`app/services/consciousness/state_store.py`
- **测试文件：** `tests/unit/test_state_store.py`（扩充）
- **验证命令：** `pytest tests/unit/test_state_store.py -v`
- **验收：** `LifeState` 新增 `place` / `time_phase` / `environment` / `activity_label` / `activity_reason` / `continuity_note`；可经 `StateStore.submit_mutation()` 写入并读回；旧 `state_json` 读取自动补默认、不抛异常；字段 clamp 合法；既有 StateStore 用例保持绿。

#### B1.2 LifeLoop 生活化推进（已完成）

- **文件：** `app/services/consciousness/life_loop.py`
- **测试文件：** `tests/unit/test_life_loop.py`（扩充）
- **验证命令：** `pytest tests/unit/test_life_loop.py -v`
- **验收：** LifeLoop 依据时间 / 环境 / 精力 / 需求产生**连贯、可解释**的生活片段；`activity_reason` 能说明"她为什么在做这件事"，`continuity_note` 串联上一片段；非随机、非固定占位；dry-run 仍不写库、disabled 仍 no-op。

#### B1.3 Reflection residue 影响下一次 LifeLoop（已完成）

- **文件：** `app/services/consciousness/reflection_engine.py`、`app/services/consciousness/life_loop.py`
- **测试文件：** `tests/unit/test_reflection_engine.py`、`tests/unit/test_life_loop.py`（扩充）
- **验证命令：** `pytest tests/unit/test_reflection_engine.py tests/unit/test_life_loop.py -v`
- **验收：** 反思写入的 `life_residue` 能被**下一次** LifeLoop 读取并改变推进结果；存在覆盖"昨天反思 → 今天生活状态"的测试；residue 回灌仍只经 `StateStore.submit_mutation()`。

#### B1.4 Living World debug endpoint schema 扩展（已完成）

- **文件：** `app/routers/debug.py`
- **测试文件：** `tests/integration/test_consciousness_living_world_debug.py`（扩充）
- **验证命令：** `pytest tests/integration/test_consciousness_living_world_debug.py -v`
- **验收：** `/debug/consciousness/living/state` 返回富字段（place / time_phase / environment / activity_label / activity_reason / continuity_note / residue）及长期记忆影响摘要；只读 / dry-run 前后 DB 计数不变。

#### B1.5 WebUI 生活验收面板（已完成）

- **文件：** `app/static/js/consciousness.js`、`app/static/js/layout.js`
- **测试文件：** `tests/integration/test_consciousness_living_world_debug.py`（面板数据来源的后端契约测试；本仓库无 JS 测试框架，前端以 `/test` 控制台人工验收）
- **验证命令：** `pytest tests/integration/test_consciousness_living_world_debug.py -v`（保证面板数据契约正确）
- **验收：** 面板展示 SPEC §7 的 Phase 4b 六项——她在哪 / 在做什么 / 为什么 / 今天经历 / 反思残留 / 长期记忆影响；不在 UI 触发真实发送；"表达闸门原因"不在 4b 面板内（属 4d）。

### 任务 C1（Phase 4c · 历史计划，现已实现并被后续世界层扩展）：Living Simulation Core

> 详细执行计划见 `PHASE_4C_LIVING_SIMULATION_PLAN.md`。本任务必须一步到位实现完整生活模拟核心，而不是继续把目标后移。

**核心验收：**

- `ActivityEpisode` 表达一段生活的开始、持续、结束、被打断和转移。
- `VirtualSpace` / `DailyIntent` / `Routine` 共同驱动活动选择。
- `MicroEvent` 从当前生活片段派生，并写入 `inner_experience_log`。
- Debug UI 能重放今天生活线，而不是只展示此刻状态。
- ReflectionEngine 读取生活线，总结"今天怎么活过"，并影响下一天 LifeLoop。
- 默认不真实调用模型、不真实发送、不改主聊天入口、不碰红线文件。

### 任务 7（Phase 4d · 可选 / 非 4c 必需）：ExpressionGate 从生活经历产生表达冲动

**文件：**

- 创建：`app/services/consciousness/expression_gate.py`
- 修改：`app/services/consciousness/__init__.py`
- 测试：`tests/unit/test_expression_gate.py`
- 回归：`tests/unit/test_phase3b.py`

**接口：**

```python
class ExpressionGate:
    async def dry_run(self, trace_id: str | None = None) -> dict: ...
    async def run_once(self, trace_id: str | None = None) -> dict: ...
```

**规则：**

- disabled 时 no-op。
- energy sleeping 时不说。
- 无 target user 时不写 `proactive_intent`。
- connection need < 60 且 desire < threshold 时不说。
- 最近 unspoken 高 salience experience 存在，并且 desire >= threshold，允许写 `proactive_intent`。
- 先生成 ExpressionPlan，再决定是否写 `proactive_intent`。
- ExpressionPlan 必须包含 fragments，即使最终不发送。
- 写入 fragments 必须极短，Phase 4C v1 不调用生成模型，可从 experience content 生成保守占位文案。
- 写入后将相关 experience 标记为 `pending_expression`。

**步骤：**

- [ ] **步骤 1：写失败测试，disabled no-op**

```python
@pytest.mark.asyncio
async def test_expression_gate_disabled_noop(tmp_path):
    ...
    result = await gate.run_once("trace_expr")
    assert result["action"] == "disabled"
```

- [ ] **步骤 2：写失败测试，无 target 不写 intent**

```python
@pytest.mark.asyncio
async def test_expression_gate_no_target_does_not_write_intent(tmp_path):
    ...
    result = await gate.run_once("trace_expr")
    rows = db_storage.fetch_all("SELECT id FROM proactive_intent")
    assert result["action"] == "no_target"
    assert rows == []
```

- [ ] **步骤 3：写失败测试，满足条件只写 proactive_intent**

```python
@pytest.mark.asyncio
async def test_expression_gate_writes_proactive_intent_only(tmp_path):
    ...
    result = await gate.run_once("trace_expr")
    rows = db_storage.fetch_all("SELECT id, fragments, status FROM proactive_intent")
    assert result["action"] == "queued_intent"
    assert result["expression_plan"]["delivery"] == "proactive_intent"
    assert len(rows) == 1
    assert rows[0]["status"] == "queued"
```

- [ ] **步骤 4：实现 ExpressionGate**

实现要求：

- 使用 `get_conn()` 写 `proactive_intent` 并取 `lastrowid`。
- 将 ExpressionPlan 写入相关 InnerExperience 的 `metadata.expression_plan`。
- 不导入 bridge。
- 不调用 `send_brain_intent()`。
- 不调用 `send_proactive_candidate()`。
- 不修改 `proactive/rules.py`。
- 真实发送仍由 Phase 3b consumer 和 env 控制。

- [ ] **步骤 5：运行测试**

```bash
pytest tests/unit/test_expression_gate.py tests/unit/test_phase3b.py -v
```

预期：通过。

### 任务 8（Phase 4a · 已完成）：Living World Debug endpoint 与最小只读 UI

> 已落地，验收归入 Phase 4a。实际测试文件是 `tests/integration/test_consciousness_living_world_debug.py`（**不是** `tests/unit/test_living_debug.py`，后者不存在）。
> 富字段展示与"生活验收面板"升级见 Phase 4b 任务 B1.4 / B1.5。

**文件：**

- 修改：`app/routers/debug.py`
- 修改：`app/static/js/consciousness.js`
- 修改：`app/static/js/layout.js`
- 测试：`tests/integration/test_consciousness_living_world_debug.py`

**Endpoint：**

- `GET /debug/consciousness/living/state`
- `GET /debug/consciousness/living/experiences?limit=50`
- `GET /debug/consciousness/living/reflections?limit=10`
- `POST /debug/consciousness/living/loop_dry_run`
- `POST /debug/consciousness/living/reflection_dry_run`
- `POST /debug/consciousness/living/expression_preflight` 〔Phase 4c optional〕

**步骤：**

- [ ] **步骤 1：写失败测试，只读 endpoint 不写库**

使用 FastAPI `TestClient` 或直接调用 router 函数。测试前后比较：

```sql
SELECT COUNT(*) FROM inner_experience_log;
SELECT COUNT(*) FROM proactive_intent;
SELECT COUNT(*) FROM long_term_memory;
```

断言 GET 和 dry-run POST 不改变计数。

- [ ] **步骤 2：实现 endpoint**

实现要求：

- 全部使用 `Depends(require_admin_token)`。
- dry-run 只调用 `dry_run()` 或 preflight，不调用 `run_once()`。
- endpoint 失败返回 `success=false` 和 reason，不抛 500 到页面。

- [ ] **步骤 3：实现最小 UI**

UI 只读展示：

- 当前 LifeState。
- 最近 InnerExperience。
- InnerExperience 的 related message ids、tempo、ExpressionPlan。
- 最近 Reflection run。
- 三个 dry-run 按钮。

不做复杂交互，不在 UI 触发真实发送。

- [ ] **步骤 4：运行 debug 测试**

```bash
pytest tests/integration/test_consciousness_living_world_debug.py -v
```

预期：通过。

## 5. 总体验证

### Phase 4a 验证（已验收 · 仅用实际存在的测试）

```bash
pytest tests/unit/test_experience_recorder.py \
       tests/unit/test_life_loop.py \
       tests/unit/test_reflection_engine.py \
       tests/integration/test_consciousness_living_world_debug.py -v
```

> 注意：`tests/unit/test_living_debug.py` **不存在**；Living World debug 的真实测试是上面的 integration 文件。
> `tests/unit/test_expression_gate.py` 属 **Phase 4c**，**不要**放进 4a / 4b 验证。

### 回归验证

```bash
pytest tests/unit/test_state_store.py \
       tests/unit/test_world_engine.py \
       tests/unit/test_brain.py \
       tests/unit/test_phase3b.py \
       tests/unit/test_proactive_runner_boundary.py -v
```

### 红线变更检查

```bash
git diff --name-only -- \
  app/services/session_submit_controller.py \
  app/services/session_aggregation_controller.py \
  app/services/chat/context_builder.py \
  app/services/chat_service.py \
  app/services/proactive/rules.py \
  app/services/chat/history_digest.py
```

预期：无输出。

### 默认关闭检查

```bash
pytest tests/unit/test_life_loop.py::test_living_world_flags_default_disabled \
       tests/unit/test_reflection_engine.py::test_reflection_model_disabled_no_llm_call -v
```

预期：通过，且没有真实模型调用，没有真实发送。

### Phase 4b 验证（已完成 · Living World MVP）

```bash
pytest tests/unit/test_state_store.py \
       tests/unit/test_life_loop.py \
       tests/unit/test_reflection_engine.py \
       tests/integration/test_consciousness_living_world_debug.py -v
```

### Phase 4c 验证（待实现 · Living Simulation Core）

```bash
pytest tests/unit/test_life_simulation.py \
       tests/unit/test_life_loop.py \
       tests/unit/test_reflection_engine.py \
       tests/integration/test_consciousness_living_world_debug.py -v
```

### Phase 4d 验证（可选 · 仅启用 ExpressionGate 后）

```bash
pytest tests/unit/test_expression_gate.py -v   # 该文件 4d 才创建，当前不存在
```

## 6. 验收标准

> **历史阶段映射：** 旧「Phase 4A 验收」+「Phase 4B 验收」= Phase 4a；任务 B1 = Phase 4b；当时把任务 C1 定义为 Phase 4c。当前状态不再以本段判断。

Phase 4a 验收 · A 段（地基，已验收）：

- `inner_experience_log` 能持久化未表达经历。
- `inner_experience_log` 能保存用户多条输入的 `related_message_ids` 和 `metadata_json`。
- `NenoState.life` 兼容旧状态。
- LifeLoop disabled 默认 no-op。
- LifeLoop dry-run 不写库。
- brain judge false 不再丢事件语义。
- 被动聊天只允许旁路沉淀 UserInteractionEvent，不改变回复行为。

Phase 4a 验收 · B 段（反思闭环，已并入 4a，已验收）：

- Reflection disabled 默认 no-op。
- model disabled 时不调用模型。
- 有内在经历时能写 `dream_reflection_runs`。
- 有内在经历时能写 `long_term_memory`。
- 反思结果能通过 StateStore 影响 life residue / mood / desire。

Phase 4b 验收（Living World MVP，已验收）：

- LifeState 富字段旧 JSON 兼容。
- LifeLoop 生活化推进有时间段、地点、活动标签、原因和连续性。
- Reflection residue 能改变下一次 LifeLoop 推进。
- Debug endpoint 返回 `life` / `life_residue` / `loop_preview`，dry-run 不写库。
- WebUI 生活验收面板能展示她在哪、做什么、为什么、余波和下一轮预览。

Phase 4c 验收（历史验收清单；实现已超过本范围）：

- ActivityEpisode 有生命周期，不只是单点状态。
- VirtualSpace / DailyIntent / Routine 影响活动选择。
- MicroEvent 写入 InnerExperience，且不是随机事件列表。
- Debug UI 能重放今天生活线。
- ReflectionEngine 总结生活线并影响下一天状态。

Phase 4d 验收（ExpressionGate · 可选，非 4c 必需）：

- ExpressionGate disabled 默认 no-op。
- ExpressionGate 先生成 ExpressionPlan，再只写 `proactive_intent`。
- ExpressionPlan 支持 fragments，但不改变被动 `reply: str`。
- 真实发送仍由 Phase 3b consumer 控制。
- Debug 能追溯一次主动表达来自哪些 InnerExperience。

全局验收：

- 默认配置下不会真实调用模型。
- 默认配置下不会真实发送。
- 不修改红线文件。
- 不引入新基础设施。
- 主聊天测试和 Phase 3b 测试保持通过。

Phase 5 预留验收（⛔ Phase 5 暂停，须等 Phase 4c 验收后再启动）：

- Phase 4 文档和 schema 已保留 `UserMessageBatch`、`ExpressionPlan`、`delivery`、`tempo`。
- Phase 4 不实现 PassiveWorldIngress。
- Phase 4 不实现真正延迟 / 不回复的被动入口。

## 7. 实现顺序

### Phase 4a（已完成 · 历史顺序，供回溯）

1. 数据库表与 LifeState 最小模型。
2. ExperienceRecorder。
3. env 配置开关。
4. LifeLoop dry-run 与 disabled no-op。
5. Brain judge false 沉淀 InnerExperience。
6. ReflectionEngine deterministic 闭环。
7. Living World debug endpoint（只读 + dry-run）。

### Phase 4b（已完成 · Living World MVP）

1. B1.1 LifeState 富字段模型与旧 JSON 兼容。
2. B1.2 LifeLoop 生活化推进。
3. B1.3 Reflection residue 影响下一次 LifeLoop。
4. B1.4 Living World debug endpoint schema 扩展。
5. B1.5 WebUI 生活验收面板。

> **ExpressionGate 不在 4b 实现顺序内**——它已顺延为 Phase 4d 可选项，4b / 4c 验收完全不依赖它。

### Phase 4c（待实现 · 下一步）

- 任务 C1：Living Simulation Core，按 `PHASE_4C_LIVING_SIMULATION_PLAN.md` 执行。

### Phase 4d（可选 · 4c 验收后再考虑）

- 任务 7：ExpressionGate 写 `proactive_intent`（不发送，发送仍由 Phase 3b consumer 控制）。

### Phase 5（暂停）

- 须等 Phase 4c 验收通过后才启动；当前不实现。

不要先做 Reflection 模型接入，也不要先做更多主动发送。Phase 4 的验收对象是”连续可解释的生活”，不是”消息发出”。
