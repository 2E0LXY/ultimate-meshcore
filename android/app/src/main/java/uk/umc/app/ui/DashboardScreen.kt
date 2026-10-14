package uk.umc.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import uk.umc.app.AppState
import uk.umc.app.proto.MeshSession

private val good = Color(0xFF2E7D32)
private val warn = Color(0xFFEF6C00)
private val bad = Color(0xFFC62828)

/**
 * Everything about the radio at a glance, as tiles: what it is, how it is powered, how it
 * is connected, what it is tuned to, where it thinks it is, and what has been heard. The
 * things you reach for often sit underneath as their own tiles.
 */
@Composable
fun DashboardScreen(onOpen: (String) -> Unit) {
    val s by AppState.session.collectAsState()
    val session = s ?: return NotConnected()
    val device by session.device.collectAsState()
    val me by session.self.collectAsState()
    val contacts by session.contacts.collectAsState()
    val messages by session.messages.collectAsState()
    var battery by remember { mutableStateOf<Int?>(null) }
    LaunchedEffect(session) {
        runCatching { session.battery() }.onSuccess { battery = it.first }
    }
    val target by AppState.target.collectAsState()
    val scope = rememberCoroutineScope()

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Text(me?.name ?: "Radio", style = MaterialTheme.typography.headlineSmall,
                         fontWeight = FontWeight.Bold)
                    Text(
                        listOfNotNull(device?.model, device?.version).joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                val mv = battery
                val pct = mv?.let { ((it - 3300) * 100 / 900).coerceIn(0, 100) }
                Tile(
                    Modifier.weight(1f), Icons.Filled.BatteryFull, "BATTERY",
                    pct?.let { "$it%" } ?: "—",
                    mv?.let { "${it / 1000}.${(it % 1000) / 10}V" } ?: "no reading",
                    when { pct == null -> MaterialTheme.colorScheme.outline
                           pct < 20 -> bad
                           pct < 40 -> warn
                           else -> good },
                )
                Tile(
                    Modifier.weight(1f), Icons.Filled.Wifi, "LINK",
                    target?.kind?.name?.lowercase()?.replaceFirstChar { it.uppercase() } ?: "—",
                    target?.address ?: "", good,
                )
            }
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Tile(
                    Modifier.weight(1f).clickable { onOpen("radio") }, Icons.Filled.Podcasts, "RADIO",
                    me?.let { "%.3f".format(it.freqKhz / 1000.0) } ?: "—",
                    me?.let { "SF${it.sf} · ${it.bwKhz / 1000} kHz · CR ${it.cr}" } ?: "",
                    MaterialTheme.colorScheme.primary,
                )
                val fix = me?.let { it.lat != 0.0 || it.lon != 0.0 } ?: false
                Tile(
                    Modifier.weight(1f).clickable { onOpen("map") }, Icons.Filled.LocationOn, "POSITION",
                    if (fix) "Set" else "None",
                    me?.let { if (fix) "%.3f, %.3f".format(it.lat, it.lon) else "not shared" } ?: "",
                    if (fix) good else MaterialTheme.colorScheme.outline,
                )
            }
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Tile(
                    Modifier.weight(1f).clickable { onOpen("contacts") }, Icons.Filled.Group, "NODES",
                    contacts.size.toString(),
                    contacts.count { it.hops == 0 }.toString() + " direct",
                    MaterialTheme.colorScheme.primary,
                )
                val incoming = messages.count { !it.outgoing }
                Tile(
                    Modifier.weight(1f).clickable { onOpen("chats") }, Icons.Filled.Chat, "MESSAGES",
                    incoming.toString(),
                    "${messages.size} kept",
                    if (incoming > 0) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline,
                )
            }
        }

        item {
            ActionTile(Icons.Filled.Campaign, "Send advert", "Let other nodes find this radio") {
                scope.launch {
                    runCatching { session.advert(false) }
                        .onSuccess { AppState.say("Advert sent") }
                        .onFailure { AppState.say(it.message ?: "failed") }
                }
            }
        }
        item {
            ActionTile(Icons.Filled.Sensors, "Flood advert", "Repeaters pass it on across the mesh") {
                scope.launch {
                    runCatching { session.advert(true) }
                        .onSuccess { AppState.say("Flood advert sent") }
                        .onFailure { AppState.say(it.message ?: "failed") }
                }
            }
        }
        item {
            ActionTile(Icons.Filled.Tune, "Appearance", "Background, cards and delivery marks") { onOpen("look") }
        }
    }
}

@Composable
private fun Tile(
    modifier: Modifier = Modifier,
    icon: ImageVector,
    label: String,
    value: String,
    note: String,
    colour: Color,
) {
    GlassCard(modifier) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(icon, null, Modifier.size(16.dp), tint = colour)
                Spacer(Modifier.width(6.dp))
                Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
            }
            Spacer(Modifier.height(4.dp))
            Text(value, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = colour)
            if (note.isNotEmpty()) {
                Text(note, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
            }
        }
    }
}

@Composable
private fun ActionTile(icon: ImageVector, title: String, blurb: String, onClick: () -> Unit) {
    GlassCard(Modifier.fillMaxWidth().clickable { onClick() }) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, null, tint = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleSmall)
                Text(blurb, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
            }
            Icon(Icons.Filled.ChevronRight, null, tint = MaterialTheme.colorScheme.outline)
        }
    }
}
