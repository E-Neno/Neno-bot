package com.neno.app.data

import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Test

class ConnectionStateTest {
    @Test
    fun connectedPresenceUpdatesChatLabel() {
        val state = AppConnectionState().connected(presence = "稍后回复")

        assertEquals(ConnectionStatus.Connected, state.status)
        assertEquals("稍后回复", state.chatPresenceLabel())
        assertEquals("已连接", state.connectionLabel())
    }

    @Test
    fun connectedWithoutPresenceKeepsLastKnownPresence() {
        val previous = AppConnectionState(status = ConnectionStatus.Connected, presence = "睡着了")

        val state = previous.connected()

        assertEquals("睡着了", state.chatPresenceLabel())
    }

    @Test
    fun forbiddenFailureBecomesTokenInvalid() {
        val state = AppConnectionState().failed(IOException("请求失败：HTTP 403"))

        assertEquals(ConnectionStatus.Unauthorized, state.status)
        assertEquals("令牌无效", state.connectionLabel())
        assertEquals("令牌无效", state.chatPresenceLabel())
    }
}
