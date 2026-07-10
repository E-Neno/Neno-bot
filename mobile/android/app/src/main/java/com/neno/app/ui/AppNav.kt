package com.neno.app.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.animation.core.tween
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp
import com.neno.app.data.MobileConversation
import com.neno.app.data.NenoRepository
import com.neno.app.ui.agent.AgentShellScreen
import com.neno.app.ui.chat.HermesChatScreen
import com.neno.app.ui.chat.NenoChatScreen
import com.neno.app.ui.conversations.ConversationListScreen
import com.neno.app.ui.settings.SettingsScreen

private enum class AppScreen {
    Conversations,
    NenoChat,
    HermesChat,
    AgentShell,
    Settings,
    UnsupportedContact,
}

@Composable
fun AppNav(repository: NenoRepository) {
    var screen by rememberSaveable { mutableStateOf(AppScreen.Conversations) }
    var unsupportedTitle by rememberSaveable { mutableStateOf("") }
    val connectionState by repository.connectionState.collectAsState()

    BackHandler(enabled = screen != AppScreen.Conversations) {
        screen = AppScreen.Conversations
    }

    AnimatedContent(
        targetState = screen,
        transitionSpec = {
            val direction = if (targetState.ordinal >= initialState.ordinal) 1 else -1
            (
                slideInHorizontally(animationSpec = tween(220)) { width -> direction * width / 5 } +
                    fadeIn(animationSpec = tween(120))
                ) togetherWith (
                slideOutHorizontally(animationSpec = tween(170)) { width -> -direction * width / 8 } +
                    fadeOut(animationSpec = tween(90))
                )
        },
        label = "screenTransition",
    ) { currentScreen ->
        when (currentScreen) {
            AppScreen.Conversations -> ConversationListScreen(
                repository = repository,
                onOpenConversation = { conversation ->
                    if (conversation.id == "neno") {
                        screen = AppScreen.NenoChat
                    } else if (conversation.id == "hermes") {
                        screen = AppScreen.HermesChat
                    } else {
                        unsupportedTitle = conversation.title
                        screen = AppScreen.UnsupportedContact
                    }
                },
                onOpenSettings = { screen = AppScreen.Settings },
                onOpenTools = {
                    screen = AppScreen.AgentShell
                },
            )

            AppScreen.NenoChat -> NenoChatScreen(
                repository = repository,
                connectionState = connectionState,
                onBack = { screen = AppScreen.Conversations },
                onOpenSettings = { screen = AppScreen.Settings },
            )

            AppScreen.HermesChat -> HermesChatScreen(
                repository = repository,
                onBack = { screen = AppScreen.Conversations },
            )

            AppScreen.AgentShell -> AgentShellScreen(
                onBack = { screen = AppScreen.Conversations },
            )

            AppScreen.Settings -> SettingsScreen(
                repository = repository,
                connectionState = connectionState,
                onBack = { screen = AppScreen.Conversations },
            )

            AppScreen.UnsupportedContact -> UnsupportedContactScreen(
                title = unsupportedTitle.ifBlank { "工具联系人" },
                onBack = { screen = AppScreen.Conversations },
            )
        }
    }
}

@Composable
private fun UnsupportedContactScreen(
    title: String,
    onBack: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            modifier = Modifier.widthIn(max = 520.dp),
            shape = RoundedCornerShape(8.dp),
            color = MaterialTheme.colorScheme.surface,
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        ) {
        Column(
            modifier = Modifier
                    .padding(24.dp),
                verticalArrangement = Arrangement.Center,
        ) {
            Text(
                    text = title,
                    style = MaterialTheme.typography.headlineMedium,
                color = MaterialTheme.colorScheme.onBackground,
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                    text = "这个联系人还没接入。先把 Neno 的聊天体验跑顺，再接入其他常用 AI。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.secondary,
            )
                Spacer(modifier = Modifier.height(18.dp))
                Surface(
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .clickable(onClick = onBack),
                    shape = RoundedCornerShape(8.dp),
                    color = MaterialTheme.colorScheme.background,
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
                ) {
                    Text(
                        text = "返回",
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 9.dp),
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }
        }
    }
}
