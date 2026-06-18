# Neno Bot

Neno 是一个有性格的 AI 聊天机器人后端（FastAPI），人格设定为"小傲"——话少、嘴硬、偶尔怼人，不想回的时候可以不回。

核心能力：多阶段关系演进、长期记忆、主动消息、持续虚拟生活世界、Anthropic 缓存命中、阶段化历史摘要压缩、多平台消息转发。

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
│   ├── debug.py         # 调试事件、诊断、关键告警、意识面板接口
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
│   │   ├── experience_recorder.py     #    内在经历沉淀：写入 / 查询 / 去重 / 状态标记
│   │   ├── life_loop.py               #    Living World 生活循环与 dry-run 预览
│   │   ├── activity_episode_store.py  #    连续生活片段持久化
│   │   ├── life_simulation.py         #    旧生活线确定性决策器
│   │   ├── reflection_engine.py        #    梦境总结、长期记忆写入与状态回注
│   │   ├── virtual_world.json          #    房间、物品、类别与合法状态
│   │   ├── world_model.py              #    世界模型、动态物品与状态变换
│   │   ├── world_store.py              #    世界状态 SQLite 持久化
│   │   ├── world_drift.py              #    不依赖 Neno 意志的自然变化
│   │   ├── action_validator.py         #    世界动作合法性守门
│   │   ├── world_brain.py              #    受约束世界决策器
│   │   ├── daily_planner.py            #    每日生活计划
│   │   ├── day_cycle.py                #    睡眠、醒来和跨天结算
│   │   ├── life_events.py              #    从状态派生的生活事件
│   │   ├── world_loop.py               #    正式世界融合循环
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

Neno 的身份从世界引擎长出来，不在聊天 prompt 里写死（刀①「她自己活成自己」，详见 `docs/living-world.md` §5b）：
- **种子**（`prompts/seed.json`）：唯一预设——名字、18 岁、偏活泼暖松弛的气质，以及「背景靠真实生活长出来、不预设」的原则。确定性注入，聊天始终可见。
- **self_context**：世界引擎用廉价 LLM 维护一段「此刻的你」（在哪、心情、牵挂、跟对方多熟），聊天只读、绝不写回；有防伪硬守门，不会现编学历/职业等身份，也不报原始数值。
- `prompts/system.txt` 只保留声音/聊天方式规则（短句、松弛、不引用内部系统），不再写死人设事实。

### 关系演进（连续化）

关系按四项积分（熟悉 / 信任 / 情感深度 / 边界）累加表征亲近度，从"陌生"到"深度陪伴"，她对你**渐渐放开、不跳档**。
**呈现已连续化**：由分值确定性生成连续短句、并入「此刻的你」动态块；旧的 `prompts/stages/stage_0~4.txt` 离散模板保留未删但**不再被读取**。关系打分/积分漏斗模型未变。

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

### Living World

Neno 拥有一个持久化的小公寓世界。世界包含房间、物品、模拟时间、金钱、
日计划、自然漂移、生活事件、睡眠/醒来和跨天反思。正式入口是
`app/services/consciousness/world_loop.py`，世界状态存入 SQLite
`life_world_state`。

默认配置不会启动常驻循环，也不会调用真实世界模型。可在调试控制台查看
“生活世界 · 新引擎”，或使用：

- `GET /debug/consciousness/world-live`：只读当前世界。
- `POST /debug/consciousness/world-tick`：手动推进一步。

完整架构、运行开关和已知缺口见 [`docs/living-world.md`](docs/living-world.md)。
当前实现是可运行的公寓世界纵向管道；用户消息尚未作为世界事件接入。

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
| `CONSCIOUSNESS_DREAM_MODEL` | ReflectionEngine 反思模型（仅在 `CONSCIOUSNESS_REFLECTION_MODEL_ENABLED=true` 时允许真实调用） |
| `CONSCIOUSNESS_LIFE_LOOP_ENABLED` | Living World 生活循环开关（默认 false） |
| `CONSCIOUSNESS_LIFE_LOOP_INTERVAL_SECONDS` | 生活循环间隔秒数（默认 1200） |
| `CONSCIOUSNESS_REFLECTION_ENABLED` | 梦境总结 / 反思引擎开关（默认 false） |
| `CONSCIOUSNESS_REFLECTION_MODEL_ENABLED` | 反思是否允许真实模型调用（默认 false） |
| `CONSCIOUSNESS_REFLECTION_HOUR` | 每日反思小时（默认 5） |
| `CONSCIOUSNESS_REFLECTION_MINUTE` | 每日反思分钟（默认 0） |
| `CONSCIOUSNESS_EXPRESSION_GATE_ENABLED` | ExpressionGate 预留开关（默认 false，当前未实现） |
| `CONSCIOUSNESS_WORLD_LOOP_ENABLED` | 新世界常驻循环开关（默认 false） |
| `CONSCIOUSNESS_WORLD_LOOP_INTERVAL` | 常驻 tick 的真实秒数间隔（默认 8） |
| `CONSCIOUSNESS_WORLD_SIM_MIN_PER_TICK` | 每次 tick 推进的模拟分钟（默认 30） |
| `CONSCIOUSNESS_WORLD_LLM_ENABLED` | WorldBrain 是否允许真实模型调用（默认 false） |
| `CONSCIOUSNESS_WORLD_PLANNER_ENABLED` | DailyPlanner 是否允许真实模型调用（默认 false） |
| `OPENROUTER_WORLD_MODEL` | 世界决策和日计划使用的模型 |
| `CONSCIOUSNESS_WORLD_LLM_TIMEOUT` | 世界模型调用超时秒数（默认 20） |
| `BRAIN_INTENT_CONSUMER_ENABLED` | brain intent 消费器总开关（默认 false，灰度前关闭） |
| `BRAIN_WHITELIST_USERS` | brain intent 发送白名单（逗号分隔 user_id，空=全量关闭） |

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
- `.env` 可能覆盖代码默认值；启动世界引擎前应确认三个 `CONSCIOUSNESS_WORLD_*_ENABLED` 开关
