# Neno-bot AI Collaboration & Modification Guidelines (CLAUDE.md)

**System Identity (系统本质定义)**
Neno 是一个高内聚、重观测、状态驱动的“单体智能体引擎”。它运行在低内存、受限的单机环境（如小规模 VPS、SQLite）下，不依赖复杂的微服务或消息队列。其核心是一个状态机与规则网守，用于控制多模态输入、基于内存锁的消息并发、精打细算的 Token 消耗以及严密的降级防御机制。修改代码时，任何看似“不优雅”的设计背后都有其维系系统稳定的考量。

---

## 1. Execution Model (执行模型)

*   **Session 串行模型**：Neno 的核心并发策略是“外部异步，内部串行”。同一 `session_id` 的所有消息必须严格串行处理，绝不允许并发覆盖。
*   **Queue & Submit Controller**：系统通过进程内存里的 `SessionAggregationController` 与 `SessionSubmitController`（基于 `threading.Event` 与 `RLock`）实现用户 Burst（连续突发）消息的聚合拦截与单点排队。**严禁移除这些控制器或用异步协程替代现有的排队逻辑**。
*   **Runtime vs Persistent State**：消息进入时停留在内存队列，只有聚合窗口（`window_seconds`）关闭后才会推进到 SQLite（持久化）。系统重启会导致未落盘的内存队列消息丢失。

## 2. State Model Contract (状态契约)

*   **SQLite 作为绝对单一真相源 (Source of Truth)**：`messages`、`memories`、`relationship_state` 和 `debug_events` 全部由 SQLite 管理。不要引入 Redis。
*   **Digest 状态锚点**：`history_digest.json`（在文件系统）与 `messages`（在 DB）独立存储，两者没有强一致性事务包裹。其同步依靠 `last_baked_message_id` 游标实现，绝不能改变单向累加逻辑。
*   **Metadata Snapshot (状态冻结)**：`messages` 表的 `metadata_json` 会将消息发生那一刻的上下文决策（记忆提取、关系阶段）拍下快照并冻结落盘。**绝对禁止在写完数据库后对 metadata 进行追溯修改**。

## 3. Write Consistency Rules (写入规则)

*   **Write Order (写入顺序)**：状态更新必须发生在回复生成**之后**。
*   **Mutation Timing (1-Turn Lag)**：当前轮（Turn N）提取的 Memory 和变更的 Relationship Stage，绝不会作用于当前轮的回复生成，只能在下一轮（Turn N+1）生效。不要试图在当轮强行注入。
*   **Async Side Effects (副作用边界)**：`history_digest` 的压缩是在主流程内被调用的，但只压缩 `id < raw_history_start_id` 的历史。不要把当轮消息在落盘前就推进压缩流程。

## 4. Context Assembly Contract (上下文装配契约)

**CRITICAL: 绝对禁止修改 `context_builder.py` 中的上下文组装顺序。**

*   **Prompt 拼接顺序**：`SYSTEM_PROMPT` -> `history_digest` -> `relationship` -> `time` -> `memory` -> `raw history`。
*   **Cache Prefix Stability (缓存前缀稳定规则)**：Anthropic 的 Prompt Cache 严格依赖前缀的一致性。静态设定（System）和缓变文本（Digest，每积攒 200 Token 才变化一次）必须放在最前面，并绑定 `ephemeral` 控制。
*   **优先级抢占**：按组装顺序，排在最后的 `memory` 会凭借 LLM 的近因效应，在事实上覆盖掉排在前面的 `relationship` 所设定的宏观语调。

## 5. Memory & Relationship Model (记忆与关系模型)

*   **Relationship**：宏观状态。控制 Neno 对用户的整体态度（Stage 0-4），对应 `prompts/stages/stage_X.txt`。其变更存在严格的积分漏斗。
*   **Memory**：微观挂件。提取的是具体事实或边界约束（如 `preference`, `boundary`）。
*   **交互差异**：Memory 作为硬性约束，直接在 Prompt 尾部干预 LLM 表现。Relationship 仅作为基础底色。二者在 DB 中隔离，在 Prompt 中协同。

## 6. Proactive System Rules (主动交互引擎规则)

*   **触发机制**：由 Scheduler 轮询驱动，带有极其严密的漏斗规则（硬冷却时间、日常上限、失败连续暂停）。
*   **DB vs Runtime**：主动交互判定强依赖 DB 查询（如 `has_recent_user_message`）。若判断时用户的交互还在内存队列未落盘，系统会存在时序竞态（Race Condition）。
*   **Cooldown / Window**：在硬冷却期内，禁止任何形式的 `auto` 真实发送。

## 7. Failure Philosophy (降级与故障哲学)

*   **Degrade vs Crash (宁可降级，绝不崩溃)**：如果关系更新出错，回退到旧状态；如果 Digest 主模型（free）失败，使用 Fallback 模型，双双失败则挂起压缩并使用原始超长上下文。
*   **Fallback 优先级**：在遇到非预期数据时（例如多模态解析报错），拦截错误并在 `debug_events` 中记录异常，但不可让整个 Chat Loop 宕机。

## 8. Debug System is Production System (可观测性即生产环境)

*   **禁止精简**：`/debug` 路由、`debug_events` 表、`test.html` 是 Neno 在低资源环境下核心的可观测设施，绝对不允许以“清理无用代码”为由删除。
*   **Trace ID 贯穿**：所有的行为（Chat、Proactive、Memory Decision）必须携带溯源的 `trace_id`，这维系着整个快照回放的生命线。

## 9. Critical Fragile Zones (高度脆弱区域)

在修改以下代码区域时，极易引发灾难级事故：

1.  **`session_aggregation_controller.py` & `session_submit_controller.py`**：进程级内存锁。异常如果不慎遗漏将导致永久死锁，阻断特定用户的所有交互。
2.  **`history_digest.py`**：Token 账房。修改压缩阈值或越界条件，将直接导致模型上下文溢出 (HTTP 400)。
3.  **`context_builder.py`**：任何对 List Append 顺序的调换，都会清零 API 缓存命中率。
4.  **`multimodal_input_service.py`**：边界。绝对禁止将原始 Image payload 直接送入 SQLite Message 表。

## 10. Single Point of Failure (系统级崩溃命门)

*   **命门模块**：`SessionSubmitController`。
*   **原因**：它是串行化所有外部网络并发请求的唯一关卡。如果系统变为多实例部署或该模块中引发静默挂起，SQLite 锁竞争与对话时间线紊乱将瞬间摧毁所有的上下文逻辑与一致性。
