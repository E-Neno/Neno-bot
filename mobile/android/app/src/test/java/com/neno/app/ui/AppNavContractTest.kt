package com.neno.app.ui

import java.nio.file.Path
import kotlin.io.path.exists
import kotlin.io.path.readText
import org.junit.Assert.assertTrue
import org.junit.Test

class AppNavContractTest {
    @Test
    fun conversationToChatTransitionUsesMotionNotOnlyFade() {
        val source = readMainSource("com/neno/app/ui/AppNav.kt")

        assertTrue(
            "Opening a conversation should feel like a smooth screen transition, not a fade-only content swap.",
            source.contains("AnimatedContent") &&
                source.contains("slideInHorizontally") &&
                source.contains("slideOutHorizontally") &&
                source.contains("fadeIn") &&
                source.contains("fadeOut") &&
                source.contains("targetState.ordinal") &&
                source.contains("initialState.ordinal"),
        )
    }

    @Test
    fun toolsTabOpensNativeAgentShell() {
        val navSource = readMainSource("com/neno/app/ui/AppNav.kt")
        val shellSource = readMainSource("com/neno/app/ui/agent/AgentShellScreen.kt")

        assertTrue(navSource.contains("AgentShell"))
        assertTrue(navSource.contains("AgentShellScreen"))
        assertTrue(shellSource.contains("手机 Agent"))
        assertTrue(shellSource.contains("默认权限"))
    }

    private fun readMainSource(relativePath: String): String {
        val userDir = Path.of(System.getProperty("user.dir"))
        val candidates = listOf(
            userDir.resolve("src/main/java").resolve(relativePath),
            userDir.resolve("app/src/main/java").resolve(relativePath),
        )
        return candidates.firstOrNull { it.exists() }?.readText()
            ?: error("Could not locate $relativePath from $userDir; tried $candidates")
    }
}
