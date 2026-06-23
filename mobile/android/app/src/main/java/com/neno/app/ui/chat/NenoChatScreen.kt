package com.neno.app.ui.chat

import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
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
    onBack: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var messages by remember { mutableStateOf<List<MobileMessage>?>(null) }
    var draft by remember { mutableStateOf("") }
    var isSending by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf<String?>(null) }
    var softNotice by remember { mutableStateOf<String?>(null) }
    var presence by remember { mutableStateOf("连接中") }

    fun reloadMessages() {
        scope.launch {
            errorText = null
            val result = repository.loadNenoMessages()
            messages = result.messages
            presence = result.presence
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
                presence = presence,
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
            .navigationBarsPadding()
            .imePadding()
            .padding(start = 18.dp, top = 8.dp, end = 18.dp, bottom = 8.dp),
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
        ChatInputBar(
            draft = draft,
            onDraftChange = onDraftChange,
            onSend = onSend,
        )
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
        time = formatChatMessageTime(message.createdAt, message.role),
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

    return if (role == "user") "8:41" else "8:37"
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
private fun ChatInputBar(
    draft: String,
    onDraftChange: (String) -> Unit,
    onSend: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .height(40.dp),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.72f)),
        shadowElevation = 1.dp,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AppIcon(
                icon = NenoIcon.Smile,
                modifier = Modifier.size(19.dp),
                tint = MaterialTheme.colorScheme.secondary,
            )
            Spacer(modifier = Modifier.width(9.dp))
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
                    if (draft.isBlank()) {
                        Text(
                            text = "发消息给 Neno",
                            color = MaterialTheme.colorScheme.secondary,
                            fontSize = 12.sp,
                            lineHeight = 16.sp,
                        )
                    }
                    innerTextField()
                },
            )
            Spacer(modifier = Modifier.width(10.dp))
            AppIcon(
                icon = NenoIcon.Paperclip,
                modifier = Modifier.size(19.dp),
                tint = MaterialTheme.colorScheme.secondary,
            )
            Spacer(modifier = Modifier.width(10.dp))
            Box(
                modifier = Modifier
                    .size(30.dp)
                    .clip(CircleShape)
                    .clickable(onClick = onSend),
                contentAlignment = Alignment.Center,
            ) {
                AppIcon(
                    icon = NenoIcon.Mic,
                    modifier = Modifier.size(19.dp),
                    tint = MaterialTheme.colorScheme.secondary,
                )
            }
        }
    }
}

@Composable
private fun IconTapTarget(
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
