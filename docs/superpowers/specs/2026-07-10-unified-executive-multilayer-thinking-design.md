# Neno 统一主脑与多层思考设计

> 状态：第一版已实现（2026-07-10）；真人感仍需连续运行体感验收。
> 核心验收：不是“更聪明”，而是连续相处时更像一个有自己反应、会克制、能拍板的人。

## 1. 核心变化

当前聊天把主体性拆给了多个模型：选择层决定回不回，主聊天模型只写正文，世界模型决定生活行动。新架构把最终决定权收回主聊天模型。

主 LLM 是最高决策层；廉价模型只提供注意力分流和互相冲突的内心候选。后端负责验证、执行和记账，不替主 LLM 做人格决定。

## 2. 分层结构

```text
物理睡眠门
  -> TRIAGE（廉价参谋，只建议 shallow/deep，不得最终截断）
  -> 深路私有涌念（靠近 / 防备与疲惫 / 联想与好奇，独立并行）
  -> 主 LLM Executive（唯一拍板者）
       action: reply_now | defer | leave_unanswered
       response_points / max_chars / max_beats
       world_intents / memory_candidates / inner_reaction
  -> 工具与命令执行
  -> 隔离出口（同一主模型，只看裁决摘要、历史、声音样本和当前图片）
```

## 3. 权限边界

- TRIAGE 只决定是否值得运行深层思考，`should_respond` 只是建议。
- 三股涌念没有执行权，也不能直接进入用户可见回复。
- 主 LLM 对回、延后、不回应、回应重点和高层世界意图拥有最终决定权。
- `WorldLoop` 仍是 `life_world_state` 唯一物理世界写者。
- `action_validator` 可以拒绝不可能或非法的世界操作。
- 记忆候选只记录在决策快照，后续仍需记忆守门器审核。

## 4. 出口隔离

主脑裁决可以读取 `self_state_context`、关系、记忆和私有涌念；出口 prompt 不再读取这些原始块。

出口只接收：

- 可缓存 system + 历史；
- `voice_self` 真实语言样本；
- 主脑裁定的具体回应点、最大字数和最大拍数；
- 当前用户消息与当前图片。

因此世界状态只能影响她的取舍，不能被出口模型当作聊天素材主动汇报。

## 5. 世界命令

主脑产生的 `world_intents` 进入 append-only `executive_commands`。`WorldLoop` 在 LLM 路径中把它们作为“主脑已经决定的高层方向”交给世界规划器翻译成合法 `world_ops`；只有成功进入该次世界决策后才标记 consumed。

## 6. 降级

- TRIAGE 失败：按 shallow 建议继续，主脑仍拍板。
- 某股涌念失败：少一股继续；全部失败不阻断主脑。
- 主脑失败：退回现有正常回复行为，不无故沉默。
- 出口失败：退回现有 `generate_chat_reply`。
- 世界命令无法执行：保留失败原因，不直接修改世界。

## 7. 第一版范围

- 实现主脑 `ExecutiveDecision` 与解析。
- TRIAGE 增加 shallow/deep 建议，取消其最终沉默权。
- 深路运行三股私有涌念。
- 主脑决定 reply/defer/leave_unanswered。
- 输出层与原始世界状态物理隔离。
- 决策和世界意图写入 SQLite 审计表。
- `WorldLoop` 读取主脑世界意图并交给现有世界规划/校验链。

暂不实现额外的第三次“回环复看”模型调用；第一版用主脑给出的字数、拍数和回应点控制出口，避免单轮延迟继续膨胀。

## 8. 已落地模块

- `selection_layer.py`：TRIAGE 只给 `depth/emotion/should_respond` 建议。
- `inner_deliberation.py`：深路并行生成靠近、边界、联想三股私有涌念。
- `chat_executive.py`：主模型输出 `ExecutiveDecision`，当前图片以原始 image block 直接进入主脑。
- `context_builder.build_executive_output_messages`：隔离出口只见历史、声音样本、裁决面和当前输入。
- `executive_decisions` / `executive_commands`：追加式决策审计和世界命令队列。
- `WorldLoop`：queued 命令以 `directives` 交给 `WorldBrain`；真实世界 LLM 成功接收后才标记 consumed，所有 `world_ops` 仍过 validator。
- pending 到期只触发重新裁决；主脑仍可再次 defer 或永久 leave_unanswered。
- 若 pending 重考虑通道未启用，`defer` 会 fail-open 成正常回复，避免消息永久卡住。
