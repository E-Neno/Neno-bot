package com.ai.assistance.operit.ui.features.chat.components

import org.junit.Assert.assertEquals
import org.junit.Test

class NenoRemoteSelectionTest {
    @Test
    fun `configured remote opens Neno chat`() {
        assertEquals(
            NenoRemoteSelectionAction.OpenChat,
            resolveNenoRemoteSelection(isConfigured = true),
        )
    }

    @Test
    fun `unconfigured remote opens connection settings`() {
        assertEquals(
            NenoRemoteSelectionAction.OpenConfiguration,
            resolveNenoRemoteSelection(isConfigured = false),
        )
    }
}
