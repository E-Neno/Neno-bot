package com.neno.app.data

import java.nio.file.Path
import kotlin.io.path.exists
import kotlin.io.path.readText
import org.junit.Assert.assertTrue
import org.junit.Test

class NenoRealtimeContractTest {
    @Test
    fun realtimeConnectionIsThePrimaryForegroundConnectionSignal() {
        val appSource = readMainSource("com/neno/app/NenoApp.kt")
        val repoSource = readMainSource("com/neno/app/data/NenoRepository.kt")

        assertTrue(
            "NenoApp should not keep downgrading a healthy WebSocket with periodic HTTP status checks.",
            appSource.contains("repository.startRealtime()") &&
                !appSource.contains("while (true)") &&
                !appSource.contains("delay(30_000)"),
        )
        assertTrue(
            "Repository should ignore transient HTTP status failures while realtime is already connected.",
            repoSource.contains("isRealtimeConnected") &&
                repoSource.contains("if (isRealtimeConnected())") &&
                repoSource.contains("return _connectionState.value"),
        )
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
