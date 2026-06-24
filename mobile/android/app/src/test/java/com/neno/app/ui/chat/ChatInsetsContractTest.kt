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

    @Test
    fun mainManifestAllowsLanCleartextHttpForSideLoadedBuilds() {
        val manifest = readMainSource("AndroidManifest.xml")

        assertTrue(
            "Main manifest must allow cleartext HTTP because side-loaded release builds talk to LAN dev servers.",
            manifest.contains("android:usesCleartextTraffic=\"true\""),
        )
    }

    @Test
    fun chatInputUsesPromptBoxStyleWithoutPersistentPlaceholderTools() {
        val source = readMainSource("com/neno/app/ui/chat/NenoChatScreen.kt")

        assertTrue(
            "Chat input should use the prompt-box composer surface.",
            source.contains("PromptBoxActionButton") && source.contains("PromptBoxIcon"),
        )
        assertTrue(
            "Prompt-box plus button should open a tool menu with image/camera/file actions.",
            source.contains("PromptBoxToolMenu") &&
                source.contains("\"图片\"") &&
                source.contains("\"相机\"") &&
                source.contains("\"文件\""),
        )
        assertTrue(
            "Prompt-box tool menu must be rendered in a Popup so it does not resize the input bar or cover the plus button.",
            source.contains("Popup(") &&
                source.contains("PopupProperties") &&
                !source.contains(".offset(y = (-62).dp)"),
        )
        assertTrue(
            "Chat input must not keep fake smile/paperclip tools permanently visible.",
            !source.contains("icon = NenoIcon.Smile") && !source.contains("icon = NenoIcon.Paperclip"),
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
