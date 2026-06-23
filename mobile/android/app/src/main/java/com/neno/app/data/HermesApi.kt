package com.neno.app.data

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.IOException
import java.io.InputStreamReader
import java.util.concurrent.TimeUnit

class HermesApi(
    private val settingsStore: SettingsStore,
) {
    suspend fun chat(message: String, sessionId: String? = null): HermesResponse =
        withContext(Dispatchers.IO) {
            val body = buildRequestBody(message, stream = false)
            val request = buildRequest(body, sessionId)
            val response = client.newCall(request).execute()

            response.use { resp ->
                if (!resp.isSuccessful) {
                    val errBody = resp.body?.string().orEmpty()
                    throw IOException("Hermes 请求失败：HTTP ${resp.code} $errBody")
                }
                val bodyString = resp.body?.string()
                    ?: throw IOException("响应体为空")
                val json = JSONObject(bodyString)
                val content = json.optJSONArray("choices")
                    ?.optJSONObject(0)
                    ?.optJSONObject("message")
                    ?.optString("content", "")
                    .orEmpty()
                val newSessionId = resp.header("X-Hermes-Session-Id") ?: sessionId
                HermesResponse(content = content, sessionId = newSessionId)
            }
        }

    fun chatStream(message: String, sessionId: String? = null): Flow<StreamChunk> = flow {
        val body = buildRequestBody(message, stream = true)
        val request = buildRequest(body, sessionId)
        val response = client.newCall(request).execute()

        response.use { resp ->
            if (!resp.isSuccessful) {
                val errBody = resp.body?.string().orEmpty()
                throw IOException("Hermes 请求失败：HTTP ${resp.code} $errBody")
            }

            val newSessionId = resp.header("X-Hermes-Session-Id") ?: sessionId
            emit(StreamChunk.SessionId(newSessionId))

            val inputStream = resp.body?.byteStream()
                ?: throw IOException("响应体为空")
            val reader = BufferedReader(InputStreamReader(inputStream, Charsets.UTF_8))

            val dataBuffer = StringBuilder()
            try {
                while (true) {
                    val line = reader.readLine() ?: break

                    when {
                        line.isBlank() -> {
                            if (dataBuffer.isNotEmpty()) {
                                val data = dataBuffer.toString().trim()
                                dataBuffer.clear()
                                if (data == "[DONE]") break
                                parseSSEData(data)?.let { emit(it) }
                            }
                        }
                        line.startsWith("data:") -> {
                            dataBuffer.appendLine(line.removePrefix("data:").trim())
                        }
                        line.startsWith(":") -> {} // SSE comment, ignore
                    }
                }
            } finally {
                reader.close()
            }
        }
    }.flowOn(Dispatchers.IO)

    private fun parseSSEData(data: String): StreamChunk? {
        return try {
            val json = JSONObject(data)
            val choice = json.optJSONArray("choices")?.optJSONObject(0) ?: return null
            val delta = choice.optJSONObject("delta")
            val finishReason = choice.optString("finish_reason").takeIf { it.isNotEmpty() }

            // Debug: log what we're getting
            val deltaKeys = delta?.keys()?.asSequence()?.toList().orEmpty()
            Log.d(TAG, "SSE delta_keys=$deltaKeys finish=$finishReason")

            if (delta == null) {
                // No delta — might be a finish_reason-only chunk
                if (finishReason == "tool_calls") return StreamChunk.ToolExecuting
                return null
            }

            // 1. Text content
            val content = delta.optString("content").takeIf { it.isNotEmpty() }
            if (!content.isNullOrEmpty()) return StreamChunk.Text(content)

            // 2. Reasoning / thinking
            val reasoning = delta.optString("reasoning_content").takeIf { it.isNotEmpty() }
                ?: delta.optString("reasoning").takeIf { it.isNotEmpty() }
            if (!reasoning.isNullOrEmpty()) return StreamChunk.Thinking(reasoning)

            // 3. Tool calls
            val toolCalls = delta.optJSONArray("tool_calls")
            if (toolCalls != null && toolCalls.length() > 0) {
                val tc = toolCalls.optJSONObject(0) ?: return null
                val func = tc.optJSONObject("function")
                val name = func?.optString("name")?.takeIf { it.isNotEmpty() }
                val args = func?.optString("arguments")?.takeIf { it.isNotEmpty() }
                Log.d(TAG, "SSE tool_call: name=$name args=${args?.take(50)}")
                if (name != null) return StreamChunk.ToolCall(name = name, arguments = args)
            }

            // 4. finish_reason with tool_calls
            if (finishReason == "tool_calls") return StreamChunk.ToolExecuting

            null
        } catch (e: Exception) {
            Log.w(TAG, "Failed to parse SSE data: $data", e)
            null
        }
    }

    private fun buildRequestBody(message: String, stream: Boolean): JSONObject {
        val messages = JSONArray().put(
            JSONObject().put("role", "user").put("content", message),
        )
        return JSONObject().apply {
            put("model", "hermes-agent")
            put("messages", messages)
            put("stream", stream)
        }
    }

    private fun buildRequest(body: JSONObject, sessionId: String?): Request {
        val token = settingsStore.hermesApiKey
        if (token.isBlank()) {
            throw IOException("请先在设置里填写 Hermes API Key")
        }
        return Request.Builder()
            .url("${settingsStore.hermesBaseUrl}/v1/chat/completions")
            .addHeader("Authorization", "Bearer $token")
            .addHeader("Content-Type", "application/json; charset=utf-8")
            .apply {
                if (sessionId != null) {
                    addHeader("X-Hermes-Session-Id", sessionId)
                }
            }
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
    }

    /**
     * Get the api_server session with the most messages (for loading full history).
     */
    suspend fun getLatestSessionId(): String? = withContext(Dispatchers.IO) {
        val token = settingsStore.hermesApiKey
        if (token.isBlank()) return@withContext null

        val request = Request.Builder()
            .url("${settingsStore.hermesBaseUrl}/api/sessions")
            .addHeader("Authorization", "Bearer $token")
            .get()
            .build()

        val response = client.newCall(request).execute()
        response.use { resp ->
            if (!resp.isSuccessful) return@use null
            val body = resp.body?.string() ?: return@use null
            val json = org.json.JSONObject(body)
            val data = json.optJSONArray("data") ?: return@use null

            // Pick the api_server session with the most messages
            var bestId: String? = null
            var bestCount = 0
            for (i in 0 until data.length()) {
                val session = data.optJSONObject(i) ?: continue
                val source = session.optString("source", "")
                if (source == "api_server") {
                    val count = session.optInt("message_count", 0)
                    if (count > bestCount) {
                        bestCount = count
                        bestId = session.optString("id", "").ifEmpty { null }
                    }
                }
            }
            bestId
        }
    }

    /**
     * Load conversation history across ALL api_server sessions.
     * Messages are sorted by timestamp and deduplicated.
     */
    suspend fun getHistory(sessionId: String): List<HermesHistoryMessage> =
        withContext(Dispatchers.IO) {
            val token = settingsStore.hermesApiKey
            if (token.isBlank()) return@withContext emptyList()

            // First, get all sessions
            val sessionsRequest = Request.Builder()
                .url("${settingsStore.hermesBaseUrl}/api/sessions")
                .addHeader("Authorization", "Bearer $token")
                .get()
                .build()

            val sessionsResp = client.newCall(sessionsRequest).execute()
            val sessionIds = sessionsResp.use { resp ->
                if (!resp.isSuccessful) return@use listOf(sessionId)
                val body = resp.body?.string() ?: return@use listOf(sessionId)
                val json = org.json.JSONObject(body)
                val data = json.optJSONArray("data") ?: return@use listOf(sessionId)
                val ids = mutableListOf<String>()
                for (i in 0 until data.length()) {
                    val s = data.optJSONObject(i) ?: continue
                    if (s.optString("source") == "api_server") {
                        ids.add(s.optString("id"))
                    }
                }
                if (ids.isEmpty()) listOf(sessionId) else ids
            }

            // Load messages from all sessions
            data class TimestampedMsg(val role: String, val text: String, val ts: Double, val hasToolCalls: Boolean)
            val allMessages = mutableListOf<TimestampedMsg>()

            for (sid in sessionIds) {
                val request = Request.Builder()
                    .url("${settingsStore.hermesBaseUrl}/api/sessions/$sid/messages")
                    .addHeader("Authorization", "Bearer $token")
                    .get()
                    .build()

                val response = client.newCall(request).execute()
                response.use { resp ->
                    if (!resp.isSuccessful) return@use
                    val body = resp.body?.string() ?: return@use
                    val json = org.json.JSONObject(body)
                    val data = json.optJSONArray("data") ?: return@use

                    for (i in 0 until data.length()) {
                        val msg = data.optJSONObject(i) ?: continue
                        val role = msg.optString("role", "")
                        val content = msg.optString("content", "").trim()
                        val ts = msg.optDouble("timestamp", 0.0)
                        val hasToolCalls = msg.optJSONArray("tool_calls")?.length()?.let { it > 0 } == true

                        when {
                            role == "user" && content.isNotEmpty() ->
                                allMessages.add(TimestampedMsg("user", content, ts, false))
                            role == "assistant" && hasToolCalls ->
                                allMessages.add(TimestampedMsg("assistant", "", ts, true))
                            role == "assistant" && content.isNotEmpty() ->
                                allMessages.add(TimestampedMsg("assistant", content, ts, false))
                        }
                    }
                }
            }

            // Sort by timestamp
            allMessages.sortBy { it.ts }

            // Phase 2: deduplicate consecutive identical user messages
            val deduped = mutableListOf<TimestampedMsg>()
            for (msg in allMessages) {
                val prev = deduped.lastOrNull()
                if (msg.role == "user" && prev != null && prev.role == "user" && prev.text == msg.text) {
                    continue
                }
                deduped.add(msg)
            }

            // Phase 3: (removed - trailing user messages are valid from local storage)

            // Phase 4: remove assistant tool-call-only entries
            val cleaned = deduped.filter { !(it.role == "assistant" && it.hasToolCalls) }

            // Phase 5: re-dedup (Phase 4 may expose new adjacencies)
            val final = mutableListOf<HermesHistoryMessage>()
            for (msg in cleaned) {
                val prev = final.lastOrNull()
                if (msg.role == "user" && prev != null && prev.role == "user" && prev.text == msg.text) {
                    continue
                }
                final.add(HermesHistoryMessage(role = msg.role, text = msg.text, timestamp = msg.ts))
            }
            final
        }

    companion object {
        private const val TAG = "HermesApi"
        private val client = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .build()
    }
}

data class HermesHistoryMessage(
    val role: String,
    val text: String,
    val isToolCall: Boolean = false,
    val timestamp: Double = 0.0,
)

data class HermesResponse(
    val content: String,
    val sessionId: String? = null,
)

sealed class StreamChunk {
    data class Text(val content: String) : StreamChunk()
    data class SessionId(val id: String?) : StreamChunk()
    data class Thinking(val content: String) : StreamChunk()
    data class ToolCall(val name: String, val arguments: String?) : StreamChunk()
    data object ToolExecuting : StreamChunk()
}
