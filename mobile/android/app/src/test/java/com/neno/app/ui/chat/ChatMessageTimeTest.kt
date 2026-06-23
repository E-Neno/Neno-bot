package com.neno.app.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Test

class ChatMessageTimeTest {
    @Test
    fun isoTimestampDisplaysHourAndMinuteOnly() {
        assertEquals("8:42", formatChatMessageTime("2026-06-23T08:42:17", "user"))
    }

    @Test
    fun spaceSeparatedTimestampDisplaysHourAndMinuteOnly() {
        assertEquals("16:05", formatChatMessageTime("2026-06-23 16:05:01", "assistant"))
    }
}
