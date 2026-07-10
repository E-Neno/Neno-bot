package com.neno.app.data

import org.json.JSONObject

const val PHONE_AGENT_PROTOCOL = "phone-agent-v0"

fun agentWebSocketUrl(baseUrl: String): String {
    val trimmed = baseUrl.trim().trimEnd('/')
    val wsBase = when {
        trimmed.startsWith("https://") -> "wss://${trimmed.removePrefix("https://")}"
        trimmed.startsWith("http://") -> "ws://${trimmed.removePrefix("http://")}"
        trimmed.startsWith("wss://") || trimmed.startsWith("ws://") -> trimmed
        else -> "ws://$trimmed"
    }
    return "$wsBase/mobile/agent/ws"
}

data class AgentCapabilities(
    val accessibility: Boolean = false,
    val screenshot: Boolean = false,
    val notification: Boolean = false,
    val rootDaemon: Boolean = false,
    val kernelTouch: Boolean = false,
)

data class AgentScreen(
    val width: Int,
    val height: Int,
)

data class AgentObservation(
    val deviceId: String,
    val state: String,
    val foregroundApp: String? = null,
    val screen: AgentScreen,
    val capabilities: AgentCapabilities = AgentCapabilities(),
)

sealed interface AgentRealtimeEvent {
    data class Hello(
        val deviceId: String,
        val client: String,
        val protocol: String,
    ) : AgentRealtimeEvent

    data class Pong(val deviceId: String) : AgentRealtimeEvent
    data class Presence(val deviceId: String, val state: String) : AgentRealtimeEvent
    data class ObservationAck(val deviceId: String) : AgentRealtimeEvent

    companion object {
        fun parse(text: String): AgentRealtimeEvent? {
            val json = runCatching { JSONObject(text) }.getOrNull() ?: return null
            return when (json.optString("type")) {
                "hello" -> Hello(
                    deviceId = json.optString("device_id"),
                    client = json.optString("client"),
                    protocol = json.optString("protocol", PHONE_AGENT_PROTOCOL),
                )
                "pong" -> Pong(deviceId = json.optString("device_id"))
                "presence" -> Presence(
                    deviceId = json.optString("device_id"),
                    state = json.optString("state"),
                )
                "observation_ack" -> ObservationAck(deviceId = json.optString("device_id"))
                else -> null
            }
        }
    }
}
