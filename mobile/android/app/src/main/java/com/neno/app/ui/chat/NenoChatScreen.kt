package com.neno.app.ui.chat

import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
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
import com.neno.app.data.AppConnectionState
import com.neno.app.data.MobileMessage
import com.neno.app.data.NenoRepository
import com.neno.app.ui.AsyncListState
import com.neno.app.ui.asyncListState
import com.neno.app.ui.components.AppIcon
import com.neno.app.ui.components.AvatarKind
import com.neno.app.ui.components.NenoIcon
import com.neno.app.ui.components.PhotoAvatar
import kotlinx.coroutines.launch

@Composable
fun NenoChatScreen(
    repository: NenoRepository,
    connectionState: AppConnectionState,
    onBack: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var messages by remember { mutableStateOf<List<MobileMessage>?>(null) }
    var draft by remember { mutableStateOf("") }
    var isSending by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf<String?>(null) }
    var softNotice by remember { mutableStateOf<String?>(null) }

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

    LaunchedEffect(repository) {
        reloadMessages()
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
                messages = messages,
                draft = draft,
                onDraftChange = { draft = it },
                isSending = isSending,
                errorText = errorText,
                softNotice = softNotice,
                presence = connectionState.chatPresenceLabel(),
                onRetry = ::sendDraft,
                onSend = ::sendDraft,
                onBack = onBack,
                onOpenSettings = onOpenSettings,
                modifier = shellModifier,
            )
        }
    }
}

@Composable
private fun ChatShell(
    messages: List<MobileMessage>?,
    draft: String,
    onDraftChange: (String) -> Unit,
    isSending: Boolean,
    errorText: String?,
    softNotice: String?,
    presence: String,
    onRetry: () -> Unit,
    onSend: () -> Unit,
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
                isSending = isSending,
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
    messages: List<MobileMessage>?,
    isSending: Boolean,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier) {
        Crossfade(
            targetState = asyncListState(messages),
            animationSpec = tween(durationMillis = 180),
            label = "messageListState",
        ) { state ->
            when (state) {
                AsyncListState.Loading -> LoadingMessageSpace(modifier = Modifier.fillMaxSize())
                AsyncListState.Empty -> {
                    if (isSending) {
                        MessageLazyList(
                            displayMessages = emptyList(),
                            isSending = true,
                            modifier = Modifier.fillMaxSize(),
                        )
                    } else {
                        EmptyMessageSpace(modifier = Modifier.fillMaxSize())
                    }
                }
                AsyncListState.Content -> MessageLazyList(
                    displayMessages = messages.orEmpty().map(::toChatBubbleModel),
                    isSending = isSending,
                    modifier = Modifier.fillMaxSize(),
                )
            }
        }
    }
}

@Composable
private fun MessageLazyList(
    displayMessages: List<ChatBubbleModel>,
    isSending: Boolean,
    modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()
    var didInitialScroll by remember { mutableStateOf(false) }
    // 新消息或正在等回复时，把列表滚到最底，确保刚发的话和回复都在可视区。
    // 首次进入直接瞬跳（避免和淡入 Crossfade 叠加成卡顿）；之后的新消息才平滑滚动。
    LaunchedEffect(displayMessages.size, isSending) {
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
            MessageBubble(message = message)
        }
        if (isSending) {
            item(key = "neno-typing") {
                TypingBubble()
            }
        }
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
private fun MessageBubble(message: ChatBubbleModel) {
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
                Text(
                    text = message.text,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontSize = 12.sp,
                    lineHeight = 16.sp,
                )
                Spacer(modifier = Modifier.height(2.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = if (message.pending) "发送中" else message.time,
                        modifier = Modifier.weight(1f),
                        color = MaterialTheme.colorScheme.secondary,
                        fontSize = 9.sp,
                        lineHeight = 11.sp,
                    )
                    if (message.fromUser) {
                        AppIcon(
                            icon = NenoIcon.DoubleCheck,
                            modifier = Modifier.size(13.dp),
                            tint = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
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
    isSending: Boolean = false,
    placeholder: String = "发消息给 Neno",
) {
    val hasDraft = draft.trim().isNotEmpty()
    var showTools by remember { mutableStateOf(false) }
    val menuOffset = with(LocalDensity.current) {
        IntOffset(x = 0, y = -62.dp.roundToPx())
    }

    LaunchedEffect(hasDraft, isSending) {
        if (hasDraft || isSending) {
            showTools = false
        }
    }

    Box(
        modifier = Modifier.fillMaxWidth(),
    ) {
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
                    containerColor = Color.Transparent,
                    contentColor = MaterialTheme.colorScheme.secondary.copy(alpha = 0.78f),
                )
                Spacer(modifier = Modifier.width(5.dp))
                BasicTextField(
                    value = draft,
                    onValueChange = onDraftChange,
                    modifier = Modifier.weight(1f),
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
                PromptBoxToolMenu(onToolSelected = { showTools = false })
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
    onToolSelected: () -> Unit,
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
                onClick = onToolSelected,
            )
            PromptBoxToolItem(
                icon = PromptBoxIcon.Camera,
                label = "相机",
                tint = Color(0xFF8B5CF6),
                onClick = onToolSelected,
            )
            PromptBoxToolItem(
                icon = PromptBoxIcon.File,
                label = "文件",
                tint = Color(0xFF10B981),
                onClick = onToolSelected,
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

private data class ChatBubbleModel(
    val id: Long,
    val text: String,
    val time: String,
    val fromUser: Boolean,
    val pending: Boolean = false,
)
