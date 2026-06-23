# Neno Android v0 实现计划

> 面向 AI 代理的工作说明：本计划用于执行 Android 原生 App v0。执行前必须重新阅读 `NENO.md`、`NENO_ARCHITECTURE.md`、`docs/android-app-design-brief.md` 和 `docs/android-app-handoff.md`。步骤使用复选框语法跟踪进度。

**目标：** 在不破坏现有 Neno 后端主链路的前提下，新增一个 Android 原生 App v0：中文界面、对话列表首页、Neno 置顶联系人、Neno 聊天页、设置 / 连接状态页。

**架构：** 先在后端增加面向移动端的薄 API 层，再创建 `mobile/android/` 纯原生 Android 工程。Android App 不直接调用 debug 路由，不直接读写 SQLite，不直接写 `life_world_state`，只通过移动端 API 进入现有聊天服务。

**技术栈：** 后端继续使用 FastAPI + SQLite；移动端使用 Kotlin + Jetpack Compose + Material 3。HTTP 使用 `HttpURLConnection`，前台实时状态使用 OkHttp WebSocket。当前机器可见 JDK 17、Android SDK 和本机 Gradle 缓存；`gradle`、`adb`、`studio64` 不在 PATH，但已生成 `mobile/android/gradlew.bat`，后续 Android 命令使用 wrapper 执行。

---

## 输入和边界

- 产品输入：`docs/android-app-design-brief.md`
- 现有聊天入口：`app/routers/chat.py` 的 `POST /chat`
- 现有历史调试入口：`app/routers/session.py` 的 `/session/*`，仅 admin 使用，不能直接暴露给 App
- 现有鉴权：`app/security.py` 中 admin token 和 platform token
- 现有消息存储：`app/storage/db.py` 的 `messages` 表和 `get_session_messages()`
- 现有运行约束：Session 串行、prompt 装配顺序、Living World 写入边界都不可绕过

v0 明确不做：

- iOS
- Expo / React Native / WebView
- 多 AI marketplace
- 世界地图、房间页、角色养成首页
- 通知快捷回复作为核心能力
- 让 App 直接使用 `/debug/*` 或 `/session/*`

## 目标文件结构

### 后端

- 创建：`app/mobile_schemas.py`
  - 移动端请求 / 响应模型。只包含 App 需要展示的数据，不泄漏 debug 字段。
- 创建：`app/services/mobile_api_service.py`
  - 组合移动端对话列表、消息历史、发送消息和连接状态。
- 创建：`app/routers/mobile.py`
  - 移动端 API 路由，统一 prefix 为 `/mobile`。
- 修改：`app/config.py`
  - 增加 `MOBILE_TOKEN` 和 `MOBILE_DEFAULT_SESSION_ID`。
- 修改：`app/security.py`
  - 增加 `require_mobile_token()`，使用 `Authorization: Bearer <token>`。
- 修改：`app/main.py`
  - 注册 `mobile.router`。
- 创建：`tests/integration/test_mobile_api.py`
  - 覆盖移动端 API 鉴权、对话列表、历史、发送消息和字段收敛。

### Android

- 创建：`mobile/android/settings.gradle.kts`
- 创建：`mobile/android/build.gradle.kts`
- 创建：`mobile/android/gradle.properties`
- 创建：`mobile/android/app/build.gradle.kts`
- 创建：`mobile/android/app/src/main/AndroidManifest.xml`
- 创建：`mobile/android/app/src/debug/AndroidManifest.xml`
- 创建：`mobile/android/app/src/main/java/com/neno/app/MainActivity.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/NenoApp.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/data/ApiModels.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/data/ConnectionState.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/data/MobileRealtimeClient.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/data/NenoApi.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/data/NenoRepository.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/data/SettingsStore.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/ui/AppNav.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/ui/conversations/ConversationListScreen.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/ui/chat/NenoChatScreen.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/ui/settings/SettingsScreen.kt`
- 创建：`mobile/android/app/src/main/java/com/neno/app/ui/theme/Theme.kt`
- 创建：`mobile/android/app/src/test/java/com/neno/app/data/ApiModelsTest.kt`
- 创建：`mobile/android/app/src/test/java/com/neno/app/data/ConnectionStateTest.kt`
- 创建：`mobile/android/app/src/test/java/com/neno/app/data/MobileRealtimeEventTest.kt`

## API 合同

所有移动端 API 都使用：

```http
Authorization: Bearer <MOBILE_TOKEN>
```

HTTP 仍负责拉取列表、历史和发送消息。`WS /mobile/ws` 只负责前台连接状态和一句 presence（状态提示），不能绕过 `POST /mobile/conversations/neno/messages` 发送聊天内容。

### `GET /mobile/status`

用途：设置 / 连接状态页启动检查。

响应：

```json
{
  "success": true,
  "server_time": "2026-06-23T12:00:00+08:00",
  "api": "mobile-v0",
  "session_id_label": "mobile:neno",
  "features": {
    "attachments": false,
    "notifications": false,
    "quick_reply": false
  }
}
```

### `GET /mobile/conversations`

用途：对话列表首页。

响应：

```json
{
  "success": true,
  "conversations": [
    {
      "id": "neno",
      "title": "Neno",
      "subtitle": "对话停在这里",
      "last_message": "我晚点再和你说。",
      "last_message_at": "2026-06-23T12:00:00+08:00",
      "unread_count": 0,
      "pinned": true,
      "kind": "primary",
      "presence": "在线"
    },
    {
      "id": "writing",
      "title": "写作助手",
      "subtitle": "工具联系人",
      "last_message": "",
      "last_message_at": null,
      "unread_count": 0,
      "pinned": false,
      "kind": "utility",
      "presence": "在线"
    }
  ]
}
```

### `GET /mobile/conversations/neno/messages?limit=50`

用途：Neno 聊天页拉取消息历史。

响应：

```json
{
  "success": true,
  "conversation_id": "neno",
  "presence": "在线",
  "messages": [
    {
      "id": 101,
      "role": "assistant",
      "text": "我晚点再和你说。",
      "created_at": "2026-06-23T12:00:00+08:00",
      "pending": false
    }
  ]
}
```

### `POST /mobile/conversations/neno/messages`

用途：发送用户消息并返回 Neno 回复。

请求：

```json
{
  "text": "在吗"
}
```

响应：

```json
{
  "success": true,
  "conversation_id": "neno",
  "user_message": {
    "id": 201,
    "role": "user",
    "text": "在吗",
    "created_at": "2026-06-23T12:00:00+08:00",
    "pending": false
  },
  "assistant_message": {
    "id": 202,
    "role": "assistant",
    "text": "在。",
    "created_at": "2026-06-23T12:00:00+08:00",
    "pending": false
  }
}
```

v0 只支持 `conversation_id=neno` 发送消息。工具联系人可以在列表展示，但点击后显示中文占位页：“这个联系人还没接入。”

### `WS /mobile/ws`

用途：Android App 前台连接状态和低干扰 presence 更新。

鉴权同 HTTP：

```http
Authorization: Bearer <MOBILE_TOKEN>
```

服务端连接后先发送：

```json
{"type":"hello","api":"mobile-v0"}
```

随后发送或刷新：

```json
{"type":"presence","conversation_id":"neno","presence":"在线"}
```

客户端发送文本 `ping` 时，服务端返回：

```json
{"type":"pong"}
```

状态提示只允许是短中文文案，例如 `在线`、`睡着了`、`稍后回复`。WebSocket 断开后 Android 端在前台自动重连，HTTP status 检测保留为设置页和兜底路径。

## 任务 1：新增移动端后端鉴权和 schema

**文件：**

- 修改：`app/config.py`
- 修改：`app/security.py`
- 创建：`app/mobile_schemas.py`
- 创建：`tests/integration/test_mobile_api.py`

- [x] **步骤 1：写鉴权失败测试**

在 `tests/integration/test_mobile_api.py` 添加：

```python
def test_mobile_status_requires_token(client):
    response = client.get("/mobile/status")
    assert response.status_code == 403
```

- [x] **步骤 2：写鉴权成功测试**

```python
def test_mobile_status_accepts_bearer_token(client, monkeypatch):
    from app import config
    from app import security

    monkeypatch.setattr(config, "MOBILE_TOKEN", "mobile-test-token")
    monkeypatch.setattr(security, "MOBILE_TOKEN", "mobile-test-token")

    response = client.get(
        "/mobile/status",
        headers={"Authorization": "Bearer mobile-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
```

- [x] **步骤 3：实现配置和鉴权**

在 `app/config.py` 增加：

```python
MOBILE_TOKEN = os.getenv("MOBILE_TOKEN", "").strip()
MOBILE_DEFAULT_SESSION_ID = os.getenv("MOBILE_DEFAULT_SESSION_ID", "mobile:neno").strip() or "mobile:neno"
```

在 `app/security.py` 增加：

```python
from app.config import ADMIN_TOKEN, MOBILE_TOKEN, PLATFORM_TOKEN


def require_mobile_token(authorization: str | None = Header(default=None)):
    if not MOBILE_TOKEN:
        raise HTTPException(status_code=403, detail="MOBILE_TOKEN not configured")
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=403, detail="missing mobile token")
    token = authorization[len(prefix):].strip()
    if token != MOBILE_TOKEN:
        raise HTTPException(status_code=403, detail="invalid mobile token")
```

- [x] **步骤 4：创建移动端 schema**

在 `app/mobile_schemas.py` 定义：

```python
from typing import Literal

from pydantic import BaseModel, Field


class MobileFeatureFlags(BaseModel):
    attachments: bool = False
    notifications: bool = False
    quick_reply: bool = False


class MobileStatusResponse(BaseModel):
    success: bool = True
    server_time: str
    api: str = "mobile-v0"
    session_id_label: str
    features: MobileFeatureFlags = Field(default_factory=MobileFeatureFlags)


class MobileConversation(BaseModel):
    id: str
    title: str
    subtitle: str
    last_message: str = ""
    last_message_at: str | None = None
    unread_count: int = 0
    pinned: bool = False
    kind: Literal["primary", "utility"]


class MobileConversationListResponse(BaseModel):
    success: bool = True
    conversations: list[MobileConversation]


class MobileMessage(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    text: str
    created_at: str | None = None
    pending: bool = False


class MobileMessagesResponse(BaseModel):
    success: bool = True
    conversation_id: str
    messages: list[MobileMessage]


class MobileSendMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class MobileSendMessageResponse(BaseModel):
    success: bool = True
    conversation_id: str
    user_message: MobileMessage
    assistant_message: MobileMessage | None = None
```

- [x] **步骤 5：运行测试确认失败点收敛**

运行：

```powershell
pytest tests\integration\test_mobile_api.py -q
```

预期：路由尚未创建时返回 404 或导入失败。下一任务创建 router 后应通过。

## 任务 2：新增移动端服务层和路由

**文件：**

- 创建：`app/services/mobile_api_service.py`
- 创建：`app/routers/mobile.py`
- 修改：`app/main.py`
- 修改：`tests/integration/test_mobile_api.py`

- [x] **步骤 1：实现服务层**

`app/services/mobile_api_service.py`：

```python
from datetime import datetime, timedelta, timezone
from typing import Any

from app import config
from app.mobile_schemas import MobileConversation, MobileMessage
from app.services.chat_service import run_chat_turn
from app.storage.db import get_session_messages
from app.services.chat.context_builder import mask_session_id
from app.utils.logging_utils import new_trace_id


NENO_CONVERSATION_ID = "neno"
UTC8 = timezone(timedelta(hours=8))


def utc8_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone(UTC8).isoformat(timespec="seconds")


def get_mobile_status() -> dict[str, Any]:
    return {
        "server_time": utc8_now_iso(),
        "session_id_label": mask_session_id(config.MOBILE_DEFAULT_SESSION_ID),
    }


def _to_mobile_message(row: dict[str, Any]) -> MobileMessage:
    role = "assistant" if row.get("role") == "assistant" else "user"
    return MobileMessage(
        id=int(row["id"]),
        role=role,
        text=str(row.get("content") or ""),
        created_at=row.get("created_at"),
        pending=False,
    )


def list_mobile_conversations() -> list[MobileConversation]:
    recent = get_session_messages(config.MOBILE_DEFAULT_SESSION_ID, limit=1)
    last = recent[0] if recent else {}
    last_text = str(last.get("content") or "")
    return [
        MobileConversation(
            id=NENO_CONVERSATION_ID,
            title="Neno",
            subtitle="置顶联系人",
            last_message=last_text,
            last_message_at=last.get("created_at"),
            unread_count=0,
            pinned=True,
            kind="primary",
        ),
        MobileConversation(
            id="writing",
            title="写作助手",
            subtitle="工具联系人",
            kind="utility",
        ),
        MobileConversation(
            id="code",
            title="代码助手",
            subtitle="工具联系人",
            kind="utility",
        ),
    ]


def list_mobile_messages(conversation_id: str, limit: int) -> list[MobileMessage]:
    if conversation_id != NENO_CONVERSATION_ID:
        return []
    rows = get_session_messages(config.MOBILE_DEFAULT_SESSION_ID, limit=limit)
    return [_to_mobile_message(row) for row in rows]


def send_mobile_message(conversation_id: str, text: str) -> tuple[MobileMessage, MobileMessage | None]:
    if conversation_id != NENO_CONVERSATION_ID:
        raise ValueError("unsupported conversation")
    trace_id = new_trace_id()
    result = run_chat_turn(
        config.MOBILE_DEFAULT_SESSION_ID,
        text,
        trace_id=trace_id,
        input_record={
            "source": "mobile",
            "message_type": "text",
            "raw_input": text,
            "normalized_input": text,
            "attachments": [],
        },
    )
    user_message = MobileMessage(
        id=int(result["user_message_id"]),
        role="user",
        text=text,
        created_at=None,
    )
    assistant_message = MobileMessage(
        id=int(result["assistant_message_id"]),
        role="assistant",
        text=str(result["reply"]),
        created_at=None,
    )
    return user_message, assistant_message
```

- [x] **步骤 2：实现 router**

`app/routers/mobile.py`：

```python
from fastapi import APIRouter, Depends, HTTPException, Query

from app.mobile_schemas import (
    MobileConversationListResponse,
    MobileMessagesResponse,
    MobileSendMessageRequest,
    MobileSendMessageResponse,
    MobileStatusResponse,
)
from app.security import require_mobile_token
from app.services.mobile_api_service import (
    get_mobile_status,
    list_mobile_conversations,
    list_mobile_messages,
    send_mobile_message,
)

router = APIRouter(prefix="/mobile", tags=["mobile"])


@router.get("/status", response_model=MobileStatusResponse, dependencies=[Depends(require_mobile_token)])
def mobile_status():
    return MobileStatusResponse(**get_mobile_status())


@router.get(
    "/conversations",
    response_model=MobileConversationListResponse,
    dependencies=[Depends(require_mobile_token)],
)
def mobile_conversations():
    return MobileConversationListResponse(conversations=list_mobile_conversations())


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MobileMessagesResponse,
    dependencies=[Depends(require_mobile_token)],
)
def mobile_messages(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=100),
):
    return MobileMessagesResponse(
        conversation_id=conversation_id,
        messages=list_mobile_messages(conversation_id, limit),
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MobileSendMessageResponse,
    dependencies=[Depends(require_mobile_token)],
)
def mobile_send_message(conversation_id: str, req: MobileSendMessageRequest):
    try:
        user_message, assistant_message = send_mobile_message(conversation_id, req.text)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MobileSendMessageResponse(
        conversation_id=conversation_id,
        user_message=user_message,
        assistant_message=assistant_message,
    )
```

- [x] **步骤 3：注册 router**

在 `app/main.py` 的 import 列表加入 `mobile`，并在 `include_router` 区域加入：

```python
app.include_router(mobile.router)
```

- [x] **步骤 4：补路由行为测试**

`tests/integration/test_mobile_api.py` 增加：

```python
def mobile_headers(monkeypatch):
    from app import config
    from app import security

    monkeypatch.setattr(config, "MOBILE_TOKEN", "mobile-test-token")
    monkeypatch.setattr(security, "MOBILE_TOKEN", "mobile-test-token")
    return {"Authorization": "Bearer mobile-test-token"}


def test_mobile_conversations_returns_chinese_contacts(client, monkeypatch):
    response = client.get("/mobile/conversations", headers=mobile_headers(monkeypatch))
    assert response.status_code == 200
    data = response.json()
    titles = [item["title"] for item in data["conversations"]]
    assert titles[:3] == ["Neno", "写作助手", "代码助手"]
    assert data["conversations"][0]["pinned"] is True


def test_mobile_messages_do_not_expose_debug_fields(client, monkeypatch):
    response = client.get("/mobile/conversations/neno/messages", headers=mobile_headers(monkeypatch))
    assert response.status_code == 200
    body = response.json()
    assert "candidate_memory_debug" not in str(body)
    assert "relationship_context" not in str(body)
```

- [x] **步骤 5：运行后端移动端测试**

运行：

```powershell
pytest tests\integration\test_mobile_api.py -q
```

预期：新增移动端测试全部通过。

## 任务 3：创建 Android 工程骨架

**文件：**

- 创建：`mobile/android/*`

- [x] **步骤 1：安装或暴露 Android 工具链**

当前机器已有 JDK 17 和 Android SDK；`gradle`、`adb`、`studio64` 不在 PATH。实际执行使用本机 Gradle 8.14.3 缓存生成 wrapper：

```powershell
java -version
Get-Command gradle -ErrorAction SilentlyContinue
Get-Command adb -ErrorAction SilentlyContinue
```

生成后续命令使用的 wrapper：

```powershell
& 'C:\Users\Administrator\.gradle\wrapper\dists\gradle-8.14.3-bin\cv11ve7ro1n3o1j4so8xd9n66\gradle-8.14.3\bin\gradle.bat' -p .\mobile\android wrapper --gradle-version 8.14.3 --distribution-type bin
```

后续命令使用：

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:assembleDebug
```

- [x] **步骤 2：固定包名和应用名**

应用包名：`com.neno.app`

应用中文名：`Neno`

`AndroidManifest.xml` 保持最小权限：

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

v0 不申请通知权限，通知放到后续独立任务。

Debug 构建额外允许本地 HTTP，方便模拟器连接 `10.0.2.2`：

```xml
<application android:usesCleartextTraffic="true" />
```

该配置位于 `app/src/debug/AndroidManifest.xml`，不放进主 manifest。

- [x] **步骤 3：创建 Compose 入口**

`MainActivity.kt`：

```kotlin
package com.neno.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.neno.app.ui.theme.NenoTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            NenoTheme {
                NenoApp()
            }
        }
    }
}
```

`NenoApp.kt`：

```kotlin
package com.neno.app

import androidx.compose.runtime.Composable
import com.neno.app.ui.AppNav

@Composable
fun NenoApp() {
    AppNav()
}
```

## 任务 4：实现 Android 数据层

**文件：**

- 创建：`ApiModels.kt`
- 创建：`NenoApi.kt`
- 创建：`NenoRepository.kt`
- 创建：`SettingsStore.kt`
- 创建：`ApiModelsTest.kt`

- [x] **步骤 1：定义 API 模型**

`ApiModels.kt` 使用轻量 Kotlin data class，不引入额外 JSON 序列化依赖：

```kotlin
package com.neno.app.data

data class MobileConversation(
    val id: String,
    val title: String,
    val subtitle: String,
    val lastMessage: String = "",
    val lastMessageAt: String? = null,
    val unreadCount: Int = 0,
    val pinned: Boolean = false,
    val kind: String
)

data class MobileMessage(
    val id: Long,
    val role: String,
    val text: String,
    val createdAt: String? = null,
    val pending: Boolean = false
)

data class MobileSendMessageResponse(
    val success: Boolean,
    val conversationId: String,
    val userMessage: MobileMessage,
    val assistantMessage: MobileMessage? = null
)
```

- [x] **步骤 2：定义 API 客户端**

`NenoApi.kt` 使用 `HttpURLConnection` + `org.json`，避免在当前环境新增 Retrofit / OkHttp 下载依赖。所有请求带 `Authorization`：

```kotlin
setRequestProperty("Authorization", "Bearer $token")
setRequestProperty("Accept", "application/json")
if (body != null) {
    doOutput = true
    setRequestProperty("Content-Type", "application/json; charset=utf-8")
}
```

- [x] **步骤 3：实现 Repository**

`NenoRepository.kt` 对 UI 暴露：

```kotlin
class NenoRepository(
    private val api: NenoApi
) {
    suspend fun loadConversations(): List<MobileConversation> =
        api.conversations().conversations

    suspend fun loadNenoMessages(): List<MobileMessage> =
        api.messages("neno").messages

    suspend fun sendToNeno(text: String): MobileSendMessageResponse =
        api.sendMessage("neno", MobileSendMessageRequest(text.trim()))
}
```

- [x] **步骤 4：验证模型和设置边界**

`ApiModelsTest.kt` 验证中文 UI 文案保留和服务器地址归一化：

```kotlin
class ApiModelsTest {
    @Test
    fun conversationModelKeepsChineseUiText() {
        val conversation = MobileConversation(
            id = "neno",
            title = "Neno",
            subtitle = "置顶联系人",
            pinned = true,
            kind = "primary",
        )

        assertEquals("置顶联系人", conversation.subtitle)
        assertTrue(conversation.pinned)
    }
}
```

运行：

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest
```

## 任务 5：实现中文 UI 页面

**文件：**

- 创建：`AppNav.kt`
- 创建：`ConversationListScreen.kt`
- 创建：`NenoChatScreen.kt`
- 创建：`SettingsScreen.kt`
- 创建：`Theme.kt`

- [x] **步骤 1：定义主题**

`Theme.kt` 使用浅色 Material 3：

```kotlin
private val NenoLightColors = lightColorScheme(
    background = Color(0xFFFAF9F6),
    surface = Color(0xFFFFFFFF),
    surfaceVariant = Color(0xFFF0EFEC),
    primary = Color(0xFFB76E45),
    onPrimary = Color.White,
    onBackground = Color(0xFF1F1F1F),
    onSurface = Color(0xFF1F1F1F)
)
```

- [x] **步骤 2：实现导航**

`AppNav.kt` 使用轻量状态导航，避免新增 Compose Navigation 依赖。v0 页面：

```kotlin
private enum class AppScreen {
    Conversations,
    NenoChat,
    Settings,
    UnsupportedContact,
}
```

- [x] **步骤 3：实现对话列表**

中文界面文案：

- 标题：`对话`
- Neno 副标题：`置顶联系人`
- 工具联系人副标题：`工具联系人`
- 空状态：`还没有消息`
- 设置入口：`设置`

布局要求：

- 使用 `Scaffold` + `TopAppBar`
- 列表使用 `LazyColumn`
- Neno 行置顶，样式比工具联系人更强，但不做大卡片
- 不放右下角笔，不放悬浮创建按钮

- [x] **步骤 4：实现 Neno 聊天页**

中文界面文案：

- 顶部状态：`在线`、`稍后回复`、`连接中`
- 输入框占位文案：`发消息`
- 发送按钮 contentDescription：`发送`
- 加载中：`正在连接`
- 失败：`连接失败，点这里重试`

布局要求：

- 使用 `Scaffold` + `TopAppBar`
- 消息列表从下方可读，避免遮挡输入框
- Neno 气泡浅灰，用户气泡暖色
- 输入框保持普通聊天输入，不做大 AI prompt 框

- [x] **步骤 5：实现设置 / 连接状态页**

中文界面文案：

- 标题：`设置`
- 字段：`服务器地址`、`访问令牌`
- 按钮：`保存`、`测试连接`
- 状态：`已连接`、`未连接`、`令牌无效`

设置保存到 `SharedPreferences`，不提交任何真实 token。

## 任务 6：端到端验证

**文件：**

- 修改：测试和文档按实际实现补充

- [x] **步骤 1：后端测试**

运行：

```powershell
pytest tests\integration\test_mobile_api.py -q
pytest tests\unit\test_chat_cache_structure.py -q
```

预期：移动端 API 测试通过，prompt cache 结构测试继续通过。

- [x] **步骤 2：后端启动检查**

运行：

```powershell
$env:MOBILE_TOKEN="mobile-test-token"
$env:PROACTIVE_MODE="off"
$env:PROACTIVE_ENABLED="false"
$env:PROACTIVE_AUTO_SEND="false"
$env:BRAIN_INTENT_CONSUMER_ENABLED="false"
$env:CONSCIOUSNESS_WORLD_LOOP_ENABLED="false"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/mobile/status -Headers @{Authorization="Bearer mobile-test-token"}
```

预期：HTTP 200，返回 `mobile-v0`。

实际验证使用临时端口 `8766`，请求 `/mobile/status` 返回 HTTP 200 和 `api="mobile-v0"`；验证后已停止临时进程。

- [x] **步骤 3：Android 构建**

运行：

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:assembleDebug
```

预期：生成 debug APK。

- [x] **步骤 4：Android 单元测试**

运行：

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest
```

预期：数据模型和 repository 测试通过。

- [x] **步骤 5：模拟器或真机检查**

模拟器使用 `http://10.0.2.2:8000` 连接本机后端；真机使用电脑局域网 IP。检查：

- 首页标题为中文 `对话`
- Neno 是置顶联系人
- 不出现英文按钮文案
- 聊天页输入框为 `发消息`
- 设置页能保存服务器地址和 token
- 错误状态为中文

2026-06-23 真机验证已完成。无线 ADB 设备 `192.168.1.5:44043` 安装并启动成功；当前可接受首页截图见 `tmp/screens/neno-brand-light-home.png`。继续工作前先读 `docs/android-app-handoff.md`。

## 实现期间禁止事项

- 不改 `context_builder.py` 的 prompt 拼装顺序
- 不绕过 `SessionSubmitController`
- 不让 Android App 直接写 `life_world_state`
- 不把 `/test` 控制台包装成 App
- 不把 admin token 写入 Android 工程
- 不提交真实服务器地址、真实 token 或用户数据
- 不把通知快捷回复塞进 v0 核心流程
- 不把界面文案写成英文

## 提交拆分建议

1. `docs: add android app implementation plan`
2. `feat(api): add mobile app endpoints`
3. `test(api): cover mobile app contract`
4. `feat(android): scaffold native compose app`
5. `feat(android): add neno chat screens`
6. `test(android): cover mobile api models`

每个提交前至少运行对应范围的验证命令；涉及后端核心测试时运行 `pytest tests\unit\test_chat_cache_structure.py -q` 防止误伤 prompt 结构。
