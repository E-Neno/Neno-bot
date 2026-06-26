package com.neno.app.ui.chat

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Build
import android.os.SystemClock
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import androidx.core.content.ContextCompat
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.awaitLongPressOrCancellation
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupProperties
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.neno.app.data.AppConnectionState
import com.neno.app.data.ConnectionStatus
import com.neno.app.data.MobileAttachment
import com.neno.app.data.MobileMessage
import com.neno.app.data.NenoRepository
import com.neno.app.ui.AsyncListState
import com.neno.app.ui.asyncListState
import com.neno.app.ui.components.AppIcon
import com.neno.app.ui.components.AvatarKind
import com.neno.app.ui.components.NenoIcon
import com.neno.app.ui.components.PhotoAvatar
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.coroutines.resume

@Composable
fun NenoChatScreen(
    repository: NenoRepository,
    connectionState: AppConnectionState,
    onBack: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var messages by remember(repository) {
        mutableStateOf<List<MobileMessage>?>(repository.cachedNenoMessages().takeIf { it.isNotEmpty() })
    }
    var draft by remember { mutableStateOf("") }
    var isSending by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf<String?>(null) }
    var softNotice by remember { mutableStateOf<String?>(null) }
    var pendingCameraUri by remember { mutableStateOf<Uri?>(null) }
    var activeRecorder by remember { mutableStateOf<MediaRecorder?>(null) }
    var activeVoiceFile by remember { mutableStateOf<File?>(null) }
    var activeVoiceStartedAtMs by remember { mutableStateOf<Long?>(null) }
    var isRecording by remember { mutableStateOf(false) }

    DisposableEffect(Unit) {
        onDispose {
            runCatching { activeRecorder?.release() }
        }
    }

    fun reloadMessages() {
        scope.launch {
            errorText = null
            val result = repository.loadNenoMessages()
            messages = result.messages
        }
    }

    fun sendDraft() {
        val text = draft.trim()
        if (text.isBlank() || isSending) return

        val localId = -System.currentTimeMillis()
        messages = messages.orEmpty() + MobileMessage(
            id = localId,
            role = "user",
            text = text,
            pending = true,
        )
        draft = ""
        isSending = true
        errorText = null
        softNotice = null

        scope.launch {
            repository.sendToNeno(text).fold(
                onSuccess = { response ->
                    messages = buildList {
                        addAll(messages.orEmpty().filterNot { it.id == localId })
                        add(response.userMessage)
                        response.assistantMessage?.let(::add)
                    }
                    // 在场门控可能让她暂不回（assistantMessage 为空），给一句不打扰的提示。
                    softNotice = if (response.assistantMessage == null) "她看到了，晚点回你。" else null
                },
                onFailure = { error ->
                    // 失败时回收乐观气泡，并把刚才打的字还回输入框，别让用户白打。
                    messages = messages.orEmpty().filterNot { it.id == localId }
                    draft = text
                    errorText = error.message ?: "发送失败"
                },
            )
            isSending = false
        }
    }

    fun sendUploadedAttachment(kind: String, uri: Uri, durationMsOverride: Long? = null) {
        if (isSending) return

        val text = draft.trim()
        val localDurationMs = if (kind == "voice") {
            durationMsOverride ?: readVoiceDurationMs(context, localUri = uri)
        } else {
            null
        }
        val localAttachment = MobileAttachment(
            kind = kind,
            durationMs = localDurationMs,
            localUri = uri.toString(),
        )
        val localId = -System.currentTimeMillis()
        messages = messages.orEmpty() + MobileMessage(
            id = localId,
            role = "user",
            text = text,
            attachments = listOf(localAttachment),
            pending = true,
        )
        draft = ""
        isSending = true
        errorText = null
        softNotice = "正在上传"

        scope.launch {
            val payload = runCatching { readMobileUploadPayload(context, uri, kind) }
            payload.fold(
                onSuccess = { upload ->
                    repository.uploadAttachment(
                        kind = kind,
                        filename = upload.filename,
                        mimeType = upload.mimeType,
                        bytes = upload.bytes,
                    ).fold(
                        onSuccess = { attachment ->
                            val persistedAttachment = if (kind == "voice") {
                                attachment.copy(durationMs = localDurationMs)
                            } else {
                                attachment
                            }
                            repository.sendToNeno(text, listOf(persistedAttachment)).fold(
                                onSuccess = { response ->
                                    val responseAttachment = response.userMessage.attachments.firstOrNull()
                                        ?: persistedAttachment
                                    val displayAttachment = responseAttachment.copy(
                                        durationMs = responseAttachment.durationMs ?: localDurationMs,
                                        localUri = uri.toString(),
                                    )
                                    val displayUserMessage = response.userMessage.copy(
                                        text = text,
                                        attachments = listOf(displayAttachment),
                                    )
                                    messages = buildList {
                                        addAll(messages.orEmpty().filterNot { it.id == localId })
                                        add(displayUserMessage)
                                        response.assistantMessage?.let(::add)
                                    }
                                    softNotice = if (response.assistantMessage == null) "她看到了，晚点回你。" else null
                                },
                                onFailure = { error ->
                                    messages = messages.orEmpty().filterNot { it.id == localId }
                                    draft = text
                                    errorText = error.message ?: "发送失败"
                                    softNotice = null
                                },
                            )
                        },
                        onFailure = { error ->
                            messages = messages.orEmpty().filterNot { it.id == localId }
                            draft = text
                            errorText = error.message ?: "上传失败"
                            softNotice = null
                        },
                    )
                },
                onFailure = { error ->
                    messages = messages.orEmpty().filterNot { it.id == localId }
                    draft = text
                    errorText = error.message ?: "读取文件失败"
                    softNotice = null
                },
            )
            isSending = false
        }
    }

    val imagePicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        uri?.let { sendUploadedAttachment("image", it) }
    }
    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        uri?.let { sendUploadedAttachment("file", it) }
    }
    val cameraLauncher = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { captured ->
        val uri = pendingCameraUri
        pendingCameraUri = null
        if (captured && uri != null) {
            sendUploadedAttachment("image", uri)
        }
    }

    fun launchCameraCapture() {
        val uri = createCameraCaptureUri(context)
        pendingCameraUri = uri
        cameraLauncher.launch(uri)
    }

    val cameraPermissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            launchCameraCapture()
        } else {
            errorText = "没有相机权限"
        }
    }

    fun startVoiceRecording() {
        if (isSending || isRecording) return

        val file = createVoiceCaptureFile(context)
        val recorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(context)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }

        val started = runCatching {
            recorder.setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            recorder.setAudioEncodingBitRate(96_000)
            recorder.setAudioSamplingRate(44_100)
            recorder.setAudioChannels(1)
            recorder.setOutputFile(file.absolutePath)
            recorder.prepare()
            recorder.start()
        }

        started.fold(
            onSuccess = {
                activeRecorder = recorder
                activeVoiceFile = file
                activeVoiceStartedAtMs = SystemClock.elapsedRealtime()
                isRecording = true
                errorText = null
                softNotice = "正在录音，再点一次发送"
            },
            onFailure = { error ->
                runCatching { recorder.release() }
                runCatching { file.delete() }
                errorText = error.message ?: "录音启动失败"
                softNotice = null
            },
        )
    }

    fun stopVoiceRecording(cancelled: Boolean = false) {
        val recorder = activeRecorder ?: return
        val file = activeVoiceFile ?: return
        val startedAtMs = activeVoiceStartedAtMs
        activeRecorder = null
        activeVoiceFile = null
        activeVoiceStartedAtMs = null
        isRecording = false
        softNotice = null

        val stopped = runCatching {
            recorder.stop()
            recorder.release()
        }

        if (cancelled) {
            runCatching { file.delete() }
            softNotice = "已取消"
            return
        }

        stopped.fold(
            onSuccess = {
                val recordedDurationMs = startedAtMs
                    ?.let { SystemClock.elapsedRealtime() - it }
                    ?.takeIf { it > 0L }
                sendUploadedAttachment("voice", Uri.fromFile(file), durationMsOverride = recordedDurationMs)
            },
            onFailure = { error ->
                runCatching { recorder.release() }
                runCatching { file.delete() }
                errorText = error.message ?: "录音保存失败"
            },
        )
    }

    val recordAudioPermissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            startVoiceRecording()
        } else {
            errorText = "没有麦克风权限"
        }
    }

    fun requestVoiceRecording() {
        val granted = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.RECORD_AUDIO,
        ) == PackageManager.PERMISSION_GRANTED
        if (granted) {
            startVoiceRecording()
        } else {
            recordAudioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    fun stopVoiceRecordingIfActive(cancelled: Boolean) {
        if (isRecording) {
            stopVoiceRecording(cancelled)
        }
    }

    fun toggleVoiceRecording() {
        requestVoiceRecording()
    }

    LaunchedEffect(repository, connectionState.status) {
        val cached = repository.cachedNenoMessages()
        if (cached.isNotEmpty()) {
            messages = cached
        }
        if (cached.isEmpty() || connectionState.status != ConnectionStatus.Connected) {
            if (cached.isNotEmpty()) {
                delay(260)
            }
            reloadMessages()
        }
    }

    LaunchedEffect(repository) {
        repository.nenoMessageSnapshots.collect { snapshot ->
            messages = snapshot
        }
    }

    LaunchedEffect(repository) {
        repository.incomingNenoMessages.collect { incoming ->
            messages = (messages.orEmpty().filterNot { it.id == incoming.id } + incoming)
                .sortedBy { it.id }
        }
    }

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
    ) {
        val wide = maxWidth >= 520.dp
        val shellModifier = if (wide) {
            Modifier
                .width(430.dp)
                .fillMaxHeight()
        } else {
            Modifier.fillMaxSize()
        }

        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center,
        ) {
            ChatShell(
                repository = repository,
                messages = messages,
                draft = draft,
                onDraftChange = { draft = it },
                isSending = isSending,
                errorText = errorText,
                softNotice = softNotice,
                presence = connectionState.chatPresenceLabel(),
                onRetry = ::sendDraft,
                onSend = ::sendDraft,
                onPickImage = { imagePicker.launch("image/*") },
                onPickCamera = { cameraPermissionLauncher.launch(Manifest.permission.CAMERA) },
                onPickVoice = {},
                onPickFile = { filePicker.launch("*/*") },
                onVoiceHoldStart = { requestVoiceRecording() },
                onVoiceHoldEnd = { cancelled -> stopVoiceRecordingIfActive(cancelled) },
                isRecording = isRecording,
                onBack = onBack,
                onOpenSettings = onOpenSettings,
                modifier = shellModifier,
            )
        }
    }
}

@Composable
private fun ChatShell(
    repository: NenoRepository,
    messages: List<MobileMessage>?,
    draft: String,
    onDraftChange: (String) -> Unit,
    isSending: Boolean,
    errorText: String?,
    softNotice: String?,
    presence: String,
    onRetry: () -> Unit,
    onSend: () -> Unit,
    onPickImage: () -> Unit,
    onPickCamera: () -> Unit,
    onPickVoice: () -> Unit,
    onPickFile: () -> Unit,
    onVoiceHoldStart: () -> Unit,
    onVoiceHoldEnd: (Boolean) -> Unit,
    isRecording: Boolean,
    onBack: () -> Unit,
    onOpenSettings: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .background(MaterialTheme.colorScheme.background)
            .statusBarsPadding()
            .padding(start = 18.dp, top = 8.dp, end = 18.dp),
    ) {
        ChatHeader(presence = presence, onBack = onBack, onOpenSettings = onOpenSettings)
        Spacer(modifier = Modifier.height(14.dp))
        DateDivider()
        Spacer(modifier = Modifier.height(8.dp))

        if (errorText != null) {
            ErrorBar(message = errorText, onRetry = onRetry)
            Spacer(modifier = Modifier.height(12.dp))
        }

        MessageList(
            repository = repository,
            messages = messages,
            isSending = isSending,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
        )

        if (softNotice != null) {
            Spacer(modifier = Modifier.height(8.dp))
            SoftNotice(text = softNotice)
        }

        Spacer(modifier = Modifier.height(10.dp))
        KeyboardAwareInputArea {
            ChatInputBar(
                draft = draft,
                onDraftChange = onDraftChange,
                onSend = onSend,
                onPickImage = onPickImage,
                onPickCamera = onPickCamera,
                onPickVoice = onPickVoice,
                onPickFile = onPickFile,
                onVoiceHoldStart = onVoiceHoldStart,
                onVoiceHoldEnd = onVoiceHoldEnd,
                isSending = isSending,
                isRecording = isRecording,
            )
        }
    }
}

@Composable
private fun ChatHeader(
    presence: String,
    onBack: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    // 只有真「在线」才点亮暖色圆点；睡着/稍后回复/连接中都用中性灰，别假装她一直精神地等着。
    val online = presence == "在线"
    val dotColor = if (online) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconTapTarget(icon = NenoIcon.Back, onClick = onBack)
        Spacer(modifier = Modifier.width(13.dp))
        PhotoAvatar(
            kind = AvatarKind.Neno,
            modifier = Modifier.size(42.dp),
        )
        Spacer(modifier = Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "Neno",
                color = MaterialTheme.colorScheme.onBackground,
                fontSize = 20.sp,
                lineHeight = 24.sp,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(7.dp)
                        .clip(CircleShape)
                        .background(dotColor),
                )
                Spacer(modifier = Modifier.width(6.dp))
                Text(
                    text = presence,
                    color = MaterialTheme.colorScheme.secondary,
                    fontSize = 12.sp,
                    lineHeight = 16.sp,
                )
            }
        }
        IconTapTarget(icon = NenoIcon.MoreVertical, onClick = onOpenSettings)
    }
}

@Composable
private fun DateDivider() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .weight(1f)
                .height(1.dp)
                .background(MaterialTheme.colorScheme.outline.copy(alpha = 0.70f)),
        )
        Text(
            text = "今天",
            modifier = Modifier.padding(horizontal = 14.dp),
            color = MaterialTheme.colorScheme.secondary,
            fontSize = 13.sp,
            lineHeight = 18.sp,
        )
        Box(
            modifier = Modifier
                .weight(1f)
                .height(1.dp)
                .background(MaterialTheme.colorScheme.outline.copy(alpha = 0.70f)),
        )
    }
}

@Composable
private fun ErrorBar(
    message: String,
    onRetry: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .clickable(onClick = onRetry),
        color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.72f),
        shape = RoundedCornerShape(14.dp),
    ) {
        Column(modifier = Modifier.padding(horizontal = 15.dp, vertical = 10.dp)) {
            Text(
                text = message,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
                fontSize = 13.sp,
                lineHeight = 18.sp,
            )
            Spacer(modifier = Modifier.height(2.dp))
            Text(
                text = "点这里重试",
                color = MaterialTheme.colorScheme.primary,
                fontSize = 11.sp,
                lineHeight = 15.sp,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

@Composable
private fun SoftNotice(text: String) {
    Text(
        text = text,
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.secondary,
        fontSize = 12.sp,
        lineHeight = 16.sp,
        textAlign = TextAlign.Center,
    )
}

@Composable
private fun MessageList(
    repository: NenoRepository,
    messages: List<MobileMessage>?,
    isSending: Boolean,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier) {
        when (asyncListState(messages)) {
            AsyncListState.Loading -> LoadingMessageSpace(modifier = Modifier.fillMaxSize())
            AsyncListState.Empty -> {
                if (isSending) {
                    MessageLazyList(
                        repository = repository,
                        displayMessages = emptyList(),
                        isSending = true,
                        modifier = Modifier.fillMaxSize(),
                    )
                } else {
                    EmptyMessageSpace(modifier = Modifier.fillMaxSize())
                }
            }
            AsyncListState.Content -> MessageLazyList(
                repository = repository,
                displayMessages = messages.orEmpty().map(::toChatBubbleModel),
                isSending = isSending,
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}

@Composable
private fun MessageLazyList(
    repository: NenoRepository,
    displayMessages: List<ChatBubbleModel>,
    isSending: Boolean,
    modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()
    var didInitialScroll by remember { mutableStateOf(false) }
    var imageLayoutRevision by remember { mutableStateOf(0) }
    var previewAttachment by remember { mutableStateOf<MobileAttachment?>(null) }
    // 新消息或正在等回复时，把列表滚到最底，确保刚发的话和回复都在可视区。
    // 首次进入直接瞬跳（避免和淡入 Crossfade 叠加成卡顿）；之后的新消息才平滑滚动。
    LaunchedEffect(displayMessages.size, isSending, imageLayoutRevision) {
        val lastIndex = displayMessages.size - 1 + if (isSending) 1 else 0
        if (lastIndex >= 0) {
            if (didInitialScroll) {
                listState.animateScrollToItem(lastIndex)
            } else {
                listState.scrollToItem(lastIndex)
                didInitialScroll = true
            }
        }
    }

    LazyColumn(
        modifier = modifier,
        state = listState,
        reverseLayout = false,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        items(displayMessages, key = { it.id }) { message ->
            MessageBubble(
                repository = repository,
                message = message,
                onPreviewImage = { previewAttachment = it },
                onImageLoaded = { imageLayoutRevision += 1 },
            )
        }
        if (isSending) {
            item(key = "neno-typing") {
                TypingBubble()
            }
        }
    }

    previewAttachment?.let { attachment ->
        AttachmentImagePreview(
            repository = repository,
            attachment = attachment,
            onDismiss = { previewAttachment = null },
        )
    }
}

@Composable
private fun LoadingMessageSpace(modifier: Modifier = Modifier) {
    Box(modifier = modifier)
}

@Composable
private fun EmptyMessageSpace(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier,
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "还没有消息",
            color = MaterialTheme.colorScheme.secondary,
            fontSize = 12.sp,
            lineHeight = 16.sp,
        )
    }
}

private fun toChatBubbleModel(message: MobileMessage): ChatBubbleModel =
    ChatBubbleModel(
        id = message.id,
        text = message.text,
        attachments = message.attachments,
        time = formatChatMessageTime(message.displayTime ?: message.createdAt, message.role),
        fromUser = message.role == "user",
        pending = message.pending,
    )

internal fun formatChatMessageTime(createdAt: String?, role: String): String {
    val raw = createdAt?.trim().orEmpty()
    val match = Regex("""[T\s](\d{1,2}):(\d{2})""").find(raw)
        ?: Regex("""^(\d{1,2}):(\d{2})""").find(raw)

    if (match != null) {
        val hour = match.groupValues[1].toIntOrNull()?.toString()
            ?: match.groupValues[1].trimStart('0').ifEmpty { "0" }
        return "$hour:${match.groupValues[2]}"
    }

    return ""
}

@Composable
private fun TypingBubble() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Start,
    ) {
        Surface(
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(10.dp),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.72f)),
            shadowElevation = 2.dp,
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                val transition = rememberInfiniteTransition(label = "typing")
                repeat(3) { index ->
                    val alpha by transition.animateFloat(
                        initialValue = 0.30f,
                        targetValue = 1f,
                        animationSpec = infiniteRepeatable(
                            animation = tween(durationMillis = 600, delayMillis = index * 160),
                            repeatMode = RepeatMode.Reverse,
                        ),
                        label = "dot$index",
                    )
                    Box(
                        modifier = Modifier
                            .size(6.dp)
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.secondary.copy(alpha = alpha)),
                    )
                }
            }
        }
    }
}

@Composable
private fun MessageBubble(
    repository: NenoRepository,
    message: ChatBubbleModel,
    onPreviewImage: (MobileAttachment) -> Unit,
    onImageLoaded: () -> Unit,
) {
    val imageAttachments = message.attachments.filter { it.kind == "image" }
    val voiceAttachments = message.attachments.filter { it.kind == "voice" }
    val displayText = when {
        message.text.isNotBlank() -> message.text
        imageAttachments.isNotEmpty() -> ""
        voiceAttachments.isNotEmpty() -> ""
        message.attachments.any { it.kind == "file" } -> "文件"
        else -> ""
    }
    if (imageAttachments.isNotEmpty()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = if (message.fromUser) Arrangement.End else Arrangement.Start,
        ) {
            Column(
                horizontalAlignment = if (message.fromUser) Alignment.End else Alignment.Start,
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                imageAttachments.forEach { attachment ->
                    AttachmentImage(
                        repository = repository,
                        attachment = attachment,
                        onClick = { onPreviewImage(attachment) },
                        onImageLoaded = onImageLoaded,
                    )
                }
                if (displayText.isNotBlank()) {
                    Surface(
                        modifier = Modifier.widthIn(max = 210.dp),
                        color = if (message.fromUser) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface,
                        shape = RoundedCornerShape(10.dp),
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = if (message.fromUser) 0.40f else 0.72f)),
                        shadowElevation = 2.dp,
                    ) {
                        Text(
                            text = displayText,
                            modifier = Modifier.padding(horizontal = 11.dp, vertical = 7.dp),
                            color = MaterialTheme.colorScheme.onSurface,
                            fontSize = 12.sp,
                            lineHeight = 16.sp,
                        )
                    }
                }
                Row(
                    modifier = Modifier.widthIn(max = 210.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = if (message.fromUser) Arrangement.End else Arrangement.Start,
                ) {
                    Text(
                        text = if (message.pending) "发送中" else message.time,
                        color = MaterialTheme.colorScheme.secondary,
                        fontSize = 9.sp,
                        lineHeight = 11.sp,
                    )
                }
            }
        }
        return
    }
    if (voiceAttachments.isNotEmpty()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = if (message.fromUser) Arrangement.End else Arrangement.Start,
        ) {
            Column(
                horizontalAlignment = if (message.fromUser) Alignment.End else Alignment.Start,
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                voiceAttachments.forEach { attachment ->
                    VoiceMessageContent(
                        repository = repository,
                        attachment = attachment,
                        fromUser = message.fromUser,
                    )
                }
                if (displayText.isNotBlank()) {
                    Surface(
                        modifier = Modifier.widthIn(max = 210.dp),
                        color = if (message.fromUser) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface,
                        shape = RoundedCornerShape(10.dp),
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = if (message.fromUser) 0.40f else 0.72f)),
                        shadowElevation = 2.dp,
                    ) {
                        Text(
                            text = displayText,
                            modifier = Modifier.padding(horizontal = 11.dp, vertical = 7.dp),
                            color = MaterialTheme.colorScheme.onSurface,
                            fontSize = 12.sp,
                            lineHeight = 16.sp,
                        )
                    }
                }
                Row(
                    modifier = Modifier.widthIn(min = 154.dp, max = 220.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = if (message.fromUser) Arrangement.End else Arrangement.Start,
                ) {
                    Text(
                        text = if (message.pending) "发送中" else message.time,
                        color = MaterialTheme.colorScheme.secondary,
                        fontSize = 9.sp,
                        lineHeight = 11.sp,
                    )
                }
            }
        }
        return
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (message.fromUser) Arrangement.End else Arrangement.Start,
    ) {
        Surface(
            modifier = Modifier
                .widthIn(max = 210.dp),
            color = if (message.fromUser) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(10.dp),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = if (message.fromUser) 0.40f else 0.72f)),
            shadowElevation = 2.dp,
        ) {
            Column(modifier = Modifier.padding(start = 11.dp, top = 7.dp, end = 10.dp, bottom = 6.dp)) {
                voiceAttachments.forEach { attachment ->
                    VoiceMessageContent(
                        repository = repository,
                        attachment = attachment,
                        fromUser = message.fromUser,
                    )
                    if (displayText.isNotBlank()) {
                        Spacer(modifier = Modifier.height(6.dp))
                    }
                }
                imageAttachments.forEach { attachment ->
                    AttachmentImage(
                        repository = repository,
                        attachment = attachment,
                        onClick = { onPreviewImage(attachment) },
                        onImageLoaded = onImageLoaded,
                    )
                    if (displayText.isNotBlank()) {
                        Spacer(modifier = Modifier.height(6.dp))
                    }
                }
                if (displayText.isNotBlank()) {
                    Text(
                        text = displayText,
                        color = MaterialTheme.colorScheme.onSurface,
                        fontSize = 12.sp,
                        lineHeight = 16.sp,
                    )
                }
                Spacer(modifier = Modifier.height(2.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = if (message.pending) "发送中" else message.time,
                        modifier = Modifier.weight(1f),
                        color = MaterialTheme.colorScheme.secondary,
                        fontSize = 9.sp,
                        lineHeight = 11.sp,
                    )
                }
            }
        }
    }
}

@Composable
private fun AttachmentImage(
    repository: NenoRepository,
    attachment: MobileAttachment,
    onClick: () -> Unit,
    onImageLoaded: () -> Unit,
) {
    val context = LocalContext.current
    var imageBytes by remember(attachment.localUri, attachment.url, attachment.mediaPath) {
        mutableStateOf<ByteArray?>(null)
    }

    LaunchedEffect(attachment.localUri, attachment.url, attachment.mediaPath) {
        imageBytes = loadAttachmentImageBytes(context, repository, attachment)
    }

    val bitmap = remember(imageBytes) {
        imageBytes?.let { bytes ->
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
        }
    }
    val ratio = remember(bitmap) {
        bitmap?.let { image ->
            image.width.toFloat() / image.height.coerceAtLeast(1).toFloat()
        } ?: 1.33f
    }

    LaunchedEffect(bitmap) {
        if (bitmap != null) {
            onImageLoaded()
        }
    }

    Box(
        modifier = Modifier
            .width(210.dp)
            .aspectRatio(ratio)
            .clickable(enabled = bitmap != null, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        if (bitmap != null) {
            Image(
                bitmap = bitmap,
                contentDescription = "图片",
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Fit,
            )
        } else {
            Text(
                text = "图片",
                color = MaterialTheme.colorScheme.secondary,
                fontSize = 12.sp,
                lineHeight = 16.sp,
            )
        }
    }
}

@Composable
private fun VoiceMessageContent(
    repository: NenoRepository,
    attachment: MobileAttachment,
    fromUser: Boolean,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val voiceInteractionSource = remember { MutableInteractionSource() }
    var isPlaying by remember(attachment.localUri, attachment.url, attachment.mediaPath) {
        mutableStateOf(false)
    }
    val transcript = attachment.textHint
        ?.trim()
        ?.takeIf { it.isNotBlank() && !it.endsWith(".wav") && !it.endsWith(".m4a") && !it.endsWith(".mp3") }
    val durationLabel = voiceDurationLabel(context, attachment)
    val voiceColor = if (fromUser) {
        Color(0xFF93EE9B)
    } else {
        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.72f)
    }
    val voiceTextColor = if (fromUser) {
        Color(0xFF0E2411)
    } else {
        MaterialTheme.colorScheme.onSurface
    }
    val voiceWaveColor = if (fromUser) {
        Color(0xFF0C2B10)
    } else {
        MaterialTheme.colorScheme.primary
    }
    val playStateLabel = if (isPlaying) "播放中" else "听"

    Column(
        modifier = Modifier.widthIn(min = 154.dp, max = 220.dp),
        horizontalAlignment = if (fromUser) Alignment.End else Alignment.Start,
    ) {
        Row(
            modifier = Modifier
                .clickable(
                    enabled = !isPlaying,
                    indication = null,
                    interactionSource = voiceInteractionSource,
                ) {
                    scope.launch {
                        isPlaying = true
                        runCatching {
                            playVoiceAttachment(context, repository, attachment)
                        }
                        isPlaying = false
                    }
                },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (!fromUser) {
                VoiceTailCorner(
                    color = voiceColor,
                    fromUser = false,
                )
                VoiceWaveIcon(
                    backgroundColor = voiceColor,
                    waveColor = voiceWaveColor,
                    fromUser = false,
                )
            }
            Box(
                modifier = Modifier
                    .width(132.dp)
                    .height(38.dp)
                    .clip(
                        RoundedCornerShape(
                            topStart = if (fromUser) 8.dp else 0.dp,
                            bottomStart = if (fromUser) 8.dp else 0.dp,
                            topEnd = if (fromUser) 0.dp else 8.dp,
                            bottomEnd = if (fromUser) 0.dp else 8.dp,
                        ),
                    )
                    .background(voiceColor)
                    .padding(horizontal = 14.dp),
                contentAlignment = Alignment.CenterEnd,
            ) {
                Text(
                    text = if (isPlaying) playStateLabel else durationLabel,
                    color = voiceTextColor,
                    fontSize = 16.sp,
                    lineHeight = 20.sp,
                    fontWeight = FontWeight.Medium,
                )
            }
            if (fromUser) {
                VoiceWaveIcon(
                    backgroundColor = voiceColor,
                    waveColor = voiceWaveColor,
                    fromUser = true,
                )
                VoiceTailCorner(
                    color = voiceColor,
                    fromUser = true,
                )
            }
        }
        if (transcript != null) {
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "转文字：$transcript",
                color = MaterialTheme.colorScheme.secondary,
                fontSize = 11.sp,
                lineHeight = 15.sp,
            )
        }
    }
}

@Composable
private fun VoiceWaveIcon(
    backgroundColor: Color,
    waveColor: Color,
    fromUser: Boolean,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .width(27.dp)
            .height(38.dp)
            .background(backgroundColor),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.size(width = 15.dp, height = 20.dp)) {
            val w = size.width
            val h = size.height
            val centerX = if (fromUser) w * 0.20f else w * 0.80f
            val startAngle = if (fromUser) -44f else 136f
            repeat(2) { index ->
                val radius = w * (0.36f + index * 0.30f)
                drawArc(
                    color = waveColor,
                    startAngle = startAngle,
                    sweepAngle = if (fromUser) 88f else -88f,
                    useCenter = false,
                    topLeft = Offset(centerX - radius, h * 0.50f - radius),
                    size = androidx.compose.ui.geometry.Size(radius * 2f, radius * 2f),
                    style = Stroke(width = w * 0.16f, cap = StrokeCap.Round),
                )
            }
        }
    }
}

@Composable
private fun VoiceTailCorner(
    color: Color,
    fromUser: Boolean,
    modifier: Modifier = Modifier,
) {
    Canvas(
        modifier = modifier
            .width(9.dp)
            .height(38.dp),
    ) {
        val w = size.width
        val h = size.height
        val tail = Path().apply {
            if (fromUser) {
                moveTo(0f, h * 0.34f)
                cubicTo(w * 0.36f, h * 0.40f, w * 0.72f, h * 0.45f, w, h * 0.50f)
                cubicTo(w * 0.72f, h * 0.55f, w * 0.36f, h * 0.60f, 0f, h * 0.66f)
            } else {
                moveTo(w, h * 0.34f)
                cubicTo(w * 0.64f, h * 0.40f, w * 0.28f, h * 0.45f, 0f, h * 0.50f)
                cubicTo(w * 0.28f, h * 0.55f, w * 0.64f, h * 0.60f, w, h * 0.66f)
            }
            close()
        }
        drawPath(tail, color)
    }
}

@Composable
private fun voiceDurationLabel(
    context: Context,
    attachment: MobileAttachment,
): String = remember(attachment.durationMs, attachment.localUri, attachment.mediaPath, attachment.url) {
    readVoiceDurationLabel(context, attachment) ?: "12\""
}

@Composable
private fun AttachmentImagePreview(
    repository: NenoRepository,
    attachment: MobileAttachment,
    onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    var imageBytes by remember(attachment.localUri, attachment.url, attachment.mediaPath) {
        mutableStateOf<ByteArray?>(null)
    }

    LaunchedEffect(attachment.localUri, attachment.url, attachment.mediaPath) {
        imageBytes = loadAttachmentImageBytes(context, repository, attachment)
    }

    val bitmap = remember(imageBytes) {
        imageBytes?.let { bytes ->
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
        }
    }
    var previewScale by remember(attachment.localUri, attachment.url, attachment.mediaPath) {
        mutableStateOf(1f)
    }
    var previewOffset by remember(attachment.localUri, attachment.url, attachment.mediaPath) {
        mutableStateOf(Offset.Zero)
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.94f))
                .clickable(onClick = onDismiss)
                .padding(14.dp),
            contentAlignment = Alignment.Center,
        ) {
            if (bitmap != null) {
                Image(
                    bitmap = bitmap,
                    contentDescription = "图片预览",
                    modifier = Modifier
                        .fillMaxSize()
                        .pointerInput(bitmap) {
                            detectTransformGestures { _, pan, zoom, _ ->
                                val nextScale = (previewScale * zoom).coerceIn(1f, 5f)
                                previewScale = nextScale
                                previewOffset = if (nextScale == 1f) {
                                    Offset.Zero
                                } else {
                                    previewOffset + pan
                                }
                            }
                        }
                        .graphicsLayer(
                            scaleX = previewScale,
                            scaleY = previewScale,
                            translationX = previewOffset.x,
                            translationY = previewOffset.y,
                        ),
                    contentScale = ContentScale.Fit,
                )
            } else {
                Text(
                    text = "图片加载中",
                    color = Color.White.copy(alpha = 0.78f),
                    fontSize = 13.sp,
                    lineHeight = 17.sp,
                )
            }
        }
    }
}

@Composable
internal fun KeyboardAwareInputArea(content: @Composable () -> Unit) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .imePadding()
            .padding(bottom = 8.dp),
    ) {
        content()
    }
}

@Composable
internal fun ChatInputBar(
    draft: String,
    onDraftChange: (String) -> Unit,
    onSend: () -> Unit,
    onPickImage: () -> Unit = {},
    onPickCamera: () -> Unit = {},
    onPickVoice: () -> Unit = {},
    onPickFile: () -> Unit = {},
    onVoiceHoldStart: () -> Unit = {},
    onVoiceHoldEnd: (Boolean) -> Unit = {},
    isSending: Boolean = false,
    isRecording: Boolean = false,
    placeholder: String = "发消息给 Neno",
) {
    val hasDraft = draft.trim().isNotEmpty()
    var showTools by remember { mutableStateOf(false) }
    var voiceMode by remember { mutableStateOf(false) }
    var voiceCanceling by remember { mutableStateOf(false) }
    var inputActive by remember { mutableStateOf(false) }
    val focusRequester = remember { FocusRequester() }
    val menuOffset = with(LocalDensity.current) {
        IntOffset(x = 0, y = -62.dp.roundToPx())
    }
    val cancelThresholdPx = with(LocalDensity.current) {
        54.dp.toPx()
    }

    fun toggleVoiceRecording() {
        if (!hasDraft && !isSending) {
            voiceMode = !voiceMode
            inputActive = false
            showTools = false
        }
    }

    LaunchedEffect(hasDraft, isSending) {
        if (hasDraft || isSending) {
            showTools = false
            voiceMode = false
        }
        if (isSending) {
            inputActive = false
        }
    }

    LaunchedEffect(inputActive) {
        if (inputActive) {
            focusRequester.requestFocus()
        }
    }

    val voiceHoldModifier = Modifier.pointerInput(voiceMode, isSending, hasDraft) {
        awaitEachGesture {
            val down = awaitFirstDown(requireUnconsumed = false)
            val longPress = awaitLongPressOrCancellation(down.id)
            if (longPress != null && !hasDraft && !isSending) {
                inputActive = false
                voiceCanceling = false
                onVoiceHoldStart()
                var cancelled = false
                do {
                    val event = awaitPointerEvent()
                    val pointer = event.changes.firstOrNull { it.id == down.id }
                        ?: event.changes.firstOrNull()
                    cancelled = pointer?.position?.y?.let { y ->
                        y < down.position.y - cancelThresholdPx
                    } ?: false
                    voiceCanceling = cancelled
                } while (event.changes.any { it.pressed })
                onVoiceHoldEnd(cancelled)
                voiceCanceling = false
            } else if (!voiceMode && !hasDraft && !isSending) {
                inputActive = true
            }
        }
    }

    Box(
        modifier = Modifier.fillMaxWidth(),
    ) {
        if (isRecording) {
            VoiceRecordingOverlay(
                isCanceling = voiceCanceling,
            )
        }
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp),
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(18.dp),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.46f)),
            shadowElevation = 6.dp,
        ) {
            Row(
                modifier = Modifier.padding(start = 8.dp, top = 7.dp, end = 8.dp, bottom = 7.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                PromptBoxActionButton(
                    icon = PromptBoxIcon.Mic,
                    enabled = true,
                    onClick = {
                        onPickVoice()
                        toggleVoiceRecording()
                    },
                    containerColor = if (voiceMode || isRecording) MaterialTheme.colorScheme.primaryContainer else Color.Transparent,
                    contentColor = if (voiceMode || isRecording) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.secondary.copy(alpha = 0.78f),
                )
                Spacer(modifier = Modifier.width(5.dp))
                if (voiceMode && !hasDraft) {
                    VoiceHoldSurface(
                        modifier = Modifier
                            .weight(1f)
                            .height(38.dp)
                            .then(voiceHoldModifier),
                        label = "按住说话",
                        isRecording = isRecording,
                        isCanceling = voiceCanceling,
                    )
                } else if (!hasDraft && !inputActive) {
                    VoiceHoldSurface(
                        modifier = Modifier
                            .weight(1f)
                            .height(38.dp)
                            .then(voiceHoldModifier),
                        label = placeholder,
                        isRecording = isRecording,
                        isCanceling = voiceCanceling,
                    )
                } else {
                    BasicTextField(
                        value = draft,
                        onValueChange = onDraftChange,
                        modifier = Modifier
                            .weight(1f)
                            .focusRequester(focusRequester),
                        textStyle = TextStyle(
                            color = MaterialTheme.colorScheme.onSurface,
                            fontSize = 12.sp,
                            lineHeight = 16.sp,
                        ),
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                        keyboardActions = KeyboardActions(onSend = { onSend() }),
                        decorationBox = { innerTextField ->
                            Box(contentAlignment = Alignment.CenterStart) {
                                if (draft.isBlank()) {
                                    Text(
                                        text = placeholder,
                                        color = MaterialTheme.colorScheme.secondary.copy(alpha = 0.78f),
                                        fontSize = 14.sp,
                                        lineHeight = 18.sp,
                                    )
                                }
                                innerTextField()
                            }
                        },
                    )
                }
                Spacer(modifier = Modifier.width(7.dp))
                Crossfade(
                    targetState = when {
                        isSending -> PromptBoxIcon.Stop
                        hasDraft -> PromptBoxIcon.Send
                        else -> PromptBoxIcon.Plus
                    },
                    animationSpec = tween(durationMillis = 140),
                    label = "composerAction",
                ) { icon ->
                    PromptBoxActionButton(
                        icon = icon,
                        enabled = icon != PromptBoxIcon.Stop,
                        onClick = {
                            when (icon) {
                                PromptBoxIcon.Send -> onSend()
                                PromptBoxIcon.Plus -> showTools = !showTools
                                else -> Unit
                            }
                        },
                        containerColor = if (icon == PromptBoxIcon.Send) {
                            MaterialTheme.colorScheme.onSurface
                        } else {
                            Color.Transparent
                        },
                        contentColor = if (icon == PromptBoxIcon.Send) {
                            MaterialTheme.colorScheme.surface
                        } else {
                            MaterialTheme.colorScheme.secondary.copy(alpha = 0.78f)
                        },
                    )
                }
            }
        }

        if (showTools && !hasDraft && !isSending) {
            Popup(
                alignment = Alignment.BottomEnd,
                offset = menuOffset,
                onDismissRequest = { showTools = false },
                properties = PopupProperties(
                    focusable = true,
                    dismissOnBackPress = true,
                    dismissOnClickOutside = true,
                ),
            ) {
                PromptBoxToolMenu(
                    onPickImage = {
                        showTools = false
                        onPickImage()
                    },
                    onPickCamera = {
                        showTools = false
                        onPickCamera()
                    },
                    onPickFile = {
                        showTools = false
                        onPickFile()
                    },
                )
            }
        }
    }
}

@Composable
private fun VoiceHoldSurface(
    label: String,
    isRecording: Boolean,
    isCanceling: Boolean,
    modifier: Modifier = Modifier,
) {
    val background = when {
        isRecording && isCanceling -> MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.68f)
        isRecording -> MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.80f)
        else -> MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.42f)
    }
    val contentColor = when {
        isRecording && isCanceling -> MaterialTheme.colorScheme.onErrorContainer
        isRecording -> MaterialTheme.colorScheme.primary
        else -> MaterialTheme.colorScheme.secondary.copy(alpha = 0.86f)
    }
    val labelAlignment = if (!isRecording && label != "按住说话") {
        Alignment.CenterStart
    } else {
        Alignment.Center
    }
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .background(background)
            .padding(horizontal = 12.dp),
        contentAlignment = labelAlignment,
    ) {
        Text(
            text = when {
                isRecording && isCanceling -> "松开取消"
                isRecording -> "松开发送"
                else -> label
            },
            color = contentColor,
            fontSize = 14.sp,
            lineHeight = 18.sp,
            fontWeight = FontWeight.Medium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun VoiceRecordingOverlay(
    isCanceling: Boolean,
    modifier: Modifier = Modifier,
) {
    val overlayOffset = with(LocalDensity.current) {
        IntOffset(0, -108.dp.roundToPx())
    }
    Popup(
        alignment = Alignment.BottomCenter,
        offset = overlayOffset,
        properties = PopupProperties(
            focusable = false,
            dismissOnBackPress = false,
            dismissOnClickOutside = false,
        ),
    ) {
        Surface(
            modifier = modifier.widthIn(min = 142.dp, max = 190.dp),
            color = if (isCanceling) {
                MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.94f)
            } else {
                MaterialTheme.colorScheme.surface.copy(alpha = 0.96f)
            },
            shape = RoundedCornerShape(18.dp),
            border = BorderStroke(
                1.dp,
                if (isCanceling) {
                    MaterialTheme.colorScheme.error.copy(alpha = 0.42f)
                } else {
                    MaterialTheme.colorScheme.outline.copy(alpha = 0.35f)
                },
            ),
            shadowElevation = 10.dp,
        ) {
            Column(
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    text = if (isCanceling) "松开取消" else "正在录音",
                    color = if (isCanceling) {
                        MaterialTheme.colorScheme.onErrorContainer
                    } else {
                        MaterialTheme.colorScheme.onSurface
                    },
                    fontSize = 14.sp,
                    lineHeight = 18.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(modifier = Modifier.height(3.dp))
                Text(
                    text = if (isCanceling) "已上滑" else "上滑取消",
                    color = MaterialTheme.colorScheme.secondary,
                    fontSize = 11.sp,
                    lineHeight = 14.sp,
                )
            }
        }
    }
}

private enum class PromptBoxIcon {
    Mic,
    Plus,
    Send,
    Stop,
    Image,
    Camera,
    File,
}

@Composable
private fun PromptBoxToolMenu(
    modifier: Modifier = Modifier,
    onPickImage: () -> Unit,
    onPickCamera: () -> Unit,
    onPickFile: () -> Unit,
) {
    Surface(
        modifier = modifier.width(148.dp),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(14.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.42f)),
        shadowElevation = 10.dp,
    ) {
        Column(modifier = Modifier.padding(6.dp)) {
            PromptBoxToolItem(
                icon = PromptBoxIcon.Image,
                label = "图片",
                tint = Color(0xFF3B82F6),
                onClick = onPickImage,
            )
            PromptBoxToolItem(
                icon = PromptBoxIcon.Camera,
                label = "相机",
                tint = Color(0xFF8B5CF6),
                onClick = onPickCamera,
            )
            PromptBoxToolItem(
                icon = PromptBoxIcon.File,
                label = "文件",
                tint = Color(0xFF10B981),
                onClick = onPickFile,
            )
        }
    }
}

@Composable
private fun PromptBoxToolItem(
    icon: PromptBoxIcon,
    label: String,
    tint: Color,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        PromptBoxIcon(icon = icon, modifier = Modifier.size(18.dp), tint = tint)
        Spacer(modifier = Modifier.width(10.dp))
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurface,
            fontSize = 13.sp,
            lineHeight = 17.sp,
        )
    }
}

@Composable
private fun PromptBoxActionButton(
    icon: PromptBoxIcon,
    enabled: Boolean = true,
    onClick: () -> Unit = {},
    containerColor: Color,
    contentColor: Color,
) {
    Box(
        modifier = Modifier
            .size(38.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(containerColor)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        PromptBoxIcon(
            icon = icon,
            modifier = Modifier.size(20.dp),
            tint = contentColor,
        )
    }
}

@Composable
private fun PromptBoxIcon(
    icon: PromptBoxIcon,
    modifier: Modifier = Modifier,
    tint: Color,
) {
    Canvas(modifier = modifier) {
        val w = size.width
        val h = size.height
        val strokeWidth = w * 0.10f
        val stroke = Stroke(width = strokeWidth, cap = StrokeCap.Round)
        when (icon) {
            PromptBoxIcon.Mic -> {
                drawRoundRect(
                    color = tint,
                    topLeft = Offset(w * 0.39f, h * 0.12f),
                    size = androidx.compose.ui.geometry.Size(w * 0.22f, h * 0.48f),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(w * 0.11f, w * 0.11f),
                    style = stroke,
                )
                drawArc(
                    color = tint,
                    startAngle = 20f,
                    sweepAngle = 140f,
                    useCenter = false,
                    topLeft = Offset(w * 0.25f, h * 0.36f),
                    size = androidx.compose.ui.geometry.Size(w * 0.50f, h * 0.36f),
                    style = stroke,
                )
                drawLine(tint, Offset(w * 0.50f, h * 0.72f), Offset(w * 0.50f, h * 0.86f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
            }

            PromptBoxIcon.Plus -> {
                drawLine(tint, Offset(w * 0.50f, h * 0.24f), Offset(w * 0.50f, h * 0.76f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.24f, h * 0.50f), Offset(w * 0.76f, h * 0.50f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
            }

            PromptBoxIcon.Send -> {
                drawLine(tint, Offset(w * 0.50f, h * 0.78f), Offset(w * 0.50f, h * 0.22f), strokeWidth = strokeWidth * 1.15f, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.50f, h * 0.22f), Offset(w * 0.28f, h * 0.44f), strokeWidth = strokeWidth * 1.15f, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.50f, h * 0.22f), Offset(w * 0.72f, h * 0.44f), strokeWidth = strokeWidth * 1.15f, cap = StrokeCap.Round)
            }

            PromptBoxIcon.Stop -> {
                drawRoundRect(
                    color = tint,
                    topLeft = Offset(w * 0.30f, h * 0.30f),
                    size = androidx.compose.ui.geometry.Size(w * 0.40f, h * 0.40f),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(w * 0.08f, w * 0.08f),
                )
            }

            PromptBoxIcon.Image -> {
                drawRoundRect(
                    color = tint,
                    topLeft = Offset(w * 0.16f, h * 0.22f),
                    size = androidx.compose.ui.geometry.Size(w * 0.68f, h * 0.56f),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(w * 0.08f, w * 0.08f),
                    style = stroke,
                )
                drawCircle(tint, radius = w * 0.07f, center = Offset(w * 0.36f, h * 0.38f))
                drawLine(tint, Offset(w * 0.22f, h * 0.72f), Offset(w * 0.44f, h * 0.54f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.44f, h * 0.54f), Offset(w * 0.58f, h * 0.66f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.58f, h * 0.66f), Offset(w * 0.78f, h * 0.46f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
            }

            PromptBoxIcon.Camera -> {
                drawRoundRect(
                    color = tint,
                    topLeft = Offset(w * 0.16f, h * 0.30f),
                    size = androidx.compose.ui.geometry.Size(w * 0.68f, h * 0.44f),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(w * 0.08f, w * 0.08f),
                    style = stroke,
                )
                drawLine(tint, Offset(w * 0.38f, h * 0.30f), Offset(w * 0.44f, h * 0.20f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.44f, h * 0.20f), Offset(w * 0.62f, h * 0.20f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.62f, h * 0.20f), Offset(w * 0.68f, h * 0.30f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
                drawCircle(tint, radius = w * 0.13f, center = Offset(w * 0.50f, h * 0.52f), style = stroke)
            }

            PromptBoxIcon.File -> {
                drawRoundRect(
                    color = tint,
                    topLeft = Offset(w * 0.24f, h * 0.14f),
                    size = androidx.compose.ui.geometry.Size(w * 0.52f, h * 0.72f),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(w * 0.06f, w * 0.06f),
                    style = stroke,
                )
                drawLine(tint, Offset(w * 0.36f, h * 0.40f), Offset(w * 0.64f, h * 0.40f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.36f, h * 0.56f), Offset(w * 0.64f, h * 0.56f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.36f, h * 0.72f), Offset(w * 0.54f, h * 0.72f), strokeWidth = strokeWidth, cap = StrokeCap.Round)
            }
        }
    }
}

@Composable
internal fun IconTapTarget(
    icon: NenoIcon,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .size(32.dp)
            .clip(CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        AppIcon(
            icon = icon,
            modifier = Modifier.size(22.dp),
            tint = MaterialTheme.colorScheme.onSurface,
        )
    }
}

private data class MobileUploadPayload(
    val filename: String,
    val mimeType: String,
    val bytes: ByteArray,
)

private fun readMobileUploadPayload(
    context: Context,
    uri: Uri,
    kind: String,
): MobileUploadPayload {
    val resolver = context.contentResolver
    val isFileUri = uri.scheme == "file"
    val filename = if (isFileUri) {
        File(uri.path.orEmpty()).name.takeIf { it.isNotBlank() }
    } else {
        resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            ?.use { cursor ->
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
            }
            ?.takeIf { it.isNotBlank() }
    }
        ?: uri.lastPathSegment
        ?: "upload"
    val mimeType = resolver.getType(uri) ?: when (kind) {
        "image" -> "image/jpeg"
        "voice" -> "audio/mp4"
        else -> "application/octet-stream"
    }
    val bytes = if (isFileUri) {
        File(uri.path.orEmpty()).readBytes()
    } else {
        resolver.openInputStream(uri)?.use { it.readBytes() }
            ?: throw IllegalArgumentException("无法读取文件")
    }
    return MobileUploadPayload(filename = filename, mimeType = mimeType, bytes = bytes)
}

private fun createCameraCaptureUri(context: Context): Uri {
    val file = File(context.cacheDir, "neno_camera_${captureTimestamp()}.jpg")
    return FileProvider.getUriForFile(
        context,
        "${context.packageName}.fileprovider",
        file,
    )
}

private fun createVoiceCaptureFile(context: Context): File =
    File(context.cacheDir, "neno_voice_${captureTimestamp()}.m4a")

private fun captureTimestamp(): String =
    SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(Date())

private fun readLocalAttachmentBytes(context: Context, uri: Uri): ByteArray? =
    if (uri.scheme == "file") {
        File(uri.path.orEmpty()).readBytes()
    } else {
        context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
    }

private suspend fun loadAttachmentImageBytes(
    context: Context,
    repository: NenoRepository,
    attachment: MobileAttachment,
): ByteArray? = withContext(Dispatchers.IO) {
    if (!attachment.localUri.isNullOrBlank()) {
        runCatching {
            readLocalAttachmentBytes(context, Uri.parse(attachment.localUri))
        }.getOrNull()?.let { bytes ->
            saveCachedAttachmentImageBytes(context, attachment, bytes)
            return@withContext bytes
        }
    }

    val cacheFile = cachedAttachmentImageFile(context, attachment) ?: return@withContext repository
        .downloadAttachment(attachment)
        .getOrNull()
    if (cacheFile.exists() && cacheFile.length() > 0L) {
        return@withContext runCatching { cacheFile.readBytes() }.getOrNull()
    }

    val bytes = repository.downloadAttachment(attachment).getOrNull() ?: return@withContext null
    saveCachedAttachmentImageBytes(context, attachment, bytes)
    return@withContext bytes
}

private fun saveCachedAttachmentImageBytes(
    context: Context,
    attachment: MobileAttachment,
    bytes: ByteArray,
) {
    if (bytes.isEmpty()) return
    val cacheFile = cachedAttachmentImageFile(context, attachment) ?: return
    runCatching {
        cacheFile.parentFile?.mkdirs()
        cacheFile.writeBytes(bytes)
    }
}

private fun cachedAttachmentImageFile(
    context: Context,
    attachment: MobileAttachment,
): File? {
    val key = listOfNotNull(
        attachment.url?.takeIf { it.isNotBlank() },
        attachment.mediaPath?.takeIf { it.isNotBlank() },
        attachment.localUri?.takeIf { it.isNotBlank() },
    ).firstOrNull() ?: return null
    val digest = MessageDigest.getInstance("SHA-256")
        .digest(key.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }
    return File(File(context.cacheDir, "mobile_image_cache"), "$digest.img")
}

private fun readVoiceDurationLabel(
    context: Context,
    attachment: MobileAttachment,
): String? {
    attachment.durationMs
        ?.takeIf { it > 0L }
        ?.let { return formatVoiceDurationLabel(it) }
    return readVoiceDurationMs(
        context = context,
        localUri = attachment.localUri?.takeIf { it.isNotBlank() }?.let(Uri::parse),
        mediaPath = attachment.mediaPath?.takeIf { it.isNotBlank() },
    )?.let(::formatVoiceDurationLabel)
}

private fun readVoiceDurationMs(
    context: Context,
    localUri: Uri? = null,
    mediaPath: String? = null,
): Long? {
    val path = when {
        localUri?.scheme == "file" -> localUri.path?.let(::File)
        else -> mediaPath
            ?.takeIf { it.isNotBlank() }
            ?.let(::File)
    }?.takeIf { it.exists() }

    return runCatching {
        val retriever = MediaMetadataRetriever()
        try {
            when {
                path != null -> retriever.setDataSource(path.absolutePath)
                localUri != null -> retriever.setDataSource(context, localUri)
                else -> return@runCatching null
            }
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull()
        } finally {
            retriever.release()
        }
    }.getOrNull()
}

private fun formatVoiceDurationLabel(durationMs: Long): String {
    val seconds = ((durationMs + 999L) / 1000L).coerceAtLeast(1L).coerceAtMost(99L)
    return "$seconds\""
}

private suspend fun playVoiceAttachment(
    context: Context,
    repository: NenoRepository,
    attachment: MobileAttachment,
) {
    val localUri = attachment.localUri?.takeIf { it.isNotBlank() }?.let(Uri::parse)
    val uri = localUri ?: run {
        val bytes = repository.downloadAttachment(attachment).getOrThrow()
        val file = File(context.cacheDir, "neno_play_${captureTimestamp()}.m4a")
        file.writeBytes(bytes)
        Uri.fromFile(file)
    }
    suspendCancellableCoroutine { continuation ->
        val player = MediaPlayer.create(context, uri)
        if (player == null) {
            continuation.resume(Unit)
            return@suspendCancellableCoroutine
        }
        continuation.invokeOnCancellation {
            runCatching {
                player.stop()
                player.release()
            }
        }
        player.setOnCompletionListener {
            it.release()
            if (continuation.isActive) {
                continuation.resume(Unit)
            }
        }
        player.setOnErrorListener { mp, _, _ ->
            mp.release()
            if (continuation.isActive) {
                continuation.resume(Unit)
            }
            true
        }
        player.start()
    }
}

private data class ChatBubbleModel(
    val id: Long,
    val text: String,
    val attachments: List<MobileAttachment> = emptyList(),
    val time: String,
    val fromUser: Boolean,
    val pending: Boolean = false,
)
