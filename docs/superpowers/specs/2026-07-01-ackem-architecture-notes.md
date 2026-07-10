# Ackem 架构调研笔记 · Neno 可借鉴项

> 状态：研究笔记，**非实现计划**。
> 调研对象：`JasonLiu0826/ackem`，HEAD `2bdacc0`（2026-06-30）。
> 目的：记录可借鉴的 memory（记忆）、extension（扩展）、search（搜索）和 desktop-agent（桌面代理）架构形状，供 Neno 后续设计使用。
> 红线：Ackem 为 AGPL-3.0；Neno 只能借鉴架构思想，**不得直接复制代码**。

## 1. 总体判断

Ackem 不是空壳。它是一套本地优先的 Electron 桌面 AI 伴侣，核心形状是：

```text
用户消息
  -> L0 事件解释
  -> L1 关系状态
  -> L2 情绪状态
  -> L3 psycheBlock
  -> L4 记忆检索
  -> prompt 组装
  -> LLM 回复
  -> 异步记忆写入 / 整理 / 索引刷新
```

对 Neno 有价值的主要不是它的“人格演绎”，而是它把记忆工程化得很完整：事实、情节、知识图谱、时间锚点、关联边、向量缓存、主动避让、异步写入队列，都有明确边界。

## 2. 最值得借鉴的记忆结构

Ackem 的记忆不是单一 `memories` 表，而是多层：

- `memory_facts`：结构化事实。字段包含 `domain`、`subcategory`、`subject`、`summary`、`weight`、`confidence`、`status`、`emotional_context`、`self_relevance`、`triggers`、`tier`、`sensitivity`、`privacy_level`。
- `episodes`：情节记忆。按多轮对话提炼片段，记录情绪强度、关键词、起止 turn。
- `knowledge_triples`：知识图谱三元组。
- `memory_associations`：事实之间的弱关联边，支持一跳联想。
- `temporal_anchors`：生日、纪念日、模糊时间、周期性事件。
- `fact_embeddings` / FTS5：向量与全文检索派生索引。

Neno 可借的最小形状：

```text
memories              现有具体事实 / 偏好 / 边界
memory_links          新增：memory_id_a, memory_id_b, type, strength, last_activated_at
memory_sensitivity    可并入 memories：normal | avoid | private
memory_trace          继续走 debug_events / metadata_json，不另建黑盒
```

不要一口气照搬完整 facts/episodes/kg/anchors。Neno 的低资源约束更重，第一步只需要“关联边 + 主动避让”。

## 3. 检索管线可借鉴项

Ackem 的 `MemoryRetriever` 做了多路召回：

1. 触发词匹配。
2. 核心记忆优先。
3. FTS5 全文检索。
4. 语义 / Jaccard 检索。
5. embedding（嵌入向量）检索。
6. TF-IDF fallback（兜底）。
7. 时间语义和时间锚点。
8. 关联图一跳扩散。
9. 统一预算裁剪后组装 `Tier B`。

对 Neno 最有用的是“多路召回后统一预算”，不是具体算法。Neno 可以把未来记忆注入改成：

```text
候选来源：
  - exact / keyword
  - recency
  - relationship / boundary
  - linked memories
  - optional embedding

统一排序：
  score = relevance * confidence * boundary_priority * decay * current_need

统一预算：
  先放硬边界，再放用户偏好，再放关联事实，最后放弱背景。
```

这能避免现在常见的“某一路检索独占 prompt 空间”。但必须守住 `context_builder.py` 的缓存顺序：动态记忆仍只能放在历史之后，不能上移到 system 前缀。

## 4. 关联边：最适合 Neno 的第一块

Ackem 的 `memory_associations` 不是大知识图谱，而是轻量联想边：

```text
fact_id_a
fact_id_b
association_type: temporal | entity | event_chain | emotion_peak | self_reference | thematic
strength
created_at
last_activated_at
```

Neno 可简化为：

```text
memory_id_a
memory_id_b
kind: same_topic | caused_by | emotional_echo | user_boundary | recurring
strength: 0..1
last_activated_at
```

使用方式：

- 检索到 A 时，最多扩散 1 跳找 B。
- 只把强度高、且不为 `avoid` 的 B 纳入候选。
- 扩散结果要在 metadata/debug 里留痕，方便回放“为什么想起这条”。
- 不允许扩散结果绕过 memory 的边界和优先级。

这特别适合 Neno 的“会想起，但不一定说”。关联边可以喂给 triage（分流）或内心层，而不一定喂给出口层。

## 5. 主动避让：比删除更重要

Ackem 有 `sensitivity: avoid` 的思路：用户表达“不想聊 / 别提 / 换话题”后，相关事实不一定删除，而是标记为避让。

Neno 可借：

```text
normal   可以正常检索和注入
avoid    可以内部识别，但默认不注入出口
private  只用于安全/边界判断，不进入普通回复
```

这比“忘掉”更符合陪伴系统：她不是失忆，而是记得“这个不能乱提”。它也贴合多层思考设计里的“咽回”：内心知道，出口不说。

## 6. 写入管线：后置、串行、失败不阻断

Ackem 的记忆写入是后台 job，并按 session 串行排队：

```text
主回复完成
  -> enqueueMemoryWrite(session)
  -> 同 session promise chain
  -> LLM 抽取 / 轻量规则 / episode / kg / association
  -> finalizeNewFacts 刷新索引和通知 UI
```

Neno 已有更严格的 Session 串行模型，不能直接搬异步形状。但可借原则：

- 回复生成优先，不让记忆整理阻断聊天。
- 同 session 的记忆后处理必须有顺序。
- 记忆写入失败只记录 `debug_events`，不能炸主流程。
- 新记忆仍遵守 1-turn lag（下一轮才生效）。

如果以后增强记忆写入，建议做成 `post_turn_memory_job`，由 `SessionSubmitController` 之后排队，且写入结果进 metadata/debug 可观测链路。

## 7. Embedding 降级链

Ackem 的 embedding provider（嵌入提供器）优先级：

```text
本地 ONNX
  -> 远程 OpenAI-compatible embedding API
  -> noop fallback / TF-IDF
```

这符合 Neno 的生存哲学：能力不可用时降级，而不是阻断聊天。

Neno 如接 embedding，应满足：

- 默认关闭或低频启用，避免 VPS 内存爆。
- 本地不可用时直接退回关键词/FTS。
- embedding 只影响候选排序，不成为唯一检索路径。
- 派生索引可重建，不能成为唯一真相源。

## 8. 扩展边界：EngineSnapshot 很值得借

Ackem 的扩展系统有一个好边界：扩展只能读取 `EngineSnapshot`，通过事件回传，不能直接 import engine/memory 内部。

Neno 可借这个协议形状：

```text
NenoSnapshot:
  - current session id
  - recent state summary
  - relationship summary
  - memory counts / selected safe facts
  - world read-only summary
  - capability flags

ExtensionEvent:
  - source
  - type
  - payload
  - context_injection?
  - trace_id
```

这适合未来做：

- 网页搜索。
- MCP 工具。
- Android / phone-agent 能力。
- 桌面或手机传感能力。

关键是扩展不能直接写 Neno 的权威状态，只能产出事件或候选注入，由核心网守决定是否采用。

## 9. 网页搜索：不一定要 MCP

Ackem 的 web-search 是内置 skill，通过 dispatch 判断何时触发，默认 Bing HTML，支持 SearXNG。

对 Neno 的启发：

- 如果搜索只服务 Neno 自己，内置 `tool` + 权限边界比 MCP 轻。
- 如果搜索要给 Claude Code、桌面端、多客户端共用，MCP 更合适。
- 无论哪种，都要有 dispatch 条件，不能每轮搜索。

建议的 Neno 形状：

```text
search intent detector
  -> permission gate
  -> provider adapter: searxng | tavily | brave | bing
  -> normalized results
  -> source-cited context block
  -> debug trace
```

## 10. 分波回复：可参考但要小心

Ackem 有 wave chat：第一波快速回复，后续波等待延迟检索 enrich，再继续输出。这个在桌面伴侣里很有生命感。

但 Neno 当前有 burst 聚合、split 降级、wx 测试切分和 session 串行红线。不能直接引入“多 wave LLM 调用”。可借的只有：

- 第一拍轻，后续是否加深由 triage 决定。
- 延迟检索可以作为“深路”能力，不影响浅路。
- 每一拍都必须能被 trace/debug 回放。

这和 2026-06-28 多层思考设计里的“浅 / 深路径”是相容的。

## 11. 不适合 Neno 直接借的部分

- `psycheBlock` 直灌 prompt：Ackem 会把“情绪基调、态度倾向、回复长度”显式交给 LLM 演。Neno 现在要的是出口层物理隔离，不能学。
- 动态块进 system 前部：Neno 的 Anthropic cache（缓存）经济学不允许。
- 大规模 facts/episodes/kg 一次性落地：Neno VPS 资源更紧，先做轻量 linked memory。
- 成人模式相关情绪反转逻辑：与 Neno 当前目标无关。
- AGPL 代码实现：只能参考思想，不能复制。

## 12. 建议后续拆成三小步

**A. 记忆关联与避让**

- 给现有 memory 增加 `sensitivity` 或等价字段。
- 新增轻量 `memory_links`。
- 检索时支持一跳扩散，但默认只喂内心/triage。

**B. 统一检索预算**

- 把硬边界、偏好、近期、关联事实放入统一候选列表。
- 明确每类候选的优先级和预算。
- metadata 记录最终入选原因。

**C. 扩展快照协议**

- 定义只读 `NenoSnapshot`。
- 搜索/MCP/phone-agent 只能通过事件或候选注入回核心。
- 所有外部能力必须带权限和 trace。

## 13. 和多层思考设计的关系

Ackem 的可借鉴项应服务于 Neno 的“厚底子、薄出口”：

- 记忆关联让底子更厚。
- `avoid` 让出口更会闭嘴。
- 统一预算让出口不被无关记忆淹没。
- Snapshot + Event 让外部能力不破坏核心状态。
- memoryEcho 类思路可以喂 triage / 内心层，但不能以状态字段形式泄漏给出口。

一句话：**借 Ackem 的记忆工程，不借 Ackem 的人格表演。**
