# Neno Bot

Neno 是一个本地优先的 AI 聊天机器人后端。它不是无状态 LLM wrapper，而是一个单节点、SQLite 驱动、带长期记忆、关系演进、主动消息和 Living World 的智能体引擎。

当前主界面是后端托管的调试控制台：`http://127.0.0.1:8000/test`。前端在 `app/static/`，使用原生 HTML/CSS/JS，不是 React/Vite 项目。

## 当前能力

- 多轮聊天：`POST /chat` 进入主聊天链路。
- 多平台接入：`POST /platform/openclaw/message` 接收 OpenClaw 桥接的 QQ/WX 消息。
- 长期记忆：自动提取候选记忆，人工或规则确认后进入上下文。
- 关系演进：按熟悉、信任、情感深度、边界稳定度累积分值，并连续化地影响语气。
- 历史摘要：长历史通过 digest（摘要）压缩，降低上下文成本。
- 主动消息：支持 observe / candidate / dry_run / auto 模式。
- Living World：Neno 有持久化小公寓世界、活动片段、睡醒节律、世界事件、自我库和意图通道。
- 调试台：`/test` 可查看聊天、记忆、主动消息、世界状态、debug events 和诊断信息。
- Android App：`mobile/android/` 是原生 Kotlin + Jetpack Compose App，通过 `/mobile/*` 和 `/mobile/ws` 接入后端，不是 `/test` 控制台封装。

## 快速开始

### 1. 安装依赖

PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Bash:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

至少需要设置：

| 变量 | 用途 |
| --- | --- |
| `OPENROUTER_API_KEY` | 聊天、记忆、世界模型调用 |
| `ADMIN_TOKEN` | 调试台和管理接口鉴权 |
| `PLATFORM_TOKEN` | 非本机平台消息入口鉴权 |
| `MOBILE_TOKEN` | Android App 的 `/mobile/*` 和 `/mobile/ws` 鉴权 |
| `MOBILE_DEFAULT_SESSION_ID` | Android App 使用的后端会话，默认 `mobile:neno` |
| `MIMO_API_KEY` | 选择层、部分世界/反思模型使用 |

`PLATFORM_TOKEN` 未配置时，非本机平台请求会被拒绝；本机 OpenClaw bridge 仍可走 loopback（回环）绕过。

### 3. 启动服务

默认只监听本机：

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开调试台：

```text
http://127.0.0.1:8000/test
```

如确实需要局域网或公网访问，先确认 `ADMIN_TOKEN` 和 `PLATFORM_TOKEN` 已配置，再显式改成：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 常用命令

```bash
# 全量测试
python -m pytest -q

# 语法编译检查
python -m compileall -q app scripts tests

# 检查依赖环境是否冲突
python -m pip check

# Git whitespace 检查
git diff --check

# Android App 单元测试和 debug APK
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest
.\mobile\android\gradlew.bat -p .\mobile\android :app:assembleDebug
```

世界 LLM 开关脚本（Windows PowerShell）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\neno-llm.ps1 status
powershell -ExecutionPolicy Bypass -File scripts\neno-llm.ps1 on
powershell -ExecutionPolicy Bypass -File scripts\neno-llm.ps1 off
```

`scripts\neno-llm.ps1` 默认用 `127.0.0.1` 重启 uvicorn。需要覆盖监听地址时设置 `NENO_UVICORN_HOST`。

## 运行入口

| 入口 | 鉴权 | 说明 |
| --- | --- | --- |
| `GET /` | 无 | 健康检查 |
| `GET /test` | 无 | 调试控制台页面 |
| `POST /chat` | 无 | Web/控制台聊天入口，建议只本机监听 |
| `POST /platform/openclaw/message` | loopback 或 `X-Platform-Token` | OpenClaw 平台消息入口 |
| `GET /mobile/status` | `Authorization: Bearer <MOBILE_TOKEN>` | Android App 连接检测 |
| `GET /mobile/conversations` | `Authorization: Bearer <MOBILE_TOKEN>` | Android App 对话列表 |
| `GET /mobile/conversations/{id}/messages` | `Authorization: Bearer <MOBILE_TOKEN>` | Android App 消息历史和状态提示 |
| `POST /mobile/conversations/{id}/messages` | `Authorization: Bearer <MOBILE_TOKEN>` | Android App 发送消息，当前只支持 `neno` |
| `WS /mobile/ws` | `Authorization: Bearer <MOBILE_TOKEN>` | Android App 前台长连接，推送 `hello`、`presence`、`pong` |
| `/memory/*` | `X-Admin-Token` | 记忆管理 |
| `/session/*` | `X-Admin-Token` | 会话查询和清理 |
| `/proactive/*` | `X-Admin-Token` | 主动消息配置、候选、发送 |
| `/debug/*` | `X-Admin-Token` | 诊断、事件、世界调试 |
| `/config/update` | `X-Admin-Token` | 写 `.env` 中允许更新的配置 |

## 核心架构

主聊天链路：

```text
HTTP/Web/Platform
  -> 输入归一化
  -> SessionAggregationController 聚合连续消息
  -> SessionSubmitController 串行化同一 session
  -> load_chat_contexts()
  -> process_memory_candidate()
  -> build_chat_messages()
  -> generate_chat_reply()
  -> SQLite 落库和状态更新
```

关键文件：

| 区域 | 文件 |
| --- | --- |
| FastAPI 入口 | `app/main.py` |
| 路由 | `app/routers/` |
| 聊天编排 | `app/services/chat/turn_orchestrator.py` |
| 上下文组装 | `app/services/chat/context_builder.py` |
| LLM 网关 | `app/services/chat/llm_gateway.py` |
| SQLite 访问 | `app/storage/db.py` |
| 关系状态 | `app/storage/relationship.py`, `app/services/relationship_service.py` |
| 主动消息 | `app/services/proactive/`, `app/services/proactive_service.py` |
| Living World | `app/services/consciousness/` |
| 调试台前端 | `app/static/` |
| Android App | `mobile/android/` |

## 状态模型

Neno 的状态不是都在 prompt 里，也不是都在内存里。

| 状态 | 存储 | 所有权 |
| --- | --- | --- |
| 聊天消息 | SQLite `messages` | `app/storage/db.py` |
| 记忆 | SQLite `memories` / `long_term_memory` | 记忆服务和反思引擎 |
| 关系 | SQLite `relationship_state` | `relationship_service` |
| 内在状态 | SQLite `agent_state` | `StateStore` 单写者 |
| 世界状态 | SQLite `life_world_state` | `WorldStore` / `WorldLoop` |
| 活动片段 | SQLite `life_activity_episodes` | `ActivityEpisodeStore` |
| 内在经历 | SQLite `inner_experience_log` | `ExperienceRecorder` |
| 历史摘要 | `data/history_digest/*.json` | `history_digest.py` |
| 聚合队列/提交锁 | 进程内存 | `SessionAggregationController` / `SessionSubmitController` |

不要引入 Redis 或外部队列来替换这些边界，除非先重设整个一致性模型。

## Living World

Living World 是后端正式运行的一套持久生活系统，不是演示 prompt。正式入口是 `WorldLoop.tick()`，世界事实写入 `life_world_state`。

当前已经具备：

- 房间、物品、世界时钟、金钱、计划、事件和近期行动。
- 睡眠/醒来、精力变化、跨天和活动片段。
- `self_context`：世界引擎维护“此刻的你”，聊天只读使用。
- 自我库：从真实经历和反思中结晶 `subject="neno"` 的自我事实。
- 意图通道：用户消息进入世界为意图候选，由世界 LLM 决定做不做。
- pending 消息：睡着或选择暂不回时，消息会攒进世界，稍后再处理。

常用调试端点：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/debug/consciousness/world-live` | 只读世界快照 |
| `POST` | `/debug/consciousness/world-tick` | 手动推进一次正式 `WorldLoop.tick()` |
| `GET` | `/debug/consciousness/events` | 查看世界/意识事件 |

关键开关：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CONSCIOUSNESS_WORLD_LOOP_ENABLED` | `false` | 是否注册常驻世界 tick |
| `CONSCIOUSNESS_WORLD_LLM_ENABLED` | `false` | WorldBrain 是否允许真实模型调用 |
| `CONSCIOUSNESS_WORLD_PLANNER_ENABLED` | `false` | DailyPlanner 是否允许真实模型调用 |
| `CONSCIOUSNESS_SELF_CONTEXT_LLM_ENABLED` | `false` | 是否允许 LLM 重写 self_context |

完整说明见 [`docs/living-world.md`](docs/living-world.md)。

## Prompt 和缓存红线

`app/services/chat/context_builder.py` 的顺序是成本和行为红线：

```text
system: SYSTEM_PROMPT + history_digest
history: 近期原文历史
user: self_context / 关系 / 记忆 / 时间 / 对方刚说
```

动态内容不能移动到历史之前，否则 Anthropic cache（缓存）前缀会被打断，成本和延迟都会变差。

当轮提取出的新记忆和关系变化不会影响当轮回复，只能下一轮生效。这是 1-turn lag（单轮延迟）契约。

## 开发边界

修改前先读：

- `NENO.md`
- `NENO_ARCHITECTURE.md`
- 涉及 Living World 时再读 [`docs/living-world.md`](docs/living-world.md)

不要做这些事：

- 不要绕过 `SessionSubmitController` 并发处理同一 `session_id`。
- 不要把 `SessionAggregationController` / `SessionSubmitController` 改成随手的 async queue。
- 不要绕过 `StateStore` 直接写 `agent_state`。
- 不要让聊天侧直接写 `life_world_state`；世界状态进聊天只能走 `self_context` 只读通道。
- 不要把图片/语音原始 payload 直接写入 `messages.content`。
- 不要删除 `/debug`、`debug_events` 或调试台，它们是生产可观测性的一部分。
- 不要随意把服务暴露到 `0.0.0.0`，除非 token 和网络边界已经配置好。

## 项目文档

| 文档 | 用途 |
| --- | --- |
| [`NENO.md`](NENO.md) | AI 协作和修改红线 |
| [`NENO_ARCHITECTURE.md`](NENO_ARCHITECTURE.md) | 运行时拓扑和危险区域 |
| [`docs/living-world.md`](docs/living-world.md) | Living World 当前实现、开关、端点和缺口 |
| [`docs/android-app-design-brief.md`](docs/android-app-design-brief.md) | Android 原生 App 产品和视觉方向 |
| [`docs/android-app-implementation-plan.md`](docs/android-app-implementation-plan.md) | Android App v0 后端 / App 合同和任务记录 |
| [`docs/android-app-handoff.md`](docs/android-app-handoff.md) | Android App 当前实现、验证状态和接手边界 |
| [`docs/codegraph-query-rebuild.md`](docs/codegraph-query-rebuild.md) | 本地 CodeGraph 索引重建流程 |
| [`docs/phase5-presence.md`](docs/phase5-presence.md) | 在场/延迟回复相关设计 |
| [`docs/wx-image-input-route-v1_1.md`](docs/wx-image-input-route-v1_1.md) | 微信图片输入链路 |
| [`docs/archive/README.md`](docs/archive/README.md) | 历史计划、旧设计稿和被当前实现取代的资料索引 |

## 已知注意点

- `requirements.txt` 当前是直接依赖列表，不是锁文件。
- `data/`、`.codegraphcontext/`、venv、缓存目录都不应纳入搜索或提交。
- `scripts/world_live_server.py` 仍保留独立演示逻辑，正式世界以 `WorldLoop` 为准。
- 多 worker / 多实例部署会破坏进程内 session 锁，需要重新设计一致性。
- 当前代码仍有 Pydantic v2 deprecation warnings（弃用警告），但测试通过。
