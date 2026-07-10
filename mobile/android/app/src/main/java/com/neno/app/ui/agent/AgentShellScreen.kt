package com.neno.app.ui.agent

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.neno.app.ui.components.AppIcon
import com.neno.app.ui.components.NenoIcon

private val AgentBackground = Color.White
private val AgentPanel = Color(0xFFF8F8F8)
private val AgentLine = Color(0xFFE9E9E9)
private val AgentText = Color(0xFF111111)
private val AgentWeakText = Color(0xFF7A7A7A)
private val AgentAccent = Color(0xFF111111)
private val AgentWarn = Color(0xFFD64F45)

@Composable
fun AgentShellScreen(
    onBack: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(AgentBackground)
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 18.dp, vertical = 12.dp),
    ) {
        AgentTopBar(onBack = onBack)
        Spacer(modifier = Modifier.height(14.dp))
        AgentStatusStrip()
        Spacer(modifier = Modifier.height(12.dp))
        AgentDeviceStage(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(12.dp))
        AgentTaskComposer()
        Spacer(modifier = Modifier.height(10.dp))
        AgentExecutionRail()
    }
}

@Composable
private fun AgentTopBar(onBack: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(44.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(36.dp)
                .clickable(onClick = onBack),
            contentAlignment = Alignment.Center,
        ) {
            AppIcon(
                icon = NenoIcon.Back,
                modifier = Modifier.size(22.dp),
                tint = AgentText,
            )
        }
        Spacer(modifier = Modifier.width(8.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "手机 Agent",
                color = AgentText,
                fontSize = 20.sp,
                lineHeight = 24.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "默认权限",
                color = AgentWeakText,
                fontSize = 11.sp,
                lineHeight = 14.sp,
            )
        }
        AgentSignalDot(label = "待命", color = AgentAccent)
    }
}

@Composable
private fun AgentStatusStrip() {
    Surface(
        color = Color.White,
        border = BorderStroke(1.dp, AgentLine),
        shape = RoundedCornerShape(18.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StatusItem(title = "连接", value = "已连接")
            StatusItem(title = "Root", value = "只读")
            StatusItem(title = "权限", value = "默认")
        }
    }
}

@Composable
private fun StatusItem(title: String, value: String) {
    Column {
        Text(
            text = title,
            color = AgentWeakText,
            fontSize = 10.sp,
            lineHeight = 12.sp,
        )
        Text(
            text = value,
            color = AgentText,
            fontSize = 13.sp,
            lineHeight = 16.sp,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
private fun AgentDeviceStage(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .background(AgentPanel, RoundedCornerShape(8.dp))
            .padding(12.dp),
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val step = size.width / 6f
            repeat(7) { index ->
                val x = step * index
                drawLine(
                    color = AgentLine.copy(alpha = 0.55f),
                    start = Offset(x, 0f),
                    end = Offset(x, size.height),
                    strokeWidth = 1f,
                )
            }
            repeat(10) { index ->
                val y = size.height / 9f * index
                drawLine(
                    color = AgentLine.copy(alpha = 0.44f),
                    start = Offset(0f, y),
                    end = Offset(size.width, y),
                    strokeWidth = 1f,
                )
            }
            drawLine(
                color = AgentAccent.copy(alpha = 0.84f),
                start = Offset(size.width * 0.18f, size.height * 0.22f),
                end = Offset(size.width * 0.76f, size.height * 0.22f),
                strokeWidth = 2f,
                cap = StrokeCap.Round,
            )
            drawCircle(
                color = AgentAccent.copy(alpha = 0.84f),
                radius = 7f,
                center = Offset(size.width * 0.76f, size.height * 0.22f),
            )
            drawLine(
                color = AgentWarn.copy(alpha = 0.72f),
                start = Offset(size.width * 0.34f, size.height * 0.70f),
                end = Offset(size.width * 0.86f, size.height * 0.70f),
                strokeWidth = 2f,
                cap = StrokeCap.Round,
            )
        }
        Column(
            modifier = Modifier.align(Alignment.BottomStart),
        ) {
            Text(
                text = "设备画面",
                color = AgentText,
                fontSize = 16.sp,
                lineHeight = 20.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "后续接入截图流与可点击区域标注",
                color = AgentWeakText,
                fontSize = 12.sp,
                lineHeight = 16.sp,
            )
        }
    }
}

@Composable
private fun AgentTaskComposer() {
    Surface(
        color = Color.White,
        border = BorderStroke(1.dp, AgentLine),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .height(128.dp)
                .padding(14.dp),
        ) {
            Text(
                text = "默认权限",
                color = AgentWeakText,
                fontSize = 12.sp,
                lineHeight = 15.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(modifier = Modifier.height(10.dp))
            Text(
                text = "打开浏览器，查看 KernelSU 模块日志；只读命令自动执行，写入前停下确认。",
                modifier = Modifier
                    .weight(1f)
                    .verticalScroll(rememberScrollState()),
                color = AgentText,
                fontSize = 15.sp,
                lineHeight = 22.sp,
            )
        }
    }
}

@Composable
private fun AgentExecutionRail() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        RailBlock(
            title = "计划",
            body = "读取前台 · 搜索模块 · 回传截图",
            modifier = Modifier.weight(1.2f),
        )
        RailBlock(
            title = "确认",
            body = "高风险动作暂停",
            modifier = Modifier.weight(0.8f),
        )
    }
}

@Composable
private fun RailBlock(
    title: String,
    body: String,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier.height(72.dp),
        color = Color.White,
        border = BorderStroke(1.dp, AgentLine),
        shape = RoundedCornerShape(16.dp),
    ) {
        Column(
            modifier = Modifier.padding(10.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                text = title,
                color = AgentWeakText,
                fontSize = 10.sp,
                lineHeight = 12.sp,
            )
            Spacer(modifier = Modifier.height(5.dp))
            Text(
                text = body,
                color = AgentText,
                fontSize = 12.sp,
                lineHeight = 16.sp,
            )
        }
    }
}

@Composable
private fun AgentSignalDot(label: String, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(color, RoundedCornerShape(50)),
        )
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            text = label,
            color = AgentWeakText,
            fontSize = 11.sp,
            lineHeight = 13.sp,
        )
    }
}
