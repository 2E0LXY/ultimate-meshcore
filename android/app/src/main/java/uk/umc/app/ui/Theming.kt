package uk.umc.app.ui

import android.graphics.BitmapFactory
import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import uk.umc.app.AppState

/**
 * The background a page is drawn over, and the cards that sit on it.
 *
 * Pages are built from translucent cards floating over a background you choose, so the
 * app can be made to look like whatever suits: the plain system colours, a single colour,
 * a gradient, or one of your own photographs dimmed and blurred behind the text.
 */
enum class Background(val label: String, val blurb: String) {
    SYSTEM("System", "The plain look"),
    COLOUR("Colour", "One solid colour"),
    GRADIENT("Gradient", "Two colours blended"),
    PHOTO("Photo", "Your own picture, dimmed"),
}

/** Backgrounds to choose from, as a colour pair: a gradient runs from the first to the second. */
val backgroundPalette: List<Pair<String, Pair<Color, Color>>> = listOf(
    "Forest" to (Color(0xFF0B1F17) to Color(0xFF123A2A)),
    "Ocean" to (Color(0xFF07182B) to Color(0xFF123A5A)),
    "Dusk" to (Color(0xFF1A0E2B) to Color(0xFF3A1A4A)),
    "Ember" to (Color(0xFF2A0F0B) to Color(0xFF4A2412)),
    "Slate" to (Color(0xFF14181C) to Color(0xFF2A3038)),
    "Aurora" to (Color(0xFF071F22) to Color(0xFF2A1A4A)),
)

/**
 * Wraps a page in the chosen background. Everything drawn inside sits on top of it, so
 * cards read as glass over whatever is behind them.
 */
@Composable
fun Backdrop(content: @Composable () -> Unit) {
    val kind by AppState.background.collectAsState()
    val paletteIndex by AppState.backgroundColour.collectAsState()
    val photo by AppState.backgroundPhoto.collectAsState()
    val pair = backgroundPalette.getOrElse(paletteIndex) { backgroundPalette.first() }.second

    Box(Modifier.fillMaxSize()) {
        when (kind) {
            Background.SYSTEM -> Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background))
            Background.COLOUR -> Box(Modifier.fillMaxSize().background(pair.second))
            Background.GRADIENT -> Box(
                Modifier.fillMaxSize().background(
                    Brush.linearGradient(listOf(pair.first, pair.second), start = Offset.Zero, end = Offset.Infinite)
                )
            )
            Background.PHOTO -> {
                val ctx = LocalContext.current
                val bitmap = remember(photo) {
                    photo?.let {
                        runCatching {
                            ctx.contentResolver.openInputStream(Uri.parse(it)).use { s -> BitmapFactory.decodeStream(s) }
                        }.getOrNull()
                    }
                }
                if (bitmap != null) {
                    Image(
                        bitmap.asImageBitmap(), null,
                        Modifier.fillMaxSize().blur(18.dp), contentScale = ContentScale.Crop,
                    )
                    // dimmed, so text stays readable whatever the picture is
                    Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.45f)))
                } else {
                    Box(Modifier.fillMaxSize().background(pair.second))
                }
            }
        }
        content()
    }
}

/** True when the backdrop is something other than the plain system colours. */
@Composable
fun onGlass(): Boolean = AppState.background.collectAsState().value != Background.SYSTEM

/**
 * A card that reads as glass when there is a backdrop behind it, and as an ordinary
 * surface when there is not.
 */
@Composable
fun GlassCard(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val glass = onGlass()
    val shape = RoundedCornerShape(12.dp)
    val c = MaterialTheme.colorScheme
    // shadcn's card: a flat surface with a 1 dp border; over a photo or gradient it is frosted glass instead
    Box(
        modifier
            .clip(shape)
            .background(if (glass) Color.White.copy(alpha = 0.08f) else c.surface)
            .border(1.dp, if (glass) Color.White.copy(alpha = 0.14f) else c.outlineVariant, shape)
            .padding(16.dp),
        contentAlignment = Alignment.TopStart,
    ) { content() }
}
