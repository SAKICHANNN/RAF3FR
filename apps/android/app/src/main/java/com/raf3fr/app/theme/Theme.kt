package com.raf3fr.app.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val ProductColorScheme = darkColorScheme(
    primary = InstrumentOrange,
    onPrimary = Graphite,
    primaryContainer = InstrumentOrange,
    onPrimaryContainer = Graphite,
    secondary = Paper,
    onSecondary = Graphite,
    background = Graphite,
    onBackground = Paper,
    surface = GraphiteSurface,
    onSurface = Paper,
    surfaceVariant = GraphiteRaised,
    onSurfaceVariant = Muted,
    outline = GraphiteLine,
    error = ErrorRed,
)

@Composable
fun RAF3FRTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = ProductColorScheme, typography = ProductTypography, content = content)
}
