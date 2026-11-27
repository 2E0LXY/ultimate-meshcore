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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.Typography
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import com.composables.icons.lucide.Info
import com.composables.icons.lucide.Lucide
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * The app's component kit, after shadcn/ui: 1 dp borders, 14 sp text, and a small set of components
 * (button, card, badge, alert, separator). Colours and radii come from the active UMC theme palette
 * (UmcPalette.kt, from docs/umc/theme/tokens.json); this object only holds the type scale.
 */
object Sh {
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

/** The theme every screen sits in: one of the two UMC themes, chosen in Look > Appearance. */
@Composable
fun ShadTheme(theme: UmcThemeId, content: @Composable () -> Unit) = UmcTheme(theme, content)

enum class ShVariant { Default, Secondary, Outline, Ghost, Destructive }

/** The button set: Default (accent), Secondary (chip fill with a border), Outline, Ghost and Destructive, 36 dp tall, small radius. */
@Composable
fun ShButton(
    onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, variant: ShVariant = ShVariant.Default,
    content: @Composable RowScope.() -> Unit,
) {
    val c = MaterialTheme.colorScheme
    val p = LocalUmcPalette.current
    val pad = PaddingValues(horizontal = 16.dp, vertical = 8.dp)
    val m = modifier.heightIn(min = 36.dp)
    val shape = MaterialTheme.shapes.small
    when (variant) {
        ShVariant.Default -> Button(onClick, m, enabled, shape = shape, colors = ButtonDefaults.buttonColors(containerColor = p.accent, contentColor = p.accentInk), contentPadding = pad, content = content)
        ShVariant.Secondary -> Button(onClick, m, enabled, shape = shape, colors = ButtonDefaults.buttonColors(containerColor = p.chip, contentColor = p.ink), border = BorderStroke(1.dp, p.border), contentPadding = pad, content = content)
        ShVariant.Destructive -> Button(onClick, m, enabled, shape = shape, colors = ButtonDefaults.buttonColors(containerColor = p.bad, contentColor = p.mainTop), contentPadding = pad, content = content)
        ShVariant.Outline -> OutlinedButton(onClick, m, enabled, shape = shape, border = BorderStroke(1.dp, c.outlineVariant), colors = ButtonDefaults.outlinedButtonColors(contentColor = c.onSurface), contentPadding = pad, content = content)
        ShVariant.Ghost -> TextButton(onClick, m, enabled, shape = shape, colors = ButtonDefaults.textButtonColors(contentColor = c.onSurface), contentPadding = pad, content = content)
    }
}

/**
 * The card: `card` fill, 1 dp `border`, the theme's radius. The header is an optional small icon, the title (600)
 * and an optional info icon at the right (its [info] text is the accessibility description), then the description.
 */
@Composable
fun ShCard(
    modifier: Modifier = Modifier, title: String? = null, description: String? = null,
    icon: ImageVector? = null, info: String? = null, content: @Composable ColumnScope.() -> Unit,
) {
    val c = MaterialTheme.colorScheme
    val p = LocalUmcPalette.current
    Surface(modifier.fillMaxWidth(), shape = MaterialTheme.shapes.large, color = p.card, contentColor = p.ink, border = BorderStroke(1.dp, p.border)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (title != null || description != null) {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    if (title != null) Row(verticalAlignment = Alignment.CenterVertically) {
                        if (icon != null) { Icon(icon, null, Modifier.size(16.dp), tint = p.muted); Spacer(Modifier.width(8.dp)) }
                        Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        if (info != null) Icon(Lucide.Info, info, Modifier.size(16.dp), tint = p.muted)
                    }
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
    val p = LocalUmcPalette.current
    val (bg, fg, border) = when (kind) {
        ShBadgeKind.Default -> Triple(p.accent, p.accentInk, Color.Transparent)
        ShBadgeKind.Secondary -> Triple(c.secondary, c.onSecondary, Color.Transparent)
        ShBadgeKind.Outline -> Triple(Color.Transparent, c.onSurface, c.outlineVariant)
        ShBadgeKind.Destructive -> Triple(p.badBg, p.bad, Color.Transparent)
        ShBadgeKind.Success -> Triple(p.okBg, p.ok, Color.Transparent)
        ShBadgeKind.Warning -> Triple(p.warnBg, p.warn, Color.Transparent)
    }
    Surface(modifier, shape = RoundedCornerShape(p.radiusPill), color = bg, contentColor = fg, border = if (border == Color.Transparent) null else BorderStroke(1.dp, border)) {
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
