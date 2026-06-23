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

Skills 位于 `.agents/skills/` 目录，每个 skill 有独立的 `SKILL.md` 文件。

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
- **workflow-runner**: 在 Codex / OpenClaw / Cursor 中直接运行 agency-orchestrator YAML 工作流——无需 API key，使用当前会话的 LLM 作为执行引擎。当用户提供 .yaml 工作流文件或要求多角色协作完成任务时触发。
- **writing-plans**: 当你有规格说明或需求用于多步骤任务时使用，在动手写代码之前
- **writing-skills**: 当创建新技能、编辑现有技能或在部署前验证技能是否有效时使用

- **codegraph-query**: 轻量级代码图谱查询——通过命令行直接调用 `cgc --db kuzudb --db-path ".codegraphcontext\codegraph.kuzu"` 查找函数、调用关系、类结构，不启动 MCP server（省 228MB 内存）。当需要理解代码结构、追踪调用链、修改前影响分析时使用；重建索引见 `docs/codegraph-query-rebuild.md`。
## 如何使用

当任务匹配某个 skill 时，使用 `Skill` 工具加载对应 skill 并严格遵循其流程。绝不要用 Read 工具读取 SKILL.md 文件。

如果你认为哪怕只有 1% 的可能性某个 skill 适用于你正在做的事情，你必须调用该 skill 检查。
<!-- superpowers-zh:end -->

---

# 📦 上下文 / 文件忽略（省 token，所有 AI agent 必读）

本仓库有大量**生成产物和二进制目录**，体积巨大且与编码任务无关。**不要读取、不要搜索、不要遍历**以下路径——它们会瞬间撑爆上下文和 token：

| 路径 | 说明 | 体积 |
|---|---|---|
| `.codegraphcontext/`、`.codegraphcontext*/`、`.codegraphcontext.prev-*/` | 代码图谱二进制索引（kuzu DB） | **~310 MB** |
| `*.kuzu` | 图数据库文件 | 大 |
| `venv/`、`.venv/`、`env/` | Python 虚拟环境 | ~100 MB |
| `data/`、`*.db`、`*.sqlite*` | SQLite 运行时数据 | 含真实数据 |
| `node_modules/`、`__pycache__/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/` | 依赖 / 缓存 | — |
| `.git/`、`dist/`、`build/`、`logs/`、`backups/`、`tmp/`、`uploads/` | 版本控制内部 / 构建 / 临时 | — |
| `.agents/`、`.claude/skills/` | 技能插件（由 harness 加载，无需被搜索） | — |

**规则：**

- 需要理解代码结构时，**只在 `app/`、`tests/`、`scripts/`、`prompts/` 等源码目录内**做 Grep/Glob/Read。
- 绝不 `Read` 上述任何二进制 / 数据库 / 缓存文件。
- 绝不输出 `.env`、token、API key、数据库内容到上下文或日志。
- 真实的排除以根目录 `.gitignore` 为准（ripgrep 系工具会自动遵守）；`.claudeignore` 仅作补充约定，不保证被所有工具识别。

---

# Living World 修改边界

Living World 已有可运行实现，不再只是 `LifeState` 模板。修改相关代码前先读：

- `docs/living-world.md`：当前能力、数据流、运行开关、端点和已知缺口。
- `NENO_ARCHITECTURE.md` §3.1：世界状态与意识状态的所有权边界。

必须遵守：

- `life_world_state` 是虚拟世界状态的 SQLite 单一真相源；不要另建并行内存世界。
- `WorldLoop` 是后端正式融合循环；新增能力应接入它，不能继续复制演示循环。
- 世界 LLM、日计划 LLM 和常驻循环必须分别由环境变量控制，示例配置默认关闭。
- `world_ops` 必须先经过 `action_validator`，再由 `world_model.apply_op()` 落账。
- 用户聊天尚未进入世界引擎。不要绕过 Phase 5 设计直接改主聊天 prompt 或六个红线文件。
- 不能因为存在房间、事件、日计划和跨天逻辑就宣称“完整世界引擎完成”；验收标准是持续生活、因果延续和用户消息作为外部事件。

---

# Android App 修改边界

Android 产品端是 `mobile/android/` 下的原生 Kotlin + Jetpack Compose App，不是 `/test` 调试控制台、WebView、Expo 或 React Native。修改相关代码前先读：

- `docs/android-app-design-brief.md`：产品方向、中文界面和视觉边界。
- `docs/android-app-implementation-plan.md`：移动端 API 合同和 Android 工程结构。
- `docs/android-app-handoff.md`：当前实现、验证状态和接手任务。

必须遵守：

- App 只能通过 `/mobile/*` 进入后端；不得直接调用 `/debug/*`、`/session/*` 或 admin-only 端点。
- `/mobile/ws` 只承载前台连接状态和 presence，不负责发送聊天内容；聊天仍走 `POST /mobile/conversations/neno/messages`。
- 不要在 Android 工程提交真实 `MOBILE_TOKEN`、admin token、平台 token、服务器密钥或真实用户数据。
