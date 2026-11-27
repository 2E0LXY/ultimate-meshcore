package uk.umc.app.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * One UMC theme as Compose colours. Built from [UmcTokens], which mirror docs/umc/theme/tokens.json.
 * Charts and custom components read this through [LocalUmcPalette] (or [Dc] outside composables);
 * Material components read the [ColorScheme] derived from it.
 */
data class UmcPalette(
    val id: UmcThemeId,
    val label: String,
    val page: Color, val surface: Color, val surface2: Color, val sidebar: Color, val card: Color,
    val border: Color, val chip: Color, val track: Color,
    val ink: Color, val muted: Color, val faint: Color,
    val accent: Color, val accentInk: Color, val navActive: Color, val navActiveInk: Color,
    val ok: Color, val okBg: Color, val warn: Color, val warnBg: Color, val bad: Color, val badBg: Color,
    val series: List<Color>,
    val radius: Dp, val radiusSm: Dp, val radiusPill: Dp,
    val navIsAccent: Boolean,
    val hasGradient: Boolean, val mainTop: Color, val mainBottom: Color,
) {
    /** Series colour [i] in order, wrapping when a chart has more series than the palette has colours. */
    fun series(i: Int): Color = series[((i % series.size) + series.size) % series.size]
}

private fun Long.c(): Color = Color(this)

fun UmcTokens.toPalette(): UmcPalette = UmcPalette(
    id = id, label = label,
    page = page.c(), surface = surface.c(), surface2 = surface2.c(), sidebar = sidebar.c(), card = card.c(),
    border = border.c(), chip = chip.c(), track = track.c(),
    ink = ink.c(), muted = muted.c(), faint = faint.c(),
    accent = accent.c(), accentInk = accentInk.c(), navActive = navActive.c(), navActiveInk = navActiveInk.c(),
    ok = ok.c(), okBg = okBg.c(), warn = warn.c(), warnBg = warnBg.c(), bad = bad.c(), badBg = badBg.c(),
    series = series.map { it.c() },
    radius = radius.dp, radiusSm = radiusSm.dp, radiusPill = radiusPill.dp,
    navIsAccent = navIsAccent,
    hasGradient = hasGradient, mainTop = mainTop.c(), mainBottom = mainBottom.c(),
)

object UmcPalettes {
    val overview: UmcPalette = UmcThemes.overview.toPalette()
    val analytics: UmcPalette = UmcThemes.analytics.toPalette()
    fun of(id: UmcThemeId): UmcPalette = if (id == UmcThemeId.ANALYTICS) analytics else overview
}

val LocalUmcPalette = compositionLocalOf { UmcPalettes.overview }

/**
 * The theme in force. A snapshot state, so anything that reads it (in composition, layout or draw)
 * redraws the moment [set] is called: switching theme needs no restart.
 */
object UmcThemeState {
    var id: UmcThemeId by mutableStateOf(UmcThemeId.DEFAULT)
        private set
    val palette: UmcPalette get() = UmcPalettes.of(id)
    fun set(theme: UmcThemeId) { id = theme }
}

/** Both themes are dark: Material is told so, and every role is filled from the palette. */
fun umcColorScheme(p: UmcPalette): ColorScheme = darkColorScheme(
    primary = p.accent, onPrimary = p.accentInk,
    primaryContainer = p.accent, onPrimaryContainer = p.accentInk,
    secondary = p.chip, onSecondary = p.ink, secondaryContainer = p.chip, onSecondaryContainer = p.ink,
    tertiary = p.series(2), onTertiary = p.mainTop,
    background = p.mainTop, onBackground = p.ink,
    surface = p.card, onSurface = p.ink,
    surfaceVariant = p.chip, onSurfaceVariant = p.muted, surfaceTint = p.accent,
    surfaceContainerLowest = p.mainTop, surfaceContainerLow = p.card, surfaceContainer = p.card,
    surfaceContainerHigh = p.surface2, surfaceContainerHighest = p.chip,
    outline = p.muted, outlineVariant = p.border,
    error = p.bad, onError = p.mainTop, errorContainer = p.badBg, onErrorContainer = p.bad,
    inverseSurface = p.ink, inverseOnSurface = p.mainTop, inversePrimary = p.accent,
    scrim = Color.Black,
)

/** Rounded corners from the radius tokens: cards 14/16 dp, small controls 8 dp. */
fun umcShapes(p: UmcPalette): Shapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp), small = RoundedCornerShape(p.radiusSm), medium = RoundedCornerShape(p.radiusSm + 2.dp),
    large = RoundedCornerShape(p.radius), extraLarge = RoundedCornerShape(p.radius),
)

/** The theme every screen sits in: Material colours, shapes and type from the chosen palette, plus [LocalUmcPalette]. */
@Composable
fun UmcTheme(theme: UmcThemeId, content: @Composable () -> Unit) {
    val p = UmcPalettes.of(theme)
    CompositionLocalProvider(LocalUmcPalette provides p) {
        MaterialTheme(colorScheme = umcColorScheme(p), shapes = umcShapes(p), typography = Sh.typography, content = content)
    }
}

/**
 * Palette shorthand for code that is not a composable (draw lambdas, helpers). Reads [UmcThemeState], so
 * anything composed or drawn with it redraws when the theme changes. Status colours are only ok/warn/bad;
 * chart colours are only [series], in order.
 */
object Dc {
    private val p: UmcPalette get() = UmcThemeState.palette
    val page: Color get() = p.page
    val surface: Color get() = p.surface
    val mainTop: Color get() = p.mainTop
    val mainBottom: Color get() = p.mainBottom
    val navActive: Color get() = p.navActive
    val navActiveInk: Color get() = p.navActiveInk
    val card: Color get() = p.card
    val line: Color get() = p.border
    val grid: Color get() = p.border
    val track: Color get() = p.track
    val chip: Color get() = p.chip
    val tx: Color get() = p.ink
    val mu: Color get() = p.muted
    val faint: Color get() = p.faint
    val accent: Color get() = p.accent
    val accentInk: Color get() = p.accentInk
    val ok: Color get() = p.ok
    val okBg: Color get() = p.okBg
    val warn: Color get() = p.warn
    val warnBg: Color get() = p.warnBg
    val bad: Color get() = p.bad
    val badBg: Color get() = p.badBg
    fun series(i: Int): Color = p.series(i)
    val radius: Dp get() = p.radius
    val radiusSm: Dp get() = p.radiusSm
}
