package com.neno.app.data

import kotlin.io.path.exists
import kotlin.io.path.readText
import java.nio.file.Path
import org.junit.Assert.assertTrue
import org.junit.Test

class NenoAttachmentContractTest {
    @Test
    fun nenoApiUploadsAttachmentsAndSendsAttachmentJson() {
        val apiSource = readMainSource("com/neno/app/data/NenoApi.kt")
        val modelSource = readMainSource("com/neno/app/data/ApiModels.kt")
        val repoSource = readMainSource("com/neno/app/data/NenoRepository.kt")

        assertTrue(
            "Mobile data models must include an attachment object matching the backend MediaAttachment shape.",
            modelSource.contains("data class MobileAttachment") &&
                modelSource.contains("url") &&
                modelSource.contains("mediaPath") &&
                modelSource.contains("textHint") &&
                modelSource.contains("durationMs") &&
                modelSource.contains("localUri"),
        )
        assertTrue(
            "Mobile messages must keep attachments so chat bubbles can render photos instead of normalized vision text.",
            modelSource.contains("attachments: List<MobileAttachment>"),
        )
        assertTrue(
            "NenoApi must upload raw attachment bytes to /mobile/uploads before sending.",
            apiSource.contains("uploadAttachment") &&
                apiSource.contains("mobile/uploads") &&
                apiSource.contains("rawBody"),
        )
        assertTrue(
            "NenoApi.sendMessage must serialize attachments into the message JSON body.",
            apiSource.contains("attachments") &&
                apiSource.contains("attachmentToJson") &&
                apiSource.contains("duration_ms"),
        )
        assertTrue(
            "NenoApi should surface backend error detail instead of hiding it behind a bare HTTP code.",
            apiSource.contains("errorDetail") &&
                apiSource.contains("optString(\"detail\""),
        )
        assertTrue(
            "Repository must expose uploadAttachment and sendToNeno attachments overloads to the UI.",
            repoSource.contains("uploadAttachment") &&
                repoSource.contains("downloadAttachment") &&
                repoSource.contains("attachments: List<MobileAttachment>") &&
                repoSource.contains("api.sendMessage(\"neno\", normalized, attachments)"),
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
