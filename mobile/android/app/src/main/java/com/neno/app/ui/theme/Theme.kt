package com.neno.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

private val NenoLightColors = lightColorScheme(
    background = Color(0xFFFFFCF8),
    surface = Color(0xFFFFFCF8),
    surfaceVariant = Color(0xFFF2EEE8),
    primary = Color(0xFFE96332),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFFFE7D7),
    onPrimaryContainer = Color(0xFF2B1A12),
    secondary = Color(0xFF5D5A55),
    secondaryContainer = Color(0xFFF1EAE3),
    tertiary = Color(0xFF6B7463),
    onBackground = Color(0xFF141414),
    onSurface = Color(0xFF161616),
    outline = Color(0xFFE3DDD5),
)

private val NenoTypography = Typography(
    headlineLarge = TextStyle(
        fontSize = 32.sp,
        lineHeight = 38.sp,
        fontWeight = FontWeight.SemiBold,
    ),
    headlineMedium = TextStyle(
        fontSize = 25.sp,
        lineHeight = 31.sp,
        fontWeight = FontWeight.SemiBold,
    ),
    titleLarge = TextStyle(
        fontSize = 22.sp,
        lineHeight = 28.sp,
        fontWeight = FontWeight.SemiBold,
    ),
    titleMedium = TextStyle(
        fontSize = 17.sp,
        lineHeight = 23.sp,
        fontWeight = FontWeight.SemiBold,
    ),
    bodyLarge = TextStyle(
        fontSize = 16.sp,
        lineHeight = 23.sp,
        fontWeight = FontWeight.Normal,
    ),
    bodyMedium = TextStyle(
        fontSize = 14.sp,
        lineHeight = 20.sp,
        fontWeight = FontWeight.Normal,
    ),
    labelMedium = TextStyle(
        fontSize = 12.sp,
        lineHeight = 16.sp,
        fontWeight = FontWeight.Medium,
    ),
)

@Composable
fun NenoTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = NenoLightColors,
        typography = NenoTypography,
        content = content,
    )
}
