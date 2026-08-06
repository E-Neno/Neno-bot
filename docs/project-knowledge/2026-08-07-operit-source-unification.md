# Operit 源码统一管理记录

## 状态

- 日期：2026-08-07
- 状态：已完成本地迁移与 Notion 同步
- 源码真相源：`mobile/operit`
- 原路径：`C:\Users\hxie7\Desktop\operit-neno`（已删除）

## 目标与范围

将 Operit Neno fork 的整个工作目录并入 Neno 主仓，保留源目录中的源码、未提交改动、构建产物、本地配置、子目录 Git 历史和其它工作状态。Neno 原有 Android 客户端 `mobile/android` 保持不变，两个客户端由各自目录负责。

## 已执行决策

- 使用同盘目录移动，将 Operit 工作区放在 `mobile/operit`。
- Operit 根目录及已检出子目录的 `.git` 元数据改名为 `.operit-git`，保留本地历史但解除父仓嵌套 Git 边界。
- `mobile/operit/.gitignore` 忽略 `.operit-git`。
- 构建缓存、APK、`local.properties` 等文件按用户要求物理保留；它们继续由 Operit 忽略规则阻止进入父仓提交。
- `D:\OperitNenoMerge.work` 保留为迁移前完整回滚快照；`D:\OperitNenoBuildMirror` 仅为构建镜像，不是源码来源。

## 验证证据

- 快照原始规模：47,962 个文件，3,265,980,699 字节。
- 迁移后按 `.git` / `.operit-git` 规范化后可比文件：47,961 个。
- 可比文件差异：0。
- `mobile/operit` 存在，桌面原路径不存在。
- 父仓未把 Operit 识别为嵌套仓库；父仓原有未提交改动未清理或回滚。

## 构建入口

在 `mobile/operit` 目录使用仓库已有的 Gradle wrapper 执行定向任务，例如 `./gradlew.bat tasks` 或项目既有测试任务。任何签名、平台 Token、密码和本地用户数据均不写入本记录。

## 限制与后续

- 当前只统一源码目录和 Git 管理边界，没有改变 Neno 后端 Prompt、Session 锁、Living World 或 Android API 合同。
- 后续 Android 改动应以 `mobile/operit` 为 Operit fork 入口，并遵循其 `AGENTS.md` 与 Neno 移动端文档。
- Obsidian MCP 未在当前工具中发现，标记为 `Obsidian sync pending`。
- Notion 已更新[项目总控台中的 Neno 项目页](https://app.notion.com/p/39d6d61a230a8059a4c8c3547ef6cdb5)，并在现有决策库创建[源码统一管理架构决策](https://app.notion.com/p/3b46d61a230a81969cd4ec81ca7fa79f)。未创建新数据库。
