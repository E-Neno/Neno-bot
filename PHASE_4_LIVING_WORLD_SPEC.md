# Phase 4 Living World 规格草案

> 本文是 Phase 4 的设计规格，不是代码实现计划。
> 目标是先定义 Neno 要成为什么、系统边界在哪里、哪些能力必须可验证。
> 具体文件修改、测试代码、迁移步骤后续再拆到 `PHASE_4_IMPL_PLAN.md`。

---

## 0. 当前状态与阶段重划（2026-06-06 二次校正 · 权威）

> **重要：Phase 4a 已验收 ≠ Phase 4 完成 ≠ 世界引擎完成。**
> 本节是 Phase 4 阶段划分的**唯一权威来源**。本文其余章节（含 §8 Phasing）如有出入，**以本节为准**。
> 已经做完的 4a / 4b 只是"地基 + 可观测生活状态机"。Neno 已能沉淀、反思、回写和展示生活状态，但生活内容仍偏模板；完整世界引擎必须继续在 Phase 4 内完成。

### Phase 4a — 已验收（ACCEPTED）

地基与数据管道，代码已合入并通过测试：

- SQLite `inner_experience_log` / `dream_reflection_runs` 两张表
- `LifeState`（`agent_state.state_json` 的兼容扩展，旧 JSON 自动补默认）
- `ExperienceRecorder`（写入 / 查询 / 去重 / 状态标记 / 批次 metadata）
- `LifeLoop` 最小脉冲（dry-run + disabled no-op + 最小状态推进）
- Brain 未表达经历沉淀（judge false → `unspoken`；无 target → `suppressed`；写 intent → `pending_expression`）
- `ReflectionEngine`（反思 run + 回写 `long_term_memory` + 通过 StateStore 回注状态）
- Living World debug endpoint（只读 + dry-run 预览）

**4a 的本质**：经历能被沉淀、能被反思、能回写长期记忆与状态。但 LifeState 仍是**占位级的粗粒度推进**，Neno 没有连续可信的"生活"。

### Phase 4b — 已验收（ACCEPTED · Living World MVP）

把占位 LifeState 升级为可观测的 Living World MVP，代码已落地并通过测试：

- **Living World Model**：LifeState 新增
  `place` / `time_phase` / `environment` / `activity_label` / `activity_reason` / `continuity_note`（见 §5.2.1）。
- **LifeLoop 生活化推进**：基于时间 / 环境 / 精力 / 需求 / 余波产生**连贯、可解释**的生活片段（而非随机或固定占位）；`activity_reason` 必须能说明"她为什么在做这件事"，`continuity_note` 串起前后片段。
- **Reflection residue 参与下一次生活状态**：反思产出的 `life_residue` 必须真正影响**次日 / 下一次** LifeLoop 推进，形成"昨天影响今天"的闭环（4a 只做到写入 residue，未做到回灌驱动）。
- **WebUI 改成"生活验收面板"**：从只读列表升级为能验收"她现在在哪、在做什么、为什么、今天怎么活过、昨晚反思留下什么余波"的面板。

**4b 的本质**：Neno 已有可读、可调试、可回归测试的生活状态机。但它仍主要由确定性规则和固定文案驱动，不能被宣称为完整世界引擎。

### Phase 4c — 待做（PENDING · Living Simulation Core）

完整世界引擎核心。目标不是继续扩主动表达，而是把 4b 的模板状态机升级为**连续生活模拟**：

- **ActivityEpisode**：一段生活有开始、持续、结束、被打断、转移，而不是每次 tick 只产出一个静态状态。
- **VirtualSpace**：以命名生活场景表达空间和物品，例如房间、桌前、床边、窗边、手机、电脑；不做可导航地图或 3D 世界。
- **DailyIntent / Routine**：每天的生活倾向由精力、需求、记忆余波、时间段共同决定，而不是固定分支。
- **MicroEvent**：生活内部小事件由当前 episode、空间、长期记忆、余波和外界刺激派生，禁止变成随机事件列表。
- **Timeline Debug**：Debug UI 必须能展示"今天怎么活过"，而不仅是"此刻状态"。

**4c 验收对象**：Neno 的一天能被重放为连续、可信、可解释的生活线；生活线中的事件能进入 ReflectionEngine，并影响下一天。

### Phase 4d — 可选表达层（OPTIONAL · 原 4c 顺延）

- **ExpressionGate**：从 LifeState + InnerExperience 生成 ExpressionPlan，仅写 `proactive_intent`，发送仍由 Phase 3b 漏斗决定。
- 明确降级为 optional：**不是 4b / 4c 的前置或必需项**，完整世界引擎验收不依赖 ExpressionGate。可在 4c 之后单独推进，或长期保持关闭。

### Phase 5 — 暂停（PAUSED）

- 被动消息进入世界引擎（PassiveWorldIngress / 回复前世界决策）**暂停**。
- **硬性前提：必须等 Phase 4c 验收通过后再启动。** 在 4c 把连续生活模拟做实之前，让用户消息先过世界引擎只会放大不确定性。

### 一句话总览

```text
4a 已验收（地基/管道） ──▶ 4b 已验收（Living World MVP）
                                  │
                       4c 待做（Living Simulation Core）★完整世界引擎
                                  │
                       4d 可选（ExpressionGate）
                                  │
                       Phase 5 暂停（等 4c 验收）
```

---

## 1. Proposal

Phase 3b 已经证明主动消息链路可行：`brain` 写入 `proactive_intent`，consumer 转成 `proactive_candidates`，最后复用 `send_proactive_candidate()` 发送。

但 Phase 3b 的概念方向容易滑向“事件池 + 随机事件 + 判断要不要发送”。这不是 Neno 世界引擎的最终形态。

Phase 4 的核心目标是：

**让 Neno 从事件驱动的主动消息机器人，推进成有连续虚拟生活、会沉淀经历、会被记忆改变的单体智能体。**

Phase 4 采用单机约束架构：

- 继续使用 SQLite 作为唯一持久化事实源。
- 不引入 Redis、Kafka、Celery、PostgreSQL 或独立向量库。
- 不改主聊天 prompt 拼接顺序。
- 不新造主动发送链路。
- 所有真实模型调用和真实发送相关能力默认 env disabled。

## 2. Terminology

- Living World（虚拟生活世界）：Neno 的连续生活线。它不是地图模拟，也不是多智能体社会，而是时间、状态、需求、记忆余波和外界输入共同形成的单人生活流。
- Memory OS（记忆操作层）：管理经历进入、整理、检索、沉淀和回注的轻量抽象。底层仍是 SQLite。
- LifeLoop（生活循环）：周期性推进 Neno 的生活状态。循环只负责时间流动，不负责制造随机内容。
- LifeState（生活状态）：Neno 当前处于什么生活片段，例如醒着发呆、整理记忆、低能量、想靠近、安静观察。
- InnerExperience（内在经历）：Neno 生活中发生过但不一定说出口的内容，包括外界刺激、未表达想法、情绪变化、注意力转移。
- UserMessageBatch（用户消息批次）：用户端一次进入世界的消息集合。它保留单条、短时间连续多条、图片/语音归一化后的结构信息，不只是一段拼接文本。
- UserInteractionEvent（用户互动事件）：用户消息或消息批次进入 Neno 世界后的事件表示。Phase 4 只做旁路沉淀，Phase 5 才用于回复前决策。
- ExpressionPlan（表达计划）：世界引擎对“是否表达、几段表达、何时表达、走哪个出口”的计划。Phase 4 先保留结构，主动链路可使用 fragments，被动链路暂不改返回协议。
- ReflectionEngine（反思引擎）：夜间或低频整理当天经历，生成长期记忆和次日状态倾向。
- ExpressionGate（表达闸门）：判断某个内在冲动是否需要“此刻说出来”。通过后只能写 `proactive_intent`。
- PassiveWorldIngress（被动世界入口）：Phase 5 的入口重构模块。它会让用户消息先进入世界引擎，再决定立即回复、延迟回复、不回复或只沉淀。
- State Feedback（状态回注）：长期记忆和反思结果通过 `StateStore.submit_mutation()` 影响 mood、desire、world_state 等状态。

## 3. Requirements

### 3.1 Must Have

1. Neno 必须拥有连续的生活状态，而不是只在事件出现时被动响应。
2. 外界输入必须被视为进入 Neno 生活的刺激，而不是世界引擎本体。
3. brain judge 的语义必须从“说 / 丢弃”改为“此刻说 / 暂不说”。
4. 暂不说的内容也必须沉淀为 InnerExperience。
5. InnerExperience 必须进入 SQLite 持久化表，不能只放在 `agent_state.today_experiences`。
6. ReflectionEngine 必须优先整理“今天 Neno 怎么活过”，而不是只摘要事件列表。
7. ReflectionEngine 产出的长期记忆必须写入现有 `long_term_memory` 或其兼容扩展。
8. 长期记忆或反思结果必须能通过 `StateStore` 回注 Neno 状态。
9. 主动表达只能走既有 Phase 3b 链路：`proactive_intent -> consume_brain_intents() -> send_brain_intent() -> send_proactive_candidate()`。
10. Debug 面板必须能看见 Phase 4b 生活验收六项：Neno 在哪里、正在做什么、为什么这样、今天经历、反思残留、长期记忆影响。（"表达闸门原因" 属 Phase 4d optional，不是 4b / 4c 必需项。）
11. InnerExperience 必须能保存用户多条输入的批次信息，至少包括 related message ids 和 metadata。
12. Phase 4 仅保留 ExpressionPlan / ExpressionGate 的 **schema 与语义预留**；真正基于 ExpressionPlan 的表达属于 **Phase 4d（可选）**，**不是 Phase 4c 完整世界引擎必需项**。被动聊天接口不变。
13. Phase 4 必须明确为 Phase 5 的 PassiveWorldIngress 预留输入/输出语义，但不得在 Phase 4 改造主聊天入口。

### 3.2 Must Not Have

1. 不修改 `session_submit_controller.py`。
2. 不修改 `session_aggregation_controller.py`。
3. 不修改 `context_builder.py`。
4. 不修改 `chat_service.py`。
5. 不修改 `proactive/rules.py`。
6. 不修改 `history_digest.py`。
7. 不让 proactive 走 `SessionSubmitController`。
8. 不直接调用微信 bridge。
9. 不新增第二套真实发送链路。
10. 不让 Dream / Reflection 默认真实调用模型。
11. 不把本地模型、向量库或多进程 worker 作为 Phase 4 前提。

### 3.3 Should Have

1. 所有新能力可在本地 SQLite 上完整运行。
2. 2 核 2GB ECS 应能承载默认关闭重模型调用的 Phase 4。
3. Debug endpoint 必须有只读预览能力，避免为了观察而触发模型或发送。
4. 数据结构保留未来接入向量检索的字段，但 Phase 4 不实现向量库。

## 4. Current Code Grounding

CGC 和源码审计确认当前接入点如下：

- `NenoBrain.run_cycle()` 当前负责事件消费、LLM judge、LLM generate、写 `proactive_intent`。
- `EventPool.pop_pending()` 当前会把 `pending` 事件标记为 `consumed`，如果 judge 返回 false，事件语义上已经被消费但没有沉淀为经历。
- `StateStore.submit_mutation()` 是 `agent_state` 的唯一安全写入口。
- `WorldEngine.register_jobs()` 当前已有 heartbeat、event expiry 和 `daily_dream` placeholder。
- `MemoryRecall.add_memory()` 已能写入 `long_term_memory`，适合作为 Phase 4 最小闭环出口。
- `consume_brain_intents()` 每次只消费一条 queued intent，并通过 Phase 3b 漏斗发送。

Phase 4 应优先沿这些边界扩展，不改变主聊天路径和发送路径。

## 5. Design

### 5.1 Architecture

Phase 4 新增一层 Living World，不替换现有 consciousness 层。

```text
time / weather / hot topics / user chat residue
                 |
                 v
          LifeLoop（生活循环）
                 |
                 v
       LifeState + InnerExperience
                 |
        +--------+---------+
        |                  |
        v                  v
 ExpressionGate      ReflectionEngine
        |                  |
        v                  v
 proactive_intent    long_term_memory
        |                  |
        v                  v
 Phase 3b sender     StateStore feedback
```

核心原则：

- LifeLoop 负责“生活推进”，不是随机事件制造器。
- InnerExperience 是主资产，主动消息只是少数经历的外溢。
- ReflectionEngine 处理长期沉淀，不参与实时聊天 prompt。
- Memory OS 使用 SQLite 表和服务边界实现，不引入独立数据库。

### 5.2 LifeState

Phase 4 的 LifeState 应作为 `agent_state.state_json` 的兼容扩展字段，而不是新建独立状态真相源。

建议最小字段：

```json
{
  "life": {
    "mode": "idle",
    "attention": "ambient",
    "need": {
      "connection": 0.0,
      "novelty": 0.0,
      "quiet": 0.0,
      "order": 0.0
    },
    "current_activity": "quiet_observing",
    "last_transition_at": "2026-06-05T00:00:00+00:00",
    "residue": {
      "topic": "",
      "mood": "",
      "intensity": 0.0
    }
  }
}
```

字段含义：

- `mode`：粗粒度生活模式，例如 `idle`、`absorbed`、`reflecting`、`resting`、`seeking_connection`。
- `attention`：注意力朝向，例如 `ambient`、`user`、`world`、`memory`、`self`。
- `need`：需求强度，范围 0-100。
- `current_activity`：当前生活片段，例如 `quiet_observing`、`memory_sorting`、`thinking_of_user`。
- `residue`：上一段经历留下的余波。

兼容策略：

- 老的 `NenoState` 读取旧 JSON 时必须有默认 life 字段。
- 所有 life 状态写入必须通过 `StateStore.submit_mutation()`。
- 不允许其他服务直接更新 `agent_state`。

#### 5.2.1 Phase 4b 扩展：Living World Model（已完成）

> 4a 的 LifeState（`mode` / `attention` / `need` / `current_activity` / `residue`）是**占位级最小集**。
> Phase 4b 已把它升级为可观测生活状态机，新增以下字段（仍是 `life` 下的兼容扩展，旧 JSON 自动补默认）：

```json
{
  "life": {
    "place": "home_desk",
    "time_phase": "late_night",
    "environment": "安静，窗外有雨",
    "activity_label": "整理今天的心情",
    "activity_reason": "白天那条暴雨预警一直没说出口",
    "continuity_note": "接着下午没说完的那件事",
    "...": "（保留 4a 既有 mode/attention/need/current_activity/residue）"
  }
}
```

字段含义：

- `place`：她此刻"在哪"（如 `home_desk`、`bed`、`out`）。Phase 4 是虚拟生活，不接真实定位。
- `time_phase`：生活化时段（如 `early_morning`、`afternoon`、`late_night`），区别于精确时钟。
- `environment`：一句话环境氛围，来自感知层（天气 / 时间）降维。
- `activity_label`：当前生活片段的人话标签。
- `activity_reason`：**为什么在做这件事**——4b 的核心，必须可解释、可在面板上展示。
- `continuity_note`：与上一片段的连续性线索，串起"昨天 / 上一段影响这一段"。

约束（沿用 4a 红线）：

- 仍只通过 `StateStore.submit_mutation()` 写入。
- **不注入主聊天 prompt**；这些字段只服务于 LifeLoop / ReflectionEngine / debug 面板。
- 旧 `state_json` 读取必须自动补默认值，不得抛异常。

### 5.3 InnerExperience

InnerExperience 是 Phase 4 的核心数据。

建议新增 SQLite 表 `inner_experience_log`：

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

最小索引：

```sql
CREATE INDEX IF NOT EXISTS idx_inner_exp_created ON inner_experience_log(created_at);
CREATE INDEX IF NOT EXISTS idx_inner_exp_status ON inner_experience_log(expression_status, created_at);
CREATE INDEX IF NOT EXISTS idx_inner_exp_source ON inner_experience_log(source, kind);
```

字段含义：

- `source`：`life_loop`、`event_pool`、`brain_judge`、`reflection`、`user_residue`。
- `kind`：`observation`、`impulse`、`memory_echo`、`state_shift`、`unspoken_thought`。
- `expression_status`：`unspoken`、`pending_expression`、`expressed`、`suppressed`、`expired`。
- `related_event_hash`：对应原 `event_log.topic_hash`，没有则为空。
- `related_message_ids`：JSON list，对应一次用户互动涉及的 `messages.id`。
- `related_intent_id`：如果最终写入主动意图，记录 `proactive_intent.id`。
- `metadata_json`：JSON object，记录批次节奏、消息类型、ExpressionPlan、debug trace 等扩展信息。

沉淀规则：

- LifeLoop 状态变化必须写 InnerExperience。
- brain judge 返回 `should_share=false` 时必须写 InnerExperience。
- brain judge 返回 `should_share=true` 且成功写入 `proactive_intent` 时也必须写 InnerExperience，并标记为 `expressed` 或 `pending_expression`。
- P0 事件即使不表达，也必须沉淀。
- 同一事件在短时间内不得重复沉淀，使用 `related_event_hash + kind + 日期` 做应用层去重。
- 用户消息或消息批次进入 Phase 4 时，必须保留 `related_message_ids` 和 `metadata_json`；连续多条输入不能只退化成一段拼接文本。

### 5.4 LifeLoop

LifeLoop 是 `WorldEngine` 旁边的低频生活推进器。

最小行为：

- 每 10-30 分钟运行一次，具体间隔由 env 控制。
- 读取当前 `agent_state`、最近 InnerExperience、最近外界输入摘要。
- 根据时间、能量、心情、需求、记忆余波推进 LifeState。
- 写入一条 InnerExperience。
- 通过 `StateStore.submit_mutation()` 更新 life、mood delta、desire pulse。

LifeLoop 不应：

- 直接生成主动消息。
- 直接调用真实模型。
- 直接读取或改写主聊天 prompt。
- 大量制造随机事件。

### 5.5 ExpressionGate

ExpressionGate 判断“此刻说 / 暂不说”。

输入：

- 当前 LifeState。
- 当前 mood / desire / energy。
- 最近 InnerExperience。
- 最近一次用户互动摘要。
- proactive 现有冷却状态只读查询结果。

输出：

```json
{
  "speak_now": false,
  "reason": "connection_need_low",
  "candidate_experience_ids": [1, 2],
  "target_user_id": null,
  "urgency": "low"
}
```

规则：

- `speak_now=false` 不代表丢弃，只代表暂不说。
- `speak_now=true` 后仍只能写 `proactive_intent`。
- 如果没有 `target_user_id`，不得写主动意图。
- 默认 dry-run，不发送；真实消费仍受 `BRAIN_INTENT_CONSUMER_ENABLED` 和白名单控制。

### 5.6 ReflectionEngine

ReflectionEngine 替换 `WorldEngine._daily_reset_placeholder()` 的语义，但实现时不应直接大改 `WorldEngine`。

最小输入：

- 当天 InnerExperience。
- 当天已表达的 proactive intent 摘要。
- 当前 `agent_state`。
- 最近长期记忆的少量召回结果。

最小输出：

```json
{
  "summary": "今天 Neno 的生活体验摘要",
  "memories": [
    {
      "content": "长期记忆内容",
      "tags": ["life", "user", "mood"],
      "subject": "optional subject",
      "salience": 0.7
    }
  ],
  "state_feedback": {
    "mood_valence_delta": 0.05,
    "desire_pulse": 8.0,
    "life_residue": {
      "topic": "想起用户",
      "mood": "soft",
      "intensity": 0.4
    }
  }
}
```

写入策略：

- 先写 `dream_reflection_runs` 或等价表，保留原始输入摘要和模型输出。
- 再通过 `MemoryRecall.add_memory()` 写 `long_term_memory`。
- 最后通过 `StateStore.submit_mutation()` 回注状态。
- 任一阶段失败必须降级，不得影响主聊天和 WorldEngine heartbeat。

默认开关：

- `CONSCIOUSNESS_REFLECTION_ENABLED=false`
- `CONSCIOUSNESS_REFLECTION_MODEL_ENABLED=false`
- `CONSCIOUSNESS_LIFE_LOOP_ENABLED=false`
- `CONSCIOUSNESS_EXPRESSION_GATE_ENABLED=false`

### 5.7 Memory OS

Phase 4 的 Memory OS 是服务边界，不是新数据库。

最小职责：

- `record_experience()`：写 InnerExperience。
- `list_recent_experiences()`：给 LifeLoop、ExpressionGate、ReflectionEngine 读取。
- `mark_expressed()`：主动意图写入后更新经历状态。
- `write_reflection_memory()`：调用 `MemoryRecall.add_memory()` 写长期记忆。
- `preview_retrieval()`：debug 只读检索，不触发模型。

检索策略：

- Phase 4A 使用 SQLite `LIKE` / tag / salience / 时间窗口。
- 可以预留 `embedding_json` 或 `embedding_ref` 字段，但不启用向量库。
- 不把 Memory OS 注入主聊天 prompt；主聊天仍走现有 memory/context 机制。

### 5.8 Passive Input and ExpressionPlan Reservations

Phase 4 不重构被动聊天入口，但必须为 Phase 5 预留语义接口。

Phase 4 对被动消息的处理方式：

```text
用户消息
  -> 现有聚合 / 串行化 / run_chat_turn()
  -> 正常回复并落库
  -> 旁路生成 UserInteractionEvent
  -> 写 InnerExperience
```

Phase 5 的目标处理方式：

```text
用户消息
  -> UserMessageBatch
  -> PassiveWorldIngress
  -> ReplyPolicy / ExpressionPlan
  -> reply_now / delay_reply / no_reply / absorb_only
```

`UserMessageBatch` 最小结构：

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

`tempo` 取值：

- `single`：单条输入。
- `rapid_burst`：短时间连续多条输入。
- `long_pause`：间隔较长，不应视为同一生活事件。

`ExpressionPlan` 最小结构：

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

- `passive_response`：被动聊天 HTTP 返回，Phase 4 不改变现有单条 reply 协议。
- `proactive_intent`：主动消息，Phase 4C 可写入现有 `proactive_intent.fragments`。
- `absorb_only`：只沉淀，不表达。
- `delayed_outbound`：真正延迟外发，Phase 5C 才允许实现。

Phase 4 规则：

- 可以在 metadata 中保存 ExpressionPlan。
- 主动链路可以使用 fragments。
- 被动链路只保存 fragments，不拆成多条返回。
- 不修改 `run_chat_turn()` 的返回结构。
- 不修改平台接口的 `reply: str`。

## 6. Data Flow

### 6.1 External Stimulus Flow

```text
weather / hot topic / user residue
        |
        v
WorldEngine / Perception
        |
        v
event_log + StateStore world update
        |
        v
LifeLoop observes state and writes InnerExperience
```

### 6.2 Brain Judge Flow

```text
event_log pending
        |
        v
NenoBrain.run_cycle()
        |
        v
LLM judge: speak now?
        |
        +-- false --> record InnerExperience(unspoken)
        |
        +-- true  --> generate fragments
                       |
                       v
                  proactive_intent queued
                       |
                       v
                  record InnerExperience(expressed/pending)
```

### 6.3 Reflection Flow

```text
inner_experience_log for day
        |
        v
ReflectionEngine
        |
        +--> dream_reflection_runs
        +--> long_term_memory
        +--> StateStore mood/desire/life residue
```

### 6.4 Passive Message Reservation Flow

Phase 4 只做旁路沉淀：

```text
user message / batch
        |
        v
existing chat pipeline replies normally
        |
        v
messages table
        |
        v
InnerExperience(source=user_interaction, kind=message_batch)
```

Phase 5 才做入口重构：

```text
user message / batch
        |
        v
PassiveWorldIngress
        |
        v
ExpressionPlan
        |
        +-- reply_now
        +-- delay_reply
        +-- no_reply
        +-- absorb_only
```

## 7. Debug Design

新增 debug endpoint 应全部受 admin token 保护。

建议 endpoint：

- `GET /debug/consciousness/living/state`
  - 返回 `agent_state.life`、mood、desire、energy。
- `GET /debug/consciousness/living/experiences?limit=50`
  - 返回最近 InnerExperience。
- `GET /debug/consciousness/living/reflections?limit=10`
  - 返回最近 ReflectionEngine 运行记录。
- `POST /debug/consciousness/living/loop_dry_run`
  - 只预览 LifeLoop 决策，不写状态。
- `POST /debug/consciousness/living/reflection_dry_run`
  - 只预览 ReflectionEngine 输入和计划输出，不写记忆、不回注状态。
- `POST /debug/consciousness/living/expression_preflight` 〔Phase 4d optional〕
  - 只预览 ExpressionGate 结果，不写 `proactive_intent`。**仅当启用 Phase 4d ExpressionGate 时需要，非 4b / 4c 必需项。**

UI 目标 · Phase 4b 生活验收面板必须展示（验收项）：

- Neno 现在在哪里（`place`）。
- 正在做什么（`activity_label`）。
- 为什么这样（`activity_reason`）。
- 今天经历过什么（今日 InnerExperience，含未说出口的想法）。
- 昨晚反思留下了什么残留（`life_residue`）。
- 长期记忆对今天的影响（reflection → `long_term_memory` → 状态回注的可见结果）。

UI 目标 · Phase 4d optional（非 4b / 4c 必需，仅启用 ExpressionGate 后展示）：

- “为什么这次不说 / 为什么这次想说”（表达闸门原因）。

## 8. Phasing（细化 · 以 §0 为权威）

> 阶段边界以 **§0** 为准。本节细化每个阶段的内容与成功标准。
> ⚠️ 旧版曾把"反思与记忆闭环"列为 4B；现已**并入已验收的 4a**。4b 是 Living World MVP，4c 才是完整 Living Simulation Core。

### Phase 4a — 已验收：地基与管道（ACCEPTED，合并旧 4A + 4B）

- LifeState 兼容字段；`inner_experience_log` / `dream_reflection_runs` 表与 recorder。
- InnerExperience 保留 `related_message_ids` 和 `metadata_json`。
- LifeLoop dry-run + disabled no-op + 最小推进。
- brain judge false / 无 target / 写 intent 三路径沉淀经历。
- ReflectionEngine：反思 run + 写 `long_term_memory` + StateStore 回注。
- Debug 只读展示 experiences / reflections。

成功标准（已达成）：

- 默认关闭模型与发送时，经历能持续积累、能被反思、能回写长期记忆与状态。
- 事件被 judge 暂不说后不会丢失。

### Phase 4b — 已验收：Living World MVP（ACCEPTED）

- Living World Model：LifeState 升级，新增 `place` / `time_phase` / `environment` / `activity_label` / `activity_reason` / `continuity_note`（见 §5.2.1）。
- LifeLoop 生活化推进：连贯、可解释的生活片段；`activity_reason` 可说明动机，`continuity_note` 串联前后。
- Reflection residue 回灌：反思 `life_residue` 必须真正影响**下一次** LifeLoop 推进（昨天影响今天）。
- WebUI 升级为"生活验收面板"：展示她在哪 / 在做什么 / 为什么 / 今天怎么活过 / 昨晚余波。

成功标准（已达成）：

- Neno 此刻的生活状态可读、可解释、可 dry-run 预览。
- 反思余波可见地改变下一次 LifeLoop 推进。
- 默认仍不真实调用模型、不真实发送；不碰红线文件。

局限：

- 活动仍主要由模板规则生成。
- 没有 ActivityEpisode 生命周期。
- 没有今日生活线 replay。
- 没有 VirtualSpace / Routine / MicroEvent。

### Phase 4c — 待做：Living Simulation Core（PENDING · 完整世界引擎核心）

- ActivityEpisode：生活片段具备开始、持续、结束、转移和打断。
- VirtualSpace：以命名场景 / 物品表达虚拟生活环境，不做地图模拟。
- DailyIntent / Routine：根据精力、需求、时间、长期记忆、life_residue 形成当天生活倾向。
- MicroEvent：从当前生活片段派生内部小事件，写入 InnerExperience；禁止随机事件列表化。
- Timeline Debug：UI 能重放今天生活线，显示每段活动为什么发生、如何结束、被什么影响。

成功标准：

- Neno 的一天能被重放为连续、可信、可解释的生活。
- 前一天反思余波和长期记忆能改变今天的生活线，而不是只改一句文案。
- LifeLoop / ReflectionEngine / debug endpoint 均保持默认关闭或只读安全边界。

### Phase 4d — 可选：Expression From Living World（OPTIONAL · 非 4c 必需）

- ExpressionGate：从 InnerExperience + LifeState 生成 ExpressionPlan，仅写 `proactive_intent`，发送仍由 Phase 3b consumer 决定。
- **不是 4b / 4c 的前置或必需项**，世界引擎验收不依赖它；可在 4c 后单独推进或长期关闭。

成功标准：

- 主动消息来源能追溯到生活经历，而不是孤立随机事件。
- Debug 能说明一次主动表达来自哪些经历、为什么现在说。

### Phase 5 — 暂停：Passive Message Through World Engine（PAUSED）

> **暂停。硬性前提：Phase 4c 验收通过后才能启动。** Phase 4 仍只为它保留接口，不实现入口改造。

- Phase 5A：用户消息先进入 PassiveWorldIngress，但 policy 永远是 `reply_now`，行为不变。
- Phase 5B：允许短延迟回复，仍在平台同步请求可接受范围内。
- Phase 5C：允许真正延迟 / 不回复；延迟外发必须复用现有 outbound 能力，不直接调用 bridge。

## 9. Test Requirements

### Unit Tests

- LifeState 旧 JSON 兼容读取。
- InnerExperience recorder 写入、查询、去重。
- InnerExperience recorder 保存 `related_message_ids` 和 `metadata_json`。
- LifeLoop dry-run 不写 DB。
- LifeLoop enabled 时只通过 StateStore 写状态。
- brain judge false 时写 `unspoken` InnerExperience。
- brain judge true 但无 target 时写 `unspoken/suppressed`，不写 `proactive_intent`。
- ReflectionEngine disabled 时 no-op。
- ReflectionEngine model disabled 时不真实调用模型。
- ReflectionEngine 输出写入 `long_term_memory`。
- Living Simulation Core 能生成 ActivityEpisode。
- MicroEvent 写入 InnerExperience 且可被 ReflectionEngine 读取。
- ExpressionGate true 时只写 `proactive_intent`（4d optional）。
- ExpressionGate false 时不丢经历（4d optional）。

### Integration Tests

- `event_log -> brain false -> inner_experience_log`。
- `messages -> user interaction batch -> inner_experience_log`。
- `inner_experience_log -> reflection -> long_term_memory -> StateStore`。
- `ActivityEpisode -> MicroEvent -> inner_experience_log -> reflection -> next-day life tendency`。
- `inner_experience_log -> expression gate -> proactive_intent -> existing consumer preflight`（4d optional）。
- Debug endpoint 只读请求不改变 DB。

### Regression Tests

- 主聊天测试保持通过。
- proactive Phase 3b 测试保持通过。
- StateStore 单写者测试保持通过。
- WorldEngine heartbeat 测试保持通过。
- 禁止修改红线文件的变更检查。

## 10. Acceptance Criteria

Phase 4 不能以“发出更多主动消息”为验收标准。

验收标准是：

1. Neno 的一天能被重放为连续生活经历（Phase 4c）。
2. 未表达内容能被保存，并能进入夜间反思。
3. 反思能产生长期记忆。
4. 长期记忆能影响次日状态。
5. 主动消息能追溯到生活经历（4d optional；不是完整世界引擎前置）。
6. 用户多条输入能作为一组生活事件被保存，不丢失节奏和 message ids。
7. Phase 4 仅保留 ExpressionPlan 的 schema / 语义预留；真正基于 ExpressionPlan 的表达属于 Phase 4d（可选），**不是 Phase 4c 完整世界引擎验收项**。被动回复协议不变。
8. 默认配置下不会真实调用模型、不会真实发送。
9. 现有主聊天链路和 Phase 3b 发送链路不被改变。

## 11. Explicit Non-goals

- 不做 3D 世界。
- 不做多智能体社会。
- 不做可导航地点地图模拟；允许命名虚拟场景和物品。
- 不做经济系统、工具市场或治理系统。
- 不迁移 PostgreSQL。
- 不引入 Redis / Kafka / Celery。
- 不实现本地大模型。
- 不实现向量数据库。
- 不重写 consciousness 总入口。
- 不改主聊天 prompt 架构。

## 12. Self Audit

### Product Audit

- 是否仍然围绕“连续虚拟生活”？
  - 通过。规格以 LifeState、LifeLoop、InnerExperience、ReflectionEngine 为主轴。
- 是否把主动消息降为生活外溢？
  - 通过。ExpressionGate 只在后期 Phase 4C 引入，且只写既有 `proactive_intent`。
- 是否为被动消息进入世界引擎留了接口？
  - 通过。Phase 4 只做旁路沉淀，Phase 5 才允许 PassiveWorldIngress 改造入口。
- 是否为多条用户输入和多条回复留了结构？
  - 通过。`related_message_ids`、`metadata_json` 和 ExpressionPlan 保留了批次与 fragments。
- 是否避免回到随机事件机？
  - 通过。LifeLoop 明确不负责大量制造随机内容。
- 是否保留未说出口的东西？
  - 通过。brain judge false 必须写 `unspoken` InnerExperience。

### Architecture Audit

- 是否继续 SQLite？
  - 通过。Memory OS 被定义为服务边界，不是新数据库。
- 是否引入复杂队列？
  - 通过。未引入 Redis、Kafka、Celery。
- 是否触碰主聊天 prompt？
  - 通过。明确不注入 `context_builder.py`。
- 是否绕开发送链路？
  - 通过。主动表达只能写 `proactive_intent`。
- 是否通过 StateStore 写状态？
  - 通过。life/mood/desire 回注必须走 `StateStore.submit_mutation()`。

### Risk Audit

- 最大风险 1：LifeState 扩展 `NenoState` 时破坏旧 `state_json` 兼容。
  - 后续实现计划必须先写旧 JSON 兼容测试。
- 最大风险 2：ReflectionEngine 输出变成普通摘要，不能改变状态。
  - 规格要求必须同时写 `long_term_memory` 和 StateStore feedback。
- 最大风险 3：ExpressionGate 变成第二套 proactive 规则。
  - 规格要求 ExpressionGate 只决定写不写 `proactive_intent`，发送仍由 Phase 3b 漏斗决定。
- 最大风险 4：Debug dry-run 意外写库。
  - 规格要求 dry-run endpoint 不改变 DB，必须有测试覆盖。

### Redline Audit

- 红线文件在 Phase 4 规格中只作为禁止修改对象出现。
- Phase 4 不要求修改：
  - `app/services/session_submit_controller.py`
  - `app/services/session_aggregation_controller.py`
  - `app/services/chat/context_builder.py`
  - `app/services/chat_service.py`
  - `app/services/proactive/rules.py`
  - `app/services/chat/history_digest.py`
