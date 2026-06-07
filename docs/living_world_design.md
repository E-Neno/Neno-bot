# 活的世界 · 双层架构设计（一页纸）

> 状态：设计讨论稿，未实现。不碰红线文件，不 commit。
> 目标：让世界一直活着且会出意外，但把贵的 LLM 钱花在刀刃上。

---

## 0. 一句话原则

**世界（免费）负责出事，身体（免费）负责把事做成或搞砸，LLM（付费、稀疏）负责在烂摊子里做出一个连你都没料到、却又说得通的选择。**

意外是模拟层免费造的，新意是 LLM 偶尔付费给的。

---

## 1. 两层

```
┌─ 灵魂层（付费，稀疏触发）───────────────────────┐
│  LLM：决定"做什么"(意图) + 偶尔无中生有的新目标   │
│  只在"压力攒够"或"出大事"时被唤醒                  │
└───────────────────────────────────────────────┘
            ▲ 唤醒                  │ 下发意图
            │                       ▼
┌─ 模拟底盘（免费，每 8 秒）─────────────────────┐
│  drift 物理衰减 + 随机事件 + 身体执行 LLM 的意图 │
│  + 把"压力"累积起来，够了就向上捅醒灵魂层         │
└───────────────────────────────────────────────┘
```

底盘永远 8 秒一动（她不僵、画面一直活），LLM 一天可能就几十次（¥1 以内）。

---

## 2. 意外的三个出处 → 现有模块 → 要加什么

| 出处 | 是什么 | 现有模块 | 要加什么 |
|---|---|---|---|
| ① 外部意外 | 世界丢给她：水壶坏、天气变、你来消息、钱光了 | `life_events.py` (`LifeEventSource`) | 给每个事件打一个**显著度权重**，喂给压力累积器 |
| ② 内部意外（真新意） | 她自己冒出的新意图，菜单外的 | `world_brain.py` + `create/destroy_object` | **放开，让她自己长**：允许声明全新意图，由底盘去尝试执行（可能失败）。不做太多约束，只保留一个**人工干预口**当方向盘 |
| ③ 执行意外 | 身体/现实顶回来：想泡茶但壶坏了 | `action_validator.py` | 把**拒绝原因**回写进 state，下次唤醒 LLM 时塞进 prompt，逼她改主意 |

**执行那一步故意是笨的、忠实的——意外夹在它上下两头，不在它身上。**

---

## 3. 触发模型（核心：不用钟表，用压力）

> 解决"定时=模板化、随机=失控"。时机由世界里发生的事决定，跟几点钟无关。

### 压力累积器（每 tick 免费算，不调 LLM）

```
每个 tick：
    pressure += Σ(本 tick 发生的事的显著度)
                + 微小的"无聊滴漏"(防止安静太久永不思考)
```

**显著度不写死，全部走配置表，可热调（调试友好）：**

```json
// config / 或一张可在控制台里改的 salience 表
{
  "kettle_broken":  50,   "message_in":    40,
  "money_low":      30,   "action_done":   20,
  "phase_change":   15,   "plant_thirsty": 10,
  "boredom_drip":    1,   "threshold":    100
}
```

> 这些数字不是法律，是旋钮。先填个手感值，跑起来看她节奏，觉得太闹就调高阈值、太呆就调高滴漏。最好做成控制台里能直接改、不用重启就生效，方便你边看边调。

### 唤醒条件（满足任一就调一次 LLM，然后 pressure 清零）

```
1. pressure ≥ THRESHOLD        # 攒够了，正常唤醒
2. 来了 hard 事件(权重≥50)      # 大事立刻醒，不等攒
```

### 可控性 = 两个硬阀门（防失控 + 控成本）

```
MIN_GAP   两次唤醒至少隔 N 秒    # 防止大事连发把钱烧爆
BUDGET    每小时/每天最多 M 次   # 硬预算上限，超了就只走免费底盘
```

**效果**：时机天然不规则（不模板化，因为跟着真事走），但每次都有原因（可控，因为是逻辑触发），且成本有硬顶（预算阀）。安静的日子她少思考、省钱；出事的日子她频繁思考、该花就花。

---

## 4. 一个完整 tick 的样子

```python
def tick():                       # 每 8 秒，绝大多数 tick 全免费
    world.drift()                 # ① 物理衰减
    ev = life_events.maybe_emit() # ① 随机事件
    pressure += salience(ev) + boredom_drip

    if current_action.unfinished:
        body.continue_action()    # 身体继续执行上次 LLM 的意图（免费）

    if should_wake(pressure, budget, min_gap):   # 绝大多数时候 False
        intent = LLM.decide(state, memories, rejections, events)  # ← 唯一花钱处
        ops = validator.validate(intent)          # ③ 现实顶回来
        record_rejections(ops.rejected)           # 拒绝原因回写
        body.start_action(ops.accepted)
        pressure = 0

    persist(world_state)
```

---

## 4.5 人工干预口（方向盘，不是缰绳）

让她自由发展，但你随时能插手。一个轻量的控制台入口就够，不限制她平时的自主：

```
注入事件   往她世界里塞一个 LifeEvent（"下雨了" / "收到一封信"）→ 影响她接下来的选择
轻推意图   给一句软提示("要不要歇会儿")，进 prompt 但不强制，她可不听
否决/撤销  对某个动作喊停或回滚（比如她要乱花钱）
暂停/继续  冻结整个世界
```

原则：**平时她说了算，你只在想介入时才转一下方向盘。** 干预记进记忆，让她"记得你来过"。

---

## 5. 边界（红线）

- 不碰：`session_submit_controller / session_aggregation_controller / context_builder / chat_service / proactive/rules / history_digest`
- 改动只落在 `consciousness/` 下：`world_loop.py`(触发逻辑) / `life_events.py`(显著度) / `action_validator.py`(回写拒绝) / `world_brain.py`(放宽新意图) / `config.py`(阀门参数)
- 不改 DB schema（沿用 `life_world_state` 单行 JSON）
- 默认 `world_loop_enabled=False`；LLM 默认关
- 不 commit、不 push

---

## 6. 落地步骤（两条轨，各管各的）

### ⚠️ 先说"完成"的定义

**不是"测试全绿"。是"轨 2 的时间线你亲眼看过、点头说像她在过日子"。**
单元测试只证明管子接对了，证明不了她活得好不好。上次的空壳就是停在全绿。

### 轨 1：TDD —— 只管"管子接对没"（有标准答案的部分）

1. `config.py`：加阀门/旋钮参数（`pressure_threshold / wake_min_gap_seconds / wake_budget_per_hour / boredom_drip`）+ 可热调的 `salience` 表
2. `life_events.py`：每类事件返回 `salience` 权重（纯函数，单测）
3. `world_loop.py`：压力累积器 + `should_wake()`（纯函数，单测：攒够才 True、大事立刻 True、预算超了 False、`min_gap` 内 False）
4. `world_loop.tick()`：把"每 tick 调 LLM"改成"`should_wake` 才调"，其余 tick 走免费底盘续动作
5. `action_validator.py` / `world_brain.py`：拒绝原因回写 + prompt 展示 + 放开新意图
6. 人工干预口：注入事件 / 轻推 / 否决 / 暂停（控制台入口）

### 轨 2：验收 —— 管"她活得像不像活人"（只能你看，这才是真的完成线）

7. 写一个 dry-run 脚本：跑几百个 tick（先 mock 后真 LLM），把**完整时间线**打印出来——每个 tick 她在干嘛、什么时候醒来思考、为什么醒、做了什么决定、遇到什么意外、拒绝了什么
8. **你亲眼看这条时间线**，对照这几个问题（没有一个能靠 assert）：
   - 她绕圈吗？还是真有变化？
   - 唤醒时机像不像有节奏，还是要么死板要么乱？
   - 意外来得是时候吗？她应对得合理吗？
   - 那些权重/阈值要不要调？（直接在控制台调，再跑一遍看）
   - 真新意够不够野？她有没有冒出你没料到的东西？
9. 反复调旋钮 + 重跑 + 再看，直到**你**满意。满意了，才算完成。

---

## 7. 成本预期

- 安静日：唤醒主要靠无聊滴漏，约 每 30~60 分钟一次 → 几十次/天 → **< ¥1/天**
- 多事日：事件频繁唤醒，但被预算阀顶住 → 最多 M 次/天，成本封顶
- 底盘永远免费、永远 8 秒一动 → 她从不冻住
```