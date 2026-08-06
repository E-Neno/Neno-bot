# Neno Bot

Neno 是一个本地优先、SQLite 驱动的 AI 伴侣后端。它把聊天、长期记忆、关系演进、主动性和 Living World 收在同一个状态驱动引擎里，而不是一个无状态的 LLM wrapper。

## 项目地图

```text
HTTP / Web / OpenClaw / Android / Operit
                    |
          输入归一化与媒体解析
                    |
     Session 聚合 -> Session 串行提交锁
                    |
        上下文组装 -> 主聊天 / Executive
                    |
       回复出口、记忆、关系、审计落库
                    |
       WorldLoop -> validator -> world store
```

| 路径 | 职责 |
| --- | --- |
| `app/` | FastAPI 后端、聊天编排、状态存储、Living World 和调试路由 |
| `app/static/` | 后端托管的调试控制台，入口为 `/test` |
| `mobile/android/` | 原生 Kotlin + Jetpack Compose 的 Neno v0 客户端 |
| `mobile/operit/` | 完整 Operit Neno fork，当前 Operit 源码真相源 |
| `prompts/` | Neno 系统提示词、陪伴版提示词和阶段性实验提示词 |
| `tests/` | 后端单元测试、集成测试和协议测试 |
| `docs/` | 架构契约、移动端交接、Living World 和迁移记录 |

两个 Android 客户端相互独立。`mobile/operit` 的 Neno 特殊好友通过后端 `/mobile/*` 连接，不把 Neno 当作角色卡模型，也不绕过后端接入 Operit 本地模型链。

## 快速开始

### 安装后端依赖

PowerShell：

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Bash：

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 配置环境

```powershell
Copy-Item .env.example .env
```

至少配置以下变量。真实值只放在本机 `.env`，不要写入 README、测试或提交：

| 变量 | 用途 |
| --- | --- |
| `OPENROUTER_API_KEY` | 聊天、记忆和世界模型调用 |
| `ADMIN_TOKEN` | `/debug/*`、`/session/*`、记忆和配置管理 |
| `PLATFORM_TOKEN` | 非回环平台消息入口 |
| `MOBILE_TOKEN` | Android `/mobile/*` 与 `/mobile/ws` |
| `MOBILE_DEFAULT_SESSION_ID` | 默认移动端会话，通常为 `mobile:neno` |
| `MIMO_API_KEY` | 选择层和部分反思/世界模型 |

### 启动服务

默认只监听本机：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

调试控制台：<http://127.0.0.1:8000/test>

只有在 token 和网络边界已经配置好时，才显式监听局域网：

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API 入口

| 方法 | 路径 | 鉴权 / 用途 |
| --- | --- | --- |
| `GET` | `/` | 健康检查 |
| `GET` | `/test` | 后端调试控制台 |
| `POST` | `/chat` | Web/控制台聊天；建议只监听回环 |
| `POST` | `/platform/openclaw/message` | OpenClaw 平台消息；回环或 `X-Platform-Token` |
| `GET` | `/mobile/status` | `Bearer MOBILE_TOKEN`，移动端连接检查 |
| `POST` | `/mobile/uploads` | `Bearer MOBILE_TOKEN`，上传图片、语音或文件 |
| `GET` | `/mobile/conversations` | `Bearer MOBILE_TOKEN`，对话列表 |
| `GET` | `/mobile/conversations/{id}/messages` | `Bearer MOBILE_TOKEN`，消息历史 |
| `POST` | `/mobile/conversations/{id}/messages` | `Bearer MOBILE_TOKEN`，发送文本或附件 |
| `WS` | `/mobile/ws` | `Bearer MOBILE_TOKEN`，前台连接状态和 presence |
| `GET/POST` | `/memory/*` | `X-Admin-Token`，记忆管理 |
| `GET/POST` | `/session/*` | `X-Admin-Token`，会话查询和清理 |
| `GET/POST` | `/proactive/*` | `X-Admin-Token`，主动消息控制 |
| `GET/POST` | `/debug/*` | `X-Admin-Token`，诊断、事件和世界调试 |

移动端约束：Android 只能访问 `/mobile/*`；`/mobile/ws` 不承载聊天正文，聊天必须走 `POST /mobile/conversations/neno/messages`。Android 不得直接访问 `/debug/*`、`/session/*` 或 admin-only 路由。

## 核心运行模型

同一 `session_id` 的消息必须经过现有的聚合窗口和提交锁，内部严格串行：

1. 归一化文本、图片、语音和文件输入。
2. `SessionAggregationController` 合并短时间内的连续消息。
3. `SessionSubmitController` 获取会话锁，组装缓存安全的上下文。
4. 运行记忆候选、TRIAGE、私有涌念和可选 Executive。
5. 生成隔离出口回复，随后将消息、关系、审计和世界命令写入 SQLite。
6. `WorldLoop` 独立消费世界命令，并通过 `action_validator` 后再应用物理操作。

### 状态所有权

| 状态 | 真相源 |
| --- | --- |
| `messages`、`memories`、`relationship_state` | SQLite |
| `agent_state` | `StateStore` 管理的 SQLite 状态 |
| `life_world_state`、活动片段、世界经历 | `WorldStore` / `WorldLoop` 管理的 SQLite 状态 |
| `executive_decisions`、`executive_commands` | SQLite 追加审计 |
| `history_digest.json` | 文件系统摘要，游标单调推进 |
| 聚合队列、提交锁 | 进程内存 |

不要用 Redis、外部队列或第二套内存世界替换上述边界。当前设计假设单节点运行；多 worker 或多实例部署前必须重新设计一致性模型。

## Living World

Living World 的正式入口是 `WorldLoop.tick()`，不是演示脚本。它维护房间、物品、世界时钟、计划、睡醒节律、活动片段、内在经历和 `self_context`。

- 聊天消息作为经历和意图候选进入世界，但聊天侧不能直接写 `life_world_state`。
- 主聊天只能追加 `executive_commands`；物理操作必须经过 `WorldLoop -> action_validator -> world_model.apply_op()`。
- 世界循环、世界 LLM、日计划 LLM 和 self-context LLM 分别由环境变量控制，示例默认关闭。
- 世界当前状态只能通过受控的 `self_context` 只读通道进入主聊天。

端点和缺口见 [`docs/living-world.md`](docs/living-world.md)。

## Prompt 与并发红线

修改聊天核心前必须先读 [`NENO.md`](NENO.md) 和 [`NENO_ARCHITECTURE.md`](NENO_ARCHITECTURE.md)。以下约束不能随意改动：

- `context_builder.py` 的缓存前缀顺序：`SYSTEM_PROMPT -> history_digest -> 原文历史 -> 动态块`。
- `SessionAggregationController` 与 `SessionSubmitController` 的串行语义和异常释放路径。
- `history_digest` 的单调 `last_baked_message_id` 游标和 200-token 回收阈值。
- 当轮新记忆和关系变化遵守 1-turn lag，只影响下一轮上下文。
- 原始图片、音频 payload 和 provider-ready data URL 不写入 SQLite `messages`。
- `/debug`、`debug_events` 和 trace ID 是生产级可观测性设施，不做清理式删除。

## Android 与 Operit

### Neno 原生客户端

`mobile/android` 是原生 Compose 客户端，包含对话列表、Neno 聊天、附件上传、连接状态和 Phone Agent v0 协议骨架。构建和 API 合同见 [`docs/android-app-handoff.md`](docs/android-app-handoff.md)。

### Operit fork

`mobile/operit` 是 2026-08-07 从桌面工作区整体迁入的 Operit Neno fork：

- 原源码、未提交状态、构建产物、本地配置和子目录 Git 历史均保留。
- 原 `.git` 元数据改名为 `.operit-git`，不形成父仓嵌套仓库。
- `D:\OperitNenoMerge.work` 是迁移前完整快照；`D:\OperitNenoBuildMirror` 只是构建镜像。
- 本地签名配置、token、密码、APK、`build/` 和 `.gradle/` 物理保留但不提交。

构建入口：

```powershell
cd mobile\operit
.\gradlew.bat tasks
```

具体边界见 [`mobile/operit/README.NENO.md`](mobile/operit/README.NENO.md)。

## 验证与常用命令

后端：

```powershell
python -m pytest -q
python -m compileall -q app scripts tests
python -m pip check
git diff --check
```

原生 Neno Android：

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest
.\mobile\android\gradlew.bat -p .\mobile\android :app:assembleDebug
```

Operit fork：

```powershell
.\mobile\operit\gradlew.bat -p .\mobile\operit tasks
```

世界 LLM 开关（PowerShell）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\neno-llm.ps1 status
powershell -ExecutionPolicy Bypass -File scripts\neno-llm.ps1 on
powershell -ExecutionPolicy Bypass -File scripts\neno-llm.ps1 off
```

## 文档索引

| 文档 | 说明 |
| --- | --- |
| [`NENO.md`](NENO.md) | AI 协作规则与状态契约 |
| [`NENO_ARCHITECTURE.md`](NENO_ARCHITECTURE.md) | 运行时拓扑和危险区域 |
| [`docs/living-world.md`](docs/living-world.md) | Living World 当前能力、开关、端点和缺口 |
| [`docs/android-app-design-brief.md`](docs/android-app-design-brief.md) | Android 产品与视觉边界 |
| [`docs/android-app-implementation-plan.md`](docs/android-app-implementation-plan.md) | Android API 合同和工程计划 |
| [`docs/android-app-handoff.md`](docs/android-app-handoff.md) | Android 实现、验证和接手边界 |
| [`mobile/operit/README.NENO.md`](mobile/operit/README.NENO.md) | Operit fork 的源码边界和迁移信息 |
| [`docs/project-knowledge/2026-08-07-operit-source-unification.md`](docs/project-knowledge/2026-08-07-operit-source-unification.md) | 本次源码统一管理记录 |
| [`docs/codegraph-query-rebuild.md`](docs/codegraph-query-rebuild.md) | CodeGraph 索引维护 |

## Git 与数据边界

提交前确认没有把 `.env`、`data/`、`uploads/`、构建缓存、本地签名文件、token 或用户数据加入暂存区。父仓负责 `mobile/operit` 的源码变更；`.operit-git` 只是原始历史归档。
