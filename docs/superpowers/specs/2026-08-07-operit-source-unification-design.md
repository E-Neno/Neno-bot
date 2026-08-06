# Operit 源码统一管理设计

## 目标

把 `C:\Users\hxie7\Desktop\operit-neno` 的完整工作目录迁入
`C:\Users\hxie7\Desktop\neno-bot-local\mobile\operit`，迁移完成后删除原桌面路径。
Neno 后端仓库成为统一工作区，现有 `mobile/android` 保留不变。

## 目录与所有权

- `mobile/android`：原生 Neno Android v0 客户端，继续保留。
- `mobile/operit`：Operit Neno fork 的完整源码、未提交改动、构建产物和本地配置。
- `D:\OperitNenoBuildMirror`：低磁盘压力下的构建镜像，不是源码真相源。
- `D:\OperitNenoMerge.work`：迁移前完整快照，包含原 Git 元数据，用于回滚和完整性复核。

## Git 边界

Operit 工作目录中的根 `.git` 会随目录迁入，但随后改名为 `.operit-git`。这样保留原分支、提交、
对象库和 remote 信息，同时避免 Neno 主仓把 `mobile/operit` 识别为嵌套仓库。父仓负责后续源码管理；
`.operit-git` 仅作为本地历史归档并由 `mobile/operit/.gitignore` 忽略。

迁移时发现的子模块 `.git` 标记同样改名为 `.operit-git`，避免形成嵌套 Git 边界。未初始化子模块
仍保留其空目录和 `.gitmodules` 声明；已检出的子模块文件完整保留。

## 数据与密钥

用户要求完整并入，因此 `build/`、`.gradle/`、APK、`local.properties` 等本地文件物理保留。
Operit 原有 `.gitignore` 继续阻止构建缓存、本地配置、密钥和环境文件进入父仓提交。
迁移和知识记录不得输出其中的 Token、密码或签名配置。

## 迁移与回滚

1. 用 Robocopy 把完整源目录复制到 `D:\OperitNenoMerge.work`。
2. 对比源与快照的文件数和总字节数。
3. 在同一 C 盘内把原目录移动到 `mobile/operit`，确保原路径消失。
4. 改名 Git 元数据，补充统一管理说明。
5. 再次对比目标与快照的文件数和总字节数，并运行 Git/Gradle 只读检查。

任何校验失败都停止后续修改；D 盘快照保持不动，可恢复原路径。

## 验收标准

- 原路径 `C:\Users\hxie7\Desktop\operit-neno` 不存在。
- `mobile/operit` 存在，并与快照在排除迁移说明文件后保持原始文件规模一致。
- Operit 原未提交 Neno 改动仍可在迁入目录中找到。
- Neno 主仓不会把 `mobile/operit` 识别为嵌套 Git 仓库。
- 文档明确源码真相源、构建镜像、回滚快照和后续构建入口。

