package com.neno.app.data

const val DEFAULT_NENO_PRESENCE = "在线"

enum class ConnectionStatus {
    Checking,
    Connected,
    Disconnected,
    Unauthorized,
}

data class AppConnectionState(
    val status: ConnectionStatus = ConnectionStatus.Checking,
    val presence: String? = null,
    val errorMessage: String? = null,
) {
    fun connected(presence: String? = null): AppConnectionState =
        copy(
            status = ConnectionStatus.Connected,
            presence = presence?.takeIf { it.isNotBlank() } ?: this.presence,
            errorMessage = null,
        )

    fun checking(): AppConnectionState =
        copy(status = ConnectionStatus.Checking, errorMessage = null)

    fun failed(error: Throwable): AppConnectionState =
        copy(
            status = if (error.message?.contains("403") == true) {
                ConnectionStatus.Unauthorized
            } else {
                ConnectionStatus.Disconnected
            },
            errorMessage = error.message,
        )

    fun connectionLabel(): String = when (status) {
        ConnectionStatus.Checking -> "连接中"
        ConnectionStatus.Connected -> "已连接"
        ConnectionStatus.Disconnected -> "未连接"
        ConnectionStatus.Unauthorized -> "令牌无效"
    }

    fun chatPresenceLabel(): String = when (status) {
        ConnectionStatus.Checking -> presence ?: "连接中"
        ConnectionStatus.Connected -> presence ?: DEFAULT_NENO_PRESENCE
        ConnectionStatus.Disconnected -> "未连接"
        ConnectionStatus.Unauthorized -> "令牌无效"
    }
}
