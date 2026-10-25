package uk.umc.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Shapes
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * The app's design system, after shadcn/ui: Tailwind's colour scale, 8 dp rounding, 1 dp borders,
 * 14 sp text, and a small set of components (button, card, badge, alert, separator). shadcn itself is a
 * web (React) library, so this is the same design written for Compose, not the library.
 */
object Sh {
    // Tailwind green and zinc, tinted a little toward green for the dark theme
    val green500 = Color(0xFF22C55E); val green600 = Color(0xFF16A34A); val green950 = Color(0xFF052E16); val green300 = Color(0xFF86EFAC)
    val red500 = Color(0xFFEF4444); val red600 = Color(0xFFDC2626); val amber400 = Color(0xFFFBBF24)
    val zinc50 = Color(0xFFFAFAFA); val zinc100 = Color(0xFFF4F4F5); val zinc200 = Color(0xFFE4E4E7); val zinc500 = Color(0xFF71717A); val zinc950 = Color(0xFF09090B)

    val darkBg = Color(0xFF08100C); val darkCard = Color(0xFF0D1511); val darkMuted = Color(0xFF131C17); val darkBorder = Color(0xFF1F2D27); val darkMutedFg = Color(0xFF8AA096); val darkFg = Color(0xFFE9F7EF)

    val radius = 8.dp
    val cardRadius = 12.dp

    fun dark(): ColorScheme = darkColorScheme(
        primary = green500, onPrimary = green950, primaryContainer = Color(0xFF0F2A1B), onPrimaryContainer = green300,
        secondary = darkMuted, onSecondary = darkFg, secondaryContainer = darkMuted, onSecondaryContainer = darkFg,
        tertiary = Color(0xFF38BDF8), onTertiary = Color(0xFF082F49),
        background = darkBg, onBackground = darkFg, surface = darkCard, onSurface = darkFg,
        surfaceVariant = darkMuted, onSurfaceVariant = darkMutedFg, surfaceTint = green500,
        surfaceContainerLowest = darkBg, surfaceContainerLow = darkCard, surfaceContainer = darkCard, surfaceContainerHigh = darkMuted, surfaceContainerHighest = darkMuted,
        outline = darkMutedFg, outlineVariant = darkBorder, error = red500, onError = Color.White,
    )

    fun light(): ColorScheme = lightColorScheme(
        primary = green600, onPrimary = zinc50, primaryContainer = Color(0xFFDCFCE7), onPrimaryContainer = Color(0xFF14532D),
        secondary = zinc100, onSecondary = zinc950, secondaryContainer = zinc100, onSecondaryContainer = zinc950,
        tertiary = Color(0xFF0284C7), onTertiary = Color.White,
        background = Color.White, onBackground = zinc950, surface = Color.White, onSurface = zinc950,
        surfaceVariant = zinc100, onSurfaceVariant = zinc500, surfaceTint = green600,
        surfaceContainerLowest = Color.White, surfaceContainerLow = Color(0xFFFAFAFA), surfaceContainer = zinc100, surfaceContainerHigh = zinc100, surfaceContainerHighest = zinc200,
        outline = zinc500, outlineVariant = zinc200, error = red600, onError = Color.White,
    )

    val shapes = Shapes(
        extraSmall = RoundedCornerShape(6.dp), small = RoundedCornerShape(radius), medium = RoundedCornerShape(10.dp),
        large = RoundedCornerShape(cardRadius), extraLarge = RoundedCornerShape(cardRadius),
    )

    // Tailwind's text scale: text-xs 12, text-sm 14, text-base 16, text-xl 20, text-2xl 24; semibold headings
    val typography = Typography(
        headlineLarge = TextStyle(fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.5).sp),
        headlineMedium = TextStyle(fontSize = 24.sp, lineHeight = 30.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.4).sp),
        headlineSmall = TextStyle(fontSize = 20.sp, lineHeight = 26.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.3).sp),
        titleLarge = TextStyle(fontSize = 20.sp, lineHeight = 26.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.3).sp),
        titleMedium = TextStyle(fontSize = 16.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold),
        titleSmall = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.SemiBold),
        bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 24.sp),
        bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
        bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 16.sp),
        labelLarge = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.Medium),
        labelMedium = TextStyle(fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.Medium),
        labelSmall = TextStyle(fontSize = 11.sp, lineHeight = 14.sp, fontWeight = FontWeight.Medium),
    )
}

/** The theme every screen sits in. Follows the phone's light or dark setting. */
@Composable
fun ShadTheme(dark: Boolean, content: @Composable () -> Unit) {
    androidx.compose.material3.MaterialTheme(colorScheme = if (dark) Sh.dark() else Sh.light(), shapes = Sh.shapes, typography = Sh.typography, content = content)
}

enum class ShVariant { Default, Secondary, Outline, Ghost, Destructive }

/** shadcn's button: Default (green), Secondary, Outline, Ghost and Destructive, 36 dp tall, rounded-md. */
@Composable
fun ShButton(
    onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, variant: ShVariant = ShVariant.Default,
    content: @Composable RowScope.() -> Unit,
) {
    val c = MaterialTheme.colorScheme
    val pad = PaddingValues(horizontal = 16.dp, vertical = 8.dp)
    val m = modifier.heightIn(min = 36.dp)
    val shape = MaterialTheme.shapes.small
    when (variant) {
        ShVariant.Default -> Button(onClick, m, enabled, shape = shape, colors = ButtonDefaults.buttonColors(containerColor = c.primary, contentColor = c.onPrimary), contentPadding = pad, content = content)
        ShVariant.Secondary -> Button(onClick, m, enabled, shape = shape, colors = ButtonDefaults.buttonColors(containerColor = c.secondary, contentColor = c.onSecondary), contentPadding = pad, content = content)
        ShVariant.Destructive -> Button(onClick, m, enabled, shape = shape, colors = ButtonDefaults.buttonColors(containerColor = c.error, contentColor = c.onError), contentPadding = pad, content = content)
        ShVariant.Outline -> OutlinedButton(onClick, m, enabled, shape = shape, border = BorderStroke(1.dp, c.outlineVariant), colors = ButtonDefaults.outlinedButtonColors(contentColor = c.onSurface), contentPadding = pad, content = content)
        ShVariant.Ghost -> TextButton(onClick, m, enabled, shape = shape, colors = ButtonDefaults.textButtonColors(contentColor = c.onSurface), contentPadding = pad, content = content)
    }
}

/** shadcn's card: a bordered surface with a title and a description above its content. */
@Composable
fun ShCard(modifier: Modifier = Modifier, title: String? = null, description: String? = null, content: @Composable ColumnScope.() -> Unit) {
    val c = MaterialTheme.colorScheme
    Surface(modifier.fillMaxWidth(), shape = MaterialTheme.shapes.large, color = c.surface, contentColor = c.onSurface, border = BorderStroke(1.dp, c.outlineVariant)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (title != null || description != null) {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    if (title != null) Text(title, style = MaterialTheme.typography.titleMedium)
                    if (description != null) Text(description, style = MaterialTheme.typography.bodySmall, color = c.onSurfaceVariant)
                }
            }
            content()
        }
    }
}

enum class ShBadgeKind { Default, Secondary, Outline, Destructive, Success, Warning }

/** shadcn's badge: a small rounded label. */
@Composable
fun ShBadge(text: String, modifier: Modifier = Modifier, kind: ShBadgeKind = ShBadgeKind.Secondary) {
    val c = MaterialTheme.colorScheme
    val (bg, fg, border) = when (kind) {
        ShBadgeKind.Default -> Triple(c.primary, c.onPrimary, Color.Transparent)
        ShBadgeKind.Secondary -> Triple(c.secondary, c.onSecondary, Color.Transparent)
        ShBadgeKind.Outline -> Triple(Color.Transparent, c.onSurface, c.outlineVariant)
        ShBadgeKind.Destructive -> Triple(c.error.copy(alpha = 0.15f), c.error, Color.Transparent)
        ShBadgeKind.Success -> Triple(Sh.green500.copy(alpha = 0.15f), Sh.green500, Color.Transparent)
        ShBadgeKind.Warning -> Triple(Sh.amber400.copy(alpha = 0.15f), Sh.amber400, Color.Transparent)
    }
    Surface(modifier, shape = RoundedCornerShape(99.dp), color = bg, contentColor = fg, border = if (border == Color.Transparent) null else BorderStroke(1.dp, border)) {
        Text(text, Modifier.padding(horizontal = 10.dp, vertical = 2.dp), style = MaterialTheme.typography.labelSmall)
    }
}

/** shadcn's alert: a short notice with a title. */
@Composable
fun ShAlert(title: String, text: String? = null, modifier: Modifier = Modifier, destructive: Boolean = false) {
    val c = MaterialTheme.colorScheme
    val tone = if (destructive) c.error else c.onSurface
    Surface(modifier.fillMaxWidth(), shape = MaterialTheme.shapes.small, color = Color.Transparent, border = BorderStroke(1.dp, if (destructive) c.error.copy(alpha = 0.5f) else c.outlineVariant)) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall, color = tone)
            if (text != null) Text(text, style = MaterialTheme.typography.bodySmall, color = if (destructive) c.error.copy(alpha = 0.9f) else c.onSurfaceVariant)
        }
    }
}

/** shadcn's separator. */
@Composable
fun ShSeparator(modifier: Modifier = Modifier) {
    HorizontalDivider(modifier, color = MaterialTheme.colorScheme.outlineVariant)
}

/** A label and its value on one line, for the table-like lists the app prefers to prose. */
@Composable
fun ShRow(label: String, value: String, modifier: Modifier = Modifier, valueColor: Color = Color.Unspecified) {
    Row(modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(120.dp))
        Text(value, style = MaterialTheme.typography.bodyMedium, color = valueColor, modifier = Modifier.weight(1f))
    }
}
