# 陪伴 Neno 独立分叉实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 创建可独立运行的 `neno-companion`，使用陪伴版 prompt 并默认不启动世界/主动生活系统。

**架构：** 在原项目增加默认关闭的陪伴模式配置，原 Neno 行为保持不变。复制项目到兄弟目录后，仅在陪伴副本中启用该模式、使用独立端口和本地状态；桥接副本预设为指向陪伴端口，但不触碰现有 OpenClaw 安装。

**技术栈：** Python、FastAPI、SQLite、python-dotenv、PowerShell、OpenClaw 插件。

---

## 文件结构

- 修改：`app/config.py`，读取陪伴模式和可覆盖的 system prompt 路径，默认保持原行为。
- 修改：`app/main.py`，陪伴模式下不启动 ConsciousnessEngine 与主动调度器。
- 创建：`tests/unit/test_companion_mode.py`，锁定默认模式与陪伴模式的配置/启动行为。
- 创建：`C:\Users\hxie7\Desktop\neno-companion\`，完整但独立的陪伴项目副本。
- 修改：`C:\Users\hxie7\Desktop\neno-companion\.env`，启用陪伴 prompt 与关闭世界、主动、类真人决策开关；不输出其内容。
- 修改：`C:\Users\hxie7\Desktop\neno-companion\openclaw-plugins\neno-bridge\index.js`，让桥 endpoint 可由环境变量覆盖，默认陪伴端口 `8010`。
- 创建：`C:\Users\hxie7\Desktop\neno-companion\scripts\start-companion-backend.ps1`，启动陪伴版的本地后端。

### 任务 1：增加受控陪伴模式

**文件：**
- 修改：`app/config.py:95`
- 修改：`app/main.py:33-50`
- 创建：`tests/unit/test_companion_mode.py`

- [ ] **步骤 1：写失败测试**

```python
def test_companion_mode_defaults_off(monkeypatch):
    monkeypatch.delenv("NENO_COMPANION_MODE", raising=False)
    module = import_config_module()
    assert module.COMPANION_MODE is False


def test_companion_mode_reads_prompt_override(monkeypatch):
    monkeypatch.setenv("NENO_COMPANION_MODE", "true")
    monkeypatch.setenv("NENO_SYSTEM_PROMPT_PATH", "prompts/neno_companion_prompt.md")
    module = import_config_module()
    assert module.COMPANION_MODE is True
    assert "明确是 AI" in module.SYSTEM_PROMPT
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest -q tests/unit/test_companion_mode.py`

预期：FAIL，提示 `COMPANION_MODE` 不存在。

- [ ] **步骤 3：实现最小配置和启动分支**

```python
# app/config.py
COMPANION_MODE = _env_bool("NENO_COMPANION_MODE", False)
SYSTEM_PROMPT_PATH = os.getenv("NENO_SYSTEM_PROMPT_PATH", "prompts/system.txt").strip() or "prompts/system.txt"
SYSTEM_PROMPT = load_text(SYSTEM_PROMPT_PATH)

# app/main.py startup_event
if not config.COMPANION_MODE:
    start_proactive_scheduler()
    _consciousness = ConsciousnessEngine(db=None, scheduler=_scheduler)
    await _consciousness.start()
```

关闭时按同一 `COMPANION_MODE` 条件停止相应组件；数据库与关系表初始化始终保留。

- [ ] **步骤 4：运行测试确认通过**

运行：`python -m pytest -q tests/unit/test_companion_mode.py tests/unit/test_chat_cache_structure.py`

预期：PASS。

- [ ] **步骤 5：提交原项目兼容改动**

```powershell
git add app/config.py app/main.py tests/unit/test_companion_mode.py
git commit -m "feat: 增加陪伴模式运行开关"
```

### 任务 2：创建独立陪伴目录和配置

**文件：**
- 创建：`C:\Users\hxie7\Desktop\neno-companion\`
- 修改：`C:\Users\hxie7\Desktop\neno-companion\.env`
- 修改：`C:\Users\hxie7\Desktop\neno-companion\openclaw-plugins\neno-bridge\index.js`
- 创建：`C:\Users\hxie7\Desktop\neno-companion\scripts\start-companion-backend.ps1`

- [ ] **步骤 1：验证目标目录未存在**

运行：`Test-Path C:\Users\hxie7\Desktop\neno-companion`

预期：`False`；若为 `True`，停止复制并检查目录归属，绝不覆盖既有文件。

- [ ] **步骤 2：复制源码和本机环境，但排除运行状态**

运行：

```powershell
robocopy C:\Users\hxie7\Desktop\neno-bot-local C:\Users\hxie7\Desktop\neno-companion /E /XD .git venv .venv env data node_modules __pycache__ .pytest_cache .mypy_cache .ruff_cache dist build logs backups tmp uploads .codegraphcontext /XF *.db *.sqlite *.sqlite3
Copy-Item C:\Users\hxie7\Desktop\neno-bot-local\.env C:\Users\hxie7\Desktop\neno-companion\.env
```

预期：目标目录有源码与 `.env`，但没有原数据库、摘要、日志、上传文件或 Git 历史。

- [ ] **步骤 3：配置陪伴模式和独立端口**

将下列无敏感配置附加到陪伴 `.env`：

```ini
NENO_COMPANION_MODE=true
NENO_SYSTEM_PROMPT_PATH=prompts/neno_companion_prompt.md
CONSCIOUSNESS_CHAT_SELF_STATE_ENABLED=false
CONSCIOUSNESS_WORLD_LOOP_ENABLED=false
CONSCIOUSNESS_WORLD_LLM_ENABLED=false
CONSCIOUSNESS_WORLD_PLANNER_ENABLED=false
CONSCIOUSNESS_REFLECTION_ENABLED=false
CONSCIOUSNESS_REFLECTION_MODEL_ENABLED=false
CONSCIOUSNESS_EXPRESSION_GATE_ENABLED=false
WORLD_PRESENCE_GATE_ENABLED=false
WORLD_PRESENCE_WX_AUTO_SEND=false
PROACTIVE_ENABLED=false
PROACTIVE_MODE=off
CHAT_SELECTION_LAYER_ENABLED=false
CHAT_EXECUTIVE_LAYER_ENABLED=false
CHAT_MULTILAYER_THINKING_ENABLED=false
BRAIN_INTENT_CONSUMER_ENABLED=false
```

- [ ] **步骤 4：让陪伴桥使用独立 endpoint**

将桥的常量改成：

```js
const ENDPOINT = process.env.NENO_BRIDGE_ENDPOINT ?? "http://127.0.0.1:8010/platform/openclaw/message";
```

创建启动脚本，使用 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8010` 并把日志写入陪伴目录 `logs/`。

- [ ] **步骤 5：配置隔离检查**

运行：

```powershell
Test-Path C:\Users\hxie7\Desktop\neno-companion\data\bot.db
Test-Path C:\Users\hxie7\Desktop\neno-bot-local\data\bot.db
Select-String -Path C:\Users\hxie7\Desktop\neno-companion\.env -Pattern '^NENO_COMPANION_MODE=true$','^NENO_SYSTEM_PROMPT_PATH=prompts/neno_companion_prompt.md$'
```

预期：陪伴库首次启动前不存在，原库保持存在，陪伴模式和 prompt 覆盖均命中。

### 任务 3：启动并验证陪伴聊天闭环

**文件：**
- 验证：`C:\Users\hxie7\Desktop\neno-companion\scripts\start-companion-backend.ps1`
- 验证：`C:\Users\hxie7\Desktop\neno-companion\data\bot.db`

- [ ] **步骤 1：运行陪伴版定向测试**

运行：`python -m pytest -q tests/unit/test_companion_mode.py tests/unit/test_chat_cache_structure.py tests/unit/test_wecom_aibot.py`

工作目录：`C:\Users\hxie7\Desktop\neno-companion`

预期：PASS。

- [ ] **步骤 2：启动陪伴后端**

运行：`powershell -ExecutionPolicy Bypass -File .\scripts\start-companion-backend.ps1`

预期：`127.0.0.1:8010` 监听，首次启动创建 `data\bot.db`。

- [ ] **步骤 3：发送本地平台消息**

运行：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8010/platform/openclaw/message -ContentType 'application/json' -Body '{"platform":"wx","user_id":"companion-smoke","chat_type":"private","message":"今天有点累。"}'
```

预期：HTTP 200，返回非空 `reply` 和以 `wx:private:companion-smoke` 为键的 session。

- [ ] **步骤 4：验证陪伴版状态独立且不启动世界循环**

运行：

```powershell
Test-Path .\data\bot.db
Select-String -Path .\.env -Pattern '^CONSCIOUSNESS_WORLD_LOOP_ENABLED=false$','^NENO_COMPANION_MODE=true$'
```

预期：陪伴数据库存在，配置显式禁用世界循环和启用陪伴模式。

- [ ] **步骤 5：提交陪伴项目初始化**

在 `C:\Users\hxie7\Desktop\neno-companion` 初始化独立 Git 仓库，只提交源码、配置模板、脚本与测试；`.env`、数据、日志和上传文件保持忽略。
