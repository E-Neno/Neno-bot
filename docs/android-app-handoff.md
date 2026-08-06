# Neno Android App Handoff

> Status date: 2026-06-30.
> Audience: Claude or another coding agent continuing the native Android app.

## Read First

Before editing code, read these files in order:

1. `NENO.md`
2. `NENO_ARCHITECTURE.md`
3. `docs/android-app-design-brief.md`
4. `docs/android-app-implementation-plan.md`
5. This handoff document

The Android app is a native Kotlin + Jetpack Compose app under `mobile/android/`. It is not the backend web console, not Expo, not React Native, and not a WebView wrapper.

## Android Client Boundary

The repository now contains two independent Android clients:

- `mobile/android/` is the original Neno native v0 client described by this handoff.
- `mobile/operit/` is the complete Operit Neno fork, migrated into this repository on 2026-08-07.

The Operit fork is the richer client that reuses Operit chat, media, Agent, Root, plugin, and Tavern surfaces.
Its Neno entry still calls the backend only through `/mobile/*` and must not route Neno through a character-card
prompt or a second local model. See `mobile/operit/README.NENO.md` before changing that client.

## Product Direction

The user-approved direction is a Chinese Android chat app, closer to a real messaging app than an AI tool homepage.

Keep these constraints:

- UI text shown to the user must be Chinese unless it is the product name `Neno`.
- The first screen is a conversation list. Neno is pinned as the primary contact.
- Other AI contacts can exist as lighter utility contacts, but they must not compete with Neno.
- Do not turn the first screen into a virtual-person status page, room page, dashboard, or tool launcher.
- Do not add a dark visual theme. A black brand banner was tried and rejected as visually abrupt.
- Do not generate a new broad visual direction. Continue refining the existing light messaging direction.

## Current Implementation

Backend mobile API files:

- `app/mobile_schemas.py`
- `app/routers/mobile.py`
- `app/services/mobile_api_service.py`
- `app/services/mobile_upload_service.py`
- `app/services/mobile_file_parser.py`
- Tests: `tests/integration/test_mobile_api.py`

Mobile API contract:

- `GET /mobile/status`
- `WS /mobile/ws`
- `POST /mobile/uploads`
- `GET /mobile/conversations`
- `GET /mobile/conversations/neno/messages?limit=50`
- `POST /mobile/conversations/neno/messages`
- Authentication uses `Authorization: Bearer <MOBILE_TOKEN>`.
- Default mobile session is controlled by `MOBILE_DEFAULT_SESSION_ID`, defaulting to `mobile:neno`.
- `/mobile/ws` sends `hello`, then `presence`; it responds to text `ping` with `pong` and refreshes presence on idle. It is a lightweight foreground connection, not a replacement for the chat POST route.
- `/mobile/uploads` accepts raw request bytes plus `kind` and `filename` query parameters. Supported kinds are `image`, `voice`, and `file`; files are stored under ignored `uploads/mobile/`.
- `/mobile/conversations/neno/messages` accepts `attachments` using the existing `MediaAttachment` shape. Images reuse `normalize_multimodal_message()`, voice reuses `transcribe_voice()`, and files are parsed into text before entering the chat core.
- File parsing supports text-like files, Markdown, CSV/TSV, JSON, log files, DOCX, and PDF via `pypdf`.

Android app files:

- Root: `mobile/android/`
- App package: `com.neno.app`
- Entry: `mobile/android/app/src/main/java/com/neno/app/MainActivity.kt`
- Navigation: `mobile/android/app/src/main/java/com/neno/app/ui/AppNav.kt`
- Conversation list: `mobile/android/app/src/main/java/com/neno/app/ui/conversations/ConversationListScreen.kt`
- Chat screen: `mobile/android/app/src/main/java/com/neno/app/ui/chat/NenoChatScreen.kt`
- Settings screen: `mobile/android/app/src/main/java/com/neno/app/ui/settings/SettingsScreen.kt`
- API layer: `mobile/android/app/src/main/java/com/neno/app/data/NenoApi.kt`
- Repository: `mobile/android/app/src/main/java/com/neno/app/data/NenoRepository.kt`
- Connection state: `mobile/android/app/src/main/java/com/neno/app/data/ConnectionState.kt`
- WebSocket client: `mobile/android/app/src/main/java/com/neno/app/data/MobileRealtimeClient.kt`
- Shared visuals: `mobile/android/app/src/main/java/com/neno/app/ui/components/NenoVisuals.kt`

Implemented UI details:

- The conversation list uses a light background with a pinned Neno card and lighter utility contacts.
- The top of the list now uses a light inline brand row: a custom self-drawn `NenoBrandIcon` plus `Neno`.
- The rejected version had a full black banner. Do not restore it.
- The app is locked to portrait in `AndroidManifest.xml`.
- The chat screen has a Neno header, date divider, preview bubbles when there are no backend messages, and a bottom input bar.
- The real chat loop is wired in `NenoChatScreen.kt`: optimistic pending user bubble, send via `/mobile/conversations/neno/messages`, append the real user and assistant messages, auto-scroll to the newest message, and a Neno typing indicator (three animated dots) while the reply is in flight.
- The chat input has image/audio/file pickers. The UI reads the selected Android `Uri`, uploads raw bytes to `/mobile/uploads`, then sends the returned attachment through `/mobile/conversations/neno/messages`.
- The mic button currently opens an audio picker. It is not a press-and-hold recorder yet.
- The camera action currently reuses image picking. It is not a real camera capture flow yet.
- On send failure the optimistic bubble is removed, the typed text is restored into the input box, and a Chinese error bar with `点这里重试` resends the draft.
- If the backend returns no assistant message (sleeping, deferred, or deliberate non-reply), the chat shows the neutral hint `消息已送达`; it must not promise that Neno will reply later.
- The conversation list refreshes the Neno last-message preview on every return because the `when`-based nav in `AppNav.kt` disposes and re-runs `ConversationListScreen`'s `LaunchedEffect`.
- `NenoRepository.connectionState` is the app-wide connection state. `NenoApp.kt` starts `MobileRealtimeClient` while the app composition is alive and still runs periodic HTTP status refresh as a fallback.
- Settings is now a connection/status page. It shows `已连接` / `未连接` / `令牌无效`, has a lower top offset for real devices, and hides raw server/token fields behind a long press on the title.
- Settings stores server URL and mobile token in `SharedPreferences`; do not commit real tokens.

Phone Agent v0 additions:

- Protocol document: `docs/phone-agent-protocol.md`
- Backend protocol schema: `app/phone_agent_schemas.py`
- Backend WebSocket skeleton: `app/routers/phone_agent.py`
- PC controller endpoint: `WS /agent/ws?device_id=<local-device-id>`
- Android APK endpoint: `WS /mobile/agent/ws?device_id=<local-device-id>`; keep Android agent traffic under `/mobile/*`.
- Android protocol models: `mobile/android/app/src/main/java/com/neno/app/data/AgentProtocol.kt`
- Native Agent Shell screen: `mobile/android/app/src/main/java/com/neno/app/ui/agent/AgentShellScreen.kt`
- Bottom navigation `工具` now opens the native `AgentShellScreen` instead of the unsupported-contact placeholder.
- Current Agent Shell is static UI only: it does not execute Accessibility, root, notification, or kernel-touch actions yet.
- The WebSocket skeleton only sends protocol hello, idle presence, pong, and observation ack. It is not a task planner, action dispatcher, or safety-confirmation engine yet.

## Verified State

Commands run successfully on 2026-06-23:

```powershell
pytest tests\integration\test_mobile_api.py -q
python -m compileall -q app tests
git diff --check
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest
.\mobile\android\gradlew.bat -p .\mobile\android :app:assembleDebug
```

`git diff --check` only reported LF/CRLF warnings.

Manual WebSocket verification:

```text
recv1={"type":"hello","api":"mobile-v0"}
recv2={"type":"presence","conversation_id":"neno","presence":"睡着了"}
recv3={"type":"pong"}
```

Real-device validation:

- Wireless ADB device used: `192.168.1.5:44043`
- APK install, start, and settings screenshot succeeded with:

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb -s 192.168.1.5:44043 install -r .\mobile\android\app\build\outputs\apk\debug\app-debug.apk
& $adb -s 192.168.1.5:44043 shell am start -n com.neno.app/.MainActivity
```

Runtime evidence:

- backend log showed `192.168.1.5 ... "WebSocket /mobile/ws" [accepted]`
- final settings screenshot showed the page lower than the status bar and connection state `已连接`

## Next Best Task

The backend `/mobile/*` HTTP contract, `/mobile/ws` presence channel, Android connection state, settings visual offset, and mobile attachment v1 are implemented.

The next useful task is a real-device attachment pass:

1. Reconnect wireless ADB and install the current debug APK.
2. Open Neno chat on the device.
3. Send one text-only Chinese message and confirm pending bubble -> typing dots -> assistant reply.
4. Use the plus menu to send one image and one text file.
5. Use the mic button to pick one audio file and confirm it goes through ASR.
6. Confirm backend `uploads/mobile/` receives files and does not get tracked by git.
7. Return to the conversation list and confirm the Neno last-message preview updated.

After that, the next product-quality pass is real camera capture, press-and-hold recording, and attachment preview bubbles.

Suggested backend command for local validation:

```powershell
$env:MOBILE_TOKEN="mobile-test-token"
$env:PROACTIVE_MODE="off"
$env:PROACTIVE_ENABLED="false"
$env:PROACTIVE_AUTO_SEND="false"
$env:BRAIN_INTENT_CONSUMER_ENABLED="false"
$env:CONSCIOUSNESS_WORLD_LOOP_ENABLED="false"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Use the computer LAN IP in the app settings when testing on a physical phone. Use `http://10.0.2.2:8000` only for an Android emulator.
The active Python environment must include a WebSocket implementation for uvicorn. `requirements.txt` uses `uvicorn[standard]`; if `/mobile/ws` returns HTTP 404 with `Unsupported upgrade request`, install the extras in the active venv.

## Hard Boundaries

Do not change these while continuing the app:

- `context_builder.py` prompt assembly order
- Session aggregation or submit locks
- `history_digest` cursor semantics
- Living World write ownership
- Any direct Android read/write path to SQLite
- Any direct Android call to `/debug/*`, `/session/*`, or admin-only endpoints
- Any committed real `MOBILE_TOKEN`, admin token, platform token, or server secret

The Android app must enter the existing chat path only through `/mobile/*`; `/mobile/ws` is only for presence/connection status and must not bypass `POST /mobile/conversations/neno/messages`.

## Useful Checks

Run these before claiming the handoff task is complete:

```powershell
pytest tests\integration\test_mobile_api.py -q
pytest tests\unit\test_chat_cache_structure.py -q
.\mobile\android\gradlew.bat -p .\mobile\android :app:assembleDebug
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest
git diff --check
```

If only Android UI code changed, the two Gradle commands and `git diff --check` are the minimum.

Additional verification run on 2026-06-24 for mobile attachments:

```powershell
python -m pytest tests/integration/test_mobile_api.py tests/unit/test_multimodal_normalization.py tests/unit/test_multimodal_polish.py tests/unit/test_mobile_upload_service.py -q
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest :app:assembleDebug --rerun-tasks
git diff --check
```

Backend smoke checks on 2026-06-24:

- `GET /mobile/status` returned `features.attachments=true`.
- `POST /mobile/uploads?kind=file&filename=smoke.txt` returned 200 and a `MediaAttachment`.

Real-device APK install was not re-run for this attachment pass because `adb devices` was empty. `adb mdns services` saw `192.168.1.5:44043`, but direct `adb connect` was refused, likely because the phone-side wireless debugging session had expired.

Additional verification on 2026-06-30 for Phone Agent v0 backend:

```powershell
& .\venv\Scripts\python.exe -m pytest tests\integration\test_phone_agent_protocol.py -q
```

Result: 6 passed. Existing FastAPI/Pydantic deprecation warnings remain unrelated.

Android unit tests were not executed in this shell because `JAVA_HOME` is unset and no `java` command is available in `PATH`. Re-run when JDK is available:

```powershell
.\gradlew.bat :app:testDebugUnitTest --tests "com.neno.app.data.AgentProtocolTest"
.\gradlew.bat :app:testDebugUnitTest --tests "com.neno.app.ui.AppNavContractTest"
```
