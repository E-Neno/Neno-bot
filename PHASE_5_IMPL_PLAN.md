# Phase 5 World Ingress Implementation Plan

> **状态：暂停，未开始。** 本计划依赖的前置条件不再简单等同于旧文档中的
> “Phase 4c 完成”。必须先按 `docs/living-world.md` 完成持续生活、因果延续、
> 双循环收敛和多日模拟验收，再允许用户消息进入世界引擎。

> **面向 AI 代理的工作者：** 实现此计划前，必须阅读 `NENO.md`、`NENO_ARCHITECTURE.md`、`PHASE_4_LIVING_WORLD_SPEC.md`、`PHASE_4_IMPL_PLAN.md`。推荐使用 `superpowers:executing-plans` 或 `superpowers:subagent-driven-development` 执行；每个任务完成后先跑对应测试，再进入下一任务。

**目标：** 将用户输入纳入 Neno 的世界引擎入口，由世界决策决定立即表达、延迟表达或不表达，而不是让被动消息直接等价于聊天回复。

**架构：** 新增 `WorldIngress` 层作为平台/Web 输入和聊天生成之间的网关。用户消息先落库为世界事件和 `messages.user`，再由规则优先、模型可选的 `WorldDecisionEngine` 输出 `world_action`。即时表达只写 assistant；延迟表达写 SQLite pending 记录并通过现有 proactive candidate 发送链路执行；不表达只沉淀 experience，不写 assistant。

**技术栈：** FastAPI、Pydantic、SQLite、现有 `run_chat_turn`/`send_proactive_candidate` 链路、OpenClaw `neno-bridge` 插件。

---

## 0. 红线和默认安全策略

### 严禁修改

- `app/services/session_submit_controller.py`
- `app/services/session_aggregation_controller.py`
- `app/services/chat/context_builder.py`
- `app/services/chat_service.py`
- `app/services/proactive/rules.py`
- `app/services/chat/history_digest.py`

### 必须保持

- 单机 SQLite，不引入 Redis、Kafka、Celery、Postgres。
- 不直接调用 QQ/WX bridge。延迟表达必须走 `proactive_candidates` 和 `send_proactive_candidate()`。
- 不改变 `context_builder.py` 内的 prompt append order。
- 同一 `session_id` 的平台消息仍由现有 session submit/aggregation 控制器串行。
- 默认不真实调用世界判断模型，不真实发送延迟表达，不启用 no-expression 行为。

### 新增 env 默认值

在 `app/config.py` 中新增：

```python
WORLD_INGRESS_MODE = _env_choice("WORLD_INGRESS_MODE", "off", {"off", "observe", "control"})
WORLD_CONTROL_ENABLED = _env_bool("WORLD_CONTROL_ENABLED", False)
WORLD_JUDGE_LLM_ENABLED = _env_bool("WORLD_JUDGE_LLM_ENABLED", False)
WORLD_EXPRESSION_CONSUMER_ENABLED = _env_bool("WORLD_EXPRESSION_CONSUMER_ENABLED", False)
WORLD_EXPRESSION_AUTO_SEND = _env_bool("WORLD_EXPRESSION_AUTO_SEND", False)
WORLD_BRIDGE_ACTION_PROTOCOL_ENABLED = _env_bool("WORLD_BRIDGE_ACTION_PROTOCOL_ENABLED", False)
WORLD_INGRESS_ALLOWED_SESSIONS = _env_csv("WORLD_INGRESS_ALLOWED_SESSIONS")
WORLD_PENDING_MAX_DELAY_SECONDS = _env_int("WORLD_PENDING_MAX_DELAY_SECONDS", 1800)
WORLD_PENDING_CONSUME_INTERVAL_SECONDS = _env_int("WORLD_PENDING_CONSUME_INTERVAL_SECONDS", 30)
```

默认行为：

- `off`：完全走旧路径，不改变平台/Web 行为。
- `observe`：记录 world ingress 和 decision，但强制 `immediate_expression`。
- `control`：只有 `WORLD_CONTROL_ENABLED=true` 且 session 在白名单内，才允许 `no_expression` / `schedule_expression` 生效。

---

## 1. 新增数据协议

### World action

统一使用 `world_action`，不要使用过窄的 `passive_reply` 命名。

允许值：

```python
WORLD_ACTION_IMMEDIATE = "immediate_expression"
WORLD_ACTION_SCHEDULE = "schedule_expression"
WORLD_ACTION_NONE = "no_expression"
```

语义：

- `immediate_expression`：本轮立即生成表达，平台/Web response 带 `reply`。
- `schedule_expression`：本轮不返回文本表达，写入 `pending_expressions`，到期后通过 proactive candidate 发送。
- `no_expression`：本轮不表达，只沉淀用户消息和 experience。

### 响应 schema

修改 `app/schemas.py`：

```python
class ChatResponse(BaseModel):
    reply: str
    world_action: str | None = None
    world_decision_id: int | None = None
    world_ingress_event_id: int | None = None
    pending_expression_id: int | None = None
    reply_fragments: list[str] = Field(default_factory=list)
    ...


class PlatformMessageResponse(BaseModel):
    success: bool
    reply: str
    session_id: str
    world_action: str | None = None
    world_decision_id: int | None = None
    world_ingress_event_id: int | None = None
    pending_expression_id: int | None = None
    reply_fragments: list[str] = Field(default_factory=list)
```

兼容要求：

- 旧调用方仍可只读 `reply`。
- `reply` 始终是字符串。
- `no_expression` / `schedule_expression` 时 `reply=""`。

---

## 2. SQLite schema

### 文件

- 修改：`app/storage/db.py`
- 测试：`tests/unit/test_world_ingress_storage.py`

### 新增表

在 `init_db()` 中添加：

```sql
CREATE TABLE IF NOT EXISTS world_ingress_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    source TEXT NOT NULL,
    platform TEXT,
    chat_type TEXT,
    user_id TEXT,
    message TEXT NOT NULL,
    message_type TEXT DEFAULT 'text',
    user_message_ids TEXT NOT NULL,
    input_record_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_world_ingress_session_created
ON world_ingress_events(session_id, created_at);

CREATE TABLE IF NOT EXISTS world_turn_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    ingress_event_id INTEGER,
    session_id TEXT NOT NULL,
    requested_action TEXT NOT NULL,
    effective_action TEXT NOT NULL,
    reason TEXT,
    confidence REAL DEFAULT 1.0,
    rule_result_json TEXT,
    llm_result_json TEXT,
    control_enabled INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_world_decision_session_created
ON world_turn_decisions(session_id, created_at);

CREATE TABLE IF NOT EXISTS pending_expressions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    platform TEXT,
    chat_type TEXT,
    user_id TEXT,
    ingress_event_id INTEGER,
    decision_id INTEGER,
    user_message_ids TEXT NOT NULL,
    message TEXT NOT NULL,
    input_record_json TEXT,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    superseded_by_trace_id TEXT,
    candidate_ids TEXT,
    result_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pending_expressions_due
ON pending_expressions(status, due_at);

CREATE INDEX IF NOT EXISTS idx_pending_expressions_session
ON pending_expressions(session_id, status);
```

### 新增 storage functions

在 `app/storage/db.py` 增加：

```python
def add_world_ingress_event(...) -> dict: ...
def add_world_turn_decision(...) -> dict: ...
def add_pending_expression(...) -> dict: ...
def list_due_pending_expressions(limit: int = 10) -> list[dict]: ...
def update_pending_expression_status(expression_id: int, status: str, ...) -> dict | None: ...
def cancel_pending_expressions_for_session(session_id: str, trace_id: str, reason: str) -> int: ...
def list_recent_world_ingress_events(limit: int = 50) -> list[dict]: ...
def list_recent_world_turn_decisions(limit: int = 50) -> list[dict]: ...
def list_pending_expressions(limit: int = 50) -> list[dict]: ...
```

JSON 字段写入使用 `json.dumps(..., ensure_ascii=False)`，读取时返回 Python dict/list。

### 测试

- `test_init_db_creates_world_ingress_tables`
- `test_add_world_ingress_event_round_trips_user_message_ids`
- `test_add_world_turn_decision_records_requested_and_effective_action`
- `test_pending_expression_lifecycle_pending_to_sent`
- `test_cancel_pending_expressions_for_session_marks_superseded`

命令：

```powershell
pytest tests/unit/test_world_ingress_storage.py -v
```

---

## 3. WorldIngress 模块

### 文件

- 创建：`app/services/world_ingress/__init__.py`
- 创建：`app/services/world_ingress/models.py`
- 创建：`app/services/world_ingress/decision_engine.py`
- 创建：`app/services/world_ingress/gateway.py`
- 测试：`tests/unit/test_world_ingress_decision.py`
- 测试：`tests/unit/test_world_ingress_gateway.py`

### models.py

定义：

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class UserMessageBatch:
    trace_id: str
    session_id: str
    source: str
    message: str
    input_record: dict[str, Any]
    persist_user_messages: list[dict[str, Any]] | None = None
    platform: str | None = None
    chat_type: str | None = None
    user_id: str | None = None

@dataclass
class WorldTurnDecision:
    requested_action: str
    effective_action: str
    reason: str
    confidence: float = 1.0
    delay_seconds: int | None = None
    reply_fragments: list[str] = field(default_factory=list)
    rule_result: dict[str, Any] = field(default_factory=dict)
    llm_result: dict[str, Any] | None = None

@dataclass
class WorldIngressResult:
    trace_id: str
    session_id: str
    world_action: str
    reply: str
    ingress_event_id: int | None
    decision_id: int | None
    pending_expression_id: int | None
    user_message_ids: list[int]
    assistant_message_id: int | None
    reply_fragments: list[str]
    chat_result: dict[str, Any] | None = None
```

### decision_engine.py

实现 `WorldDecisionEngine.decide(batch) -> WorldTurnDecision`。

规则优先：

- 默认 requested 和 effective 都是 `immediate_expression`。
- `WORLD_INGRESS_MODE=off` 时不应该进入 gateway；如果进入，仍返回 immediate。
- `observe` 时允许 requested 为 schedule/no-expression，但 effective 必须 immediate。
- `control` 时只有满足：
  - `WORLD_CONTROL_ENABLED=true`
  - `session_id` 在 `WORLD_INGRESS_ALLOWED_SESSIONS`
  - action 被规则允许
  才能让 requested 变成 effective。

第一版 deterministic rules：

- 空白或预处理 fallback 消息：`requested_action="immediate_expression"`。
- 含明确求助、问题、紧急语气：`immediate_expression`。
- 含低强度分享、无问句、短陈述：可请求 `no_expression`，但默认 effective immediate。
- 含“晚点/等下/不急”等语义：可请求 `schedule_expression`，delay 不超过 `WORLD_PENDING_MAX_DELAY_SECONDS`。

LLM judge：

- 只在 `WORLD_JUDGE_LLM_ENABLED=true` 且白名单命中时调用。
- LLM 输出只能作为 requested action；effective action 仍受控制开关约束。
- LLM 失败时记录 debug event，回退规则。

### gateway.py

实现：

```python
class WorldIngressGateway:
    def handle_user_batch(self, batch: UserMessageBatch) -> WorldIngressResult:
        ...
```

步骤：

1. 取消同 session 旧 pending expression：
   - 调用 `cancel_pending_expressions_for_session(session_id, trace_id, "new_user_message")`。
2. 立即写入 user messages：
   - 如果 `persist_user_messages` 存在，逐条 `add_message(...)`。
   - 否则写入单条 user message。
   - metadata 必须包含 `world_ingress.status="received"`，后续不要回写修改这批 metadata。
3. 写 `world_ingress_events`。
4. 调 `WorldDecisionEngine.decide()`。
5. 写 `world_turn_decisions`。
6. 按 `effective_action` 分支：
   - `immediate_expression`：调用任务 4 新增的 persisted-user chat API，只写 assistant。
   - `schedule_expression`：写 `pending_expressions`，返回空 reply。
   - `no_expression`：写 experience/debug，返回空 reply。

测试：

- `test_gateway_off_mode_behaves_like_immediate`
- `test_gateway_persists_user_before_decision`
- `test_gateway_immediate_writes_one_assistant_only`
- `test_gateway_schedule_writes_pending_and_no_assistant`
- `test_gateway_no_expression_writes_user_only`
- `test_gateway_new_message_cancels_existing_pending`

命令：

```powershell
pytest tests/unit/test_world_ingress_decision.py tests/unit/test_world_ingress_gateway.py -v
```

---

## 4. 已落库用户消息的聊天生成 API

### 文件

- 修改：`app/services/chat/turn_orchestrator.py`
- 测试：`tests/unit/test_chat_turn_from_persisted_user.py`

### 新增函数

在 `turn_orchestrator.py` 中新增，不改 `chat_service.py` re-export：

```python
def run_chat_turn_from_persisted_user_messages(
    *,
    session_id: str,
    message: str,
    trace_id: str | None,
    user_message_ids: list[int],
    input_record: dict | None = None,
) -> dict:
    ...
```

职责：

- 读取上下文时不能让本轮已落库 user messages 重复进入 prompt。
- 不修改 `context_builder.py`。
- 可新增本文件内 helper：

```python
def _filter_history_excluding_message_ids(history: list[dict], excluded_ids: set[int]) -> list[dict]:
    return [item for item in history if int(item.get("id") or 0) not in excluded_ids]
```

实现方式：

1. 调用 `load_chat_contexts(session_id, message, trace_id=trace_id)`。
2. 从 `contexts["history"]` 中过滤 `user_message_ids`。
3. 调用 `build_chat_messages(...)` 重新组装 messages。
   - 从 `app.services.chat.context_builder` 导入 `build_chat_messages`。
   - 传入原 contexts 中的 `relationship_context`、`time_context`、`memory_context`、`history_digest`。
   - 不改变 `build_chat_messages` 的顺序。
4. 调 `process_memory_candidate(...)`。
5. 调 `generate_chat_reply(...)`。
6. 只写 assistant message：
   - `add_message(session_id, "assistant", reply, trace_id=trace_id, message_type="assistant", source=...)`
7. 调 `apply_relationship_update(session_id, message)`，保持当前 1-turn lag 语义。
8. 返回结构与 `run_chat_turn` 保持兼容，但 `user_message_ids` 来自参数。

测试必须断言：

- prompt 中本轮用户消息只出现一次。
- `messages` 表中不会新增重复 user。
- assistant 正常写入。
- relationship conversation_count 增加一次。
- `context_builder.py` 未修改。

命令：

```powershell
pytest tests/unit/test_chat_turn_from_persisted_user.py -v
```

---

## 5. 平台和 Web 入口接入

### 文件

- 修改：`app/routers/platform.py`
- 修改：`app/routers/chat.py`
- 测试：`tests/integration/test_world_ingress_platform.py`
- 测试：`tests/integration/test_world_ingress_web.py`
- 回归：`tests/integration/test_wx_session_submit_flow.py`
- 回归：`tests/integration/test_platform_session_routing.py`

### platform.py

接入点：

- 不修改 `SessionSubmitController` / `SessionAggregationController`。
- 在 `run_platform_chat_turn(...)` 内部，将原 `run_chat_turn(...)` 替换为 `WorldIngressGateway.handle_user_batch(...)`。
- 因为 `submit_platform_chat_turn(...)` 已经在 submit controller 的 handler 内调用 `run_platform_chat_turn(...)`，所以 gateway 会在现有 session lock 内运行。

伪代码：

```python
if should_use_world_ingress(input_record=input_record, session_id=session_id):
    world_result = world_gateway.handle_user_batch(
        UserMessageBatch(
            trace_id=trace_id,
            session_id=session_id,
            source=f"platform:{platform}",
            platform=platform,
            user_id=user_id,
            chat_type=chat_type,
            message=message,
            input_record=input_record or {},
            persist_user_messages=persist_user_messages,
        )
    )
    return PlatformMessageResponse(
        success=True,
        reply=world_result.reply,
        session_id=session_id,
        world_action=world_result.world_action,
        world_decision_id=world_result.decision_id,
        world_ingress_event_id=world_result.ingress_event_id,
        pending_expression_id=world_result.pending_expression_id,
        reply_fragments=world_result.reply_fragments,
    )
```

`should_use_world_ingress(...)` 规则：

- `WORLD_INGRESS_MODE == "off"` 时 false。
- Web/platform test 可通过 monkeypatch 强制 true。
- 生产控制由 `WORLD_INGRESS_MODE`、`WORLD_CONTROL_ENABLED`、白名单在 decision engine 中处理。

### chat.py

Web `/chat` 也接入 gateway：

- `WORLD_INGRESS_MODE=off` 时保持旧路径。
- 开启后用同一 `WorldIngressGateway`。
- Web source 为 `"web"`，platform 为 `"web"`。

### 测试

- `test_world_ingress_off_platform_keeps_existing_reply`
- `test_world_ingress_observe_platform_returns_immediate_with_world_fields`
- `test_world_ingress_control_no_expression_platform_returns_empty_reply`
- `test_world_ingress_control_schedule_platform_returns_pending_id`
- `test_wx_aggregation_creates_single_world_decision_for_batch`
- `test_web_chat_world_ingress_observe_keeps_reply`
- `test_platform_session_routing_override_still_controls_session_id`
- `test_wx_session_submit_flow_still_serial`

命令：

```powershell
pytest tests/integration/test_world_ingress_platform.py tests/integration/test_world_ingress_web.py -v
pytest tests/integration/test_wx_session_submit_flow.py tests/integration/test_platform_session_routing.py -v
```

---

## 6. Bridge action protocol

### 文件

- 修改：`openclaw-plugins/neno-bridge/index.js`
- 测试：如果当前插件无测试框架，新增 `openclaw-plugins/neno-bridge/test-send-to-neno.js`

### 协议

后端 response：

```json
{
  "success": true,
  "reply": "",
  "session_id": "wx:private:user",
  "world_action": "no_expression"
}
```

bridge 行为：

- `world_action === "immediate_expression"`：发送 `reply`，若 reply 为空则使用失败文案。
- `world_action === "no_expression"`：返回 handled，不发送文本，不使用失败文案。
- `world_action === "schedule_expression"`：返回 handled，不发送文本，不使用失败文案。
- 没有 `world_action` 字段：保持旧行为，防止未知后端版本破坏插件。

修改 `sendToNeno(api, payload)`：

```javascript
const action = typeof data?.world_action === "string" ? data.world_action : "";
if (data?.success === true && action === "no_expression") {
  api?.logger?.info?.("[neno-bridge] world_action=no_expression no reply sent");
  return { handled: true, text: "", noReply: true };
}
if (data?.success === true && action === "schedule_expression") {
  api?.logger?.info?.("[neno-bridge] world_action=schedule_expression no immediate reply sent");
  return { handled: true, text: "", noReply: true };
}
if (data?.success === true && reply) {
  api?.logger?.info?.(`[neno-bridge] replied len=${reply.length}`);
  return { handled: true, text: reply };
}
```

验证点：

- `no_expression` 不返回 `FAILURE_REPLY`。
- `schedule_expression` 不返回 `FAILURE_REPLY`。
- 旧 response `{success:true, reply:"hi"}` 仍发送 `hi`。
- 旧 response `{success:true, reply:""}` 仍发送 `FAILURE_REPLY`，除非 `WORLD_BRIDGE_ACTION_PROTOCOL_ENABLED` 在后端已开启并带 action。

命令：

```powershell
node openclaw-plugins/neno-bridge/test-send-to-neno.js
```

如果无法直接单测私有函数，先将 `sendToNeno` 的 action 判定抽成纯函数：

```javascript
function resolveNenoReplyAction(data) { ... }
```

并仅测试该纯函数。

---

## 7. PendingExpression consumer

### 文件

- 创建：`app/services/world_ingress/pending_consumer.py`
- 修改：`app/services/consciousness/__init__.py`
- 修改：`app/services/proactive/send_executor.py` 或新增小 wrapper：`app/services/world_ingress/expression_sender.py`
- 测试：`tests/unit/test_pending_expression_consumer.py`

### 行为

`PendingExpressionConsumer.consume_once()`：

1. 如果 `WORLD_EXPRESSION_CONSUMER_ENABLED=false`，返回 `{"action": "consumer_disabled"}`。
2. 读取一条到期 `pending_expressions.status='pending'`。
3. 若同 session 有更新的 world ingress event，标记 pending 为 `superseded`。
4. 调 `run_chat_turn_from_persisted_user_messages(...)` 生成 assistant。
5. 将 reply 拆成 `fragments`：
   - 第一版可单段 `[reply]`。
   - 后续多段由 Phase 4 `ExpressionPlan.fragments` 接入。
6. 创建 proactive candidate 并发送：
   - 若 `WORLD_EXPRESSION_AUTO_SEND=false`，只生成 candidate，pending status 变为 `candidate_created`。
   - 若 `WORLD_EXPRESSION_AUTO_SEND=true`，调用 `send_proactive_candidate()`。
7. 更新 `pending_expressions.result_json`、`candidate_ids`、`status`。

发送要求：

- 不直接调用 `_post_neno_bridge_send_wx` 或 `_post_neno_bridge_send_qq`。
- candidate metadata 必须包含：

```json
{
  "source": "world_pending_expression",
  "session_id": "...",
  "world_trace_id": "...",
  "pending_expression_id": 1,
  "world_ingress_event_id": 1,
  "world_decision_id": 1,
  "related_user_message_ids": [10, 11]
}
```

注意：

- 如果复用 `send_brain_intent()` 会把 source 标成 `"brain"`，容易污染语义。推荐新增 `send_world_expression(...)`，内部复用 `add_proactive_candidate()` 和 `send_proactive_candidate()`，source 使用 `"world"`。

### scheduler

在 `app/services/consciousness/__init__.py` 注册：

```python
from app.services.world_ingress.pending_consumer import run_consume_pending_expressions

self._scheduler.add_job(
    run_consume_pending_expressions,
    "interval",
    seconds=self.config.world_pending_consume_interval_seconds,
    id="consume_pending_expressions",
    replace_existing=True,
)
```

如果 `ConsciousnessConfig` 不适合承载该配置，可直接从 `app.config` 读取，避免扩大 consciousness config 语义。

测试：

- consumer disabled 不改 DB。
- due pending 生成 assistant。
- auto send disabled 只生成 pending candidate。
- auto send enabled 调用 `send_proactive_candidate()`。
- 新消息 supersedes 旧 pending。
- bridge 函数未被直接调用。

命令：

```powershell
pytest tests/unit/test_pending_expression_consumer.py -v
```

---

## 8. Experience 沉淀

### 文件

- 依赖 Phase 4：`app/services/living_world/*` 或实际 Phase 4 落地文件
- 修改：`app/services/world_ingress/gateway.py`
- 测试：`tests/unit/test_world_ingress_experience.py`

### 行为

每次 world ingress 都必须写 experience：

- `immediate_expression`：`expression_status="expressed_now"`
- `schedule_expression`：`expression_status="scheduled"`
- `no_expression`：`expression_status="not_expressed"`

内容必须包括：

```json
{
  "source": "user_message",
  "kind": "external_interaction",
  "trace_id": "...",
  "related_message_ids": [1, 2],
  "related_world_ingress_event_id": 1,
  "related_world_decision_id": 1,
  "world_action": "no_expression",
  "salience": 0.3
}
```

如果 Phase 4 尚未实现 `inner_experience_log`，此任务延后到 Phase 4 存储任务完成后执行；不要在 Phase 5 中另造一张重复 experience 表。

---

## 9. Debug endpoints

### 文件

- 修改：`app/routers/debug.py`
- 测试：`tests/integration/test_world_ingress_debug.py`

### endpoints

新增：

- `GET /debug/world-ingress/recent`
- `GET /debug/world-ingress/{trace_id}`
- `GET /debug/world-decisions/recent`
- `GET /debug/world-pending`
- `POST /debug/world-pending/{id}/cancel`
- `POST /debug/world-pending/{id}/run-dry-run`
- `POST /debug/world-ingress/test-decision`

要求：

- 全部 `Depends(require_admin_token)`。
- `run-dry-run` 不真实发送。
- 返回字段包含 `trace_id`、`session_id`、`world_action`、`pending_expression_id`、`candidate_ids`、`reason`。
- 不在 debug endpoint 里直接调用 bridge。

测试：

- 未带 admin token 返回鉴权失败。
- recent endpoints 返回最新记录。
- cancel endpoint 将 pending 改为 `cancelled`。
- dry-run endpoint 不调用真实 send。

命令：

```powershell
pytest tests/integration/test_world_ingress_debug.py -v
```

---

## 10. 分阶段执行任务

### 任务 1：存储层

**文件：**

- 修改：`app/storage/db.py`
- 创建：`tests/unit/test_world_ingress_storage.py`

- [ ] 写 storage tests，覆盖三张表和 lifecycle。
- [ ] 运行 `pytest tests/unit/test_world_ingress_storage.py -v`，确认失败原因是函数/表不存在。
- [ ] 实现 schema 和 storage functions。
- [ ] 重跑测试通过。
- [ ] 检查 `git diff -- app/storage/db.py tests/unit/test_world_ingress_storage.py`。

### 任务 2：世界决策模型

**文件：**

- 创建：`app/services/world_ingress/models.py`
- 创建：`app/services/world_ingress/decision_engine.py`
- 创建：`tests/unit/test_world_ingress_decision.py`
- 修改：`app/config.py`

- [ ] 写 decision tests，覆盖 off/observe/control/白名单/LLM disabled。
- [ ] 运行测试确认失败。
- [ ] 实现 config 和 decision engine。
- [ ] 重跑测试通过。

### 任务 3：已落库用户消息生成路径

**文件：**

- 修改：`app/services/chat/turn_orchestrator.py`
- 创建：`tests/unit/test_chat_turn_from_persisted_user.py`

- [ ] 写测试证明 prompt 不重复本轮 user message。
- [ ] 新增 `run_chat_turn_from_persisted_user_messages(...)`。
- [ ] 重跑测试通过。
- [ ] 回归 `pytest tests/integration/test_relationship_stage_chain.py -v`。

### 任务 4：WorldIngressGateway

**文件：**

- 创建：`app/services/world_ingress/gateway.py`
- 创建：`app/services/world_ingress/__init__.py`
- 创建：`tests/unit/test_world_ingress_gateway.py`

- [ ] 写 gateway tests。
- [ ] 实现 user messages 先落库、ingress event、decision、三 action 分支。
- [ ] 实现新消息取消旧 pending。
- [ ] 重跑 gateway tests。

### 任务 5：平台/Web 接入

**文件：**

- 修改：`app/routers/platform.py`
- 修改：`app/routers/chat.py`
- 创建：`tests/integration/test_world_ingress_platform.py`
- 创建：`tests/integration/test_world_ingress_web.py`

- [ ] 写平台/Web integration tests。
- [ ] 接入 gateway，`WORLD_INGRESS_MODE=off` 保持旧路径。
- [ ] `observe` 模式返回 world 字段但仍 immediate。
- [ ] `control` 模式允许 no/schedule。
- [ ] 跑新测试和 WX 旧回归。

### 任务 6：Bridge action protocol

**文件：**

- 修改：`openclaw-plugins/neno-bridge/index.js`
- 创建：`openclaw-plugins/neno-bridge/test-send-to-neno.js`

- [ ] 抽出 `resolveNenoReplyAction(data)`。
- [ ] 测试 no/schedule 不返回 `FAILURE_REPLY`。
- [ ] 保持旧 response 行为。
- [ ] 运行 node 测试。

### 任务 7：Pending consumer 和发送链路

**文件：**

- 创建：`app/services/world_ingress/pending_consumer.py`
- 创建：`app/services/world_ingress/expression_sender.py`
- 修改：`app/services/consciousness/__init__.py`
- 创建：`tests/unit/test_pending_expression_consumer.py`

- [ ] 写 consumer tests。
- [ ] 实现 due pending 消费。
- [ ] 实现 `send_world_expression(...)`，只通过 proactive candidate 和 `send_proactive_candidate()`。
- [ ] auto send disabled 时只生成 candidate。
- [ ] auto send enabled 时 mock `send_proactive_candidate()`。
- [ ] 重跑测试。

### 任务 8：Experience 和 debug

**文件：**

- 修改：`app/services/world_ingress/gateway.py`
- 修改：`app/routers/debug.py`
- 创建：`tests/unit/test_world_ingress_experience.py`
- 创建：`tests/integration/test_world_ingress_debug.py`

- [ ] 接入 Phase 4 experience 存储。
- [ ] 增加 debug endpoints。
- [ ] 跑 debug 和 experience tests。

---

## 11. 全量验证命令

按顺序运行：

```powershell
pytest tests/unit/test_world_ingress_storage.py -v
pytest tests/unit/test_world_ingress_decision.py tests/unit/test_world_ingress_gateway.py -v
pytest tests/unit/test_chat_turn_from_persisted_user.py -v
pytest tests/unit/test_pending_expression_consumer.py -v
pytest tests/integration/test_world_ingress_platform.py tests/integration/test_world_ingress_web.py -v
pytest tests/integration/test_world_ingress_debug.py -v
pytest tests/integration/test_wx_session_submit_flow.py tests/integration/test_platform_session_routing.py tests/integration/test_relationship_stage_chain.py -v
node openclaw-plugins/neno-bridge/test-send-to-neno.js
```

如有时间，再跑：

```powershell
pytest tests/unit/test_phase3b.py tests/unit/test_proactive_rules.py tests/unit/test_proactive_results.py -v
```

---

## 12. 自审清单

实现完成后逐项确认：

- [ ] `context_builder.py` 没有改动。
- [ ] `history_digest.py` 没有改动。
- [ ] 两个 session controller 没有改动。
- [ ] no-expression 不会触发 bridge 失败文案。
- [ ] delayed expression 不直接调用 bridge。
- [ ] `WORLD_INGRESS_MODE=off` 时平台/Web 行为与旧路径一致。
- [ ] `observe` 模式不改变真实回复行为。
- [ ] `control` 模式只对白名单 session 生效。
- [ ] 同一 user message 不会在 prompt 中出现两次。
- [ ] delayed pending 被新消息取消，不会过时发送。
- [ ] 所有真实模型调用和真实发送默认 disabled。
- [ ] debug endpoints 可追踪 trace、decision、pending、candidate。

---

## 13. 给执行窗口的第一条指令建议

可以把下面这段发给新的实现窗口：

```text
你现在执行 Neno-bot Phase 5。请先阅读 NENO.md、NENO_ARCHITECTURE.md、PHASE_4_LIVING_WORLD_SPEC.md、PHASE_4_IMPL_PLAN.md、PHASE_5_IMPL_PLAN.md。

严格遵守 PHASE_5_IMPL_PLAN.md 的任务顺序。先做任务 1：world ingress SQLite 存储层。不要修改红线文件：session_submit_controller.py、session_aggregation_controller.py、context_builder.py、chat_service.py、proactive/rules.py、history_digest.py。

用 TDD：先写 tests/unit/test_world_ingress_storage.py，再实现 app/storage/db.py。只完成任务 1 后停下，运行对应 pytest，并汇报 diff 和测试结果。
```
