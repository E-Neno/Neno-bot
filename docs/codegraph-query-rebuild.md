# CodeGraphContext Rebuild Guide

本文件用于重建 `codegraph-query` 使用的本地代码图谱索引：

```text
.codegraphcontext/codegraph.kuzu
```

目标是让 agent 以后不再依赖旧的 Linux-only wrapper，也不启动 `cgc mcp start`。

## 适用场景

- `.codegraphcontext/` 被删除或损坏。
- 代码结构发生较大变化，需要刷新索引。
- 新机器第一次启用 `codegraph-query`。
- 查询结果明显过旧。

## 约束

- 不启动 MCP server：不要运行 `cgc mcp start`。
- 不索引运行时数据、虚拟环境、缓存、数据库、`.git/`、`.codegraphcontext*/`。
- Windows 下先设置 UTF-8，避免 `cgc` 读取配置或 `.env` 时出现 GBK 解码警告。
- 默认只索引源码范围，不索引 `app/static/`、二进制、上传文件和数据目录。

## 预检查

在仓库根目录运行：

```powershell
$env:PYTHONUTF8 = "1"
cgc version
cgc doctor
git rev-parse HEAD
```

确认 `.cgcignore` 至少包含这些规则：

```gitignore
node_modules/
venv/
.venv/
env/
.env
.env.*
data/
logs/
backups/
tmp/
uploads/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.git/
.agents/
.claude/
.codegraphcontext/
.codegraphcontext*/
*.kuzu
*.db
*.sqlite
*.sqlite3
dist/
build/
```

## Windows 本机快速重建

这是当前仓库推荐流程。

### 1. 准备临时构建目录

```powershell
$env:PYTHONUTF8 = "1"
$Root = (Get-Location).Path
$Build = Join-Path $env:TEMP ("neno-codegraph-" + (Get-Date -Format "yyyyMMddHHmmss"))
$Out = Join-Path $Build ".codegraphcontext"
$Db = Join-Path $Out "codegraph.kuzu"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
```

### 2. 索引源码范围

逐个目录索引，失败时更容易定位是哪一块卡住。

```powershell
$Targets = @(
  "app/services",
  "app/storage",
  "app/routers",
  "app/llm",
  "app/prompt",
  "app/utils",
  "tests/unit",
  "tests/integration",
  "scripts",
  "prompts"
)

foreach ($Target in $Targets) {
  if (Test-Path -LiteralPath $Target) {
    cgc --db kuzudb --db-path $Db index $Target
  }
}
```

如果 `prompts` 很慢或失败，可以先跳过；核心代码查询主要依赖 `app/`、`tests/`、`scripts/`。

### 3. 生成 manifest

```powershell
$Commit = git rev-parse HEAD
$Manifest = @{
  version = "1.0.0"
  commit = $Commit
  build_time = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  build_host = $env:COMPUTERNAME
  cgc_version = (cgc version | Select-Object -Last 1)
  db_engine = "kuzudb"
  db_type = "file"
  db_file = "codegraph.kuzu"
  scope = $Targets
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $Out "manifest.json")
Copy-Item -LiteralPath ".cgcignore" -Destination (Join-Path $Out ".cgcignore") -Force
```

### 4. 原子替换旧索引

先备份旧目录，再移动新目录。

```powershell
$Final = Join-Path $Root ".codegraphcontext"
$Prev = Join-Path $Root (".codegraphcontext.prev-" + (Get-Date -Format "yyyyMMddHHmmss"))

if (Test-Path -LiteralPath $Final) {
  Move-Item -LiteralPath $Final -Destination $Prev
}

Move-Item -LiteralPath $Out -Destination $Final
```

如果验证失败，可以回滚：

```powershell
Remove-Item -LiteralPath ".codegraphcontext" -Recurse -Force
Move-Item -LiteralPath $Prev -Destination ".codegraphcontext"
```

## 验证

```powershell
$env:PYTHONUTF8 = "1"
cgc --db kuzudb --db-path ".codegraphcontext\codegraph.kuzu" list
cgc --db kuzudb --db-path ".codegraphcontext\codegraph.kuzu" find content self_context
cgc --db kuzudb --db-path ".codegraphcontext\codegraph.kuzu" find name WorldLoop
```

期望：

- `list` 能看到 `services`、`storage`、`routers`、`unit`、`integration` 等项目。
- `find content self_context` 能返回 `self_context.py`、`world_loop.py` 或相关测试。
- 没有 GBK 解码警告；如果有，确认 `$env:PYTHONUTF8 = "1"` 已设置。

## 查询默认命令

重建完成后，agent 应始终用这种形式查询：

```powershell
$env:PYTHONUTF8 = "1"
cgc --db kuzudb --db-path ".codegraphcontext\codegraph.kuzu" find content <keyword>
```

不要使用：

```powershell
scripts/cgc-query.sh
cgc mcp start
```

## CI / Bundle 流程

仓库仍保留两个 Bash 脚本：

- `scripts/build_codegraph.sh`
- `scripts/install_codegraph_bundle.sh`

它们适合 Linux CI 或远端服务器使用。Windows 本机如果没有稳定 Bash、tar、Python 路径兼容，优先使用上面的 PowerShell 快速重建流程。

CI 构建需要环境变量：

```bash
export GITHUB_SHA="$(git rev-parse HEAD)"
export GITHUB_WORKSPACE="$(pwd)"
export CGC_BIN="cgc"
scripts/build_codegraph.sh
```

安装 bundle：

```bash
CGC_REPO_ROOT="$(pwd)" scripts/install_codegraph_bundle.sh codegraph-${GITHUB_SHA}.tar.gz
```

注意：bundle installer 会校验 manifest 里的 commit 是否等于当前 `HEAD`。

## 常见问题

### `cgc` 报 GBK 解码警告

先设置：

```powershell
$env:PYTHONUTF8 = "1"
```

不要为了消除警告去改真实 `.env`。

### 全仓库索引很慢或超时

不要全仓库索引。按本文的 `$Targets` 白名单索引源码目录即可。

### 查询结果为空

先跑：

```powershell
cgc --db kuzudb --db-path ".codegraphcontext\codegraph.kuzu" list
```

如果 `list` 没有项目，说明索引构建失败或 DB 路径不对。

### `.codegraphcontext` 没出现在 git status

这是正常的。它是本地生成索引，不应该提交。

### 需要重装 `cgc`

当前验证过的版本是 `CodeGraphContext 0.4.11`。Windows 下可用：

```powershell
python -m pip install --force-reinstall "codegraphcontext==0.4.11"
```

重装后运行：

```powershell
$env:PYTHONUTF8 = "1"
cgc doctor
```
