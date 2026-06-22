# 世界引擎实施计划（Phaser 分层 2D）

> 方向已定：B 路 + Phaser，分层场景（背景死光 → 远景 → N 个按深度排的独立组件层 →
> 角色 → 活光影/粒子顶层），物理按需挂。Python 世界引擎是权威后端，不动。
> 分工原则：**我规划+给详规+审收+整合；codex 写大部分码；用户出美术+肉眼验。**

## 硬约束（决定分工）
- **Phaser 是浏览器代码，codex 和 AI 都不能在此跑浏览器看渲染**——只有用户能肉眼验。
- 所以**不greenfield 甩给 codex**：我先把"能跑的核心骨架"写对（原型 `world-engine.html` 已是），
  codex 只在能跑的底座上做**有边界的增量**和**大量机械配置**。每个 codex 任务必须：
  自包含、API 精确（我在 brief 里写死 Phaser 调用）、不依赖它自己跑浏览器验证。
- 循环：codex 写（按我详规）→ 我结构审（语法/API/架构/红线）→ 用户肉眼测 → 迭代。

## 数据契约（我定，贯穿全程）
快照已含 `rooms[room].objects[{key,label,emoji,state,category}]`。前端配置（扩 worldViewAdapter）：
- `LAYER_OF[category|key]` → 物品落哪层 + `depth`（前后）
- `SLOT[room][key]` → 坐标（沿用现有 OBJECT_SLOTS / autoLayout 兜底）
- `PHYSICS[key]` → 是否挂物理 + 类型（pendulum 摆 / cloth 布 / drop 掉落）
- `SPRITE[key][state]` → 真实贴片 URL（沿用 OBJECT_IMG，没图回退 emoji）
- `FX[key][state]` → dim / tip / steam 等

## 分阶段（标注 owner）

### Phase 0 — 架构与骨架定稿 · 我
- 把原型 `world-engine.html` 升级成**正式引擎骨架**：5 层结构、depth 排序、相机、单房间渲染、
  快照轮询、状态→精灵、idle tween、juice、1 个物理件。API 全部写对，作为 codex 的底座。
- 定死上面的数据契约 schema。

### Phase 1 — 多房间 + 相机 + 房间切换 · codex（我给详规+审）
- 把现 DOM 控制台的"9 间房 strip + 相机平移 + 跟随她/手动切"逻辑移植进 Phaser。
- 输入：我给的骨架 + 详规（Phaser 相机 API、房间布局、切换规则）。

### Phase 2 — 分层 + 深度排序 · codex
- 实现 `LAYER_OF` + `depth`：物品按层/深度落位，"她走到柜后被挡"自然发生。
- 远景层（窗外）+ 活光影顶层（先放空容器，Phase 6 填）。

### Phase 3 — 物理件 · codex（我给精确 Matter 详规）
- 按 `PHYSICS[key]` 给标记的件挂 Matter：pendulum（风铃/挂植）、cloth（窗帘）、drop（掉落弹）。
- 我在 brief 写死 Matter constraint / body / applyForce 的精确调用（这块最容易错，详规要细）。

### Phase 4 — 配置数据（9 间全量）· codex（机械活，量大）
- 填 `LAYER_OF` / `SLOT` / `PHYSICS` / `FX` 全 9 间 112 物（像之前扩 world_def 那种纯数据活）。
- autoLayout 兜底，codex 主要标"哪些要单独摆/挂物理/特殊层"。

### Phase 5 — 替换控制台视图 · 我（整合，codex 辅助）
- 把控制台世界面板的 DOM world-view 换成 Phaser 引擎；保住 token/相机/房间切换/编辑器/快照协议。
- 这是有风险的"换引擎"接缝，我主刀。

### Phase 6 — 活光影 / 粒子 / 更多物理 · codex + 我
- 动态光顶层（开灯辉光、昼夜色调）、粒子（蒸汽/光尘/雨）、更多物理件。

### Phase 7 — 美术接入 · 用户出图 + 我接线
- lofi 独立精灵集：9 房间壳 + 共用道具库 + 状态变体。用户 ChatGPT 出，我接进 SPRITE 表，emoji 逐个换。
- 与 Phase 1-6 并行，不阻塞。

## owner 汇总
- **我**：Phase 0 骨架、每个 codex 任务的详规、全部结构审收、Phase 5 整合、美术接线。
- **codex**：Phase 1/2/3/4/6 的实现（在我骨架上增量、按我详规）。
- **用户**：每阶段肉眼验（唯一能看渲染的）、Phase 7 出美术。

## 风险
- 浏览器代码无法自动验 → 靠"能跑底座 + 紧详规 + 用户肉眼测"压住。
- codex-on-Windows 沙箱坏 → 关沙箱跑（用户已授权），我审收。
- 换引擎接缝（Phase 5）有风险 → 我主刀，先标准独立页验透再并入控制台。
- 美术资产量大 → 共用道具库 + 状态只给会变的，压到 ~80 张。

## 建议
我先做 **Phase 0**（把原型升成正式骨架 + 定死 schema），跑通你肉眼确认后，
再逐个 Phase 派 codex（每个带我的详规），我审、你验。
