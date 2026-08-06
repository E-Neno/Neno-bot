# Neno Remote Integration

## Pinned baseline

- Upstream release: `v1.12.0`
- Commit: `fc76cf5b5086c9ca85eba54384588dccd729315c`
- Working branch: `codex/neno-remote-friend`
- Upstream remote: `https://github.com/AAswordman/Operit.git`
- Android Gradle Plugin: `8.13.2`
- Gradle wrapper: `8.13`
- Kotlin plugin: `2.2.0`
- Java source and target: `17`
- Android SDK: compile `36`, target `34`, minimum `26`

The local launcher uses the configured JDK 17 at `JAVA_HOME`. The repository already includes
OkHttp `4.12.0`, Retrofit, Room `2.8.4`, and an OkHttp WebSocket implementation, so the Neno
transport does not need another network or persistence stack.

`gradlew --version` succeeds. The initial `gradlew help` baseline did not complete: the first run
failed while downloading `org.ow2.asm:asm-analysis:9.8` from Maven Central because Gradle's TLS
connection was closed by the remote peer; a direct HEAD request returned HTTP 200. A second run
stalled in dependency resolution and was stopped after the command timeout. This happened before
any source changes.

## Existing extension points

- `data/model/ActivePrompt.kt`: explicit active prompt identity used by the chat UI.
- `data/preferences/CharacterCardManager.kt`: `combinePrompts()` assembles local character-card
  prompts. Neno remote must never call this method.
- `data/model/ChatHistory.kt` and `data/model/ChatEntity.kt`: chat metadata and Room projection.
- `data/model/ChatMessage.kt` and `data/model/MessageEntity.kt`: UI message and Room projection.
- `data/repository/ChatHistoryManager.kt`: native history/cache ownership.
- `ui/features/chat/components/CharacterSelectorPanel.kt`: character list entry point.
- `ui/features/chat/screens/AIChatScreen.kt` and `ui/features/chat/viewmodel/ChatViewModel.kt`:
  active prompt selection and message submission boundary.
- `services/core/ChatHistoryDelegate.kt`: creates and restores native chats, including character
  opening messages.
- `services/core/MessageCoordinationDelegate.kt`: local model coordination boundary that the Neno
  transport must bypass.
- `api/chat/enhance/ToolExecutionManager.kt`: native Agent tool execution reused in a later phase.

## Phase-one contract

`NENO_REMOTE` is a managed remote friend, not a `CharacterCard` and not an LLM provider. It has a
deterministic local chat key scoped by normalized `backend_id + account_id`, contributes no local
prompt, has one permanent conversation, and routes message submission to the Neno transport. Local
Room data is a cache; the Neno backend remains the history source of truth.

## Runtime behavior

The character selector contains a special `Neno` entry. Selecting it opens a locked, pinned Room
projection whose ID is derived from the normalized backend URL and account ID. The selector entry
is not a `CharacterCard`; selecting or sending through it never calls `combinePrompts()` or the
local LLM service.

The connection dialog stores the backend URL, account ID, and mobile token in app-private
preferences. The token is sent only as `Authorization: Bearer ...`. The HTTP contract is:

- `GET /mobile/conversations/neno/messages?limit=100&after_id=<cursor>`
- `POST /mobile/conversations/neno/messages` with `client_message_id`
- `POST /mobile/uploads` for image, voice, and file attachments

The repository persists a cursor-scoped cache and drafts in DataStore. Remote message IDs are the
merge key, and the backend remains authoritative. Sending while offline is rejected and leaves the
draft intact. The native chat UI is reused for rendering; TTS and richer remote media rendering are
later phases.
