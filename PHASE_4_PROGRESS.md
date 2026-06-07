# Phase 4 当前进度

> 快照日期：2026-06-07  
> 权威架构与运行说明：`docs/living-world.md`  
> 本文件只记录当前交接状态，不作为实现规格。

## 1. 用户目标

Neno 应在一个持续存在的虚拟现实中生活。世界不围绕聊天临时生成；
时间、环境、物品、精力、情绪、记忆、计划和未完成事务持续演化。
用户消息后续作为外部事件进入该世界，再决定回复、不回复、延迟或多段回复。

## 2. 已实现

### 经历与意识闭环

- `ExperienceRecorder`、`inner_experience_log` 和 `dream_reflection_runs`。
- `LifeState`、`life_residue`、StateStore 回注。
- Brain 未表达经历沉淀。
- ReflectionEngine 读取 experiences 与 activity episodes，写入 residue 和长期记忆。

### 连续生活线

- `life_activity_episodes` 与 `ActivityEpisodeStore`。
- `LifeSimulation` 的 create / continue / transition / interrupt。
- LifeLoop 接入 episode、MicroEvent、dry-run 和失败降级。
- ReflectionEngine 可总结当天生活线。

### 可运行世界

- `virtual_world.json`：卧室、厨房、客厅、阳台和 15 个初始物品。
- `WorldState`：位置、物品状态、模拟时间、金钱、动态物品、移除记录、计划和最近行动。
- `WorldStore`：`life_world_state` 单行 SQLite 持久化。
- `world_drift`：水壶降温、植物缺水等自然变化。
- `action_validator`：状态、位置、预算、创建和销毁守门。
- `WorldBrain`：真实 LLM 决策与确定性 fallback。
- `DailyPlanner`、`DayCycle`、`LifeEventSource`。
- `WorldLoop`：融合世界、意识、记忆、计划、事件、行动、经历、精力、情绪和跨天反思。

### 应用接入与观测

- `ConsciousnessEngine.start()` 已调用 `WorldLoop.register_jobs()`。
- `CONSCIOUSNESS_WORLD_LOOP_ENABLED` 默认关闭，开启后注册常驻 tick。
- `GET /debug/consciousness/world-live` 返回只读世界快照。
- `POST /debug/consciousness/world-tick` 手动推进正式世界循环。
- 控制台展示时间、房间、物品、计划、事件、钱包、精力和情绪。

## 3. 尚未达到完整目标

- 世界仍局限于小公寓，长期事务、习惯、目标和复杂资源关系较浅。
- `LifeEventSource` 尚未严格执行每日事件上限。
- 旧 LifeLoop/LifeSimulation 与新 WorldLoop 尚未完全收敛为单一生活推进模型。
- `scripts/world_live_server.py` 仍保留独立循环，与正式 WorldLoop 有分叉风险。
- 日计划完成判定和长期因果仍偏简单。
- 用户消息尚未作为世界事件接入；Phase 5 未开始。

所以当前状态是：

> 已有可写库、可跨天、可接真实模型、可常驻运行的公寓世界引擎纵向实现；
> 尚未通过用户目标意义上的“完整虚拟生活”验收。

## 4. 工作区与验证状态

- 当前世界引擎、测试和文档改动均未 commit、未 push。
- 六个红线文件没有 diff。
- `.codegraphcontext/codegraph.kuzu` 是本地索引变化，不应进入功能提交。
- 2026-06-07 综合回归：`222 passed, 3 failed`。
  - 两个旧 LifeLoop 测试仍限制旧 activity 集合。
  - 一个 world-live 集成测试假定运行配置必为关闭，但应用加载 `.env` 后实际可能开启。

## 5. 下一步顺序

1. 修复三条测试并隔离 `.env` 对测试的影响。
2. 让 `scripts/world_live_server.py` 复用正式 `WorldLoop`。
3. 为生活事件增加按模拟日计数与上限。
4. 明确旧 LifeLoop 与新 WorldLoop 的状态所有权并逐步收敛。
5. 进行连续多日模拟，检查因果延续、非重复性、资源与计划变化。
6. 上述生活验收稳定后，再设计 Phase 5 用户消息事件化。

## 6. 红线

禁止修改：

- `app/services/session_submit_controller.py`
- `app/services/session_aggregation_controller.py`
- `app/services/chat/context_builder.py`
- `app/services/chat_service.py`
- `app/services/proactive/rules.py`
- `app/services/chat/history_digest.py`

保持单机 SQLite；不新增发送链路；真实模型和常驻写入能力必须有独立开关。
