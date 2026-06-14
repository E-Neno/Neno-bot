# 刀② 世界深度 — Codex 交接 Brief

> 第 4 章（开放世界）刀②。**纯数据驱动加法，不碰决策机制**。父计划见
> `docs/open-world-plan.md`。本 brief 是给 Codex 的可执行规格。

## 目标（一句话）
现在世界 = 固定四房间 + 15 个物品 + 5 类生活事件，她脑子里能活的东西太少，动作翻来
覆去。**给她更多可活的东西**：扩房间/物品、扩生活事件种类。**只加内容，不改任何判断逻辑。**

## 红线（违反即作废，必须遵守）
1. **不改决策机制**：不动 `world_brain.py`（怎么决定做什么）、不动 `world_pressure.py`
   的 `should_wake`/`accumulate`/`on_wake` 逻辑、不动 `world_loop.py` 的 tick 三分支。
2. **不绕 `action_validator`**：所有物品/状态都是封闭世界白名单。新物品的 `category` 必须
   在 `categories` 里、`state` 必须在该 category 的合法状态里，否则 validator 会拒。
3. **不复制第二套循环**，不新建生产循环。
4. **加法不改乘法**：新东西「读」现成系统，不引入新的紧耦合反馈。
5. 别动 `.env`、别提交任何敏感文件（`.env` / `allowed_wx_users.json` / `tmp/` 已 gitignore）。

## 改动点（三处 + 一处必须同步的坑）

### A. 扩 `world_def`（数据文件，零代码）
文件：`app/services/consciousness/virtual_world.json`
- 现有四房间（bedroom/kitchen/living_room/balcony）各加 2-4 个物品，让每间屋更具体。
- 可加新 `category`（连同它的合法 `states` + `default`），也可复用现有 category。
- **约束**：
  - 每个新 object 必须有 `category`（已在 `categories` 里）和 `label`（中文）。
  - 每个新 object 必须挂在某个 room 的 `objects` 数组里（否则 `room_of` 找不到）。
  - object key 用英文小写下划线；label 用中文。
  - 不要删现有物品（`gone_log`/`removed`/测试都引用现有 key）。
- 数据模型见 `world_model.py`：`WorldDef` / `CategoryDef` / `ObjectDef`。`load_world_def()`
  直接 `model_validate` 这个 json，加完跑一次确认能 load。

### B. 扩 `life_events`（生活事件种类）
文件：`app/services/consciousness/life_events.py`
- 现 `LifeEvent.kind` 只有 `weather/message/craving/memory/mishap`，`maybe_emit` 是
  优先级派生（gone_log > morning weather > low-energy craving > 默认 message）。
- 加 1-3 个**新 kind**（例：`chore` 家务念头、`idle_thought` 走神、`small_joy` 小确幸、
  `weather` 扩成更多天气）。每个新 kind 走和现有一样的派生模式（看 world_state/phase/
  energy 派生，**不是纯随机文案**——见文件 docstring 的设计约束）。
- 若新事件要改世界（如「想给盆栽浇水」），用 `WorldOp(op="set_state", ...)`，object/state
  必须在白名单内。可参考现有 mishap/weather 的 world_op 写法。
- **不要**把概率门 `EMIT_PROB`/`MISHAP_PROB` 调高到刷屏；保持低频。

### C. ⚠️ 同步 `world_salience`（最容易漏、漏了新事件就不驱动唤醒）
文件：`app/services/consciousness/world_pressure.py` 的 `_DEFAULT_SALIENCE` dict。
- **每加一个新 `LifeEvent.kind`，必须在 `_DEFAULT_SALIENCE` 里给它一个显著度权重**，
  否则 `salience_of` 返回 0.0 → 该事件永远不累积压力 → 永远不驱动她醒来想这件事 →
  等于白加。
- 权重参考现有标尺：mishap=50(hard,立刻想) / message=40 / craving=20 / weather=15 /
  memory=10。新 kind 按「这事多想让她分心」定档。日常小事给 10-20，别给 ≥50（≥50 会被
  判 hard event 立刻烧 LLM）。

### 前提认知
- world LLM 开着才有意义（`CONSCIOUSNESS_WORLD_LLM_ENABLED=1`，本地 .env 已开）。mock 模式
  下扩房间只是「更长的死循环」。所以验收要点是「她能在新物品/新事件上涌现地反应」，而非
  词表变长。但**单测不依赖 LLM**（见下）。

## 测试（先写后改，TDD）
- `tests/unit/test_life_events.py`：现有 6 个用 `_RNG`（确定性 rng）精确测分支。**每个新 kind
  加一个确定性分支测试**，照现有 `test_*` 写法（固定 rng 值 + 构造触发该分支的 world_state/
  phase/energy，断言 `ev.kind` 和必要的 `world_op`）。
- `tests/unit/test_world_pressure.py`：若加了新 salience key，加断言确认 `salience_of(new_kind,
  config) > 0`。
- 扩 world_def 后，确认 `load_world_def()` 不抛、`seed_world_state()` 能给所有新物品取到默认态。
- 跑：`python -m pytest tests/unit/test_life_events.py tests/unit/test_world_pressure.py
  tests/unit/test_world_model.py -q`。
- **已知预存在失败**（非你引入，别去修、别让它们挡你）：`tests/unit/test_life_loop.py` 有 2 个
  预存在失败；`test_world_brain.py::test_glide_falls_back_on_transient_action` 组合跑时偶发飘
  （单独跑过）。只看你碰的那几个文件全绿即可。

## 验收（codex 自己能做的）
1. 上面三个测试文件全绿。
2. `load_world_def()` 能 load 扩充后的 json。
3. 新 `LifeEvent.kind` 每个都在 `_DEFAULT_SALIENCE` 里有权重（grep 自查）。
4. 没动 world_brain/should_wake/tick 逻辑、没动 .env（git diff 自查）。

## 交付
- 改：`virtual_world.json`、`life_events.py`、`world_pressure.py`、对应两个 test 文件。
- 不 commit（用户要亲自 commit/push）；做完把 diff 摘要 + 测试输出报回。
