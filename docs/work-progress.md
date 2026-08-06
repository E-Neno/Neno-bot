## 2026-08-03 - 保存 neno 人设 prompt 并检索公开聊天语料

### Current progress
已确认仓库存在 `prompts/` 目录，工作区有大量既有未提交改动。本任务只新增 prompt 文件和本进度记录。

### Objective
保存用户确认的 neno AI 版与非 AI 版完整人设 prompt，并查找适合蒸馏的公开长篇真人聊天语料。

### Scope
新增 `prompts/neno_prompt.md` 与本记录；只读检索公开语料及其许可信息，不下载或提交个人隐私聊天记录。

### Acceptance criteria
- 文件包含 AI 版和非 AI 版完整 prompt，角色名统一为 `neno`。
- 文件内容可读取并通过关键段落检查。
- 输出公开语料候选、来源链接、许可限制和适用性判断。

### Outcome
已新增 `prompts/neno_prompt.md`，包含名字统一为 `neno` 的 AI 版与非 AI 版完整 prompt。公开语料初筛完成：未发现同时满足长篇、真人对真人、许可清晰且可直接商用的公开聊天记录；已核查 OASST1、DailyDialog、PersonaChat 和 EmpatheticDialogues。

### Verification
- `prompts/neno_prompt.md` 存在，包含 AI/非 AI 两个完整区块，回复规则区块出现 2 次。
- 已通过 Hugging Face 数据集 API/README 核对数据规模、来源描述和许可证标签。

### Remaining issues
真人私聊原始数据通常受隐私和版权约束，不能作为无条件蒸馏语料；后续需要按目标用途筛选许可，或自行收集并取得参与者授权。

## 2026-08-03 - 分离陪伴 Neno prompt

### Current progress
已确认 `prompts/neno_prompt.md` 是 AI 版与非 AI 版的设计底稿；运行时当前仍加载 `prompts/system.txt`。工作区有大量既有未提交改动，本任务只新增陪伴版 prompt 并更新本进度记录。

### Objective
从 AI 版底稿整理出一个独立的陪伴 Neno prompt，明确其情感支持职责，同时不把类真人 Neno 的生活状态、主体性表演或隐瞒 AI 身份带入陪伴版本。

### Scope
新增 `prompts/neno_companion_prompt.md`；不修改现有 `system.txt`、运行时配置、数据库或其他用户已有改动。

### Acceptance criteria
- 陪伴版 prompt 明确 Neno 是 AI，并保留可识别的名字、关系和语言风格。
- prompt 覆盖倾听、情绪接住、梳理、陪伴与按需给行动建议的完整支持顺序。
- prompt 明确禁止类真人版本的欺骗性身份、生活状态汇报和刻意冷处理。
- 文件可读取，关键边界和支持规则可通过文本检查确认。

### Outcome
已新增 `prompts/neno_companion_prompt.md`。内容以 AI 版底稿为基础，保留 Neno 的亲近语气和关系感，增加倾听、情绪接住、梳理、陪伴与按需行动建议的顺序；同时明确 AI 身份透明、不过度依赖、不刻意冷处理，并排除类真人版本的生活状态汇报和身份隐瞒。

### Verification
- PowerShell 文本检查通过：`PROMPT_CHECK=PASS`，7 条关键规则全部存在。
- 文本检查确认未出现 `不能让任何人知道你是AI` 或 `你不是AI，你是活人` 等非 AI 身份规则。

### Remaining issues
运行时是否启用该 prompt、以及陪伴版本的独立 session/状态隔离，不在本次 prompt 草案范围内；当前运行时仍加载 `prompts/system.txt`。
## 2026-08-03 - 企业微信智能机器人最小接入

### Current progress
已验证企业微信 WebSocket 订阅认证成功；当前仓库已有平台消息入口和 Session 串行控制器，但平台白名单尚未包含 `wecom`。

### Objective
把企业微信智能机器人凭证放入本机运行环境，新增可测试的长连接适配器，完成认证、消息归一化、去重和文本回复闭环。

### Scope
新增 `app/integrations/wecom_aibot/` 与单元测试；更新 `.env`、`.env.example`、平台白名单。不实现 TTS、媒体上传和语音输出，不修改 Session 控制器。

### Acceptance criteria
- `.env` 含企业微信凭证且不出现在 Git diff。
- 适配器测试覆盖订阅帧、文本归一化、会话映射和去重。
- 真实 WebSocket 认证通过。
- `wecom` 平台消息可以进入现有平台入口。

### Outcome
已新增 `app/integrations/wecom_aibot/`：包含订阅帧、文本回复帧、消息归一化、有限去重、WebSocket 认证/心跳/重连和 Neno 平台入口调用。已将 `wecom` 加入平台白名单，并把凭证写入被 `.gitignore` 忽略的本机 `.env`。真实单聊文本已完成企业微信回调、Neno 平台处理和企业微信文本回复闭环。本阶段未实现 TTS、AMR 转码和媒体上传。

### Verification
- `python -m pytest -q tests/unit/test_wecom_aibot.py` -> 4 passed。
- `python -m compileall -q app/integrations/wecom_aibot` -> 通过。
- `git diff --check` -> 通过（仅有既有 CRLF 警告）。
- 真实 `wss://openws.work.weixin.qq.com` 订阅认证 -> `errcode=0, errmsg=ok`。
- 直接导入完整平台路由检查时，本机缺少 `apscheduler`，未能完成运行时导入验证；白名单已通过源码检查确认。
- 已执行 `python -m pip install -r requirements.txt`，补齐 `apscheduler`、`dashscope`、`pypdf` 等当前环境缺失依赖。
- 启动本地 Uvicorn 后，向 `/platform/openclaw/message` 发送 `platform=wecom` 的合成消息，返回 HTTP 200，session 为 `wecom:private:test-user`；本次主脑选择 `chose_silence`，说明平台路由已接收并进入 Neno 流程。
- 监听器到企业微信的 TLS 连接处于 `Established`，但首次真实发消息未生成新的 `wecom:*` 记录；已加入不含正文和凭证的认证、回调和转发状态日志，以定位企业微信到适配器的断点。
- 第二次真实企业微信单聊：适配器记录消息接收，Neno 平台请求返回 HTTP 200，随后记录文本回复已发送；企业微信回执正常返回。
- 用户侧未看到回复后复查官方出站消息类型：智能机器人普通回复不支持 `text`，此前适配器误用该类型；已新增回归测试，先确认其失败，再将回复改为 `markdown`，同时扩展 ack 日志以记录 `errcode/errmsg`。
- 截图和适配器日志确认，修正 `markdown` 前后用户侧均未见回复的直接原因是 Neno 返回空文本（选择层 + presence gate 允许当前轮静默），不是企业微信出站回执。为完成端到端聊天验证，本机 `.env` 暂时关闭这两项全局门控，随后重启后端；后续应收敛为企业微信专用策略，而不是长期沿用全局开关。

### Remaining issues
`pip check` 仍报告其他全局工具包的既有版本冲突（如 protobuf、websockets），不由本次接入引入；语音回复仍需后续加入 TTS、AMR 转码和企业微信媒体分片上传。

## 2026-08-03 - 陪伴 Neno 独立项目分叉

### Current progress
已存在独立的 `prompts/neno_companion_prompt.md`，但当前运行时仍读取类真人版本的 `prompts/system.txt`，并与其共享状态和服务。微信 OpenClaw 桥已可作为文本入口，并已具备图片和语音输入路径。

### Objective
创建独立的 `C:\Users\hxie7\Desktop\neno-companion` 项目，作为陪伴版 Neno 的运行实体；保留聊天、记忆、多模态输入和微信桥，默认移除类真人生活模拟的运行职责。

### Scope
复制当前仓库到独立目录；为陪伴版设置独立运行配置、状态目录和提示词；关闭世界引擎、生活主动循环及类真人决策路径。暂不删除共享底层模块，暂不实现多媒体回复输出。

### Acceptance criteria
- 陪伴版目录与当前仓库物理隔离，拥有独立的数据库和运行端口配置。
- 默认聊天不读取或启动世界引擎、生活主动循环或类真人身份设定。
- 现有文本聊天、记忆及微信 OpenClaw 桥可继续接入。

### Outcome
已创建 `C:\Users\hxie7\Desktop\neno-companion` 的独立源码副本，并仅在该副本中启用陪伴模式、陪伴 prompt、独立 `8010` 端口和 OpenClaw 桥 endpoint。陪伴模式启动时保留数据库和关系表初始化，但不启动 ConsciousnessEngine、世界循环或主动调度器；配置同时关闭选择层、主脑层和多层思考等类真人路径。陪伴后端已启动并完成本地平台消息闭环，独立数据库已创建。原项目运行实例和 OpenClaw 安装未被改动。

### Verification
- `python -m pytest -q tests/unit/test_companion_mode.py tests/unit/test_chat_cache_structure.py tests/unit/test_wecom_aibot.py`：16 passed, 2 warnings（在陪伴副本中）。
- `127.0.0.1:8010` 已监听，启动日志显示 FastAPI startup complete。
- 向 `/platform/openclaw/message` 发送合成 `wx` 私聊消息，返回 HTTP 200、非空 `reply` 和 `wx:private:companion-smoke` 会话键。
- `C:\Users\hxie7\Desktop\neno-companion\data\bot.db` 已创建；陪伴 `.env` 命中 `NENO_COMPANION_MODE=true`、`CONSCIOUSNESS_WORLD_LOOP_ENABLED=false` 和 `PROACTIVE_ENABLED=false`。

### Remaining issues
复制时带入两个未使用的 `.codegraphcontext.prev-*` 缓存目录和 `.env.bak`；因环境策略拒绝删除操作，尚未清理，且不会参与运行。实际 OpenClaw 运行实例尚未切换到陪伴桥；切换时需在该实例设置 `NENO_BRIDGE_ENDPOINT=http://127.0.0.1:8010/platform/openclaw/message`，然后重载桥接进程。多媒体输出仍未实现，当前只验证文本回复。

### Checkpoint - 验收完成
独立副本、陪伴运行开关、独立端口、独立 SQLite 和本地文本聊天闭环均已验证。后端当前保持在 `127.0.0.1:8010` 运行，等待后续选择是否把某个 OpenClaw 实例切换到陪伴桥。

## 2026-08-04 - Operit Neno 好友与 Tavern 兼容接入

### Current progress
陪伴后端已在独立 `neno-companion` 目录运行；已通过需求审问确定 Neno 是 Operit 角色列表中的特殊远程好友，不是模型 Provider 或普通角色卡。上游最新稳定版为 Operit `v1.12.0`，目标目录 `C:\Users\hxie7\Desktop\operit-neno` 尚不存在。

### Objective
基于 Operit `v1.12.0` 建立独立 fork，接入持久化、增量同步、WebSocket 长连接、多媒体和原生 Agent/Root 工具执行的 Neno 好友；同时保留 Operit 原功能并补齐 Tavern V2/V3、动态世界书、Chub URL 导入和复杂渲染兼容。

### Scope
创建独立 Android 仓库和版本化 Neno 设备协议；修改 `neno-companion` 的移动端接口；优先复用 Operit 原生会话、工具、媒体、后台任务和渲染能力。第一阶段不接微信、不做多角色群聊、二维码绑定或 TTS 方案。

### Acceptance criteria
- Operit 角色列表出现不可导出为角色卡的特殊 Neno 条目，并能持久化展示后端历史。
- 在线时可通过 Token + WebSocket/HTTP 收发文本与媒体，断线只保存草稿、不自动发送。
- Neno 产生的通用工具调用可由 Operit 原生 Agent Runtime 自动执行并回传结果。
- 普通角色卡与 Neno 数据、权限和渲染链隔离；RADISEKAI 与斗罗卡作为兼容验收资产。
- Android 定向测试和后端协议测试通过，并产出可安装调试 APK。

### Outcome
实施中。

### Verification
- 待执行 Android、后端协议和端到端验证。

### Remaining issues
后端 TTS、真正多角色群聊和 Chub 私有账号同步明确不在第一阶段。

### Checkpoint - 实施开始
已确认目标目录为空、上游 Release 为 `v1.12.0`。下一步写入设计与分阶段实施计划，然后克隆固定 tag 并只读定位 Operit 原生扩展点。

### Checkpoint - 2026-08-04 恢复实施

- `C:\Users\hxie7\Desktop\operit-neno` 已固定在 `v1.12.0` 对应提交 `fc76cf5b`，当前分支为 `codex/neno-remote-friend`，官方远端名为 `upstream`。
- 旧计划中的 `/mobile/device/*` 平行路由与现有成熟 `/mobile/*` 链路冲突；实施改为扩展现有移动 API，不建立第二套聊天入口。
- 后端协议与 Android 特殊会话类型按独立文件域并行推进，均遵守先写失败测试、确认红灯、再写最小实现的 TDD 顺序。
- 第一阶段先完成版本化协议、消息游标、提交幂等、`NENO_REMOTE` 固定会话和文本闭环；多媒体、工具执行及 Tavern/Chub 兼容在后续阶段继续。
