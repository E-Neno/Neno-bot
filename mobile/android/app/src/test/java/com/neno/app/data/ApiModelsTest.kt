package com.neno.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ApiModelsTest {
    @Test
    fun conversationModelKeepsChineseUiText() {
        val conversation = MobileConversation(
            id = "neno",
            title = "Neno",
            subtitle = "置顶联系人",
            pinned = true,
            kind = "primary",
        )

        assertEquals("置顶联系人", conversation.subtitle)
        assertTrue(conversation.pinned)
    }

    @Test
    fun baseUrlNormalizationRemovesTrailingSlash() {
        assertEquals(
            "http://10.0.2.2:8000",
            SettingsStore.normalizeBaseUrl(" http://10.0.2.2:8000/ "),
        )
    }
}
