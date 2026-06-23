package com.neno.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MobileRealtimeEventTest {
    @Test
    fun websocketUrlUsesMobileWsPath() {
        assertEquals(
            "ws://10.0.2.2:8000/mobile/ws",
            mobileWebSocketUrl("http://10.0.2.2:8000/"),
        )
        assertEquals(
            "wss://neno.example.com/mobile/ws",
            mobileWebSocketUrl("https://neno.example.com"),
        )
    }

    @Test
    fun parsesPresenceEvent() {
        val event = MobileRealtimeEvent.parse(
            """{"type":"presence","conversation_id":"neno","presence":"睡着了"}""",
        )

        assertTrue(event is MobileRealtimeEvent.Presence)
        assertEquals("睡着了", (event as MobileRealtimeEvent.Presence).presence)
    }
}
