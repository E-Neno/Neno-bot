# Neno Bot

Neno 是一个有性格的 AI 聊天机器人后端（FastAPI），人格设定为"小傲"——话少、嘴硬、偶尔怼人，不想回的时候可以不回。

核心能力：多阶段关系演进、长期记忆、主动消息、Anthropic 缓存命中、阶段化历史摘要压缩、多平台消息转发。

## 快速开始

```bash
# 1. 安装依赖
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env   # 编辑填入 API key 等

# 3. 启动
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

调试控制台：`http://127.0.0.1:8000/test`

生产环境重启：`sudo systemctl restart emotion-bot`（alias `nereboot`）

## 项目结构

```
app/
├── main.py              # FastAPI 入口，挂载路由和静态文件
├── config.py            # 所有环境变量读取，统一配置入口
├── schemas.py           # Pydantic 模型
├── security.py          # Admin token 验证
├── llm/
│   └── openrouter_client.py   # OpenRouter 调用封装（支持缓存、多模态）
├── routers/             # HTTP 路由
│   ├── chat.py          # 聊天接口
│   ├── context.py       # 上下文预览（调试用）
│   ├── debug.py         # 调试事件、诊断、关键告警
│   ├── memory.py        # 记忆管理
│   ├── platform.py      # 平台消息转发（QQ/WX）
│   ├── proactive.py     # 主动消息接口
│   ├── relationship.py  # 关系状态
│   ├── session.py       # 会话管理
│   ├── stats.py         # 运行统计
│   └── system.py        # 健康检查、配置读写
├── services/
│   ├── chat/
│   │   ├── context_builder.py       # 聊天上下文组装（含缓存断点、digest 注入）
│   │   ├── history_digest.py        # 阶段化历史摘要 + 自动压缩
│   │   ├── llm_gateway.py           # 模型调用网关（路由 + fallback）
│   │   ├── memory_candidate_service.py
│   │   ├── multimodal_input_service.py
│   │   ├── preview_service.py
│   │   ├── turn_orchestrator.py     # 轮次编排（burst merge / submit gate）
│   │   └── voice_asr_service.py
│   ├── chat_service.py              # 聊天主流程
│   ├── relationship_service.py      # 关系阶段判定与提示生成
│   ├── memory_service.py            # 记忆提取与确认
│   ├── memory_context_service.py    # 记忆检索
│   ├── memory_candidate_decision_service.py
│   ├── time_context_service.py      # 时间上下文
│   ├── consciousness/               # 意识层（状态机 + 世界引擎）
│   │   ├── __init__.py               #    ConsciousnessEngine 门面
│   │   ├── config.py                 #    魔法数字集中管理
│   │   ├── models.py                 #    NenoState / StateMutation / Event
│   │   ├── desire.py                 #    表达欲推算模型
│   │   ├── mood.py                   #    二维情绪模型
│   │   ├── state_store.py            #    单写者 + 乐观锁持久化
│   │   ├── perception.py             #    天气 / 热搜 / 时间感知（TTL 缓存 + 降级）
│   │   ├── event_pool.py             #    事件池：双重去重 + 优先级出队 + 24h 过期
│   │   ├── random_events.py          #    虚拟随机事件库（20 条，按时间段概率）
│   │   ├── world_engine.py           #    APScheduler 心跳调度
│   │   ├── brain.py                  #    NenoBrain 三步决策 (规则→判断→生成)
│   │   ├── fragmenter.py             #    文案碎片化 + 打字延迟 + 频控
│   │   ├── interrupt.py              #    三态打断状态机
│   │   └── memory_recall.py          #    关键词记忆召回
│   ├── proactive/                   # 主动消息子系统
│   ├── proactive_service.py
│   ├── proactive_scheduler.py       # 后台定时调度
│   ├── session_aggregation_controller.py  # 消息聚合（防刷屏）
│   ├── session_submit_controller.py       # 提交门控
│   ├── burst_merge_service.py
│   └── stats_service.py
├── storage/
│   ├── db.py            # SQLite 访问层
│   └── relationship.py  # 关系状态持久化
├── prompt/
│   └── prompt_loader.py
├── utils/
│   └── logging_utils.py
└── static/              # 调试台前端（原生 JS，无框架）
    ├── test.html
    ├── test.js
    └── js/              # 各功能模块
```

## 核心特性

### 人格系统

Neno 的人格由 `prompts/system.txt` 定义，核心规则：
- 话少、不主动找话题、不客套
- 可以怼人、嘴硬、表达不耐烦
- 不表现出过度关心或说教
- 可以使用记忆和时间信息，但不显式引用内部系统
- 绝对禁止：提到关系阶段、分数、记忆系统、时间系统等内部信息

### 多阶段关系演进

5 个关系阶段（`prompts/stages/stage_0~4.txt`），从"陌生"到"深度陪伴"：

| 阶段 | 标签 | 对话特征 |
|------|------|----------|
| 0 | 陌生 | 克制简短，1-2句，不装熟 |
| 1 | 初步熟悉 | 自然回应，偶尔主动，轻微闲聊 |
| 2 | 稳定聊天对象 | 放松随意，可以怼人，有自己的节奏 |
| 3 | 比较亲近 | 直接、少解释，可以沉默，可以玩笑 |
| 4 | 深度陪伴 | 懒得表演，想怼就怼，熟了不等于变温柔 |

关系状态由 4 个维度计算：熟悉度、信任度、情绪深度、边界稳定度。

### Anthropic 缓存命中

- 系统提示词（人格 + 关系 + 时间 + 记忆 + 历史摘要）打包为 content blocks，最后一块标记 `cache_control: {"type": "ephemeral"}`
- 仅 `anthropic/` 模型通过 `provider: {order: ["Anthropic"]}` 锁定 Anthropic 直连（避免 Bedrock 更高的缓存阈值）
- 非 Anthropic 模型（DeepSeek、GPT）不走 provider lock

### 阶段化历史摘要

`app/services/chat/history_digest.py`：

- 每 ~1000 token 将新消息增量烘焙到缓存前缀
- 累计 ~10000 token 触发 LLM 压缩（DeepSeek V4 Flash free 主，付费版 fallback）
- 两个模型都失败时记录 critical 事件并返回原文兜底
- 存储：`data/history_digest/{session_id}.json`
- 调试台诊断卡片 `/debug/diagnose` 可查看压缩状态
- 前端每 30 秒轮询 `/debug/alerts`，critical 事件弹窗提示

### 主动消息

后台调度器按规则判断是否主动给用户发消息（QQ/微信）：
- 支持 observe / candidate / dry_run / auto 四种模式
- 时间窗、每日上限、最小间隔、随机概率等多重约束
- 调试台可手动生成测试候选、查看发送历史

### 记忆系统

- 每轮对话自动提取候选记忆
- 基于相似度检索相关记忆注入上下文
- 调试台支持确认/忽略候选记忆

## 环境变量

核心配置（`.env`）：

| 变量 | 说明 |
|------|------|
| `OPENROUTER_API_KEY` | OpenRouter API 密钥 |
| `OPENROUTER_BASE_URL` | OpenRouter 地址 |
| `OPENROUTER_PROXY` | OpenRouter 请求代理（可选，仅受限地区需要） |
| `OPENROUTER_CHAT_MODEL` | 聊天模型 |
| `OPENROUTER_VISION_MODEL` | 视觉模型 |
| `OPENROUTER_MEMORY_MODEL` | 记忆提取模型 |
| `HISTORY_LIMIT` | 对话历史上限（条数） |
| `MEMORY_LIMIT` | 记忆检索上限（条数） |
| `ADMIN_TOKEN` | 调试台/管理接口鉴权 |
| `PLATFORM_TOKEN` | 平台消息转发鉴权 |
| `CONSCIOUSNESS_JUDGE_MODEL` | 意识层判断模型（Step2） |
| `CONSCIOUSNESS_GENERATE_MODEL` | 意识层生成模型（Step3） |
| `CONSCIOUSNESS_DREAM_MODEL` | 意识层梦境模型（Phase 4 占位） |

## 平台接入

支持 QQ 和微信双平台消息转发（`/platform/*`），通过 OpenClaw 桥接。

微信图片输入路线：图片事件 → 本地文件 → base64 data: URL → OpenRouter 多模态 → 文本归一化 → 聊天主链。

当前暂不支持：语音、TTS、图片生成、视频。

## 开发注意事项

- `.env` 不提交到 git
- 修改 prompt 后需重启服务：`nereboot`
- 模型配置变更后需重启
- 调试台仅限本地使用，不要暴露到公网
- 测试脚本放 `tmp/`，不提交
