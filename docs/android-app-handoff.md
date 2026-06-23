# Neno Android App Handoff

> Status date: 2026-06-23.
> Audience: Claude or another coding agent continuing the native Android app.

## Read First

Before editing code, read these files in order:

1. `NENO.md`
2. `NENO_ARCHITECTURE.md`
3. `docs/android-app-design-brief.md`
4. `docs/android-app-implementation-plan.md`
5. This handoff document

The Android app is a native Kotlin + Jetpack Compose app under `mobile/android/`. It is not the backend web console, not Expo, not React Native, and not a WebView wrapper.

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
- Tests: `tests/integration/test_mobile_api.py`

Mobile API contract:

- `GET /mobile/status`
- `GET /mobile/conversations`
- `GET /mobile/conversations/neno/messages?limit=50`
- `POST /mobile/conversations/neno/messages`
- Authentication uses `Authorization: Bearer <MOBILE_TOKEN>`.
- Default mobile session is controlled by `MOBILE_DEFAULT_SESSION_ID`, defaulting to `mobile:neno`.

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
- Shared visuals: `mobile/android/app/src/main/java/com/neno/app/ui/components/NenoVisuals.kt`

Implemented UI details:

- The conversation list uses a light background with a pinned Neno card and lighter utility contacts.
- The top of the list now uses a light inline brand row: a custom self-drawn `NenoBrandIcon` plus `Neno`.
- The rejected version had a full black banner. Do not restore it.
- The app is locked to portrait in `AndroidManifest.xml`.
- The chat screen has a Neno header, date divider, preview bubbles when there are no backend messages, and a bottom input bar.
- The real chat loop is wired in `NenoChatScreen.kt`: optimistic pending user bubble, send via `/mobile/conversations/neno/messages`, append the real user and assistant messages, auto-scroll to the newest message, and a Neno typing indicator (three animated dots) while the reply is in flight.
- On send failure the optimistic bubble is removed, the typed text is restored into the input box, and a Chinese error bar with `点这里重试` resends the draft.
- If the backend returns no assistant message (presence gate stashed it), the chat shows a soft Chinese hint `她看到了，晚点回你。` instead of a silent gap.
- The conversation list refreshes the Neno last-message preview on every return because the `when`-based nav in `AppNav.kt` disposes and re-runs `ConversationListScreen`'s `LaunchedEffect`.
- Settings stores server URL and mobile token in `SharedPreferences`; do not commit real tokens.

## Verified State

Commands run successfully on 2026-06-23:

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:assembleDebug
.\mobile\android\gradlew.bat -p .\mobile\android :app:testDebugUnitTest
git diff --check
```

`git diff --check` only reported existing LF/CRLF warnings in backend files:

- `app/config.py`
- `app/main.py`
- `app/routers/__init__.py`
- `app/security.py`

Real-device validation:

- Wireless ADB device used: `192.168.1.5:44043`
- APK install succeeded with:

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb -s 192.168.1.5:44043 install -r -t .\mobile\android\app\build\outputs\apk\debug\app-debug.apk
& $adb -s 192.168.1.5:44043 shell am start -n com.neno.app/.MainActivity
```

Screenshots captured during validation:

- `tmp/screens/neno-brand-light-home.png`: accepted light brand row after removing the black banner.
- `tmp/screens/neno-brand-home.png`: rejected black banner reference; do not use as target.
- `tmp/screens/neno-small-chat.png`: compact chat screen from the previous UI pass.

## Next Best Task

The smallest real chat loop is now implemented in code (see Current Implementation). It builds and passes
`:app:assembleDebug` and `:app:testDebugUnitTest`; the backend `/mobile/*` contract and prompt cache tests pass.

What is NOT yet done is live end-to-end validation against a running backend on a real device. That is the next task:

1. Start the backend with mobile token and nonessential loops disabled.
2. Configure the Android settings screen with the backend base URL (LAN IP for a real phone) and the mobile token.
3. Open Neno chat.
4. Send one Chinese message and confirm: pending bubble → typing dots → assistant reply, auto-scrolled into view.
5. Kill the backend mid-send and confirm the Chinese error bar appears and the typed text is restored.
6. Return to the conversation list and confirm the Neno last-message preview updated.

Only after a person sees this work on a device should the loop be called validated.

Suggested backend command for local validation:

```powershell
$env:MOBILE_TOKEN="mobile-test-token"
$env:PROACTIVE_MODE="off"
$env:PROACTIVE_ENABLED="false"
$env:PROACTIVE_AUTO_SEND="false"
$env:BRAIN_INTENT_CONSUMER_ENABLED="false"
$env:CONSCIOUSNESS_WORLD_LOOP_ENABLED="false"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Use the computer LAN IP in the app settings when testing on a physical phone. Use `http://10.0.2.2:8000` only for an Android emulator.

## Hard Boundaries

Do not change these while continuing the app:

- `context_builder.py` prompt assembly order
- Session aggregation or submit locks
- `history_digest` cursor semantics
- Living World write ownership
- Any direct Android read/write path to SQLite
- Any direct Android call to `/debug/*`, `/session/*`, or admin-only endpoints
- Any committed real `MOBILE_TOKEN`, admin token, platform token, or server secret

The Android app must enter the existing chat path only through `/mobile/*`.

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
