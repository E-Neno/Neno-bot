package com.neno.app.data

import android.os.Handler
import android.os.Looper
import java.io.IOException
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject

fun mobileWebSocketUrl(baseUrl: String): String {
    val trimmed = baseUrl.trim().trimEnd('/')
    val wsBase = when {
        trimmed.startsWith("https://") -> "wss://${trimmed.removePrefix("https://")}"
        trimmed.startsWith("http://") -> "ws://${trimmed.removePrefix("http://")}"
        trimmed.startsWith("wss://") || trimmed.startsWith("ws://") -> trimmed
        else -> "ws://$trimmed"
    }
    return "$wsBase/mobile/ws"
}

sealed interface MobileRealtimeEvent {
    data object Hello : MobileRealtimeEvent
    data object Pong : MobileRealtimeEvent
    data class Presence(val conversationId: String, val presence: String) : MobileRealtimeEvent
    data class Conversations(val conversations: List<MobileConversation>) : MobileRealtimeEvent
    data class Messages(val conversationId: String, val messages: List<MobileMessage>) : MobileRealtimeEvent
    data class Message(val conversationId: String, val message: MobileMessage) : MobileRealtimeEvent

    companion object {
        fun parse(text: String): MobileRealtimeEvent? {
            val json = runCatching { JSONObject(text) }.getOrNull() ?: return null
            return when (json.optString("type")) {
                "hello" -> Hello
                "pong" -> Pong
                "presence" -> Presence(
                    conversationId = json.optString("conversation_id"),
                    presence = json.optString("presence", DEFAULT_NENO_PRESENCE).ifBlank { DEFAULT_NENO_PRESENCE },
                )
                "conversations" -> Conversations(
                    conversations = parseRealtimeConversations(json.optJSONArray("conversations") ?: JSONArray()),
                )
                "messages" -> Messages(
                    conversationId = json.optString("conversation_id"),
                    messages = parseRealtimeMessages(json.optJSONArray("messages") ?: JSONArray()),
                )
                "message" -> {
                    val item = json.optJSONObject("message") ?: return null
                    Message(
                        conversationId = json.optString("conversation_id"),
                        message = parseRealtimeMessage(item),
                    )
                }
                else -> null
            }
        }
    }
}

private fun parseRealtimeConversations(items: JSONArray): List<MobileConversation> =
    (0 until items.length()).mapNotNull { index ->
        val item = items.optJSONObject(index) ?: return@mapNotNull null
        MobileConversation(
            id = item.optString("id"),
            title = item.optString("title"),
            subtitle = item.optString("subtitle"),
            lastMessage = item.optString("last_message"),
            lastMessageAt = item.optNullableString("last_message_at"),
            unreadCount = item.optInt("unread_count"),
            pinned = item.optBoolean("pinned"),
            kind = item.optString("kind"),
            presence = item.optString("presence", DEFAULT_NENO_PRESENCE).ifBlank { DEFAULT_NENO_PRESENCE },
        )
    }

private fun parseRealtimeMessages(items: JSONArray): List<MobileMessage> =
    (0 until items.length()).mapNotNull { index ->
        items.optJSONObject(index)?.let(::parseRealtimeMessage)
    }

private fun parseRealtimeMessage(item: JSONObject): MobileMessage =
    MobileMessage(
        id = item.optLong("id"),
        role = item.optString("role"),
        text = item.optString("text"),
        createdAt = item.optNullableString("created_at"),
        displayTime = item.optNullableString("display_time"),
        attachments = parseRealtimeAttachments(item.optJSONArray("attachments") ?: JSONArray()),
        pending = item.optBoolean("pending"),
    )

private fun parseRealtimeAttachments(items: JSONArray): List<MobileAttachment> =
    (0 until items.length()).mapNotNull { index ->
        val item = items.optJSONObject(index) ?: return@mapNotNull null
        MobileAttachment(
            kind = item.optString("kind"),
            url = item.optNullableString("url"),
            mediaPath = item.optNullableString("media_path"),
            mimeType = item.optNullableString("mime_type"),
            source = item.optNullableString("source"),
            textHint = item.optNullableString("text_hint"),
            durationMs = item.optNullableLong("duration_ms"),
        )
    }

private fun JSONObject.optNullableString(name: String): String? =
    if (isNull(name)) null else optString(name)

private fun JSONObject.optNullableLong(name: String): Long? =
    if (isNull(name)) null else optLong(name)

class MobileRealtimeClient(
    private val settingsStore: SettingsStore,
    private val listener: Listener,
) {
    interface Listener {
        fun onOpen()
        fun onEvent(event: MobileRealtimeEvent)
        fun onFailure(error: Throwable)
        fun onClosed()
    }

    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private val reconnectHandler = Handler(Looper.getMainLooper())
    private var shouldReconnect = false
    private var reconnectAttempts = 0

    fun start() {
        stop()
        shouldReconnect = true
        reconnectAttempts = 0
        openSocket()
    }

    private fun openSocket() {
        val token = settingsStore.token
        if (token.isBlank()) {
            listener.onFailure(IOException("请先在设置里填写访问令牌"))
            return
        }

        val request = runCatching {
            Request.Builder()
                .url(mobileWebSocketUrl(settingsStore.baseUrl))
                .addHeader("Authorization", "Bearer $token")
                .build()
        }.getOrElse { error ->
            listener.onFailure(error)
            scheduleReconnect()
            return
        }

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                reconnectAttempts = 0
                listener.onOpen()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                MobileRealtimeEvent.parse(text)?.let(listener::onEvent)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                clearSocket(webSocket)
                if (shouldReconnect) {
                    listener.onClosed()
                    scheduleReconnect()
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                clearSocket(webSocket)
                if (shouldReconnect) {
                    listener.onFailure(t)
                    scheduleReconnect()
                }
            }
        })
    }

    private fun scheduleReconnect() {
        if (!shouldReconnect) return
        val delayMs = minOf(30_000L, 2_000L * (reconnectAttempts + 1))
        reconnectAttempts += 1
        reconnectHandler.removeCallbacksAndMessages(null)
        reconnectHandler.postDelayed({ openSocket() }, delayMs)
    }

    private fun clearSocket(socket: WebSocket) {
        if (webSocket == socket) {
            webSocket = null
        }
    }

    fun stop() {
        shouldReconnect = false
        reconnectHandler.removeCallbacksAndMessages(null)
        webSocket?.close(1000, "app paused")
        webSocket = null
    }
}
