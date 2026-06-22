# 🚨 CRITICAL INITIALIZATION INSTRUCTION FOR ALL AI AGENTS 🚨

Welcome to the Neno-bot repository. This is a highly constrained, state-driven, and concurrent agent engine. 

Before you start any task, planning, coding, or answering questions, **YOU MUST MANDATORILY READ AND ASSIMILATE** the following two core architecture documents located in the root of this repository:

1. `NENO.md` (AI Collaboration & Modification Guidelines and State Contract)
2. `NENO_ARCHITECTURE.md` (Runtime Architecture Topology and Hazard Map)

### 🛑 REQUIRED ACTION NOW:
If you have not yet read these files in your current session, you must immediately use your file-reading tools (e.g., `view_file`, `read_file`) to load `NENO.md` and `NENO_ARCHITECTURE.md`.

### ⚠️ WHY THIS IS NON-NEGOTIABLE:
Neno relies on extremely fragile memory locks, exact prompt appending orders for API cache economics, and monotonic digest cursors. Applying generic software engineering principles (like making things async, reordering logic, or delaying snapshot writes) without understanding the architecture **WILL silently break the system**. 

**DO NOT PROCEED with any code modifications until you have read both documents.**

<!-- superpowers-zh:begin (do not edit between these markers) -->
# Superpowers-ZH 中文增强版

本项目已安装 superpowers-zh 技能框架（20 个 skills）。

## 核心规则

1. **收到任务时，先检查是否有匹配的 skill** — 哪怕只有 1% 的可能性也要检查
2. **设计先于编码** — 收到功能需求时，先用 brainstorming skill 做需求分析
3. **测试先于实现** — 写代码前先写测试（TDD）
4. **验证先于完成** — 声称完成前必须运行验证命令

## 可用 Skills

Skills 位于 `.claude/skills/` 目录，每个 skill 有独立的 `SKILL.md` 文件。

- **brainstorming**: 在任何创造性工作之前必须使用此技能——创建功能、构建组件、添加功能或修改行为。在实现之前先探索用户意图、需求和设计。
- **chinese-code-review**: 中文 review 沟通参考——话术模板、分级标注（必须修复/建议修改/仅供参考）、国内团队常见反模式应对。仅在用户显式 /chinese-code-review 时调用，不要根据上下文自动触发。
- **chinese-commit-conventions**: 中文 commit 与 changelog 配置参考——Conventional Commits 中文适配、commitlint/husky/commitizen 中文模板、conventional-changelog 中文配置。仅在用户显式 /chinese-commit-conventions 时调用，不要根据上下文自动触发。
- **chinese-documentation**: 中文文档排版参考——中英文空格、全半角标点、术语保留、链接格式、中文文案排版指北约定。仅在用户显式 /chinese-documentation 时调用，不要根据上下文自动触发。
- **chinese-git-workflow**: 国内 Git 平台配置参考——Gitee、Coding.net、极狐 GitLab、CNB 的 SSH/HTTPS/凭据/CI 接入差异与镜像同步配置。仅在用户显式 /chinese-git-workflow 时调用，不要根据上下文自动触发。
- **dispatching-parallel-agents**: 当面对 2 个以上可以独立进行、无共享状态或顺序依赖的任务时使用
- **executing-plans**: 当你有一份书面实现计划需要在单独的会话中执行，并设有审查检查点时使用
- **finishing-a-development-branch**: 当实现完成、所有测试通过、需要决定如何集成工作时使用——通过提供合并、PR 或清理等结构化选项来引导开发工作的收尾
- **mcp-builder**: MCP 服务器构建方法论 — 系统化构建生产级 MCP 工具，让 AI 助手连接外部能力
- **receiving-code-review**: 收到代码审查反馈后、实施建议之前使用，尤其当反馈不明确或技术上有疑问时——需要技术严谨性和验证，而非敷衍附和或盲目执行
- **requesting-code-review**: 完成任务、实现重要功能或合并前使用，用于验证工作成果是否符合要求
- **subagent-driven-development**: 当在当前会话中执行包含独立任务的实现计划时使用
- **systematic-debugging**: 遇到任何 bug、测试失败或异常行为时使用，在提出修复方案之前执行
- **test-driven-development**: 在实现任何功能或修复 bug 时使用，在编写实现代码之前
- **using-git-worktrees**: 当需要开始与当前工作区隔离的功能开发，或在执行实现计划之前使用——通过原生工具或 git worktree 回退机制确保隔离工作区存在
- **using-superpowers**: 在开始任何对话时使用——确立如何查找和使用技能，要求在任何响应（包括澄清性问题）之前调用 Skill 工具
- **verification-before-completion**: 在宣称工作完成、已修复或测试通过之前使用，在提交或创建 PR 之前——必须运行验证命令并确认输出后才能声称成功；始终用证据支撑断言
- **workflow-runner**: 在 Claude Code / OpenClaw / Cursor 中直接运行 agency-orchestrator YAML 工作流——无需 API key，使用当前会话的 LLM 作为执行引擎。当用户提供 .yaml 工作流文件或要求多角色协作完成任务时触发。
- **writing-plans**: 当你有规格说明或需求用于多步骤任务时使用，在动手写代码之前
- **writing-skills**: 当创建新技能、编辑现有技能或在部署前验证技能是否有效时使用

- **codegraph-query**: 轻量级代码图谱查询——通过命令行直接调用 `cgc --db kuzudb --db-path ".codegraphcontext\codegraph.kuzu"` 查找函数、调用关系、类结构，不启动 MCP server（省 228MB 内存）。当需要理解代码结构、追踪调用链、修改前影响分析时使用；重建索引见 `docs/codegraph-query-rebuild.md`。
## 如何使用

当任务匹配某个 skill 时，使用 `Skill` 工具加载对应 skill 并严格遵循其流程。绝不要用 Read 工具读取 SKILL.md 文件。

如果你认为哪怕只有 1% 的可能性某个 skill 适用于你正在做的事情，你必须调用该 skill 检查。
<!-- superpowers-zh:end -->

---

# Living World 修改边界

Living World 已有正式 `WorldLoop`、SQLite 世界状态、房间物品、日计划、事件、
昼夜跨天、世界 LLM 和控制台接入。修改前必须阅读：

- `docs/living-world.md`
- `NENO_ARCHITECTURE.md` §3.1

不得绕过 `action_validator` 应用模型动作，不得复制第二套生产循环。世界状态进主聊天
**只能走 self_context 受控只读通道**（`build_self_state_context`，详见 `docs/living-world.md` §5b、`NENO.md` §4/§7.1）——
禁止在别处手动偷接、禁止破坏 `context_builder.py` 装配顺序。常驻循环、世界/日计划/self_context LLM 的示例配置必须默认关闭。
用户消息进世界、在场决策、意图通道（消息驱动世界行动）均已落地（详见 `docs/living-world.md` §5c）。
但全是慢热机制，**真验收靠用户连续跑数日体验，未实跑**；在此之前不得宣称完整世界完成。

新增硬规则（编辑世界引擎前必看）：

- `world_loop.tick` 的 LLM 调用由 `world_pressure.should_wake` 门控。tick 是「真想 / 滑行接续 / 纯 mock」三分支；改动时 `world_llm_enabled=False` 路径不得引入 LLM 或改变 mock 行为。
- 世界时钟是真实 UTC+8（`sim_minutes` 由 `datetime.now(_TZ8)` 推导）；`CONSCIOUSNESS_WORLD_SIM_MIN_PER_TICK` 已废弃于时间推进，勿据它累加时间。
- `world_salience` 表必须覆盖真实 `LifeEvent.kind`（mishap/message/weather/craving/memory），否则意外不驱动唤醒。
- 精力是真实时间积分（`energy_dynamics.step_energy`），作息由阈值涌现（`day_cycle.check_sleep_wake` 只看精力，不看时段）。**勿**把刚性 sleep/wake 时段闸门加回来，**勿**复活 tick 量化掉电（`CONSCIOUSNESS_WORLD_ENERGY_DROP_PER_TICK` 已废弃）。tick 内精力结算后的判睡醒/快照一律用就地内存值——`StateStore.submit_mutation` 入队异步落库，同 tick 内 `read()` 读不到刚提交的值。
- 切世界 LLM 开关用 `scripts/neno-llm.ps1 on|off`；改 `.env` 后必须重启 uvicorn 才生效。**`self_context` 是独立开关 `CONSCIOUSNESS_SELF_CONTEXT_LLM_ENABLED`，neno-llm.ps1 不管它，要手设 `.env` 再重启。**
- 聊天 prompt 是缓存敏感区（NENO.md §4）：动态内容（self_context/关系/时间/memory）只能在 `messages[last]`、排历史之后，两断点不可移；关系已连续化（不读 `prompts/stages/stage_X.txt`）。
- 刀①收尾的「做」与「沉淀」（详见 `docs/living-world.md` §5c）：新 op `relocate`/`learn` 各有一条 `action_validator` 法律，不得绕。**自我库 `subject="neno"` 只能 reflection 从落账经历结晶，聊天写不进（防伪写入路径）。意图通道严禁从聊天侧写 `WorldState`——只由 `world_loop` 读 `kind="message"` 经历当意图候选，做不做交世界 LLM（无常）。**
