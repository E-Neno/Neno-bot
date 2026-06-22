# Living World 竖切6「意外 · 情绪 · 开放世界」实现计划

> **历史实施记录。** 本文描述该 slice 的设计意图，不代表当前验收状态；
> 当前能力和已知缺口见 `docs/living-world.md`。

> **工作者：** 用 superpowers:executing-plans 逐任务执行；复选框跟踪。沿用 slice1/3/5 节奏：TDD → 确定性钉测试 → LLM 全程 mock（测试零真实调用）→ 每任务跑给用户肉眼看。

**目标：** 打破单调。让事情发生在 Neno 身上（意外事件）、让事件真正改变她的心情、让心情改变她的行为，并让世界会"长出/失去"东西（买/摔/扔，跨天惦记）。

**架构：** tick 在决策前注入低频"生活事件"（天气/消息/渴望/旧事浮现/物品损坏），事件带 mood_impact 与可选 world_op；事件 → 改世界 + 改情绪；情绪进 brain prompt 影响决策。开放世界：WorldState 承载动态物品/金钱/已弃物（gone_log），新增 create_object/destroy_object 两个 world_op，经守门（类别白名单/预算/容量/存在性）后落账。gone_log + money 进 prompt → 跨天惦记与购买。

**技术栈：** Python 3.11 / Pydantic v2 / SQLite / pytest / 复用 random_events、perception(weather)、OpenRouter(默认关)。

---

## 0. 硬约束
- 不接聊天、不碰 6 个红线文件；不 commit；真实模型默认关，测试 mock；单机 SQLite；不新增表（动态物品/金钱/gone_log 存进 life_world_state 的 JSON）。
- 事件低频：每天 ≤ ~3 件，避免"随机事件泛滥"（PHASE 文档明令禁止）。
- 守门优先：LLM 越权（造不存在物品/超预算/超容量）一律拒绝并降级，世界不被污染。

---

## 1. 反作弊验收契约（"看着更丰富的一天"，逐条勾）
- [ ] **有意外**：一天内出现 ≥1 个非她计划的事件（如"窗外下雨""手机来消息""想起一件旧事""杯子磕了一下"），页面横幅可见。
- [ ] **情绪波动**：mood valence 在一天内有可见起伏（事件造成 ±），不是恒定。
- [ ] **情绪改行为**：出现 ≥1 次"坏心情/低落 → 选择安抚/休息/不做计划内的事"，与好心情时的选择不同。
- [ ] **会买**：出现 create_object（如买花/买新杯子），money 扣减，新物品在房间里渲染出来。
- [ ] **会失去**：出现 destroy_object（摔碎扔掉/花枯死扔掉），物品从房间消失并进 gone_log。
- [ ] **跨天惦记**：次日计划或决策理由引用 gone_log 里失去的东西（"想再买个杯子"）。
- [ ] **守门有效**：越权 op（造不存在类别/超预算/不存在物品）被拒，世界未变。
- [ ] **不泛滥**：单日事件数 ≤ ~3；不刷屏。
- [ ] **降级有效**：LLM 关闭时（mock）整套仍能跑、不崩；真实模型异常时降级。

**反作弊条款：** 禁 placeholder；事件必须真的改 world/mood（测试断言实际值变化）；create/destroy 必须真的增删 object_states 与 gone_log（测试断言行/键变化与 money 变化）；守门拒绝路径必须有测试且断言世界未变。

---

## 2. 数据模型扩展（world_model.py / WorldState）
```python
# WorldState 新增（旧 JSON 缺失自动补默认）
money: int = 120
dyn_objects: dict[str, dict] = {}     # {name: {"category","room","label"}} 买来的动态物品
removed: list[str] = []               # 被扔掉的"静态"物品 key（渲染时跳过）
gone_log: list[dict] = []             # [{"object","label","cause","when"}]

# 新 WorldOp 类型：扩展 Literal
WorldOpType = Literal["set_state","move","create_object","destroy_object"]
# WorldOp 新增可选字段：category, room, label, cost, cause
```
**统一访问器（world_model.py，静态+动态+removed 一起算）：**
```python
def obj_exists(wd, state, name) -> bool
def obj_category(wd, state, name) -> str | None
def obj_room(wd, state, name) -> str | None
def legal_states_of(wd, state, name) -> list[str]
def objects_in_room(wd, state, room) -> list[str]   # 含动态、排除 removed
def room_count(wd, state, room) -> int              # 容量判断
```
`apply_op` 扩展：
- create_object：dyn_objects[name]={category,room,label}；object_states[name]=该类别 default；money-=cost。
- destroy_object：从 object_states 删；动态则删 dyn_objects，静态则加入 removed；追加 gone_log。

---

## 任务 1：生活事件系统 `life_events.py`
**文件：** 新建 `app/services/consciousness/life_events.py`；测试 `tests/unit/test_life_events.py`
```python
class LifeEvent(BaseModel):
    kind: str            # weather/message/craving/memory/mishap
    content: str         # 一句话描述
    mood_delta: float    # -0.3 ~ +0.3
    world_op: WorldOp | None = None   # 可选：如 phone->has_unread, mug->broken

class LifeEventSource:
    def __init__(self, config): ...
    def maybe_emit(self, *, world_state, nstate, phase, rng) -> LifeEvent | None:
        # 低频（每 tick 小概率，且全天有上限）。确定性可测：传入 rng（random.Random(seed)）。
        # 事件从 世界/状态/时段 派生，不是纯随机文案：
        #   - 天气：phase=morning 偶发"窗外下雨"→ window set dim, mood -0.05
        #   - 消息：偶发"手机震了一下"→ phone has_unread, mood +0.05
        #   - 渴望：need/精力低 → "突然很想喝点甜的", mood -0.0
        #   - 旧事：gone_log 非空 → "想起扔掉的那个杯子", mood -0.1
        #   - 小意外：低概率"杯子磕了一下"→ mug set broken, mood -0.15
```
- [ ] 步骤1 失败测试：固定 seed 的 rng 下，maybe_emit 在给定条件产出预期 kind/world_op/mood_delta；高 seed 多数 tick 返回 None（低频）；gone_log 非空时可产"memory"事件。
- [ ] 步骤2 FAIL → 步骤3 实现 → 步骤4 PASS → 步骤5 检查点。

---

## 任务 2：开放世界模型（动态物品/金钱/弃置）
**文件：** 增强 `world_model.py`；测试 `tests/unit/test_world_open.py`
- [ ] 失败测试：WorldState 新字段默认；create_object 后 obj_exists/obj_room/legal_states_of 正确、money 扣减、object_states 有默认态；destroy_object 后物品从 objects_in_room 消失、gone_log +1（静态进 removed、动态删 dyn_objects）；objects_in_room 含动态排除 removed。
- [ ] FAIL → 实现访问器 + apply_op 扩展 → PASS → 检查点。

---

## 任务 3：守门扩展 `action_validator.py`
**文件：** 增强 `action_validator.py`；测试 `tests/unit/test_action_validator.py`（追加）
- [ ] 失败测试（逐条断言拒因，且世界未变）：
  - create_object：类别不在白名单→reject(unknown_category)；name 已存在→reject(object_exists)；room 不存在→reject(unknown_room)；cost>money→reject(insufficient_funds)；房间超容量(>cap)→reject(room_full)；合法→accept。
  - destroy_object：物品不存在→reject(unknown_object)；合法→accept。
  - set_state/move 旧用例不回归（含对动态物品 set_state 合法）。
- [ ] FAIL → 实现（校验用任务2 的访问器；容量常量 ROOM_CAP=15）→ PASS → 检查点。

---

## 任务 4：决策纳入 事件/情绪/金钱/弃置 `world_brain.py`
**文件：** 增强 `world_brain.py`；测试 `tests/unit/test_world_brain.py`（追加）
- `_build_user_message` 追加：`[刚发生] {event.content}`、`[钱包] {money}`、`[失去过] gone_log labels`；system prompt 增："心情差就安抚/休息，别硬做计划；钱够且有需要时可以买点东西；可以扔掉坏掉/不要的东西"。
- 新增"事件→情绪"辅助：`event.mood_delta` 由 tick 转成 StateMutation.mood_valence_delta（在任务5 接线）。
- [ ] 失败测试：patch LLM，断言传出的 messages 文本含 event.content、money 数值、gone_log label；坏输出仍降级 mock；旧用例不回归。
- [ ] FAIL → 实现 → PASS → 检查点。

---

## 任务 5：接入实时演示 + 可视化 `world_live_server.py`
- tick 顺序：漂移 → **事件注入(maybe_emit)** → 事件应用(world_op 经校验落账 + mood mutation) → 取上下文(含 event/money/gone_log) → 决策 → 校验执行(含 create/destroy) → 落账 + 经历/episode + 精力/情绪反馈。
- 计划/早晨：planner prompt 也带 gone_log（跨天惦记）。
- 页面新增：事件横幅(⚡)、钱包(💰)、心情数值/箭头、失去清单(🗑 gone_log)、动态物品渲染。
- [ ] 步骤1：world_store 已序列化整个 WorldState → 新字段自动持久（确认）。
- [ ] 步骤2：实现 tick 注入 + 渲染（mock 模式可跑，不调真实模型）。
- [ ] 步骤3：mock 模式跑一天，对照第1节逐条勾（事件/情绪/买/失去/跨天惦记/守门/不泛滥）。
- [ ] 步骤4：全量回归 + 红线检查（不 commit）。

```bash
pytest tests/unit/test_world_model.py tests/unit/test_world_store.py tests/unit/test_world_drift.py \
  tests/unit/test_action_validator.py tests/unit/test_world_brain.py tests/unit/test_memory_recall_weighted.py \
  tests/unit/test_daily_planner.py tests/unit/test_day_cycle.py tests/unit/test_life_events.py \
  tests/unit/test_world_open.py --timeout=60 -q
git diff --name-only -- <6 红线文件>
```

---

## 3. 自检
覆盖：意外(任务1)、开放世界模型(任务2)、守门(任务3)、决策纳入情绪/事件/金钱(任务4)、接线+情绪波动+可视化+验收(任务5)。攻击单调根因 1/2/3。根因4（他者/对话）明确不在本刀（接聊天单独做）。
类型一致：LifeEvent/world_op 在任务1/2 定义，任务3/4/5 引用；访问器任务2 定义，任务3/4/5 复用。
占位符：无；事件与买卖均真实改状态并有测试断言实际变化。
