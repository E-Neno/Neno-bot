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

    @Test
    fun nenoChatInputWiresAttachmentPickers() {
        val source = readMainSource("com/neno/app/ui/chat/NenoChatScreen.kt")

        assertTrue(
            "Neno chat should register image and file pickers for mobile attachments.",
            source.contains("ActivityResultContracts.GetContent") &&
                source.contains("\"image/*\"") &&
                source.contains("\"*/*\""),
        )
        assertTrue(
            "Prompt-box actions must call attachment picker callbacks instead of closing the menu only.",
            source.contains("onPickImage") &&
                source.contains("onPickVoice") &&
                source.contains("onPickFile") &&
                source.contains("sendUploadedAttachment"),
        )
    }

    @Test
    fun nenoChatRendersImageAttachmentsAsPhotos() {
        val source = readMainSource("com/neno/app/ui/chat/NenoChatScreen.kt")

        assertTrue(
            "Image attachments must render as complete photos, not cropped preview bubbles or normalized vision text.",
            source.contains("AttachmentImage") &&
                source.contains("Image(") &&
                source.contains("imageAttachments") &&
                source.contains("ContentScale.Fit") &&
                !source.contains("ContentScale.Crop") &&
                !source.contains(".aspectRatio(1.22f)"),
        )
    }

    @Test
    fun nenoChatProvidesLargeImagePreviewAndStableImageScroll() {
        val source = readMainSource("com/neno/app/ui/chat/NenoChatScreen.kt")

        assertTrue(
            "Image messages should open a full-screen large preview, not only show the inline thumbnail.",
            source.contains("AttachmentImagePreview") &&
                source.contains("Dialog(") &&
                source.contains("DialogProperties(usePlatformDefaultWidth = false)") &&
                source.contains("onPreviewImage") &&
                source.contains("detectTransformGestures") &&
                source.contains("graphicsLayer"),
        )
        assertTrue(
            "Image loading must notify the list so returning to chat stays pinned to the newest message after aspect ratio changes.",
            source.contains("imageLayoutRevision") &&
                source.contains("onImageLoaded") &&
                source.contains("LaunchedEffect(displayMessages.size, isSending, imageLayoutRevision)") &&
                source.contains("animateScrollToItem(lastIndex)"),
        )
    }

    @Test
    fun nenoChatWiresRealCameraAndVoiceRecording() {
        val source = readMainSource("com/neno/app/ui/chat/NenoChatScreen.kt")

        assertTrue(
            "Camera action should use a real TakePicture contract backed by FileProvider.",
            source.contains("ActivityResultContracts.TakePicture") &&
                source.contains("FileProvider.getUriForFile") &&
                source.contains("Manifest.permission.CAMERA"),
        )
        assertTrue(
            "Voice action should record microphone audio instead of opening an audio file picker.",
            source.contains("MediaRecorder") &&
                source.contains("Manifest.permission.RECORD_AUDIO") &&
                source.contains("toggleVoiceRecording") &&
                !source.contains("voicePicker.launch(\"audio/*\")"),
        )
        assertTrue(
            "Tapping the mic should switch the composer into hold-to-talk mode; it must not immediately start recording.",
            source.contains("voiceMode") &&
                source.contains("按住说话") &&
                source.contains("toggleVoiceRecording") &&
                source.contains("voiceMode = !voiceMode") &&
                !source.contains("onPickVoice = { toggleVoiceRecording() }"),
        )
        assertTrue(
            "Hold-to-talk must send on release and support sliding up to cancel.",
            source.contains("awaitLongPressOrCancellation") &&
            source.contains("onVoiceHoldStart") &&
                source.contains("onVoiceHoldEnd(cancelled") &&
                source.contains("cancelThresholdPx") &&
                source.contains("上滑取消") &&
                source.contains("松开取消"),
        )
        assertTrue(
            "The voice button should use the previous mic icon, not the waveform icon.",
            source.contains("PromptBoxIcon.Mic") &&
                !source.contains("PromptBoxIcon.Voice") &&
                !source.contains("drawVoiceWave"),
        )
        assertTrue(
            "Entering the chat should avoid crossfading the entire message list; initial load should not combine fade animation with first scroll.",
            !source.contains("Crossfade(\n            targetState = asyncListState(messages)") &&
                source.contains("when (asyncListState(messages))"),
        )
    }

    @Test
    fun mainManifestAllowsCameraVoiceAndCacheFileProvider() {
        val manifest = readMainSource("AndroidManifest.xml")
        val filePaths = readMainSource("res/xml/file_paths.xml")

        assertTrue(
            "Main manifest must declare camera, microphone, and cache FileProvider support for capture uploads.",
            manifest.contains("android.permission.CAMERA") &&
                manifest.contains("android.permission.RECORD_AUDIO") &&
                manifest.contains("androidx.core.content.FileProvider") &&
                manifest.contains("@xml/file_paths"),
        )
        assertTrue(
            "FileProvider paths should only expose app cache files used for temporary captures.",
            filePaths.contains("<cache-path") &&
                filePaths.contains("neno_cache"),
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
