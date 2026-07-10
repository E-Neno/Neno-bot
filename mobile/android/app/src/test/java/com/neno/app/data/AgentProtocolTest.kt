package com.neno.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentProtocolTest {
    @Test
    fun websocketUrlUsesMobileAgentPath() {
        assertEquals(
            "ws://10.0.2.2:8000/mobile/agent/ws",
            agentWebSocketUrl("http://10.0.2.2:8000/"),
        )
        assertEquals(
            "wss://neno.example.com/mobile/agent/ws",
            agentWebSocketUrl("https://neno.example.com"),
        )
    }

    @Test
    fun parsesControllerHello() {
        val event = AgentRealtimeEvent.parse(
            """{"type":"hello","device_id":"controller","client":"pc-console","protocol":"phone-agent-v0"}""",
        )

        assertTrue(event is AgentRealtimeEvent.Hello)
        val hello = event as AgentRealtimeEvent.Hello
        assertEquals("controller", hello.deviceId)
        assertEquals("phone-agent-v0", hello.protocol)
    }

    @Test
    fun observationKeepsCapabilityFlagsExplicit() {
        val observation = AgentObservation(
            deviceId = "xiaomi-14-local",
            state = "idle",
            foregroundApp = "浏览器",
            screen = AgentScreen(width = 1080, height = 2400),
            capabilities = AgentCapabilities(
                accessibility = true,
                screenshot = true,
                notification = false,
                rootDaemon = false,
                kernelTouch = false,
            ),
        )

        assertTrue(observation.capabilities.accessibility)
        assertFalse(observation.capabilities.kernelTouch)
    }
}
