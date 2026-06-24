package com.neno.app.data

import android.util.Log
import java.io.IOException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.asSharedFlow

class NenoRepository(
    private val api: NenoApi,
    private val hermesApi: HermesApi,
    private val settingsStore: SettingsStore,
) {
    private val _connectionState = MutableStateFlow(AppConnectionState())
    val connectionState: StateFlow<AppConnectionState> = _connectionState.asStateFlow()
    private val _incomingNenoMessages = MutableSharedFlow<MobileMessage>(extraBufferCapacity = 32)
    val incomingNenoMessages = _incomingNenoMessages.asSharedFlow()

    private var realtimeStarted = false
    private val realtimeClient = MobileRealtimeClient(
        settingsStore = settingsStore,
        listener = object : MobileRealtimeClient.Listener {
            override fun onOpen() {
                markConnected()
            }

            override fun onEvent(event: MobileRealtimeEvent) {
                when (event) {
                    MobileRealtimeEvent.Hello,
                    MobileRealtimeEvent.Pong -> markConnected()
                    is MobileRealtimeEvent.Presence -> markConnected(event.presence)
                    is MobileRealtimeEvent.Message -> {
                        markConnected()
                        if (event.conversationId == "neno") {
                            mergeCachedNenoMessages(listOf(event.message))
                            _incomingNenoMessages.tryEmit(event.message)
                        }
                    }
                }
            }

            override fun onFailure(error: Throwable) {
                if (realtimeStarted) {
                    markFailure(error)
                }
            }

            override fun onClosed() {
                if (realtimeStarted) {
                    markFailure(IOException("WebSocket closed"))
                }
            }
        },
    )

    fun startRealtime() {
        realtimeStarted = true
        realtimeClient.start()
    }

    fun stopRealtime() {
        realtimeStarted = false
        realtimeClient.stop()
    }

    suspend fun checkStatus(): MobileStatus {
        if (_connectionState.value.status != ConnectionStatus.Connected) {
            _connectionState.value = _connectionState.value.checking()
        }
        return runCatching { api.status() }
            .onSuccess { markConnected() }
            .onFailure { markFailure(it) }
            .getOrThrow()
    }

    suspend fun refreshConnection(): AppConnectionState {
        runCatching { checkStatus() }
        return _connectionState.value
    }

    suspend fun loadConversations(): List<MobileConversation> =
        runCatching { api.conversations() }
            .onSuccess { conversations ->
                markConnected(conversations.firstOrNull { it.id == "neno" }?.presence)
            }
            .onFailure { markFailure(it) }
            .getOrElse { defaultConversations() }
            .let { convs ->
                if (settingsStore.hermesConfigured && convs.none { it.id == "hermes" }) {
                    convs + hermesConversation()
                } else {
                    convs
                }
            }

    suspend fun loadNenoMessages(): MobileMessagesResult =
        runCatching { api.messages("neno") }
            .onSuccess { result ->
                markConnected(result.presence)
                settingsStore.saveNenoMessages(result.messages)
            }
            .onFailure { markFailure(it) }
            .getOrElse {
                MobileMessagesResult(
                    messages = settingsStore.getNenoMessages(),
                    presence = _connectionState.value.presence ?: DEFAULT_NENO_PRESENCE,
                )
            }

    suspend fun sendToNeno(text: String): Result<MobileSendMessageResponse> {
        val normalized = text.trim()
        if (normalized.isBlank()) {
            return Result.failure(IllegalArgumentException("消息不能为空"))
        }
        return runCatching { api.sendMessage("neno", normalized) }
            .onSuccess { response ->
                markConnected()
                mergeCachedNenoMessages(listOfNotNull(response.userMessage, response.assistantMessage))
            }
            .onFailure { markFailure(it) }
    }

    suspend fun sendToHermes(text: String): Result<HermesResponse> {
        val normalized = text.trim()
        if (normalized.isBlank()) {
            return Result.failure(IllegalArgumentException("消息不能为空"))
        }
        settingsStore.saveHermesUserMessage(normalized)
        return runCatching {
            hermesApi.chat(normalized, hermesSessionId).also {
                hermesSessionId = it.sessionId
            }
        }
            .onSuccess { markConnected() }
            .onFailure { markFailure(it) }
    }

    /**
     * Streaming version: emits text chunks as they arrive.
     * Collect the flow and build the response incrementally.
     */
    fun sendToHermesStream(text: String): Flow<StreamChunk> = flow {
        val normalized = text.trim()
        if (normalized.isBlank()) {
            throw IllegalArgumentException("消息不能为空")
        }
        // Persist user message locally (API doesn't store it)
        settingsStore.saveHermesUserMessage(normalized)
        hermesApi.chatStream(normalized, hermesSessionId).collect { chunk ->
            when (chunk) {
                is StreamChunk.SessionId -> hermesSessionId = chunk.id
                is StreamChunk.Text -> {
                    markConnected()
                    emit(chunk)
                }
                is StreamChunk.Thinking,
                is StreamChunk.ToolCall,
                is StreamChunk.ToolExecuting -> emit(chunk)
            }
        }
    }

    /**
     * Load Hermes conversation history for the current session.
     * Merges server-side assistant messages with locally persisted user messages.
     */
    suspend fun getHermesHistory(): List<HermesHistoryMessage> {
        // If no session ID yet, discover the latest one
        if (hermesSessionId == null) {
            val latestId = runCatching { hermesApi.getLatestSessionId() }.getOrNull()
            Log.d("HermesRepo", "Latest session ID: $latestId")
            if (latestId != null) hermesSessionId = latestId
        }
        val sid = hermesSessionId
        Log.d("HermesRepo", "Loading history for session: $sid")
        if (sid == null) return emptyList()

        // Load server history (assistant messages + tool calls)
        val serverMessages = runCatching { hermesApi.getHistory(sid) }
            .onFailure { Log.e("HermesRepo", "History load failed", it) }
            .getOrDefault(emptyList())

        // Load locally saved user messages
        val localUserMsgs = settingsStore.getHermesUserMessages()
            .map { HermesHistoryMessage(role = "user", text = it.first, timestamp = it.second) }

        // Merge: combine all messages, sort by timestamp, deduplicate
        val allMessages = (serverMessages + localUserMsgs).sortedBy { it.timestamp }

        // Deduplicate consecutive identical user messages
        val final = mutableListOf<HermesHistoryMessage>()
        for (msg in allMessages) {
            val prev = final.lastOrNull()
            if (msg.role == "user" && prev != null && prev.role == "user" && prev.text == msg.text) {
                continue
            }
            final.add(msg)
        }

        Log.d("HermesRepo", "Merged ${serverMessages.size} server + ${localUserMsgs.size} local = ${final.size} final")
        return final
    }

    fun saveSettings(baseUrl: String, token: String) {
        settingsStore.save(baseUrl, token)
        _connectionState.value = _connectionState.value.checking()
        if (realtimeStarted) {
            realtimeClient.start()
        }
    }

    fun saveHermesSettings(url: String, apiKey: String) {
        settingsStore.hermesBaseUrl = url
        settingsStore.hermesApiKey = apiKey
        hermesSessionId = null
    }

    fun currentBaseUrl(): String = settingsStore.baseUrl

    fun currentToken(): String = settingsStore.token

    fun currentHermesBaseUrl(): String = settingsStore.hermesBaseUrl

    fun currentHermesApiKey(): String = settingsStore.hermesApiKey

    private fun markConnected(presence: String? = null) {
        _connectionState.value = _connectionState.value.connected(presence)
    }

    private fun markFailure(error: Throwable) {
        _connectionState.value = _connectionState.value.failed(error)
    }

    private fun mergeCachedNenoMessages(newMessages: List<MobileMessage>) {
        if (newMessages.isEmpty()) return
        val merged = (settingsStore.getNenoMessages() + newMessages)
            .filterNot { it.pending }
            .distinctBy { it.id }
            .sortedBy { it.id }
        settingsStore.saveNenoMessages(merged)
    }

    private var hermesSessionId: String?
        get() = settingsStore.hermesSessionId
        set(value) { settingsStore.hermesSessionId = value }

    private fun hermesConversation(): MobileConversation = MobileConversation(
        id = "hermes",
        title = "Hermes",
        subtitle = "AI 助手",
        lastMessage = "",
        kind = "utility",
    )

    companion object {
        fun defaultConversations(): List<MobileConversation> = listOf(
            MobileConversation(
                id = "neno",
                title = "Neno",
                subtitle = "置顶联系人",
                lastMessage = "",
                pinned = true,
                kind = "primary",
            ),
            MobileConversation(
                id = "writing",
                title = "写作助手",
                subtitle = "工具联系人",
                lastMessage = "",
                kind = "utility",
            ),
            MobileConversation(
                id = "code",
                title = "代码助手",
                subtitle = "工具联系人",
                lastMessage = "",
                kind = "utility",
            ),
            MobileConversation(
                id = "quiet",
                title = "安静记录",
                subtitle = "工具联系人",
                lastMessage = "",
                kind = "utility",
            ),
        )
    }
}
