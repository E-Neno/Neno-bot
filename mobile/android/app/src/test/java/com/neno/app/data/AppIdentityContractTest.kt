package com.neno.app.data

import java.nio.file.Path
import kotlin.io.path.exists
import kotlin.io.path.readText
import org.junit.Assert.assertTrue
import org.junit.Test

class AppIdentityContractTest {
    @Test
    fun apkIdentityIsPhoneAgentNotNeno() {
        val gradle = readProjectFile("app/build.gradle.kts")
        val strings = readProjectFile("app/src/main/res/values/strings.xml")

        assertTrue(gradle.contains("""applicationId = "com.hxie7.phoneagent""""))
        assertTrue(strings.contains("""<string name="app_name">手机智能体</string>"""))
    }

    private fun readProjectFile(relativePath: String): String {
        val userDir = Path.of(System.getProperty("user.dir"))
        val candidates = listOf(
            userDir.resolve(relativePath),
            userDir.parent?.resolve(relativePath),
        ).filterNotNull()
        return candidates.firstOrNull { it.exists() }?.readText()
            ?: error("Could not locate $relativePath from $userDir; tried $candidates")
    }
}
