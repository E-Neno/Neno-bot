package com.neno.app.ui.settings

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
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
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.neno.app.data.AppConnectionState
import com.neno.app.data.NenoRepository
import kotlinx.coroutines.launch

@Composable
fun SettingsScreen(
    repository: NenoRepository,
    connectionState: AppConnectionState,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var showAdvanced by remember { mutableStateOf(false) }

    fun recheck() {
        scope.launch {
            repository.refreshConnection()
        }
    }

    // 进设置就自动测一次连接，给「通没通」的明确反馈，不用用户去点按钮。
    LaunchedEffect(Unit) { recheck() }

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
    ) {
        val wide = maxWidth >= 760.dp
        val panelModifier = if (wide) Modifier.width(560.dp) else Modifier.fillMaxWidth()
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(
                    start = if (wide) 44.dp else 18.dp,
                    top = if (wide) 50.dp else 38.dp,
                    end = if (wide) 44.dp else 18.dp,
                    bottom = if (wide) 30.dp else 18.dp,
                ),
            contentAlignment = Alignment.TopCenter,
        ) {
            Column(modifier = panelModifier.verticalScroll(rememberScrollState())) {
                SettingsHeader(onBack = onBack, onRevealAdvanced = { showAdvanced = true })
                Spacer(modifier = Modifier.height(20.dp))
                ConnectionCard(status = connectionState.connectionLabel(), onRecheck = ::recheck)
                Spacer(modifier = Modifier.height(14.dp))
                AppInfoCard()
                if (showAdvanced) {
                    Spacer(modifier = Modifier.height(14.dp))
                    AdvancedConnectionCard(
                        repository = repository,
                        onRecheck = ::recheck,
                    )
                    Spacer(modifier = Modifier.height(14.dp))
                    HermesConnectionCard(repository = repository)
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun SettingsHeader(
    onBack: () -> Unit,
    onRevealAdvanced: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.Bottom,
    ) {
        Column(
            modifier = Modifier
                .weight(1f)
                .clip(RoundedCornerShape(8.dp))
                // 长按标题揭开高级连接设置（平时不露在外面）。
                .combinedClickable(onClick = {}, onLongClick = onRevealAdvanced),
        ) {
            Text(
                text = "设置",
                style = MaterialTheme.typography.headlineLarge,
                color = MaterialTheme.colorScheme.onBackground,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "Neno 的连接与信息",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.secondary,
            )
        }
        Surface(
            modifier = Modifier
                .clip(RoundedCornerShape(8.dp))
                .clickable(onClick = onBack),
            shape = RoundedCornerShape(8.dp),
            color = MaterialTheme.colorScheme.surface,
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

@Composable
private fun ConnectionCard(
    status: String,
    onRecheck: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "和 Neno 的连接",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = "App 通过本机后端和她对话",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.secondary,
                    )
                }
                StatusChip(text = status)
            }
            Surface(
                modifier = Modifier
                    .clip(RoundedCornerShape(8.dp))
                    .clickable(onClick = onRecheck),
                shape = RoundedCornerShape(8.dp),
                color = MaterialTheme.colorScheme.background,
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
            ) {
                Text(
                    text = "重新检测",
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 9.dp),
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
        }
    }
}

@Composable
private fun AppInfoCard() {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            InfoRow(label = "应用", value = "Neno")
            InfoRow(label = "版本", value = "0.1.0")
            Spacer(modifier = Modifier.height(2.dp))
            Text(
                text = "长按上方「设置」标题可打开连接配置。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.secondary.copy(alpha = 0.65f),
            )
        }
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.secondary,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun AdvancedConnectionCard(
    repository: NenoRepository,
    onRecheck: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var baseUrl by remember { mutableStateOf(repository.currentBaseUrl()) }
    var token by remember { mutableStateOf(repository.currentToken()) }
    var isTesting by remember { mutableStateOf(false) }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(
                text = "连接设置（高级）",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            NenoField(value = baseUrl, onValueChange = { baseUrl = it }, label = "服务器地址")
            NenoField(value = token, onValueChange = { token = it }, label = "访问令牌", isPassword = true)
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Button(
                    onClick = {
                        repository.saveSettings(baseUrl, token)
                        baseUrl = repository.currentBaseUrl()
                        onRecheck()
                    },
                    shape = RoundedCornerShape(8.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.primary,
                        contentColor = MaterialTheme.colorScheme.onPrimary,
                    ),
                ) {
                    Text("保存")
                }
                Surface(
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .clickable(enabled = !isTesting) {
                            repository.saveSettings(baseUrl, token)
                            baseUrl = repository.currentBaseUrl()
                            isTesting = true
                            scope.launch {
                                repository.refreshConnection()
                                isTesting = false
                            }
                        },
                    shape = RoundedCornerShape(8.dp),
                    color = MaterialTheme.colorScheme.background,
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
                ) {
                    Text(
                        text = "测试连接",
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }
            Text(
                text = "模拟器默认使用 http://10.0.2.2:8000；真机需要填电脑局域网地址。",
                color = MaterialTheme.colorScheme.secondary,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@Composable
private fun HermesConnectionCard(repository: NenoRepository) {
    var hermesUrl by remember { mutableStateOf(repository.currentHermesBaseUrl()) }
    var hermesApiKey by remember { mutableStateOf(repository.currentHermesApiKey()) }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(
                text = "Hermes 连接设置",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            NenoField(value = hermesUrl, onValueChange = { hermesUrl = it }, label = "Hermes API 地址")
            NenoField(value = hermesApiKey, onValueChange = { hermesApiKey = it }, label = "API Key", isPassword = true)
            Button(
                onClick = {
                    repository.saveHermesSettings(hermesUrl, hermesApiKey)
                    hermesUrl = repository.currentHermesBaseUrl()
                },
                shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    contentColor = MaterialTheme.colorScheme.onPrimary,
                ),
            ) {
                Text("保存")
            }
            Text(
                text = "Hermes 默认地址 http://10.0.2.2:8642；配置后联系人列表会出现 Hermes。",
                color = MaterialTheme.colorScheme.secondary,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@Composable
private fun NenoField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    isPassword: Boolean = false,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(label) },
        singleLine = true,
        shape = RoundedCornerShape(8.dp),
        visualTransformation = if (isPassword) PasswordVisualTransformation() else VisualTransformation.None,
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = MaterialTheme.colorScheme.primary,
            unfocusedBorderColor = MaterialTheme.colorScheme.outline,
            focusedContainerColor = MaterialTheme.colorScheme.background.copy(alpha = 0.50f),
            unfocusedContainerColor = MaterialTheme.colorScheme.background.copy(alpha = 0.50f),
        ),
    )
}

@Composable
private fun StatusChip(text: String) {
    val connected = text == "已连接"
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = if (connected) {
            MaterialTheme.colorScheme.tertiary.copy(alpha = 0.14f)
        } else {
            MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.70f)
        },
        border = BorderStroke(
            1.dp,
            if (connected) MaterialTheme.colorScheme.tertiary.copy(alpha = 0.32f) else MaterialTheme.colorScheme.outline,
        ),
    ) {
        Text(
            text = text,
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 9.dp),
            color = if (connected) MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.secondary,
            style = MaterialTheme.typography.labelMedium,
        )
    }
}
