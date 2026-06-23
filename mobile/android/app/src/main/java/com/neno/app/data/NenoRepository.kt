package com.neno.app.data

import java.io.IOException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class NenoRepository(
    private val api: NenoApi,
    private val settingsStore: SettingsStore,
) {
    private val _connectionState = MutableStateFlow(AppConnectionState())
    val connectionState: StateFlow<AppConnectionState> = _connectionState.asStateFlow()

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

    suspend fun loadNenoMessages(): MobileMessagesResult =
        runCatching { api.messages("neno") }
            .onSuccess { result -> markConnected(result.presence) }
            .onFailure { markFailure(it) }
            .getOrElse {
                MobileMessagesResult(
                    messages = emptyList(),
                    presence = _connectionState.value.presence ?: DEFAULT_NENO_PRESENCE,
                )
            }

    suspend fun sendToNeno(text: String): Result<MobileSendMessageResponse> {
        val normalized = text.trim()
        if (normalized.isBlank()) {
            return Result.failure(IllegalArgumentException("消息不能为空"))
        }
        return runCatching { api.sendMessage("neno", normalized) }
            .onSuccess { markConnected() }
            .onFailure { markFailure(it) }
    }

    fun saveSettings(baseUrl: String, token: String) {
        settingsStore.save(baseUrl, token)
        _connectionState.value = _connectionState.value.checking()
        if (realtimeStarted) {
            realtimeClient.start()
        }
    }

    fun currentBaseUrl(): String = settingsStore.baseUrl

    fun currentToken(): String = settingsStore.token

    private fun markConnected(presence: String? = null) {
        _connectionState.value = _connectionState.value.connected(presence)
    }

    private fun markFailure(error: Throwable) {
        _connectionState.value = _connectionState.value.failed(error)
    }

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
