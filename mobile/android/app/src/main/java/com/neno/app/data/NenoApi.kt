package com.neno.app.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

class NenoApi(
    private val settingsStore: SettingsStore,
) {
    suspend fun status(): MobileStatus {
        val json = requestJson(path = "mobile/status")
        val features = json.optJSONObject("features") ?: JSONObject()
        return MobileStatus(
            success = json.optBoolean("success"),
            serverTime = json.optString("server_time"),
            api = json.optString("api"),
            sessionIdLabel = json.optString("session_id_label"),
            features = MobileFeatureFlags(
                attachments = features.optBoolean("attachments"),
                notifications = features.optBoolean("notifications"),
                quickReply = features.optBoolean("quick_reply"),
            ),
        )
    }

    suspend fun conversations(): List<MobileConversation> {
        val json = requestJson(path = "mobile/conversations")
        return parseConversations(json.optJSONArray("conversations") ?: JSONArray())
    }

    suspend fun messages(conversationId: String, limit: Int = 50): MobileMessagesResult {
        val json = requestJson(path = "mobile/conversations/$conversationId/messages?limit=$limit")
        return MobileMessagesResult(
            messages = parseMessages(json.optJSONArray("messages") ?: JSONArray()),
            presence = json.optString("presence", DEFAULT_NENO_PRESENCE).ifBlank { DEFAULT_NENO_PRESENCE },
        )
    }

    suspend fun sendMessage(conversationId: String, text: String): MobileSendMessageResponse {
        val body = JSONObject().put("text", text).toString()
        val json = requestJson(
            path = "mobile/conversations/$conversationId/messages",
            method = "POST",
            body = body,
        )
        return MobileSendMessageResponse(
            success = json.optBoolean("success"),
            conversationId = json.optString("conversation_id"),
            userMessage = parseMessage(json.getJSONObject("user_message")),
            assistantMessage = json.optJSONObject("assistant_message")?.let(::parseMessage),
        )
    }

    private suspend fun requestJson(
        path: String,
        method: String = "GET",
        body: String? = null,
    ): JSONObject = withContext(Dispatchers.IO) {
        val token = settingsStore.token
        if (token.isBlank()) {
            throw IOException("请先在设置里填写访问令牌")
        }

        val url = URL("${settingsStore.baseUrl}/${path.trimStart('/')}")
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 10_000
            readTimeout = 30_000
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("Accept", "application/json")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
        }

        try {
            val stream = if (connection.responseCode in 200..299) {
                connection.inputStream
            } else {
                connection.errorStream
            }
            val response = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (connection.responseCode !in 200..299) {
                throw IOException("请求失败：HTTP ${connection.responseCode}")
            }
            JSONObject(response)
        } finally {
            connection.disconnect()
        }
    }

    private fun parseConversations(items: JSONArray): List<MobileConversation> =
        (0 until items.length()).map { index ->
            val item = items.getJSONObject(index)
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

    private fun parseMessages(items: JSONArray): List<MobileMessage> =
        (0 until items.length()).map { index -> parseMessage(items.getJSONObject(index)) }

    private fun parseMessage(item: JSONObject): MobileMessage =
        MobileMessage(
            id = item.optLong("id"),
            role = item.optString("role"),
            text = item.optString("text"),
            createdAt = item.optNullableString("created_at"),
            displayTime = item.optNullableString("display_time"),
            pending = item.optBoolean("pending"),
        )

    private fun JSONObject.optNullableString(name: String): String? =
        if (isNull(name)) null else optString(name)
}
