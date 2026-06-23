package com.neno.app.ui.settings

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.neno.app.data.NenoRepository
import kotlinx.coroutines.launch

@Composable
fun SettingsScreen(
    repository: NenoRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var baseUrl by remember { mutableStateOf(repository.currentBaseUrl()) }
    var token by remember { mutableStateOf(repository.currentToken()) }
    var statusText by remember { mutableStateOf("未连接") }
    var isTesting by remember { mutableStateOf(false) }

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
    ) {
        val wide = maxWidth >= 760.dp
        val panelModifier = if (wide) {
            Modifier.width(560.dp)
        } else {
            Modifier.fillMaxWidth()
        }
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = if (wide) 44.dp else 18.dp, vertical = if (wide) 30.dp else 18.dp),
            contentAlignment = Alignment.TopCenter,
        ) {
            Column(modifier = panelModifier) {
                SettingsHeader(onBack = onBack)
                Spacer(modifier = Modifier.height(20.dp))
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
                        NenoField(
                            value = baseUrl,
                            onValueChange = { baseUrl = it },
                            label = "服务器地址",
                        )
                        NenoField(
                            value = token,
                            onValueChange = { token = it },
                            label = "访问令牌",
                            isPassword = true,
                        )
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            Button(
                                onClick = {
                                    repository.saveSettings(baseUrl, token)
                                    baseUrl = repository.currentBaseUrl()
                                    statusText = "已保存"
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
                                        statusText = "连接中"
                                        scope.launch {
                                            runCatching { repository.checkStatus() }
                                                .onSuccess { statusText = "已连接" }
                                                .onFailure { error ->
                                                    statusText = if (error.message?.contains("403") == true) {
                                                        "令牌无效"
                                                    } else {
                                                        "未连接"
                                                    }
                                                }
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
                            StatusChip(text = statusText)
                        }
                        Text(
                            text = "模拟器默认使用 http://10.0.2.2:8000；真机需要填电脑局域网地址。",
                            color = MaterialTheme.colorScheme.secondary,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsHeader(onBack: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.Bottom,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "设置",
                style = MaterialTheme.typography.headlineLarge,
                color = MaterialTheme.colorScheme.onBackground,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "只保存本机连接信息",
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
        visualTransformation = if (isPassword) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
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
