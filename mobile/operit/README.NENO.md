# Operit 客户端

这是 Neno 仓库内置的 Operit Neno fork，源码真相源为本目录。桌面上的旧路径
`C:\Users\hxie7\Desktop\operit-neno` 已在 2026-08-07 迁移并删除。

## 目录边界

- `app/`、`mmd/`、`mnn/`、`quickjs/` 等：Operit 原生 Android 工程和模块。
- Neno 特殊远程好友：通过 `/mobile/*` 进入 Neno 后端，不进入角色卡 Prompt 或 Operit 本地模型链。
- `mobile/android/`：Neno 原生 v0 客户端，和本目录是两个独立产品端，不互相覆盖。
- `D:\OperitNenoBuildMirror`：构建镜像；构建时可从本目录同步源码，不能把镜像当作源码真相源。
- `D:\OperitNenoMerge.work`：迁移前完整快照，保留原文件和原 Git 元数据，用于回滚。

## 构建

C 盘空间有限时，把本目录同步到 D 盘构建镜像后使用原有 Gradle wrapper。构建所需的
`local.properties`、签名配置、`build/` 和 `.gradle/` 都是本机状态，已经保留但不会提交。
不要把 Token、密码或签名配置写入仓库文档。

## Git 历史

迁移时原 Operit Git 元数据改名为 `.operit-git`，包括根仓和已检出子模块的元数据均保留，
但不再形成父仓可见的嵌套 `.git` 边界。父仓负责本目录源码的统一变更；`.operit-git` 仅作本地历史归档。

## 约束

- Android 端只能通过 `/mobile/*` 调用 Neno 后端。
- `/mobile/ws` 只承载连接状态和 presence，不发送聊天正文。
- 不提交真实 `MOBILE_TOKEN`、admin token、platform token、服务器密钥或用户数据。
- 不直接修改 Neno 后端 Prompt 装配顺序、Session 锁、Living World 所有权或 SQLite。

