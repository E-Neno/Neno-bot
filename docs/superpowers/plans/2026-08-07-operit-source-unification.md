# Operit 源码统一管理实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 把 Operit Neno fork 的完整工作目录迁入 Neno 主仓，并保留全部本地状态与原 Git 历史。

**架构：** `mobile/operit` 是新的源码真相源；原 `.git` 改名归档，父仓统一管理源码。D 盘保留完整迁移快照和构建镜像，二者都不参与源码所有权。

**技术栈：** Git、PowerShell、Robocopy、Gradle、Android/Kotlin。

---

### 任务 1：创建并校验完整快照

**文件：**
- 读取：`C:\Users\hxie7\Desktop\operit-neno\**`
- 创建：`D:\OperitNenoMerge.work\**`

- [x] 统计源目录文件数与总字节数。
- [x] 使用 Robocopy 完整复制隐藏文件、Git 元数据、构建产物和本地配置。
- [x] 排除复制工具日志后，对比源与快照文件数和总字节数。

### 任务 2：移动项目并统一 Git 边界

**文件：**
- 移动：`C:\Users\hxie7\Desktop\operit-neno` -> `mobile/operit`
- 修改：`mobile/operit/.gitignore`

- [ ] 验证源、目标绝对路径及目标不存在。
- [ ] 使用同一 PowerShell 进程执行同盘目录移动。
- [ ] 确认原路径不存在、目标路径存在。
- [ ] 把目标内 `.git` 标记改名为 `.operit-git`，保留元数据并解除嵌套仓库。
- [ ] 在 Operit `.gitignore` 忽略 `.operit-git` 归档。

### 任务 3：补充统一管理文档

**文件：**
- 创建：`mobile/operit/README.NENO.md`
- 修改：`README.md`
- 修改：`docs/android-app-handoff.md`

- [ ] 记录两个 Android 客户端的职责边界。
- [ ] 标明 `mobile/operit` 是 Operit fork 的源码真相源。
- [ ] 记录 D 盘构建镜像、完整快照、构建命令和密钥边界。

### 任务 4：验证迁移结果

**文件：**
- 读取：`mobile/operit/**`

- [ ] 对比迁入目录与快照的原始文件数和字节数。
- [ ] 检查 Neno 主仓 Git 状态，确认没有嵌套仓库警告。
- [ ] 在迁入目录运行 Gradle task 列表或既有定向测试，验证工程根路径有效。
- [ ] 运行 `git diff --check`，仅允许既有换行提示。

### 任务 5：同步项目知识

**文件：**
- 创建：`docs/project-knowledge/2026-08-07-operit-source-unification.md`

- [ ] 记录目标、范围、结构决策、迁移证据、限制和下一步。
- [ ] 检测 Notion/Obsidian 连接；可用则搜索并更新既有项目记录，不可用则明确记录 pending。
- [ ] 回读本地记录和所有成功的外部同步结果。

