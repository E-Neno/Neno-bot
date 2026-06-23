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

    fun save(baseUrl: String, token: String) {
        this.baseUrl = baseUrl
        this.token = token
    }

    companion object {
        const val DEFAULT_BASE_URL = "http://10.0.2.2:8000"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_TOKEN = "mobile_token"

        fun normalizeBaseUrl(value: String): String {
            val normalized = value.trim().trimEnd('/')
            return normalized.ifBlank { DEFAULT_BASE_URL }
        }
    }
}
