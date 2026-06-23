package com.neno.app.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp

enum class NenoIcon {
    Back,
    Search,
    MoreVertical,
    Pin,
    Chat,
    Sparkles,
    Person,
    Smile,
    Paperclip,
    Mic,
    DoubleCheck,
}

enum class AvatarKind {
    Neno,
    Atlas,
    Sage,
    Hush,
}

@Composable
fun AppIcon(
    icon: NenoIcon,
    modifier: Modifier = Modifier,
    tint: Color = Color(0xFF202020),
) {
    Canvas(modifier = modifier) {
        val w = size.width
        val h = size.height
        val stroke = Stroke(width = w * 0.095f, cap = StrokeCap.Round)
        when (icon) {
            NenoIcon.Back -> {
                drawLine(tint, Offset(w * 0.64f, h * 0.20f), Offset(w * 0.30f, h * 0.50f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.30f, h * 0.50f), Offset(w * 0.64f, h * 0.80f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.32f, h * 0.50f), Offset(w * 0.84f, h * 0.50f), strokeWidth = stroke.width, cap = StrokeCap.Round)
            }

            NenoIcon.Search -> {
                drawCircle(tint, radius = w * 0.25f, center = Offset(w * 0.43f, h * 0.42f), style = stroke)
                drawLine(tint, Offset(w * 0.62f, h * 0.62f), Offset(w * 0.82f, h * 0.82f), strokeWidth = stroke.width, cap = StrokeCap.Round)
            }

            NenoIcon.MoreVertical -> {
                drawCircle(tint, radius = w * 0.055f, center = Offset(w * 0.50f, h * 0.25f))
                drawCircle(tint, radius = w * 0.055f, center = Offset(w * 0.50f, h * 0.50f))
                drawCircle(tint, radius = w * 0.055f, center = Offset(w * 0.50f, h * 0.75f))
            }

            NenoIcon.Pin -> {
                drawRoundRect(
                    color = tint,
                    topLeft = Offset(w * 0.34f, h * 0.14f),
                    size = Size(w * 0.32f, h * 0.34f),
                    cornerRadius = CornerRadius(w * 0.05f, w * 0.05f),
                )
                drawLine(tint, Offset(w * 0.50f, h * 0.47f), Offset(w * 0.50f, h * 0.83f), strokeWidth = stroke.width * 0.72f, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.38f, h * 0.82f), Offset(w * 0.62f, h * 0.82f), strokeWidth = stroke.width * 0.72f, cap = StrokeCap.Round)
            }

            NenoIcon.Chat -> {
                drawRoundRect(
                    tint,
                    topLeft = Offset(w * 0.18f, h * 0.22f),
                    size = Size(w * 0.64f, h * 0.48f),
                    cornerRadius = CornerRadius(w * 0.08f, w * 0.08f),
                    style = stroke,
                )
                val tail = Path().apply {
                    moveTo(w * 0.34f, h * 0.70f)
                    lineTo(w * 0.24f, h * 0.86f)
                    lineTo(w * 0.50f, h * 0.70f)
                }
                drawPath(tail, tint)
            }

            NenoIcon.Sparkles -> {
                drawLine(tint, Offset(w * 0.38f, h * 0.12f), Offset(w * 0.38f, h * 0.54f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.17f, h * 0.33f), Offset(w * 0.59f, h * 0.33f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.72f, h * 0.52f), Offset(w * 0.72f, h * 0.84f), strokeWidth = stroke.width * 0.78f, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.56f, h * 0.68f), Offset(w * 0.88f, h * 0.68f), strokeWidth = stroke.width * 0.78f, cap = StrokeCap.Round)
            }

            NenoIcon.Person -> {
                drawCircle(tint, radius = w * 0.18f, center = Offset(w * 0.50f, h * 0.32f), style = stroke)
                drawArc(
                    color = tint,
                    startAngle = 205f,
                    sweepAngle = 130f,
                    useCenter = false,
                    topLeft = Offset(w * 0.24f, h * 0.45f),
                    size = Size(w * 0.52f, h * 0.48f),
                    style = stroke,
                )
            }

            NenoIcon.Smile -> {
                drawCircle(tint, radius = w * 0.36f, center = Offset(w * 0.50f, h * 0.50f), style = stroke)
                drawCircle(tint, radius = w * 0.035f, center = Offset(w * 0.38f, h * 0.43f))
                drawCircle(tint, radius = w * 0.035f, center = Offset(w * 0.62f, h * 0.43f))
                drawArc(
                    color = tint,
                    startAngle = 25f,
                    sweepAngle = 130f,
                    useCenter = false,
                    topLeft = Offset(w * 0.33f, h * 0.42f),
                    size = Size(w * 0.34f, h * 0.28f),
                    style = stroke,
                )
            }

            NenoIcon.Paperclip -> {
                drawArc(
                    tint,
                    startAngle = 38f,
                    sweepAngle = 278f,
                    useCenter = false,
                    topLeft = Offset(w * 0.28f, h * 0.12f),
                    size = Size(w * 0.42f, h * 0.70f),
                    style = stroke,
                )
                drawLine(tint, Offset(w * 0.52f, h * 0.22f), Offset(w * 0.30f, h * 0.58f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.68f, h * 0.40f), Offset(w * 0.42f, h * 0.78f), strokeWidth = stroke.width, cap = StrokeCap.Round)
            }

            NenoIcon.Mic -> {
                drawRoundRect(
                    tint,
                    topLeft = Offset(w * 0.39f, h * 0.13f),
                    size = Size(w * 0.22f, h * 0.46f),
                    cornerRadius = CornerRadius(w * 0.11f, w * 0.11f),
                    style = stroke,
                )
                drawArc(
                    tint,
                    startAngle = 20f,
                    sweepAngle = 140f,
                    useCenter = false,
                    topLeft = Offset(w * 0.25f, h * 0.36f),
                    size = Size(w * 0.50f, h * 0.36f),
                    style = stroke,
                )
                drawLine(tint, Offset(w * 0.50f, h * 0.72f), Offset(w * 0.50f, h * 0.86f), strokeWidth = stroke.width, cap = StrokeCap.Round)
            }

            NenoIcon.DoubleCheck -> {
                drawLine(tint, Offset(w * 0.18f, h * 0.56f), Offset(w * 0.32f, h * 0.70f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.32f, h * 0.70f), Offset(w * 0.58f, h * 0.34f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.42f, h * 0.66f), Offset(w * 0.55f, h * 0.78f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawLine(tint, Offset(w * 0.55f, h * 0.78f), Offset(w * 0.84f, h * 0.36f), strokeWidth = stroke.width, cap = StrokeCap.Round)
            }
        }
    }
}

@Composable
fun NenoBrandIcon(
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(
                Brush.linearGradient(
                    colors = listOf(
                        Color(0xFFEAF4FF),
                        Color(0xFFD6E9FF),
                        Color(0xFFBFD8FF),
                    ),
                    start = Offset.Zero,
                    end = Offset.Infinite,
                ),
            ),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val w = size.width
            val h = size.height
            val ink = Color(0xFF13233F)
            val stroke = w * 0.075f

            drawCircle(
                color = Color.White.copy(alpha = 0.42f),
                radius = w * 0.25f,
                center = Offset(w * 0.28f, h * 0.22f),
            )
            drawLine(
                color = ink,
                start = Offset(w * 0.35f, h * 0.30f),
                end = Offset(w * 0.35f, h * 0.70f),
                strokeWidth = stroke,
                cap = StrokeCap.Round,
            )
            drawLine(
                color = ink,
                start = Offset(w * 0.35f, h * 0.30f),
                end = Offset(w * 0.65f, h * 0.70f),
                strokeWidth = stroke,
                cap = StrokeCap.Round,
            )
            drawLine(
                color = ink,
                start = Offset(w * 0.65f, h * 0.30f),
                end = Offset(w * 0.65f, h * 0.70f),
                strokeWidth = stroke,
                cap = StrokeCap.Round,
            )
        }
    }
}

@Composable
fun PhotoAvatar(
    kind: AvatarKind,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clip(CircleShape)
            .background(Color(0xFFE8E1D8)),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.size(96.dp)) {
            when (kind) {
                AvatarKind.Neno -> {
                    drawRect(
                        Brush.linearGradient(
                            colors = listOf(Color(0xFFF0ECE5), Color(0xFF6F6A61), Color(0xFF161615)),
                            start = Offset(0f, 0f),
                            end = Offset(size.width, size.height),
                        ),
                    )
                    repeat(5) { i ->
                        val x = size.width * (0.18f + i * 0.14f)
                        drawRect(Color.White.copy(alpha = 0.28f), Offset(x, 0f), Size(size.width * 0.05f, size.height))
                    }
                    drawCircle(Color(0xFF0E0E0D).copy(alpha = 0.55f), radius = size.width * 0.36f, center = Offset(size.width * 0.30f, size.height * 0.82f))
                }

                AvatarKind.Atlas -> {
                    drawRect(
                        Brush.verticalGradient(listOf(Color(0xFFBCD1DC), Color(0xFFF8F0DE), Color(0xFF4D5D42))),
                    )
                    drawCircle(Color.White.copy(alpha = 0.75f), size.width * 0.20f, Offset(size.width * 0.31f, size.height * 0.28f))
                    drawRect(Color(0xFF5F6C44), Offset(0f, size.height * 0.62f), Size(size.width, size.height * 0.38f))
                }

                AvatarKind.Sage -> {
                    drawRect(
                        Brush.linearGradient(listOf(Color(0xFFE4E0CC), Color(0xFFADB39B), Color(0xFFECE7D5))),
                    )
                    drawLine(Color(0xFF566145), Offset(size.width * 0.48f, size.height * 0.84f), Offset(size.width * 0.55f, size.height * 0.24f), strokeWidth = size.width * 0.035f, cap = StrokeCap.Round)
                    drawCircle(Color(0xFF7E8C67), size.width * 0.18f, Offset(size.width * 0.40f, size.height * 0.45f))
                    drawCircle(Color(0xFF687752), size.width * 0.15f, Offset(size.width * 0.63f, size.height * 0.34f))
                }

                AvatarKind.Hush -> {
                    drawRect(
                        Brush.radialGradient(listOf(Color(0xFFD9A757), Color(0xFF5A3319), Color(0xFF15100D))),
                    )
                    drawRoundRect(
                        Color(0xFFF5D58D),
                        topLeft = Offset(size.width * 0.38f, size.height * 0.32f),
                        size = Size(size.width * 0.24f, size.height * 0.20f),
                        cornerRadius = CornerRadius(size.width * 0.04f, size.width * 0.04f),
                    )
                    drawRect(Color(0xFF2B1B12), Offset(size.width * 0.47f, size.height * 0.52f), Size(size.width * 0.06f, size.height * 0.18f))
                    drawLine(Color(0xFFE8B85D), Offset(size.width * 0.30f, size.height * 0.70f), Offset(size.width * 0.70f, size.height * 0.70f), strokeWidth = size.width * 0.03f)
                }
            }
        }
    }
}
