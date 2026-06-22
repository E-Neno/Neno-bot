# Living World 竖切5「融合意识 + 完整的一天」实现计划

> **历史实施记录。** 当前实现已经接入正式 `WorldLoop` 与应用 scheduler；
> 现状、运行开关和未完成项见 `docs/living-world.md`。

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）。
>
> **执行节奏沿用竖切1/3：TDD（先写失败测试）→ 确定性部分钉死测试 → LLM 全程 mock，零真实调用进测试套件 → 每个任务后跑给用户肉眼看。不 commit、不碰红线。**

**目标：** 把已存在但"断电"的意识层（StateStore / ExperienceRecorder / ActivityEpisodeStore / MemoryRecall / ReflectionEngine）与世界引擎（竖切1/3）焊通，并补上每日计划、加权记忆、睡眠/醒来/跨天结算，让 Neno 过"有记忆、有计划、有心情、跨天延续"的一整天，绕圈消失。

**架构：** 世界 tick 升级为"融合 tick"：读 世界状态 + 内在状态(energy/mood/residue) + 加权记忆 + 当日计划 + 时段 → WorldBrain 决策 → 校验执行 → 写回世界 + 写 episode/经历 + 反馈 mood/energy。新增 daily_planner（晨间计划）与 day_cycle（睡眠/醒来/跨天结算，醒来时跑 ReflectionEngine 沉淀昨天）。全部复用现成意识层组件。

**技术栈：** Python 3.11 / Pydantic v2 / SQLite / pytest / OpenRouter(gpt-4o-mini，用户已授权，默认开关关)。

---

## 0. 硬约束（覆盖 skill 默认，必须遵守）

- **不接聊天、不碰红线**：本刀只焊"世界引擎 ↔ 意识层"。`context_builder.py` 等 6 个红线文件一字不动。"生活流进对话"是后续独立刀。
- **不 commit / 不 push**：commit 步骤一律替换为"验证检查点"。
- **真实模型默认关**：`world_llm_enabled` / `world_planner_enabled` 默认 False；测试用 mock，零真实调用。用户已授权实时演示开真实模型。
- **复用优先**：禁止重写 StateStore/ExperienceRecorder/ActivityEpisodeStore/MemoryRecall/ReflectionEngine；只调用与轻量增强。
- **单机 SQLite**：不引入新依赖、不引入队列/新库。
- **不注册生产 scheduler、不接 LifeLoop 主链路**：融合 tick 跑在独立演示服务器里（沿用 `world_live_server.py`），不进 `app.main`。
- **不新增表**：记忆复用 `inner_experience_log` / `life_activity_episodes` / `long_term_memory`；当日计划与"最近行动"存进已放行的 `life_world_state`（JSON 字段扩展，不加表）。

---

## 1. 反作弊验收契约（"看着过一天"，人可逐条勾）

跑加速整天演示（`python scripts/world_live_server.py`，开 `CONSCIOUSNESS_WORLD_LLM_ENABLED=1 CONSCIOUSNESS_WORLD_PLANNER_ENABLED=1`），在 `localhost:8777` 肉眼勾：

- [ ] **有计划**：晨间生成结构化当日计划（上午/下午/晚上各一条意图），页面可见。
- [ ] **不绕圈**：连续 ≥20 个 tick 内，不出现"倒水→洗杯→倒水"这类两步循环重复 ≥3 次；行动推进而非原地打转。（记忆生效的硬证据）
- [ ] **记忆可见**：决策理由中至少出现一次对"刚做过/今天做过"的引用（如"已经读过一会了"）。
- [ ] **内在状态驱动**：精力随时间下降；出现至少一次"低精力/坏心情 → 选择休息或安抚而非生产性活动"的决策（不再永远勤劳）。
- [ ] **会睡觉**：夜间时段精力耗尽 → 进入 sleeping，tick 期间不再活动。
- [ ] **会醒来 + 反思**：次日晨起，`dream_reflection_runs` 新增一条 completed；`long_term_memory` 新增昨天的沉淀。
- [ ] **跨天延续**：次日计划或 residue 引用到"昨天未完成的事"（如书没读完）。
- [ ] **守门仍在**：故意/自然产生的非法 op 被拒，世界不被污染。
- [ ] **降级有效**：断网/坏 JSON 时，决策降级到 mock，演示不崩。

**反作弊条款（审查逐条抓）：**
- [ ] 禁止 placeholder / stub / "后续实现"；`day_cycle` 不得是空函数。
- [ ] 记忆必须真的写入 `inner_experience_log`/`life_activity_episodes` 并真的被读回喂进 prompt（测试断言 prompt 含记忆内容）。
- [ ] 跨天结算必须真的调用 ReflectionEngine 并真的写 `long_term_memory`（测试断言行数增加）。
- [ ] 精力/情绪反馈必须真的 submit_mutation 改 StateStore（测试断言 revision/值变化）。
- [ ] 测试断言**状态/记忆的实际变化值**，不得只断言函数被调用或 success=True。

---

## 2. 复用 vs 新建 vs 增强

| 组件 | 处理 | 说明 |
|---|---|---|
| `StateStore` | 复用 | `read()→NenoState`；`submit_mutation(StateMutation)` 反馈情绪/精力 |
| `ExperienceRecorder` | 复用 | 每 tick 写 `InnerExperienceIn(source="life_world", ...)` |
| `ActivityEpisodeStore` | 复用 | tick 创建/延续/结束 episode（已有 start/continue/end） |
| `MemoryRecall` | 增强 | 新增加权检索 `recall_weighted()`（新近×重要×相关） |
| `ReflectionEngine` | 复用 | 醒来时 `run_once(_target_day=昨天)` 沉淀长期记忆 |
| `WorldBrain` | 增强 | prompt 纳入 状态+记忆+计划+时段 |
| `world_store` / `life_world_state` | 增强 | JSON 扩展：`recent_actions`、`daily_plan`、`sim_clock` |
| `daily_planner.py` | 新建 | 晨间结构化计划（LLM，mock fallback） |
| `day_cycle.py` | 新建 | 时段判定 + 睡眠/醒来/跨天结算 |
| `world_live_server.py` | 增强 | 融合 tick + 加速整天 + 展示计划/精力/心情/记忆 |

---

## 3. 融合 tick 主循环（脊柱，伪代码锁定逻辑）

```
fused_tick(sim_clock):
  phase = day_cycle.phase_of(sim_clock)            # morning/afternoon/evening/night
  nstate = await state_store.read()                # energy/mood/residue

  # 1. 睡眠/醒来生命周期
  transition = day_cycle.check_sleep_wake(nstate, phase, sim_clock)
  if transition == "fall_asleep":
      await day_cycle.on_sleep(state_store)         # energy.status=sleeping
      return snapshot(sleeping=True)
  if transition == "wake_up":
      await day_cycle.on_wake(state_store, reflection_engine, world_store, sim_clock)
      # → 反思昨天 + 沉淀长期记忆 + 生成今日计划 + 残留/未完成跨天
  if nstate.energy.status == "sleeping":
      return snapshot(sleeping=True)                # 睡着就不活动

  # 2. 世界漂移（竖切1）
  world, drift = apply_drift(world_def, world, elapsed, cfg)

  # 3. 取上下文：加权记忆 + 当日计划 + 内在状态
  plan = world_store.get_daily_plan()              # 晨间已生成
  memories = await recall.recall_weighted(query=ctx_query(world,phase), now=sim_clock)
  recent = world_store.get_recent_actions()        # 最近 ~8 步，防绕圈

  # 4. 决策（WorldBrain，prompt 纳入以上全部）
  plan_obj = await brain.decide(world, nstate=nstate, phase=phase,
                                plan=plan, memories=memories, recent=recent)

  # 5. 校验 + 执行（竖切1）
  world, op_log = execute_validated(world_def, world, plan_obj.world_ops)

  # 6. 落账 + 写记忆 + 反馈内在状态
  world_store.push_recent_action(plan_obj.action, sim_clock)
  await world_store.write(world)
  await episode_store...                            # 创建/延续 episode
  await recorder.record(InnerExperienceIn(source="life_world",
                          content=plan_obj.micro_event or plan_obj.action, ...))
  await state_store.submit_mutation(StateMutation(
      energy=decremented_energy(nstate, phase),
      mood_valence_delta=mood_feedback(plan_obj),
      reason="life_world tick"))
```

---

## 任务 1：加权记忆检索 `recall_weighted`

**文件：** 增强 `app/services/consciousness/memory_recall.py`；测试 `tests/unit/test_memory_recall_weighted.py`

打分：`score = relevance*0.5 + importance*0.3 + recency*0.2`
- relevance：query 关键词与 content/tags 命中数归一化（复用现有 `_tokenize`）
- importance：`salience`（已有列）
- recency：`exp(-Δhours / 24)`，Δ 用 `now - created_at`

- [ ] **步骤1：失败测试**（断言"更相关+更近"的记忆排在前；空 query 返回 []；DB 异常返回 []）

```python
def test_weighted_prefers_relevant_recent(tmp_db):
    # 插 3 条 long_term_memory：A(相关,旧) B(相关,新) C(不相关,新)
    # 期望顺序 B 在 A 前；C 不在前两名
    ...
```

- [ ] **步骤2：跑测试确认 FAIL**（`recall_weighted` 不存在）
- [ ] **步骤3：实现 `recall_weighted(self, query, now, top_k=None) -> list[dict]`**
  - 取候选（关键词 OR 命中，放宽 LIMIT 到 top_k*4），在 Python 内按 score 排序取 top_k；返回 `[{content,score,created_at}]`；失败返回 []。
- [ ] **步骤4：跑测试确认 PASS**
- [ ] **步骤5：验证检查点（不 commit）**

---

## 任务 2：晨间每日计划 `daily_planner.py`

**文件：** 新建 `app/services/consciousness/daily_planner.py`；测试 `tests/unit/test_daily_planner.py`

模型（加进 world_model 或本文件）：
```python
class DayPlanItem(BaseModel):
    phase: str          # morning/afternoon/evening
    intent: str         # 一句话意图
    done: bool = False

class DailyPlan(BaseModel):
    date: str
    items: list[DayPlanItem] = Field(default_factory=list)
    carried_over: list[str] = Field(default_factory=list)  # 昨天未完成
```

`DailyPlanner.make_plan(*, nstate, residue, carried_over, world_def) -> DailyPlan`
- `world_planner_enabled=True` → LLM 生成 3 条 phase 意图（system prompt 给出可用房间/物品 + 昨天残留 + 未完成事务），解析 JSON，失败降级。
- False/失败 → 确定性 mock 计划（morning:读书 / afternoon:收拾 / evening:休息），并把 carried_over 原样带入。

- [ ] **步骤1：失败测试**
  - LLM 关闭 → mock 计划 3 条且含 carried_over；
  - LLM 开（patch chat_with_openrouter 返回 JSON）→ 解析出 3 条 items；
  - LLM 坏输出 → 降级 mock，不抛。
- [ ] **步骤2：FAIL** → **步骤3：实现** → **步骤4：PASS** → **步骤5：检查点**

---

## 任务 3：WorldBrain 决策纳入 状态/记忆/计划/时段

**文件：** 增强 `app/services/consciousness/world_brain.py`；测试 `tests/unit/test_world_brain.py`（追加）

`decide()` 增参（全部可选，保持向后兼容竖切1/3 测试）：
```python
async def decide(self, state, *, nstate=None, phase="", plan=None,
                 memories=None, recent=None) -> ActionPlan
```
`_build_user_message` 追加分段：
```
[时段] {phase}
[精力] {energy.value}/100（{status}）   [心情] {mood.label}（valence={valence}）
[今日计划] morning: ...; afternoon: ...; evening: ...
[最近做过] 倒水(10min前) / 洗杯子(5min前) ...   ← 防绕圈
[可能想起] {memories[].content}              ← 加权记忆
```
system prompt 追加："参考你的精力与心情决定强度；别重复刚做过的事；尽量推进今天的计划。"

- [ ] **步骤1：失败测试**：构造 recent=[倒水], memories=[读过书], plan，patch LLM，断言**传给 chat_with_openrouter 的 messages 文本里包含** "倒水"、"读过书"、计划意图、精力数值。（用 `mock_call.call_args` 取 messages 断言）
- [ ] **步骤2：FAIL** → **步骤3：实现 prompt 拼接** → **步骤4：PASS（含竖切3 旧 6 测试不回归）** → **步骤5：检查点**

---

## 任务 4：时段 + 睡眠/醒来/跨天 `day_cycle.py`

**文件：** 新建 `app/services/consciousness/day_cycle.py`；测试 `tests/unit/test_day_cycle.py`

```python
def phase_of(hour: int) -> str:           # 5-11 morning,11-17 afternoon,17-22 evening,else night
def check_sleep_wake(nstate, phase, hour) -> str | None:  # "fall_asleep"/"wake_up"/None
    # 夜间且 energy<阈值 且 awake -> fall_asleep
    # morning 且 sleeping -> wake_up

async def on_sleep(state_store): ...       # energy.status=sleeping, 记一条经历
async def on_wake(state_store, reflection_engine, world_store, sim_date):
    # 1. reflection_engine.run_once(_target_day=昨天)  → 写 long_term_memory（复用 C1.5）
    # 2. 收集未完成：昨天 plan 里 done=False 的 items → carried_over
    # 3. daily_planner.make_plan(...) 写入 world_store 当日计划
    # 4. energy.status=awake, energy.value=wake_value
```

- [ ] **步骤1：失败测试**
  - `phase_of` 边界（5→morning,23→night）；
  - 夜间低精力 → fall_asleep；晨间 sleeping → wake_up；
  - `on_wake`：插入昨天 episodes → 调 on_wake → 断言 `dream_reflection_runs` +1 且 `long_term_memory` 增加 且 world_store 有了当日计划 且 energy 恢复 awake；
  - 昨天 plan 有未完成项 → carried_over 出现在新计划。
- [ ] **步骤2：FAIL** → **步骤3：实现** → **步骤4：PASS** → **步骤5：检查点**

---

## 任务 5：融合 tick 接入实时演示 + 可视化升级

**文件：** 增强 `scripts/world_live_server.py`；新增/扩展 `world_store` 的 `recent_actions`/`daily_plan`/`sim_clock` JSON 字段读写（不加表）

- 加速时钟：每 real tick 推进 sim 时间 N 分钟（演示 N≈30，约几分钟跑完一天）。
- tick 调用第 3 节融合循环（睡眠/醒来/漂移/记忆/计划/决策/执行/反馈）。
- 页面新增：当日计划三条（done 打勾）、精力条、心情、最近行动列表、"此刻想起"的记忆、睡眠遮罩（夜间显示"💤 睡着了"）。
- [ ] **步骤1：world_store 扩展读写**（`get/push_recent_action`、`get/set_daily_plan`、`get/advance_sim_clock`）+ 单测（持久、上限截断 recent 到 ~8）。
- [ ] **步骤2：实现融合 tick**（替换现 demo_decide 路径，LLM 关时仍用 mock + 计划/记忆/状态注入，保证不调真实模型也能跑）。
- [ ] **步骤3：页面渲染升级**（计划/精力/心情/记忆/睡眠遮罩）。
- [ ] **步骤4：启动加速整天演示，对照第 1 节"看着过一天"逐条勾。**
- [ ] **步骤5：全量回归 + 红线检查（不 commit）**

```bash
pytest tests/unit/test_world_model.py tests/unit/test_world_store.py \
       tests/unit/test_world_drift.py tests/unit/test_action_validator.py \
       tests/unit/test_world_brain.py tests/unit/test_memory_recall_weighted.py \
       tests/unit/test_daily_planner.py tests/unit/test_day_cycle.py -v
pytest tests/unit/test_brain.py tests/unit/test_state_store.py \
       tests/unit/test_reflection_engine.py tests/unit/test_activity_episode_store.py -v
git diff --name-only -- app/services/session_submit_controller.py \
  app/services/session_aggregation_controller.py app/services/chat/context_builder.py \
  app/services/chat_service.py app/services/proactive/rules.py app/services/chat/history_digest.py
```
预期：新测试全过；现有回归不回归（注意 test_reflection_engine 的 2 个 UTC+8 凌晨 flaky 与本刀无关）；红线 diff 空。

---

## 4. 自检

**规格覆盖：** 记忆(任务1)、计划(任务2)、状态/记忆/计划入决策(任务3)、时段+睡眠醒来跨天反思(任务4)、融合+可视化+整天验收(任务5)——"融合意识+完整一天"全覆盖。开放世界(买/摔)、长期记忆向量化、接入聊天 明确不在本刀。

**占位符扫描：** 各任务均有具体签名+核心算法+测试；`day_cycle.on_wake` 实打实调 ReflectionEngine 并写库，非空函数。

**类型一致性：** `DailyPlan/DayPlanItem` 任务2定义、任务4/5引用；`recall_weighted` 返回 `list[dict]` 任务1定义、任务3消费；`decide()` 新签名任务3定义、任务5调用；`phase_of/check_sleep_wake/on_wake` 任务4定义、任务5调用。一致。

---

## 5. 执行交接

计划已归档到 `docs/archive/superpowers-plans/2026-06-07-living-world-slice5-fusion.md`。

执行方式：**CC 内联执行（superpowers:executing-plans）**，按任务1→5，每任务后跑给用户肉眼看；确定性部分钉测试，LLM 全程 mock，最后用真实模型跑"看着过一天"验收。竖切2（开放世界）与"接入聊天"为后续独立计划。
