package com.neno.app.ui.chat

import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.exists
import kotlin.io.path.readText
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatInsetsContractTest {
    @Test
    fun chatScreensApplyImePaddingOnlyAroundTheInputArea() {
        val offenders = listOf("NenoChatScreen.kt", "HermesChatScreen.kt").filter { fileName ->
            val source = readMainSource("com/neno/app/ui/chat/$fileName")
            Regex("""\.statusBarsPadding\(\)\s*\.navigationBarsPadding\(\)\s*\.imePadding\(\)""")
                .containsMatchIn(source) ||
                !source.contains("KeyboardAwareInputArea")
        }

        assertTrue(
            "Chat shells must keep IME padding local to the input area, not the whole screen: $offenders",
            offenders.isEmpty(),
        )
    }

    @Test
    fun mainActivityLetsComposeHandleKeyboardInsets() {
        val manifest = readMainSource("AndroidManifest.xml")

        assertTrue(
            "MainActivity must use adjustNothing so Compose owns keyboard positioning.",
            manifest.contains("android:windowSoftInputMode=\"adjustNothing\""),
        )
    }

    private fun readMainSource(relativePath: String): String {
        val userDir = Path.of(System.getProperty("user.dir"))
        val candidates = listOf(
            userDir.resolve("src/main/java").resolve(relativePath),
            userDir.resolve("src/main").resolve(relativePath),
            userDir.resolve("app/src/main/java").resolve(relativePath),
            userDir.resolve("app/src/main").resolve(relativePath),
        )
        return candidates.firstOrNull { it.exists() }?.readText()
            ?: error("Could not locate $relativePath from $userDir; tried $candidates")
    }
}
