package com.neno.app.ui.conversations

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
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.neno.app.data.MobileConversation
import com.neno.app.data.NenoRepository
import com.neno.app.ui.AsyncListState
import com.neno.app.ui.asyncListState
import com.neno.app.ui.components.AppIcon
import com.neno.app.ui.components.AvatarKind
import com.neno.app.ui.components.NenoBrandIcon
import com.neno.app.ui.components.NenoIcon
import com.neno.app.ui.components.PhotoAvatar

@Composable
fun ConversationListScreen(
    repository: NenoRepository,
    onOpenConversation: (MobileConversation) -> Unit,
    onOpenSettings: () -> Unit,
    onOpenTools: () -> Unit,
) {
    var conversations by remember(repository) { mutableStateOf<List<MobileConversation>?>(repository.cachedConversations()) }

    LaunchedEffect(repository) {
        conversations = repository.cachedConversations()
        conversations = repository.loadConversations()
    }

    LaunchedEffect(repository) {
        repository.incomingConversations.collect { snapshot ->
            conversations = snapshot
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
            ConversationShell(
                conversations = conversations,
                onOpenConversation = onOpenConversation,
                onOpenSettings = onOpenSettings,
                onOpenTools = onOpenTools,
                modifier = shellModifier,
            )
        }
    }
}

@Composable
private fun ConversationShell(
    conversations: List<MobileConversation>?,
    onOpenConversation: (MobileConversation) -> Unit,
    onOpenSettings: () -> Unit,
    onOpenTools: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val listState = asyncListState(conversations)
    val loadedConversations = conversations.orEmpty()
    val neno = loadedConversations.firstOrNull { it.id == "neno" }
    val recents = loadedConversations.filterNot { it.id == "neno" }

    Column(
        modifier = modifier
            .background(MaterialTheme.colorScheme.background)
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(start = 24.dp, top = 12.dp, end = 24.dp),
    ) {
        Header()
        Spacer(modifier = Modifier.height(12.dp))

        LazyColumn(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
        ) {
            item {
                SectionLabel(icon = NenoIcon.Pin, text = "置顶")
                Spacer(modifier = Modifier.height(14.dp))
                when (listState) {
                    AsyncListState.Loading -> ConversationLoadingContent()
                    AsyncListState.Empty -> EmptyConversationContent()
                    AsyncListState.Content -> ConversationLoadedContent(
                        neno = neno,
                        recents = recents,
                        onOpenConversation = onOpenConversation,
                    )
                }
            }
        }

        BottomNav(
            selected = "对话",
            onChats = {},
            onTools = onOpenTools,
            onMe = onOpenSettings,
        )
    }
}

@Composable
private fun Header() {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(52.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        NenoBrandIcon(modifier = Modifier.size(40.dp))
        Spacer(modifier = Modifier.width(14.dp))
        Text(
            text = "Neno",
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.onBackground,
            fontSize = 28.sp,
            lineHeight = 32.sp,
            fontWeight = FontWeight.ExtraBold,
        )
    }
}

@Composable
private fun SectionLabel(
    icon: NenoIcon,
    text: String,
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        AppIcon(
            icon = icon,
            modifier = Modifier.size(16.dp),
            tint = MaterialTheme.colorScheme.secondary,
        )
        Spacer(modifier = Modifier.width(9.dp))
        Text(
            text = text,
            color = MaterialTheme.colorScheme.secondary,
            fontSize = 15.sp,
            lineHeight = 20.sp,
        )
    }
}

@Composable
private fun ConversationLoadedContent(
    neno: MobileConversation?,
    recents: List<MobileConversation>,
    onOpenConversation: (MobileConversation) -> Unit,
) {
    if (neno == null) {
        EmptyConversationContent()
        return
    }

    PinnedConversationCard(
        conversation = neno,
        onClick = { onOpenConversation(neno) },
    )
    Spacer(modifier = Modifier.height(14.dp))
    RecentHeader()
    recents.forEachIndexed { index, conversation ->
        RecentConversationRow(
            conversation = conversation,
            avatarKind = when (index) {
                0 -> AvatarKind.Atlas
                1 -> AvatarKind.Sage
                else -> AvatarKind.Hush
            },
            time = when (index) {
                0 -> "昨天"
                1 -> "周一"
                else -> "周日"
            },
            onClick = { onOpenConversation(conversation) },
        )
    }
}

@Composable
private fun ConversationLoadingContent() {
    PinnedLoadingCard()
    Spacer(modifier = Modifier.height(14.dp))
    RecentHeader()
    repeat(3) {
        LoadingConversationRow()
    }
}

@Composable
private fun EmptyConversationContent() {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .height(84.dp),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(16.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.72f)),
    ) {
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "还没有消息",
                color = MaterialTheme.colorScheme.secondary,
                fontSize = 13.sp,
                lineHeight = 17.sp,
            )
        }
    }
}

@Composable
private fun PinnedLoadingCard() {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .height(84.dp),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(16.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.50f)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            LoadingBlock(
                modifier = Modifier
                    .size(42.dp)
                    .clip(CircleShape),
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                LoadingBlock(
                    modifier = Modifier
                        .fillMaxWidth(0.36f)
                        .height(16.dp)
                        .clip(RoundedCornerShape(8.dp)),
                )
                Spacer(modifier = Modifier.height(8.dp))
                LoadingBlock(
                    modifier = Modifier
                        .fillMaxWidth(0.62f)
                        .height(12.dp)
                        .clip(RoundedCornerShape(6.dp)),
                )
            }
        }
    }
}

@Composable
private fun LoadingConversationRow() {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(60.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        LoadingBlock(
            modifier = Modifier
                .size(40.dp)
                .clip(CircleShape),
        )
        Spacer(modifier = Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            LoadingBlock(
                modifier = Modifier
                    .fillMaxWidth(0.34f)
                    .height(14.dp)
                    .clip(RoundedCornerShape(7.dp)),
            )
            Spacer(modifier = Modifier.height(8.dp))
            LoadingBlock(
                modifier = Modifier
                    .fillMaxWidth(0.58f)
                    .height(11.dp)
                    .clip(RoundedCornerShape(6.dp)),
            )
        }
    }
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(MaterialTheme.colorScheme.outline.copy(alpha = 0.35f)),
    )
}

@Composable
private fun LoadingBlock(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier.background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.78f)),
    )
}

@Composable
private fun PinnedConversationCard(
    conversation: MobileConversation,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .height(84.dp)
            .shadow(10.dp, RoundedCornerShape(16.dp), ambientColor = Color.Black.copy(alpha = 0.08f), spotColor = Color.Black.copy(alpha = 0.10f))
            .clip(RoundedCornerShape(16.dp))
            .clickable(onClick = onClick),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(16.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.72f)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            PhotoAvatar(
                kind = AvatarKind.Neno,
                modifier = Modifier.size(42.dp),
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = conversation.title,
                        color = MaterialTheme.colorScheme.onSurface,
                        fontSize = 16.sp,
                        lineHeight = 20.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = "置顶",
                        color = MaterialTheme.colorScheme.primary,
                        fontSize = 11.sp,
                        lineHeight = 14.sp,
                    )
                    val online = conversation.presence == "在线"
                    Spacer(modifier = Modifier.width(8.dp))
                    Box(
                        modifier = Modifier
                            .size(6.dp)
                            .clip(CircleShape)
                            .background(if (online) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline),
                    )
                    if (!online) {
                        Spacer(modifier = Modifier.width(5.dp))
                        Text(
                            text = conversation.presence,
                            color = MaterialTheme.colorScheme.secondary,
                            fontSize = 11.sp,
                            lineHeight = 14.sp,
                        )
                    }
                }
                Spacer(modifier = Modifier.height(3.dp))
                Text(
                    text = conversation.lastMessage.ifBlank { "还没有消息" },
                    color = MaterialTheme.colorScheme.secondary,
                    fontSize = 12.sp,
                    lineHeight = 17.sp,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Column(
                modifier = Modifier.fillMaxHeight(),
                horizontalAlignment = Alignment.End,
                verticalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = "8:42",
                    color = MaterialTheme.colorScheme.secondary,
                    fontSize = 13.sp,
                    lineHeight = 16.sp,
                )
                // 只有真有未读才显示红点，别常驻。后端目前 unread_count=0，所以默认不出现。
                if (conversation.unreadCount > 0) {
                    UnreadBadge(count = conversation.unreadCount)
                }
            }
        }
    }
}

@Composable
private fun RecentHeader() {
    Text(
        text = "最近",
        color = MaterialTheme.colorScheme.secondary,
        fontSize = 15.sp,
        lineHeight = 20.sp,
    )
    Spacer(modifier = Modifier.height(14.dp))
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(MaterialTheme.colorScheme.outline.copy(alpha = 0.82f)),
    )
}

@Composable
private fun RecentConversationRow(
    conversation: MobileConversation,
    avatarKind: AvatarKind,
    time: String,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(60.dp)
            .clickable(onClick = onClick),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        PhotoAvatar(
            kind = avatarKind,
            modifier = Modifier.size(40.dp),
        )
        Spacer(modifier = Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = conversation.title,
                color = MaterialTheme.colorScheme.onSurface,
                fontSize = 15.sp,
                lineHeight = 19.sp,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(modifier = Modifier.height(3.dp))
            Text(
                text = conversation.lastMessage.ifBlank { conversation.subtitle },
                color = MaterialTheme.colorScheme.secondary,
                fontSize = 12.sp,
                lineHeight = 16.sp,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(modifier = Modifier.width(12.dp))
        Text(
            text = time,
            color = MaterialTheme.colorScheme.secondary,
            fontSize = 11.sp,
            lineHeight = 14.sp,
        )
    }
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(MaterialTheme.colorScheme.outline.copy(alpha = 0.52f)),
    )
}

@Composable
private fun BottomNav(
    selected: String,
    onChats: () -> Unit,
    onTools: () -> Unit,
    onMe: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(56.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        NavItem(
            icon = NenoIcon.Chat,
            label = "对话",
            selected = selected == "对话",
            onClick = onChats,
        )
        NavItem(
            icon = NenoIcon.Sparkles,
            label = "工具",
            selected = selected == "工具",
            onClick = onTools,
        )
        NavItem(
            icon = NenoIcon.Person,
            label = "我的",
            selected = selected == "我的",
            onClick = onMe,
        )
    }
}

@Composable
private fun NavItem(
    icon: NenoIcon,
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .width(88.dp)
            .clip(RoundedCornerShape(18.dp))
            .clickable(onClick = onClick)
            .padding(vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Surface(
            color = if (selected) MaterialTheme.colorScheme.primaryContainer else Color.Transparent,
            shape = RoundedCornerShape(20.dp),
        ) {
            Box(
                modifier = Modifier
                    .width(52.dp)
                    .height(26.dp),
                contentAlignment = Alignment.Center,
            ) {
                AppIcon(
                    icon = icon,
                    modifier = Modifier.size(19.dp),
                    tint = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.secondary,
                )
            }
        }
        Spacer(modifier = Modifier.height(2.dp))
        Text(
            text = label,
            color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
            fontSize = 12.sp,
            lineHeight = 15.sp,
        )
    }
}

@Composable
private fun IconTapTarget(
    icon: NenoIcon,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .size(36.dp)
            .clip(CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        AppIcon(
            icon = icon,
            modifier = Modifier.size(25.dp),
            tint = MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun UnreadBadge(count: Int) {
    Box(
        modifier = Modifier
            .size(20.dp)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.primary),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = count.toString(),
            color = Color.White,
            fontSize = 10.sp,
            lineHeight = 11.sp,
            fontWeight = FontWeight.Medium,
        )
    }
}
