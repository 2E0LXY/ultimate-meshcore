package uk.umc.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.composables.icons.lucide.Activity
import com.composables.icons.lucide.ChartPie
import com.composables.icons.lucide.Download
import com.composables.icons.lucide.Globe
import com.composables.icons.lucide.Hash
import com.composables.icons.lucide.House
import com.composables.icons.lucide.Thermometer
import com.composables.icons.lucide.LocateFixed
import com.composables.icons.lucide.Lucide
import com.composables.icons.lucide.Map
import com.composables.icons.lucide.MapPin
import com.composables.icons.lucide.MessageSquare
import com.composables.icons.lucide.Radio
import com.composables.icons.lucide.Settings
import com.composables.icons.lucide.SlidersHorizontal
import com.composables.icons.lucide.Users
import com.composables.icons.lucide.Wifi

/** Everywhere the app can go: the Home tiles and the menu at the top right list these. */
enum class Dest(val label: String, val icon: ImageVector) {
    HOME("Home", Lucide.House),
    DASHBOARD("Dashboard", Lucide.ChartPie),
    CHATS("Messages", Lucide.MessageSquare),
    CONTACTS("Contacts", Lucide.Users),
    CHANNELS("Channels", Lucide.Hash),
    MAP("Map", Lucide.Map),
    SPECTRUM("Spectrum", Lucide.Activity),
    GPS("GPS", Lucide.LocateFixed),
    RADIO("Radio", Lucide.Settings),
    DEVICE("Device", Lucide.Wifi),
    SENSORS("Sensors", Lucide.Thermometer),
    NET("UMC Net", Lucide.Globe),
    RADIOS("Radios", Lucide.Radio),
    LOOK("Appearance", Lucide.SlidersHorizontal),
    GEOFENCES("Geofences", Lucide.MapPin),
    BACKUP("Backup", Lucide.Download),
}

/** The first screen: a grid of square tiles, two or three across depending on the width. */
@Composable
fun HomeScreen(onOpen: (Dest) -> Unit) {
    val glass = onGlass()
    val tiles = Dest.entries.filter { it != Dest.HOME }
    LazyVerticalGrid(
        columns = GridCells.Adaptive(104.dp),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        items(tiles) { d -> HomeTile(d, glass) { onOpen(d) } }
    }
}

@Composable
private fun HomeTile(d: Dest, glass: Boolean, onClick: () -> Unit) {
    val c = MaterialTheme.colorScheme
    val shape = MaterialTheme.shapes.large
    Surface(
        Modifier.aspectRatio(1f).clip(shape).clickable(onClick = onClick),
        shape = shape,
        color = if (glass) Color.White.copy(alpha = 0.08f) else Dc.card,
        contentColor = if (glass) Color.White else Dc.tx,
        border = BorderStroke(1.dp, if (glass) Color.White.copy(alpha = 0.14f) else Dc.line),
    ) {
        Column(Modifier.fillMaxSize().padding(8.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Icon(d.icon, contentDescription = null, modifier = Modifier.size(32.dp), tint = if (glass) Color.White else Dc.accent)
            Spacer(Modifier.height(8.dp))
            Text(d.label, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, textAlign = TextAlign.Center, maxLines = 2)
        }
    }
}
