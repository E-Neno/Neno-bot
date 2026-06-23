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

        fun normalizeBaseUrl(value: String): String {
            val normalized = value.trim().trimEnd('/')
            return normalized.ifBlank { DEFAULT_BASE_URL }
        }
    }
}
