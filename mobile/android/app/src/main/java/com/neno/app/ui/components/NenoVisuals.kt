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
            .background(Color.White),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val w = size.width
            val h = size.height
            val ink = Color(0xFF111111)
            val stroke = w * 0.075f

            drawRoundRect(
                color = Color(0xFFE9E9E9),
                cornerRadius = CornerRadius(w * 0.30f, w * 0.30f),
                style = Stroke(width = w * 0.035f),
            )

            drawCircle(
                color = Color.Black.copy(alpha = 0.035f),
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
            .clip(RoundedCornerShape(18.dp))
            .background(Color.White),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.size(96.dp)) {
            drawRoundRect(
                color = Color(0xFFE9E9E9),
                cornerRadius = CornerRadius(size.width * 0.28f, size.width * 0.28f),
                style = Stroke(width = size.width * 0.025f),
            )
            when (kind) {
                AvatarKind.Neno -> {
                    repeat(4) { index ->
                        val x = size.width * (0.16f + index * 0.13f)
                        drawRoundRect(
                            color = Color.Black.copy(alpha = 0.07f - index * 0.01f),
                            topLeft = Offset(x, 0f),
                            size = Size(size.width * 0.07f, size.height),
                            cornerRadius = CornerRadius(size.width * 0.035f, size.width * 0.035f),
                        )
                    }
                    drawCircle(
                        color = Color.Black.copy(alpha = 0.045f),
                        radius = size.width * 0.30f,
                        center = Offset(size.width * 0.32f, size.height * 0.84f),
                    )
                }

                AvatarKind.Atlas -> {
                    drawCircle(
                        color = Color(0xFF111111),
                        radius = size.width * 0.12f,
                        center = Offset(size.width * 0.50f, size.height * 0.50f),
                    )
                }

                AvatarKind.Sage -> {
                    drawLine(
                        color = Color(0xFF111111),
                        start = Offset(size.width * 0.32f, size.height * 0.68f),
                        end = Offset(size.width * 0.68f, size.height * 0.32f),
                        strokeWidth = size.width * 0.06f,
                        cap = StrokeCap.Round,
                    )
                }

                AvatarKind.Hush -> {
                    drawRoundRect(
                        color = Color(0xFF111111),
                        topLeft = Offset(size.width * 0.35f, size.height * 0.35f),
                        size = Size(size.width * 0.30f, size.height * 0.30f),
                        cornerRadius = CornerRadius(size.width * 0.08f, size.width * 0.08f),
                    )
                }
            }
        }
    }
}
