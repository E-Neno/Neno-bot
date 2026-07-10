# Phone Agent v0 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 构建手机智能体 v0 的最小闭环：PC Web 控制台下任务，Android 原生 APK 观察手机状态并执行低风险动作，双方通过 WebSocket 协议同步状态、动作和确认请求。

**架构：** PC 控制台只作为高级驾驶舱；Android APK 是日常聊天入口、权限承载和本机执行器。v0 不接触触摸驱动，不调用 Neno 的 `/mobile/*` 聊天接口，不修改 Neno 主聊天状态机；新增的 agent 协议独立于现有 Neno 会话链路。

**技术栈：** 后端 FastAPI WebSocket + Pydantic schema；Android Kotlin + Jetpack Compose + OkHttp WebSocket；PC 静态控制台继续使用 `app/static/agent-shell.html`。

---

## 文件结构

- 创建：`docs/phone-agent-protocol.md`
  - 职责：记录 Web 控制台、Android APK、controller 之间的 v0 消息协议、状态机、风险分级和确认流程。
- 创建：`app/phone_agent_schemas.py`
  - 职责：定义 Python 侧协议模型，覆盖观察、动作、确认、状态和错误。
- 创建：`app/routers/phone_agent.py`
  - 职责：提供 `/agent/ws` WebSocket 调试通道；v0 只做本机开发连接和消息转发，不进入 Neno 聊天主链路。
- 修改：`app/main.py`
  - 职责：注册 `phone_agent.router`。
- 创建：`tests/integration/test_phone_agent_protocol.py`
  - 职责：验证 schema 字段、风险等级和基础 WebSocket 握手。
- 创建：`mobile/android/app/src/main/java/com/neno/app/agent/AgentProtocol.kt`
  - 职责：定义 Android 侧协议 data class 与轻量 JSON 编解码。
- 创建：`mobile/android/app/src/main/java/com/neno/app/agent/AgentConnectionState.kt`
  - 职责：定义 Android agent 连接状态。
- 创建：`mobile/android/app/src/main/java/com/neno/app/agent/AgentRealtimeClient.kt`
  - 职责：Android 主动连接 PC/controller WebSocket，收发协议消息。
- 创建：`mobile/android/app/src/main/java/com/neno/app/ui/agent/AgentShellScreen.kt`
  - 职责：Android 原生 APK 的聊天入口静态页，不复用 Web 控制台。
- 创建：`mobile/android/app/src/test/java/com/neno/app/agent/AgentProtocolTest.kt`
  - 职责：验证 Android 侧协议 JSON 与状态枚举。

## 任务 1：写协议文档

**文件：**
- 创建：`docs/phone-agent-protocol.md`

- [ ] **步骤 1：创建协议文档**

写入：

```markdown
# Phone Agent v0 协议

## 边界

- Android APK 是原生应用，不复用 Web 控制台。
- PC Web 控制台是高级驾驶舱，只负责下任务、观察、确认和回放。
- v0 不接入 Neno 主聊天链路，不调用 `/mobile/conversations/neno/messages`。
- v0 不接触内核触摸驱动；动作后端只预留 `kernel_touch` 名称。

## 连接

Android APK 主动连接：

```text
WS /agent/ws?device_id=<local-device-id>
```

开发期鉴权使用：

```http
Authorization: Bearer <AGENT_DEV_TOKEN>
```

## 状态

- `idle`：待命
- `observing`：只观察
- `executing`：执行中
- `paused`：暂停
- `awaiting_confirmation`：等待确认
- `stopped`：急停
- `failed`：失败

## 风险等级

- `read_only`：只读观察
- `low`：低风险动作
- `medium`：中风险系统动作
- `high`：发送、删除、安装、授权、系统写入

## 消息类型

### hello

```json
{
  "type": "hello",
  "device_id": "xiaomi-14-local",
  "client": "android-apk",
  "protocol": "phone-agent-v0"
}
```

### observation

```json
{
  "type": "observation",
  "device_id": "xiaomi-14-local",
  "state": "idle",
  "foreground_app": "浏览器",
  "screen": {"width": 1080, "height": 2400},
  "capabilities": {
    "accessibility": true,
    "screenshot": true,
    "notification": false,
    "root_daemon": false,
    "kernel_touch": false
  }
}
```

### action_request

```json
{
  "type": "action_request",
  "action_id": "act_001",
  "tool": "tap",
  "risk": "low",
  "args": {"x": 5400, "y": 8200, "coordinate": "normalized_10000"},
  "reason": "点击搜索框"
}
```

### confirmation_request

```json
{
  "type": "confirmation_request",
  "action_id": "act_009",
  "risk": "high",
  "summary": "即将点击发送按钮",
  "reason": "用户要求回复当前聊天",
  "choices": ["allow_once", "deny", "stop"]
}
```

### action_result

```json
{
  "type": "action_result",
  "action_id": "act_001",
  "ok": true,
  "state": "executing",
  "message": "点击完成"
}
```

### stop

```json
{
  "type": "stop",
  "reason": "用户急停"
}
```
```

- [ ] **步骤 2：人工检查协议文档**

运行：

```powershell
Select-String -Path docs\phone-agent-protocol.md -Pattern "TODO|待定|debug|/mobile/conversations"
```

预期：没有 `TODO`、`待定`；如果出现 `/mobile/conversations`，只允许出现在“v0 不调用”的边界描述中。

- [ ] **步骤 3：Commit**

```powershell
git add docs\phone-agent-protocol.md
git commit -m "docs: define phone agent v0 protocol"
```

## 任务 2：新增 Python 协议 schema

**文件：**
- 创建：`tests/integration/test_phone_agent_protocol.py`
- 创建：`app/phone_agent_schemas.py`

- [ ] **步骤 1：编写失败测试**

创建 `tests/integration/test_phone_agent_protocol.py`：

```python
from app.phone_agent_schemas import (
    AgentActionRequest,
    AgentCapabilities,
    AgentHello,
    AgentObservation,
)


def test_agent_hello_uses_v0_protocol():
    hello = AgentHello(device_id="xiaomi-14-local", client="android-apk")

    assert hello.type == "hello"
    assert hello.protocol == "phone-agent-v0"


def test_observation_keeps_capability_flags_explicit():
    obs = AgentObservation(
        device_id="xiaomi-14-local",
        state="idle",
        foreground_app="浏览器",
        screen={"width": 1080, "height": 2400},
        capabilities=AgentCapabilities(
            accessibility=True,
            screenshot=True,
            notification=False,
            root_daemon=False,
            kernel_touch=False,
        ),
    )

    assert obs.capabilities.accessibility is True
    assert obs.capabilities.kernel_touch is False


def test_action_request_requires_known_risk_level():
    action = AgentActionRequest(
        action_id="act_001",
        tool="tap",
        risk="low",
        args={"x": 5400, "y": 8200, "coordinate": "normalized_10000"},
        reason="点击搜索框",
    )

    assert action.type == "action_request"
    assert action.risk == "low"
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```powershell
pytest tests\integration\test_phone_agent_protocol.py -q
```

预期：失败，报错 `ModuleNotFoundError: No module named 'app.phone_agent_schemas'`。

- [ ] **步骤 3：实现最少 schema**

创建 `app/phone_agent_schemas.py`：

```python
from typing import Any, Literal

from pydantic import BaseModel, Field


AgentState = Literal[
    "idle",
    "observing",
    "executing",
    "paused",
    "awaiting_confirmation",
    "stopped",
    "failed",
]
AgentRisk = Literal["read_only", "low", "medium", "high"]


class AgentHello(BaseModel):
    type: Literal["hello"] = "hello"
    device_id: str
    client: str
    protocol: str = "phone-agent-v0"


class AgentCapabilities(BaseModel):
    accessibility: bool = False
    screenshot: bool = False
    notification: bool = False
    root_daemon: bool = False
    kernel_touch: bool = False


class AgentObservation(BaseModel):
    type: Literal["observation"] = "observation"
    device_id: str
    state: AgentState
    foreground_app: str | None = None
    screen: dict[str, int] = Field(default_factory=dict)
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)


class AgentActionRequest(BaseModel):
    type: Literal["action_request"] = "action_request"
    action_id: str
    tool: Literal["tap", "swipe", "type_text", "back", "home", "open_app", "screenshot", "stop"]
    risk: AgentRisk
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str
```

- [ ] **步骤 4：运行测试验证通过**

运行：

```powershell
pytest tests\integration\test_phone_agent_protocol.py -q
```

预期：`3 passed`。

- [ ] **步骤 5：Commit**

```powershell
git add app\phone_agent_schemas.py tests\integration\test_phone_agent_protocol.py
git commit -m "feat(agent): add phone agent protocol schemas"
```

## 任务 3：新增后端 WebSocket 骨架

**文件：**
- 修改：`tests/integration/test_phone_agent_protocol.py`
- 创建：`app/routers/phone_agent.py`
- 修改：`app/main.py`

- [ ] **步骤 1：编写失败测试**

追加到 `tests/integration/test_phone_agent_protocol.py`：

```python
def test_agent_ws_sends_controller_hello(client):
    with client.websocket_connect("/agent/ws?device_id=xiaomi-14-local") as ws:
        payload = ws.receive_json()

    assert payload == {
        "type": "hello",
        "device_id": "controller",
        "client": "pc-console",
        "protocol": "phone-agent-v0",
    }
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```powershell
pytest tests\integration\test_phone_agent_protocol.py::test_agent_ws_sends_controller_hello -q
```

预期：失败，WebSocket 路由不存在或返回 404。

- [ ] **步骤 3：实现 router**

创建 `app/routers/phone_agent.py`：

```python
from fastapi import APIRouter, WebSocket

from app.phone_agent_schemas import AgentHello

router = APIRouter(prefix="/agent", tags=["phone-agent"])


@router.websocket("/ws")
async def phone_agent_ws(websocket: WebSocket, device_id: str):
    await websocket.accept()
    hello = AgentHello(
        device_id="controller",
        client="pc-console",
    )
    await websocket.send_json(hello.model_dump())
    await websocket.close()
```

修改 `app/main.py`：

```python
from app.routers import phone_agent

app.include_router(phone_agent.router)
```

如果 `app/main.py` 已经用多行 import 管理 router，遵循现有 import 顺序，只新增 `phone_agent`。

- [ ] **步骤 4：运行测试验证通过**

运行：

```powershell
pytest tests\integration\test_phone_agent_protocol.py -q
```

预期：`4 passed`。

- [ ] **步骤 5：Commit**

```powershell
git add app\routers\phone_agent.py app\main.py tests\integration\test_phone_agent_protocol.py
git commit -m "feat(agent): add phone agent websocket skeleton"
```

## 任务 4：新增 Android 协议模型

**文件：**
- 创建：`mobile/android/app/src/main/java/com/neno/app/agent/AgentConnectionState.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/agent/AgentProtocol.kt`
- 创建：`mobile/android/app/src/test/java/com/neno/app/agent/AgentProtocolTest.kt`

- [ ] **步骤 1：编写失败测试**

创建 `mobile/android/app/src/test/java/com/neno/app/agent/AgentProtocolTest.kt`：

```kotlin
package com.neno.app.agent

import org.junit.Assert.assertEquals
import org.junit.Test

class AgentProtocolTest {
    @Test
    fun helloUsesV0Protocol() {
        val hello = AgentHello(
            deviceId = "xiaomi-14-local",
            client = "android-apk",
        )

        assertEquals("hello", hello.type)
        assertEquals("phone-agent-v0", hello.protocol)
    }

    @Test
    fun connectionStateHasStoppedMode() {
        assertEquals("已急停", AgentConnectionState.Stopped.label)
    }
}
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest --tests com.neno.app.agent.AgentProtocolTest
```

预期：失败，`Unresolved reference: AgentHello`。

- [ ] **步骤 3：实现 Android 模型**

创建 `mobile/android/app/src/main/java/com/neno/app/agent/AgentConnectionState.kt`：

```kotlin
package com.neno.app.agent

enum class AgentConnectionState(val label: String) {
    Idle("待命"),
    Observing("只观察"),
    Executing("执行中"),
    Paused("已暂停"),
    AwaitingConfirmation("等待确认"),
    Stopped("已急停"),
    Failed("失败")
}
```

创建 `mobile/android/app/src/main/java/com/neno/app/agent/AgentProtocol.kt`：

```kotlin
package com.neno.app.agent

data class AgentHello(
    val deviceId: String,
    val client: String,
    val type: String = "hello",
    val protocol: String = "phone-agent-v0"
)

data class AgentCapabilities(
    val accessibility: Boolean = false,
    val screenshot: Boolean = false,
    val notification: Boolean = false,
    val rootDaemon: Boolean = false,
    val kernelTouch: Boolean = false
)
```

- [ ] **步骤 4：运行测试验证通过**

运行：

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest --tests com.neno.app.agent.AgentProtocolTest
```

预期：测试通过。

- [ ] **步骤 5：Commit**

```powershell
git add mobile\android\app\src\main\java\com\neno\app\agent mobile\android\app\src\test\java\com\neno\app\agent
git commit -m "feat(android): add phone agent protocol models"
```

## 任务 5：新增 Android 原生 Agent Shell 静态页

**文件：**
- 创建：`mobile/android/app/src/main/java/com/neno/app/ui/agent/AgentShellScreen.kt`
- 修改：`mobile/android/app/src/main/java/com/neno/app/ui/AppNav.kt`

- [ ] **步骤 1：编写 Compose 文案测试**

如果当前工程已有 Compose UI 测试配置，创建 `mobile/android/app/src/androidTest/java/com/neno/app/ui/agent/AgentShellScreenTest.kt`：

```kotlin
package com.neno.app.ui.agent

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test

class AgentShellScreenTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun showsChineseAgentEntry() {
        composeRule.setContent {
            AgentShellScreen()
        }

        composeRule.onNodeWithText("手机智能体").assertIsDisplayed()
        composeRule.onNodeWithText("急停").assertIsDisplayed()
    }
}
```

如果工程没有 Compose UI 测试配置，本步骤改为在任务 6 用截图人工验证，不在此任务添加 androidTest。

- [ ] **步骤 2：实现静态页**

创建 `mobile/android/app/src/main/java/com/neno/app/ui/agent/AgentShellScreen.kt`：

```kotlin
package com.neno.app.ui.agent

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
fun AgentShellScreen() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0B0D0E))
            .padding(18.dp),
        verticalArrangement = Arrangement.SpaceBetween
    ) {
        Column {
            Text("手机智能体", color = Color(0xFFE6ECEA))
            Text("半自动 · 本机执行器在线", color = Color(0xFF8B9697))
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .border(1.dp, Color(0xFF263033), RoundedCornerShape(18.dp))
                .padding(16.dp)
        ) {
            Text("要让手机做什么？", color = Color(0xFFE6ECEA))
            Spacer(Modifier.height(16.dp))
            Text("帮我整理刚刚下载的文件，只移动图片，不删除任何东西。", color = Color(0xFFE6ECEA))
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            OutlinedButton(modifier = Modifier.weight(1f), onClick = {}) {
                Text("只观察")
            }
            Button(modifier = Modifier.weight(1f), onClick = {}) {
                Text("急停")
            }
        }
    }
}
```

- [ ] **步骤 3：把页面挂到导航**

在 `mobile/android/app/src/main/java/com/neno/app/ui/AppNav.kt` 中新增一个进入 `AgentShellScreen()` 的入口。不要删除现有 Neno 对话列表；可以先在设置页或临时按钮进入。

- [ ] **步骤 4：运行 Android 构建**

运行：

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:assembleDebug
```

预期：构建成功。

- [ ] **步骤 5：Commit**

```powershell
git add mobile\android\app\src\main\java\com\neno\app\ui\agent mobile\android\app\src\main\java\com\neno\app\ui\AppNav.kt
git commit -m "feat(android): add native phone agent shell screen"
```

## 任务 6：端到端静态验证

**文件：**
- 修改：按验证结果补充 `docs/android-app-handoff.md`

- [ ] **步骤 1：后端协议测试**

运行：

```powershell
pytest tests\integration\test_phone_agent_protocol.py -q
```

预期：全部通过。

- [ ] **步骤 2：Android 单元测试**

运行：

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest
```

预期：全部通过。

- [ ] **步骤 3：Android 构建**

运行：

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:assembleDebug
```

预期：生成 debug APK。

- [ ] **步骤 4：Web 控制台静态检查**

运行：

```powershell
git diff --check -- app\static\agent-shell.html
```

预期：无输出，退出码 0。

- [ ] **步骤 5：补充 handoff**

在 `docs/android-app-handoff.md` 增加“Phone Agent v0”小节：

```markdown
## Phone Agent v0

- PC Web 静态控制台：`app/static/agent-shell.html`
- 协议文档：`docs/phone-agent-protocol.md`
- 后端 WebSocket 骨架：`/agent/ws`
- Android 原生入口：`AgentShellScreen`
- v0 不接入 Neno 主聊天链路，不调用 `/mobile/conversations/neno/messages`。
- v0 不接触内核触摸驱动。
```

- [ ] **步骤 6：最终验证**

运行：

```powershell
pytest tests\integration\test_phone_agent_protocol.py -q
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest :app:assembleDebug
git diff --check
```

预期：pytest 通过，Gradle 测试和构建通过，`git diff --check` 无空白错误。

- [ ] **步骤 7：Commit**

```powershell
git add docs\android-app-handoff.md
git commit -m "docs: document phone agent v0 handoff"
```
