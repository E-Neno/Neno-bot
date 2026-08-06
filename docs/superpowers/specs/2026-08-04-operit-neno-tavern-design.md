# Operit Neno 好友与 Tavern 兼容设计

## 目标

基于 Operit `v1.12.0` 建立独立 Android fork。Neno 作为角色列表中的特殊远程好友，直接连接 `neno-companion`，并复用 Operit 原生消息、媒体、Agent、Root、插件与工具 UI。普通角色卡继续走 Operit 原模型链，并补齐 SillyTavern 运行语义。

## 所有权边界

| 对象 | 真相源 | 客户端职责 |
|---|---|---|
| Neno 历史、记忆、关系 | `neno-companion` SQLite | 本地缓存、增量同步、离线草稿 |
| Neno 工具决策 | `neno-companion` | Operit 原生执行与可视化 |
| 普通角色卡历史 | Operit Room | 原生会话管理 |
| 角色卡、世界书、渲染扩展 | Operit | Tavern 解析、选择与沙箱渲染 |

Neno 不使用 OpenAI-compatible Provider，不导入角色卡 prompt，也不经过 Operit 的第二个模型。普通角色卡不读取 Neno 后端状态，不继承 Neno 的自动 Root 权限。

## Neno 客户端模型

- 角色列表中存在一个固定的 `NENO_REMOTE` 条目。
- 可改头像、备注和背景；不可删除、复制、导出或编辑 prompt。
- 每个 `backend_id + account_id` 拥有独立本地缓存。
- 进入会话立即展示缓存，再按消息游标增量同步。
- 断线时允许保存草稿，但发送按钮禁用；恢复连接后不自动发送。
- 消息追加后不可编辑、删除或重新生成；允许仅在本机隐藏。

## 传输协议

HTTP/HTTPS 负责首次同步、分页、附件上传下载和健康检查；WebSocket/WSS 负责实时消息、主动推送、工具调用、执行结果和确认事件。

所有客户端提交带稳定 `client_message_id`，服务端消息带单调递增 `message_id`。工具轮使用 `turn_id + step_id` 保证重连恢复和幂等回传。同一 Neno 会话仍服从后端 Session 串行化；客户端不自行并行推进两个工具步骤。

## 消息类型

协议双向支持文本、Markdown、图片、语音、音频、视频、文件、多附件及结构化工具事件。SQLite 只保存媒体引用和元数据，不保存 base64 或二进制。媒体正文存文件系统，客户端按 LRU 清理本地文件并可重新下载。

后端 TTS 作为独立后续设计；第一阶段保留音频附件协议和 Operit 原生播放器接入。

## Agent 与设备权限

Neno 始终具备 Agent 能力。后端产生通用 `tool_call`，`NenoToolAdapter` 映射到 Operit 原生 Agent Runtime。工具、插件、Root、终端和后台任务均复用原生注册、执行、展示与停止机制；不增加确认弹窗。普通主动聊天不启动设备工具，只有用户会话和用户建立的自动化可执行工具。

## Tavern 兼容层

- Tavern V2/V3 PNG 与 JSON。
- 保留 system prompt、示例、post-history、depth prompt 与 alternate greetings 的位置语义。
- 世界书按 constant、keys、secondary keys、scan depth、priority、probability 和 token budget 动态选择。
- 支持 Markdown、HTML、CSS、JavaScript、Regex Script 与 Quick Replies。
- 角色卡 WebView 可联网，但不获得 Operit Token、Root、文件系统或工具桥。
- Markdown 与 HTML 面板并行流式；脚本按完整块执行；消息完成后旧 DOM 冻结。
- 行动选项默认点击即发送。
- 支持 Chub.ai 公开 URL 导入角色卡与关联世界书，保留来源版本并以 diff 方式更新。

第一阶段不实现真正的多角色群聊。每个角色会话绑定卡片和世界书版本快照；编辑默认只影响新会话。

## 验收资产

- RADISEKAI：验证多开场、关联世界书、折叠状态面板和 CYOA。
- 斗罗卡：验证 285 条世界书、长上下文、行动选项和复杂面板压力。
- 合成协议 fixture：验证文本、媒体、工具、重连和幂等，不依赖真实账号或真实设备数据。

## 实施顺序

1. 固定 Operit Release，建立独立 fork 和构建基线。
2. 在 `neno-companion` 定义设备协议、历史分页和实时事件。
3. 在 Operit 增加 `NENO_REMOTE` 条目、本地缓存与 HTTP/WebSocket 客户端。
4. 复用原生 Agent Runtime 接入通用工具协议和多媒体。
5. 实现 Tavern 结构化运行时、沙箱渲染与 Chub 公开导入。
6. 使用两张真实卡和合成 Neno 后端完成 Android 端到端验收。

