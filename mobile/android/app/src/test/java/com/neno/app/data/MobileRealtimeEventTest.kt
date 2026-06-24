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

    @Test
    fun parsesMessageEvent() {
        val event = MobileRealtimeEvent.parse(
            """
            {
              "type": "message",
              "conversation_id": "neno",
              "message": {
                "id": 42,
                "role": "assistant",
                "text": "late reply",
                "created_at": null,
                "display_time": "23:41",
                "pending": false
              }
            }
            """.trimIndent(),
        )

        assertTrue(event is MobileRealtimeEvent.Message)
        val messageEvent = event as MobileRealtimeEvent.Message
        assertEquals("neno", messageEvent.conversationId)
        assertEquals(42L, messageEvent.message.id)
        assertEquals("assistant", messageEvent.message.role)
        assertEquals("late reply", messageEvent.message.text)
        assertEquals("23:41", messageEvent.message.displayTime)
    }
}
