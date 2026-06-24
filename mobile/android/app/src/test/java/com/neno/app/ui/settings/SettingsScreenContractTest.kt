package com.neno.app.ui.settings

import kotlin.io.path.exists
import kotlin.io.path.readText
import java.nio.file.Path
import org.junit.Assert.assertTrue
import org.junit.Test

class SettingsScreenContractTest {
    @Test
    fun passwordFieldsExposeVisibilityToggle() {
        val source = readMainSource("com/neno/app/ui/settings/SettingsScreen.kt")

        assertTrue(
            "Password fields must expose an eye toggle so the user can verify typed tokens.",
            source.contains("trailingIcon") && source.contains("PasswordVisibilityIcon"),
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
