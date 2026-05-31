# Neno-bot 代码库分析报告

> 本地复刻版，基于 GitHub E-Neno/Neno-bot（commit 1d09042）
> 分析日期：2026-06-01

---

## 一、项目概览

- **技术栈**：FastAPI + SQLite（无ORM） + APScheduler + OpenRouter API
- **代码量**：71 个 Python 文件，1.1MB
- **核心定位**：情感聊天机器人，通过 QQ/微信跟用户聊天

---

## 二、启动流程（main.py）

```
load_dotenv() → configure_safe_logging() → FastAPI()
挂载 /static 静态文件
添加 CORS 中间件（allow_origins=["*"）
注册 10 个路由模块

startup:
  1. init_db() → 创建/迁移 SQLite 表（7+ 张表）
  2. init_relationship_tables()
  3. start_proactive_scheduler() → APScheduler

shutdown:
  stop_proactive_scheduler()
```

---

## 三、消息从进入到回复的完整数据流

### 三条入口路径

**路径 A：Web 直连（POST /chat）**
```
用户请求 → chat.py:chat() → run_chat_turn() → [LLM] → 回复
```

**路径 B：平台消息（POST /platform/openclaw/message）— 完整管线**
```
① openclaw_message()
   ├─ resolve_platform_session_route() → 确定 session_id
   ├─ 判断 should_use_session_submit_controller(platform=="wx")
   └─ 构建 input_record

② preprocess_platform_message()
   ├─ 语音 → ASR 转文字
   ├─ 图片 → Vision 模型 normalize
   └─ 纯文本 → 直透

③ 路由分叉：
   ├─ QQ + BURST_MERGE → BurstMergeService → 合并窗口期消息
   ├─ WX → SessionAggregationController → 批量聚合
   └─ 默认 → 直接 submit

④ run_chat_turn()（核心 turn）
   ├─ load_chat_contexts() → 拼装上下文
   ├─ generate_chat_reply(messages) → LLM 调用
   ├─ add_message() 持久化
   ├─ apply_relationship_update() → 更新关系
   └─ process_memory_candidate() → 记忆处理

⑤ 返回回复
```

---

## 四、上下文拼接顺序（CRITICAL — 不可修改）

```
system content（数组）：
  [1] SYSTEM_PROMPT（prompts/system.txt）
  [2] history_digest（历史压缩摘要）
  [3] cache_control: ephemeral
  [4] relationship_context（关系阶段）
  [5] time_context（时间感知）
  [6] memory_context（记忆检索）

messages 数组：
  [system] → 上面的 blocks
  [history...] → 最近对话（token 裁剪）
  [user] → 当前消息
```

---

## 五、并发控制（三层防护）

| 层 | 模块 | 适用 | 机制 |
|---|---|---|---|
| 1 | BurstMergeService | QQ 等非 WX | 时间窗口合并（12s） |
| 2 | SessionAggregationController | WX | 批量聚合 + seal + 等待所有 source ready |
| 3 | SessionSubmitController 🔒 | 所有（命门） | arrival_seq 严格串行，单 worker |

---

## 六、主动消息系统

### 六级运行模式
off → observe → candidate → dry_run → auto

### 11 条漏斗规则（按顺序）
1. proactive_mode — 模式检查
2. hard_cooldown — 硬冷却期（10min）
3. failure_pause — 连续失败 3 次暂停
4. active_window — 活跃时段 10:30-23:30
5. random_probability — 25% 概率
6. daily_limit — 每日上限 2
7. min_interval — 最小间隔 4h
8. auto_target — 必须有目标
9. recent_chat — 45min 内有用户消息跳过
10. pending_candidate — 已有候选跳过
11. platform_permission — QQ 白名单

### 当前模板（非 LLM 生成）
```python
SAFE_TEMPLATES = [
    "你是不是又在折腾服务器。",
    "喝点水。",
    "别一坐就是几个小时。",
    "今天还顺利吗。",
    "休息一下眼睛。",
    "你那边现在忙不忙。",
]
```

---

## 七、Prompt 系统

### system.txt 核心设定
- 20 岁出头女生
- 短句、克制、自然、松弛
- 小傲、嘴硬、不刻薄
- 绝对禁止：自称 AI、客服语气、油腻甜蜜

### 5 级关系阶段
| Stage | 名称 | 风格 |
|-------|------|------|
| 0 | 陌生 | 电梯点头，克制简短 |
| 1 | 初识 | 课间搭话，偶尔接玩笑 |
| 2 | 稳定聊天对象 | 网友私聊，可以吐槽 |
| 3 | 比较熟 | 好朋友，直接吐槽 |
| 4 | 深度陪伴 | 懒得回不回，不表演 |

---

## 八、配置项

### API 密钥
- OPENROUTER_API_KEY — 主 LLM 网关
- OPENAI_API_KEY — ASR 备用
- DASHSCOPE_API_KEY — 通义千问 ASR

### 模型配置
- CHAT_MODEL_NAME — 聊天模型
- VISION_MODEL_NAME — 视觉模型
- MEMORY_MODEL_NAME — 记忆模型
- HISTORY_TOKEN_LIMIT — 500 tokens

### 安全
- ADMIN_TOKEN — 管理端鉴权
- PLATFORM_TOKEN — 平台消息鉴权（localhost 自动绕过）

---

## 九、API 路由清单（10 个路由模块）

**Chat**: POST /chat
**Platform**: POST /platform/message, routing-override
**Proactive**: 13 个端点（candidates/status/targets/events/check-now/run-once/config/generate/send...）
**Memory**: 8 个端点（add/delete/update/list/relevant/disable/enable/confirm）
**Relationship**: state/reset/update
**Session**: messages/list/clear/delete-message
**Context**: time
**Debug**: 7 个端点（chat-preview/session-submit/aggregation/memory-preview/events/health）
**Stats**: summary
**System**: / /config /config/update /test

---

## 十、依赖

```
fastapi, uvicorn, requests, python-dotenv, pydantic, httpx, pytest, pilk, dashscope
```

---

## 十一、存储层

- **SQLite**，路径 `data/bot.db`，无 ORM，纯 SQL + `sqlite3.Row`
- **7+ 张表**：messages, memories, chat_stats, proactive_candidates/targets/events, debug_events, platform_routing_overrides, relationship_state
- **增量迁移**：`PRAGMA table_info` 检测列是否存在，缺失则 ALTER TABLE
- **连接管理**：每次操作独立连接 + 自动 commit

---

## 十二、LLM 调用链路

```
run_chat_turn()
  → generate_chat_reply()
    → request_model_response()
      → chat_with_openrouter()
        → requests.post("https://openrouter.ai/api/v1/chat/completions")
```

- **同步调用**（requests，非 httpx/aiohttp）
- **默认超时 60s**
- **无重试机制**
- **Anthropic 特殊处理**：model 以 `anthropic/` 开头时加 provider 参数
- **历史压缩**：用 `deepseek/deepseek-v4-flash:free`，主备两级 fallback

---

## 十三、部署架构

```
FastAPI (uvicorn)
  ├─ 10 个路由模块
  ├─ SQLite (data/bot.db)
  ├─ APScheduler (主动消息调度)
  └─ neno-bridge (18793 端口)
       ├─ QQ: /proactive/send-qq
       └─ WX: /proactive/send-wx
```

---

## 十四、新增 consciousness 模块的集成点

基于架构分析，新模块需要对接的现有接口：

1. **llm_gateway.py** → `request_model_response()`，新增模型 key 映射
2. **proactive/engine** → `check_and_send_once()`，替换模板为意图消费
3. **memory_service.py** → 复用记忆 CRUD，新增结构化条目
4. **context_builder.py** → 在 SYSTEM_PROMPT 后注入动态状态段
5. **chat_service.py** → 回复后把用户交互作为 P0 事件
6. **main.py** → lifespan 启停 ConsciousnessEngine
