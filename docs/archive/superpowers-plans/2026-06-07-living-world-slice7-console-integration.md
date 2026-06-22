# Living World 竖切7「接入控制台 · 常驻运行」实现计划

> **历史实施记录。** 接线已落地，但仍有测试与双循环收敛问题；
> 当前事实见 `docs/living-world.md` 和 `PHASE_4_PROGRESS.md`。

> 用 superpowers:executing-plans 执行；TDD；LLM/真实模型默认关；每任务跑给用户看。

**目标：** 把新世界引擎（slice1/3/5/6）接进后端 app + WebUI 控制台。世界作为常驻定时任务自动运行（由开关 `world_loop_enabled` 控制，默认关），控制台读取并展示。之后用户可在控制台上重新设计界面。

**架构：** 抽出 `WorldLoop`（单一可信源：融合 tick + 快照），ConsciousnessEngine 在 start() 注册其定时任务（gated）。debug.py 加只读快照端点 + 手动步进端点。consciousness.js 加世界面板。scripts 的 demo 改为复用 WorldLoop。

---

## 0. 硬约束
- **不碰 6 个红线文件**（debug.py / consciousness.js 不在红线内，可改）。
- **不 commit。** 默认 `world_loop_enabled=False`：不注册 tick、对现有机器人零影响。
- 真实模型默认关（`world_llm_enabled=False`）；开了 loop 也先 mock。
- 单机 SQLite，不新增表（世界状态仍在 life_world_state）。
- 端点 admin-token 守门（沿用 require_admin_token）。

## 1. 验收契约（可勾）
- [ ] `world_loop_enabled=False` 时：app 启动不注册 world tick；现有测试不回归。
- [ ] `world_loop_enabled=True` 时：注册一个 interval job，每次推进世界并写 life_world_state。
- [ ] `GET /debug/consciousness/world-live` 返回快照（房间/物品/动态物品/钱包/失去/计划/最近行动/事件/精力/心情），admin 守门。
- [ ] `POST /debug/consciousness/world-tick` 手动推进一步并返回新快照，admin 守门。
- [ ] WorldLoop.tick() 真实推进：world_store 写入、StateStore 精力下降（单测断言实际变化）。
- [ ] consciousness.js 新面板渲染世界；空态有中文提示。
- [ ] 红线 diff 空；默认配置下不调真实模型、不自动注册 loop。

## 2. 任务

### 任务1：抽出 WorldLoop（单一可信源）
- 创建 `app/services/consciousness/world_loop.py`：
  - `class WorldLoop`：持有 world_def/world_store/state_store/brain/planner/day_cycle/recorder/recall/episode_store/reflection/event_source/rng/config + sim 时钟。
  - `async def tick() -> dict`：一次融合 tick（漂移→事件→决策→校验执行→落账+经历/episode+精力情绪反馈→写 last_tick），返回快照。
  - `def register_jobs(scheduler)`：`world_loop_enabled` 为真才 add_job(interval=world_loop_interval_seconds)。
  - 模块函数 `build_snapshot(world_def, world_state, nstate) -> dict`（从 demo 的 _snapshot 抽来）。
- WorldState 加 `last_tick: dict | None = None`（持久化最近一步，端点只读 DB 即可还原快照）。
- config 加 `world_loop_enabled`、`world_loop_interval_seconds=8`、`world_sim_minutes_per_tick=30`。
- 测试 `tests/unit/test_world_loop.py`：tick 后 world_store 状态变、StateStore energy 下降（带 _drain）；register_jobs 关时不加 job、开时加 job（用假 scheduler 断言）。

### 任务2：接入 ConsciousnessEngine
- `__init__.py`：实例化 WorldLoop（复用 self.state_store/recall/config），start() 调 `world_loop.register_jobs(self._scheduler)`。
- 暴露 `self.world_loop` 供需要时访问。
- 测试：test_brain/test_state_store 不回归；新增小测试确认 enabled 时引擎注册了 world tick（假 scheduler）。

### 任务3：debug 端点
- `debug.py` 加：
  - `GET /consciousness/world-live`：读 life_world_state + agent_state → build_snapshot → JSON。
  - `POST /consciousness/world-tick`：构造一个 WorldLoop（或复用），await tick()，返回快照。
- 测试 `tests/integration/test_world_live_debug.py`：无 token 401；有 token 200 且含 rooms/money/plan 字段；tick 端点推进世界。

### 任务4：控制台面板
- `consciousness.js` + 对应 HTML 模板：加"生活世界"面板，轮询 `/debug/consciousness/world-live`，渲染房间/物品/钱包/失去/计划/事件/精力/心情；空态中文提示；admin。
- `node --check app/static/js/consciousness.js`。

### 任务5：demo 复用 + 全量验收
- `scripts/world_live_server.py` 改为调用 `WorldLoop.tick()` + `build_snapshot()`（去重，单一可信源）。
- 全量回归 + 红线检查 + node --check。

## 3. 自检
覆盖：常驻运行(任务1/2)、控制台读取与步进(任务3)、界面(任务4)、去重(任务5)。安全阀 world_loop_enabled 默认关。真实模型默认关。红线不碰。
