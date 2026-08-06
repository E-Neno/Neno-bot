# Operit Neno 好友第一阶段实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框跟踪进度。

**目标：** 在 Operit `v1.12.0` 中增加一个持久化的 Neno 特殊角色，完成后端历史增量同步、在线文本消息和可扩展事件协议的最小闭环。

**架构：** `neno-companion` 提供版本化设备 API；Operit 使用独立 transport 和 repository，把远程历史镜像到原生 Room。Neno 条目复用角色列表和聊天 UI，但通过显式类型绕过角色卡 prompt 与 Operit 模型链。

**技术栈：** Kotlin、Jetpack Compose、Room、Ktor/OkHttp（按上游现状选用）、FastAPI、Pydantic、SQLite、pytest、JUnit。

---

### 任务 1：建立固定 Release fork

**文件：**
- 创建：`C:\Users\hxie7\Desktop\operit-neno\`
- 创建：`C:\Users\hxie7\Desktop\operit-neno\docs\neno-integration.md`

- [ ] 克隆 `AAswordman/Operit` 的 `v1.12.0` tag 到独立目录。
- [ ] 创建 `codex/neno-remote-friend` 分支并保留 `upstream` remote。
- [ ] 读取上游 `AGENTS.md` 与构建说明，记录 Java、Gradle、Android SDK 基线。
- [ ] 运行上游允许的最小测试或 Gradle 配置检查，保存原始结果。

### 任务 2：定义后端设备协议

**文件：**
- 创建：`C:\Users\hxie7\Desktop\neno-companion\app\schemas\device_protocol.py`
- 创建：`C:\Users\hxie7\Desktop\neno-companion\app\routers\device.py`
- 创建：`C:\Users\hxie7\Desktop\neno-companion\tests\unit\test_device_protocol.py`
- 修改：`C:\Users\hxie7\Desktop\neno-companion\app\main.py`

- [ ] 先写失败测试，锁定协议版本、消息游标、`client_message_id`、媒体引用和工具事件解析。
- [ ] 运行测试，确认因设备协议模块缺失而失败。
- [ ] 实现 Pydantic discriminated union 和 `/mobile/device/*` 路由最小骨架。
- [ ] 重跑定向测试，确认协议 round-trip 和错误校验通过。

### 任务 3：定位并扩展 Operit 会话类型

**文件：**
- 测试和实现路径以 `v1.12.0` 实际 Room entity、角色列表 ViewModel 与导航代码为准，定位结果必须先写入 `docs/neno-integration.md`。

- [ ] 只读追踪角色卡列表到聊天服务的调用链，确定最小扩展点。
- [ ] 先写 JUnit 测试：`NENO_REMOTE` 不产生角色卡 prompt，且固定映射到唯一会话键。
- [ ] 运行测试并确认缺少远程会话类型。
- [ ] 实现显式会话来源枚举和特殊角色 descriptor，不修改普通角色卡行为。
- [ ] 重跑定向测试和相关原生测试。

### 任务 4：本地缓存与增量同步

**文件：**
- 创建或修改路径按上游现有 repository/Room 结构落位。

- [ ] 先写 repository 测试：缓存立即返回、远程消息按游标合并、重复消息幂等、后端身份隔离。
- [ ] 运行测试确认失败。
- [ ] 实现 Neno remote repository，复用现有消息 entity，附加远程 ID、后端 ID 和同步状态。
- [ ] 实现草稿保存；离线状态禁止发送且不创建待发队列。
- [ ] 重跑 repository 与数据库迁移测试。

### 任务 5：在线文本闭环

**文件：**
- 创建：Operit 的 Neno HTTP/WebSocket transport、连接设置和 adapter 文件。
- 修改：角色列表、聊天 ViewModel 与依赖注入入口。

- [ ] 先写 transport fixture 测试：Token Header、增量事件、断线状态和重复 ack。
- [ ] 运行测试确认失败。
- [ ] 实现 HTTP 同步和 WebSocket 事件客户端；Token 存 Android Keystore。
- [ ] 把 Neno 特殊条目接入角色列表，点击进入固定会话并绕过 Operit 模型链。
- [ ] 使用本地合成后端完成发送、回复、重启缓存和增量同步测试。

### 任务 6：验证与阶段收尾

- [ ] 运行 Operit 定向 JUnit、lint/compile 和可用的 debug APK 构建。
- [ ] 运行 `neno-companion` 设备协议及现有聊天回归测试。
- [ ] 安装或使用模拟器验证特殊角色、断线草稿、在线发送和本地恢复。
- [ ] 更新工作记录，列出第二阶段多媒体、工具与 Tavern 兼容入口的准确文件位置。

