package com.neno.app.data

import android.content.Context

class SettingsStore(context: Context) {
    private val prefs = context.getSharedPreferences("neno_settings", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL
        private set(value) {
            prefs.edit().putString(KEY_BASE_URL, normalizeBaseUrl(value)).apply()
        }

    var token: String
        get() = prefs.getString(KEY_TOKEN, "") ?: ""
        private set(value) {
            prefs.edit().putString(KEY_TOKEN, value.trim()).apply()
        }

    var hermesBaseUrl: String
        get() = prefs.getString(KEY_HERMES_URL, DEFAULT_HERMES_URL) ?: DEFAULT_HERMES_URL
        set(value) {
            prefs.edit().putString(KEY_HERMES_URL, normalizeBaseUrl(value)).apply()
        }

    var hermesApiKey: String
        get() = prefs.getString(KEY_HERMES_API_KEY, "") ?: ""
        set(value) {
            prefs.edit().putString(KEY_HERMES_API_KEY, value.trim()).apply()
        }

    var hermesSessionId: String?
        get() = prefs.getString(KEY_HERMES_SESSION_ID, null)
        set(value) {
            prefs.edit().putString(KEY_HERMES_SESSION_ID, value).apply()
        }

    /** Locally persisted user messages (API doesn't store them) */
    fun saveHermesUserMessage(text: String) {
        val existing = prefs.getString(KEY_HERMES_USER_MSGS, "[]") ?: "[]"
        val arr = org.json.JSONArray(existing)
        arr.put(org.json.JSONObject().apply {
            put("text", text)
            put("ts", System.currentTimeMillis() / 1000.0)
        })
        prefs.edit().putString(KEY_HERMES_USER_MSGS, arr.toString()).apply()
    }

    fun getHermesUserMessages(): List<Pair<String, Double>> {
        val raw = prefs.getString(KEY_HERMES_USER_MSGS, "[]") ?: "[]"
        val arr = org.json.JSONArray(raw)
        val result = mutableListOf<Pair<String, Double>>()
        for (i in 0 until arr.length()) {
            val obj = arr.optJSONObject(i) ?: continue
            result.add(Pair(obj.optString("text", ""), obj.optDouble("ts", 0.0)))
        }
        return result
    }

    fun clearHermesUserMessages() {
        prefs.edit().remove(KEY_HERMES_USER_MSGS).apply()
    }

    fun saveNenoMessages(messages: List<MobileMessage>) {
        val arr = org.json.JSONArray()
        messages.takeLast(MAX_CACHED_NENO_MESSAGES).forEach { message ->
            arr.put(org.json.JSONObject().apply {
                put("id", message.id)
                put("role", message.role)
                put("text", message.text)
                put("created_at", message.createdAt)
                put("display_time", message.displayTime)
                put("attachments", org.json.JSONArray().apply {
                    message.attachments.forEach { attachment ->
                        put(org.json.JSONObject().apply {
                            put("kind", attachment.kind)
                            put("url", attachment.url)
                            put("media_path", attachment.mediaPath)
                            put("mime_type", attachment.mimeType)
                            put("source", attachment.source)
                            put("text_hint", attachment.textHint)
                            put("duration_ms", attachment.durationMs)
                            put("local_uri", attachment.localUri)
                        })
                    }
                })
                put("pending", message.pending)
            })
        }
        prefs.edit().putString(KEY_NENO_MESSAGES, arr.toString()).apply()
    }

    fun getNenoMessages(): List<MobileMessage> {
        val raw = prefs.getString(KEY_NENO_MESSAGES, "[]") ?: "[]"
        val arr = runCatching { org.json.JSONArray(raw) }.getOrDefault(org.json.JSONArray())
        val result = mutableListOf<MobileMessage>()
        for (i in 0 until arr.length()) {
            val item = arr.optJSONObject(i) ?: continue
            result.add(
                MobileMessage(
                    id = item.optLong("id"),
                    role = item.optString("role"),
                    text = item.optString("text"),
                    createdAt = item.optNullableString("created_at"),
                    displayTime = item.optNullableString("display_time"),
                    attachments = item.optJSONArray("attachments")?.let(::parseCachedAttachments).orEmpty(),
                    pending = item.optBoolean("pending"),
                ),
            )
        }
        return result
    }

    fun saveConversations(conversations: List<MobileConversation>) {
        val arr = org.json.JSONArray()
        conversations.forEach { conversation ->
            arr.put(org.json.JSONObject().apply {
                put("id", conversation.id)
                put("title", conversation.title)
                put("subtitle", conversation.subtitle)
                put("last_message", conversation.lastMessage)
                put("last_message_at", conversation.lastMessageAt)
                put("unread_count", conversation.unreadCount)
                put("pinned", conversation.pinned)
                put("kind", conversation.kind)
                put("presence", conversation.presence)
            })
        }
        prefs.edit().putString(KEY_CONVERSATIONS, arr.toString()).apply()
    }

    fun getConversations(): List<MobileConversation> {
        val raw = prefs.getString(KEY_CONVERSATIONS, "[]") ?: "[]"
        val arr = runCatching { org.json.JSONArray(raw) }.getOrDefault(org.json.JSONArray())
        val result = mutableListOf<MobileConversation>()
        for (i in 0 until arr.length()) {
            val item = arr.optJSONObject(i) ?: continue
            result.add(
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
                ),
            )
        }
        return result
    }

    val hermesConfigured: Boolean
        get() = hermesBaseUrl.isNotBlank() && hermesApiKey.isNotBlank()

    fun save(baseUrl: String, token: String) {
        this.baseUrl = baseUrl
        this.token = token
    }

    companion object {
        const val DEFAULT_BASE_URL = "http://10.0.2.2:8000"
        const val DEFAULT_HERMES_URL = "http://10.0.2.2:8642"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_TOKEN = "mobile_token"
        private const val KEY_HERMES_URL = "hermes_base_url"
        private const val KEY_HERMES_API_KEY = "hermes_api_key"
        private const val KEY_HERMES_SESSION_ID = "hermes_session_id"
        private const val KEY_HERMES_USER_MSGS = "hermes_user_msgs"
        private const val KEY_NENO_MESSAGES = "neno_messages"
        private const val KEY_CONVERSATIONS = "conversations"
        private const val MAX_CACHED_NENO_MESSAGES = 100

        fun normalizeBaseUrl(value: String): String {
            val normalized = value.trim().trimEnd('/')
            return normalized.ifBlank { DEFAULT_BASE_URL }
        }
    }
}

private fun org.json.JSONObject.optNullableString(name: String): String? =
    if (isNull(name)) null else optString(name)

private fun parseCachedAttachments(items: org.json.JSONArray): List<MobileAttachment> =
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
            localUri = item.optNullableString("local_uri"),
        )
    }

private fun org.json.JSONObject.optNullableLong(name: String): Long? =
    if (isNull(name)) null else optLong(name)
