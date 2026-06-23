package com.neno.app.ui.chat

import android.util.Log
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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.neno.app.data.NenoRepository
import com.neno.app.data.StreamChunk
import com.neno.app.ui.components.AvatarKind
import com.neno.app.ui.components.NenoIcon
import com.neno.app.ui.components.PhotoAvatar
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val STREAM_THROTTLE_MS = 100L // ~10fps — smooth enough for text

@Composable
fun HermesChatScreen(
    repository: NenoRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val messages = remember { mutableStateListOf<ChatMessage>() }
    var draft by remember { mutableStateOf("") }
    var isSending by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf<String?>(null) }

    // Streaming state — separate from the message list for performance
    var streamingText by remember { mutableStateOf("") }
    var isStreaming by remember { mutableStateOf(false) }
    // Activity feed: tool calls and thinking during this turn
    val activityFeed = remember { mutableStateListOf<ChatMessage>() }

    // Load history on first composition
    var historyLoaded by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        if (!historyLoaded) {
            Log.d("HermesChat", "Loading history...")
            val history = repository.getHermesHistory()
            Log.d("HermesChat", "Got ${history.size} history messages")
            if (history.isNotEmpty()) {
                val localMessages = history.mapIndexed { idx, msg ->
                    ChatMessage(
                        id = idx.toLong(),
                        role = msg.role,
                        text = msg.text,
                    )
                }
                messages.addAll(localMessages)
            }
            historyLoaded = true
        }
    }

    fun sendDraft() {
        val text = draft.trim()
        if (text.isBlank() || isSending) return

        val localId = -System.currentTimeMillis()
        messages.add(ChatMessage(id = localId, role = "user", text = text))
        draft = ""
        isSending = true
        errorText = null
        streamingText = ""
        isStreaming = false

        scope.launch {
            val streamBuffer = StringBuilder()
            var flushJob: Job? = null
            activityFeed.clear()

            try {
                repository.sendToHermesStream(text).collect { chunk ->
                    Log.d("HermesStream", "Chunk: ${chunk::class.simpleName} ${
                        when (chunk) {
                            is StreamChunk.Text -> chunk.content.take(30)
                            is StreamChunk.Thinking -> "thinking..."
                            is StreamChunk.ToolCall -> "${chunk.name}(${chunk.arguments?.take(30)})"
                            is StreamChunk.ToolExecuting -> "executing"
                            is StreamChunk.SessionId -> "sid=${chunk.id}"
                        }
                    }")
                    when (chunk) {
                        is StreamChunk.Text -> {
                            streamBuffer.append(chunk.content)
                            if (!isStreaming) isStreaming = true
                            if (flushJob?.isActive != true) {
                                flushJob = launch {
                                    delay(STREAM_THROTTLE_MS)
                                    streamingText = streamBuffer.toString()
                                }
                            }
                        }
                        is StreamChunk.Thinking -> {
                            // Show thinking as a dimmed activity item
                            if (activityFeed.lastOrNull()?.isThinking != true) {
                                activityFeed.add(ChatMessage(
                                    id = System.nanoTime(),
                                    role = "activity",
                                    text = "",
                                    isThinking = true,
                                ))
                            }
                        }
                        is StreamChunk.ToolCall -> {
                            // Show tool call in activity feed
                            activityFeed.add(ChatMessage(
                                id = System.nanoTime(),
                                role = "activity",
                                text = chunk.arguments?.let { args ->
                                    // Try to make args readable
                                    val short = try {
                                        val argJson = org.json.JSONObject(args)
                                        argJson.keys().asSequence()
                                            .joinToString(", ") { k -> "$k: ${argJson.opt(k)}" }
                                            .take(80)
                                    } catch (_: Exception) { args.take(80) }
                                    "${chunk.name}($short)"
                                } ?: chunk.name,
                                toolName = chunk.name,
                            ))
                        }
                        is StreamChunk.ToolExecuting -> {
                            // Hermes is executing the tool — show spinner
                            activityFeed.add(ChatMessage(
                                id = System.nanoTime(),
                                role = "activity",
                                text = "执行中…",
                            ))
                        }
                        is StreamChunk.SessionId -> { /* handled by repo */ }
                    }
                }

                // Final flush
                flushJob?.join()
                streamingText = streamBuffer.toString()

                // Move streaming text into the message list
                if (streamingText.isNotEmpty()) {
                    messages.add(ChatMessage(
                        id = System.currentTimeMillis(),
                        role = "assistant",
                        text = streamingText,
                    ))
                }
                streamingText = ""
                isStreaming = false
                activityFeed.clear()
            } catch (error: Exception) {
                Log.e("HermesChat", "Stream error: ${error.message}", error)
                flushJob?.join()
                if (streamingText.isNotEmpty()) {
                    messages.add(ChatMessage(
                        id = System.currentTimeMillis(),
                        role = "assistant",
                        text = streamingText,
                    ))
                    streamingText = ""
                    isStreaming = false
                } else {
                    isStreaming = false
                    errorText = error.message ?: "发送失败"
                }
                activityFeed.clear()
            } finally {
                isSending = false
            }
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
            HermesChatShell(
                messages = messages,
                streamingText = streamingText,
                isStreaming = isStreaming,
                activityFeed = activityFeed,
                draft = draft,
                onDraftChange = { draft = it },
                isSending = isSending,
                errorText = errorText,
                onRetry = ::sendDraft,
                onSend = ::sendDraft,
                onBack = onBack,
                historyLoaded = historyLoaded,
                modifier = shellModifier,
            )
        }
    }
}

private data class ChatMessage(
    val id: Long,
    val role: String,
    val text: String,
    val toolName: String? = null,       // non-null = tool call message
    val isThinking: Boolean = false,    // true = reasoning/thinking
)

@Composable
private fun HermesChatShell(
    messages: List<ChatMessage>,
    streamingText: String,
    isStreaming: Boolean,
    activityFeed: List<ChatMessage>,
    draft: String,
    onDraftChange: (String) -> Unit,
    isSending: Boolean,
    errorText: String?,
    onRetry: () -> Unit,
    onSend: () -> Unit,
    onBack: () -> Unit,
    historyLoaded: Boolean = false,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .background(MaterialTheme.colorScheme.background)
            .statusBarsPadding()
            .padding(start = 18.dp, top = 8.dp, end = 18.dp),
    ) {
        HermesChatHeader(onBack = onBack)
        Spacer(modifier = Modifier.height(14.dp))

        if (errorText != null) {
            ErrorBar(message = errorText, onRetry = onRetry)
            Spacer(modifier = Modifier.height(12.dp))
        }

        MessageList(
            messages = messages,
            streamingText = streamingText,
            isStreaming = isStreaming,
            activityFeed = activityFeed,
            isSending = isSending,
            historyLoaded = historyLoaded,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
        )

        Spacer(modifier = Modifier.height(10.dp))
        KeyboardAwareInputArea {
            ChatInputBar(
                draft = draft,
                onDraftChange = onDraftChange,
                onSend = onSend,
                placeholder = "发消息给 Hermes",
            )
        }
    }
}

@Composable
private fun HermesChatHeader(onBack: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconTapTarget(icon = NenoIcon.Back, onClick = onBack)
        Spacer(modifier = Modifier.width(13.dp))
        PhotoAvatar(
            kind = AvatarKind.Atlas,
            modifier = Modifier.size(42.dp),
        )
        Spacer(modifier = Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "Hermes",
                color = MaterialTheme.colorScheme.onBackground,
                fontSize = 20.sp,
                lineHeight = 24.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "AI 助手",
                color = MaterialTheme.colorScheme.secondary,
                fontSize = 12.sp,
                lineHeight = 16.sp,
            )
        }
    }
}

@Composable
private fun MessageList(
    messages: List<ChatMessage>,
    streamingText: String,
    isStreaming: Boolean,
    activityFeed: List<ChatMessage>,
    isSending: Boolean,
    historyLoaded: Boolean = false,
    modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()

    // Scroll to bottom after history loads (with delay for layout)
    LaunchedEffect(historyLoaded) {
        if (historyLoaded && messages.isNotEmpty()) {
            kotlinx.coroutines.delay(100) // wait for layout
            listState.scrollToItem(messages.size - 1)
        }
    }

    // Auto-scroll on new messages
    LaunchedEffect(messages.size, isStreaming, activityFeed.size) {
        if (messages.isNotEmpty() || isStreaming || activityFeed.isNotEmpty()) {
            val totalItems = messages.size + activityFeed.size + if (isStreaming) 1 else 0
            listState.animateScrollToItem(maxOf(0, totalItems - 1))
        }
    }

    LazyColumn(
        modifier = modifier,
        state = listState,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        items(messages, key = { it.id }) { message ->
            HermesMessageBubble(text = message.text, isUser = message.role == "user")
        }

        // Activity feed: tool calls & thinking (shown while agent is working)
        if (activityFeed.isNotEmpty()) {
            items(activityFeed, key = { "act-${it.id}" }) { activity ->
                ActivityBubble(activity = activity)
            }
        }

        // Streaming bubble — reads from separate state, doesn't trigger list recomposition
        if (isStreaming) {
            item(key = "streaming") {
                HermesMessageBubble(text = streamingText, isUser = false)
            }
        }

        // Typing dots — only while waiting for first chunk
        if (isSending && !isStreaming && activityFeed.isEmpty()) {
            item(key = "hermes-typing") {
                TypingBubble()
            }
        }
    }
}

@Composable
private fun HermesMessageBubble(text: String, isUser: Boolean) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Surface(
            modifier = Modifier.widthIn(max = 280.dp),
            color = if (isUser) MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
            else MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(10.dp),
            border = if (isUser) null else BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.72f)),
            shadowElevation = if (isUser) 0.dp else 2.dp,
        ) {
            Text(
                text = text.ifEmpty { " " }, // prevent collapse when empty
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 9.dp),
                color = MaterialTheme.colorScheme.onSurface,
                fontSize = 14.sp,
                lineHeight = 19.sp,
            )
        }
    }
}

// Tool name → emoji mapping
private fun toolEmoji(name: String): String = when {
    name.contains("terminal", ignoreCase = true) -> "🖥️"
    name.contains("web_search", ignoreCase = true) -> "🔍"
    name.contains("browser", ignoreCase = true) -> "🌐"
    name.contains("read_file", ignoreCase = true) -> "📄"
    name.contains("search_files", ignoreCase = true) -> "🔎"
    name.contains("write_file", ignoreCase = true) -> "✏️"
    name.contains("patch", ignoreCase = true) -> "🔧"
    name.contains("memory", ignoreCase = true) -> "🧠"
    name.contains("skill", ignoreCase = true) -> "📚"
    name.contains("cron", ignoreCase = true) -> "⏰"
    name.contains("send_message", ignoreCase = true) -> "💬"
    name.contains("delegate", ignoreCase = true) -> "🤖"
    name.contains("image", ignoreCase = true) -> "🖼️"
    name.contains("vision", ignoreCase = true) -> "👁️"
    else -> "⚡"
}

@Composable
private fun ActivityBubble(activity: ChatMessage) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Start,
    ) {
        Surface(
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
            shape = RoundedCornerShape(8.dp),
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                if (activity.isThinking) {
                    Text(
                        text = "💭",
                        fontSize = 12.sp,
                    )
                    Text(
                        text = "思考中…",
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                        fontSize = 12.sp,
                        lineHeight = 16.sp,
                    )
                } else if (activity.toolName != null) {
                    Text(
                        text = toolEmoji(activity.toolName),
                        fontSize = 12.sp,
                    )
                    Text(
                        text = activity.toolName,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 12.sp,
                        lineHeight = 16.sp,
                        fontWeight = FontWeight.Medium,
                    )
                    if (activity.text != activity.toolName && activity.text.isNotEmpty()) {
                        Text(
                            text = activity.text.removePrefix(activity.toolName).removePrefix("(").removeSuffix(")"),
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                            fontSize = 11.sp,
                            lineHeight = 15.sp,
                            maxLines = 1,
                        )
                    }
                } else {
                    Text(
                        text = activity.text,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                        fontSize = 12.sp,
                        lineHeight = 16.sp,
                    )
                }
            }
        }
    }
}

@Composable
private fun ErrorBar(message: String, onRetry: () -> Unit) {
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
