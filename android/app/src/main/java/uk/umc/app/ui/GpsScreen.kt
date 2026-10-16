package uk.umc.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import uk.umc.app.AppState

/**
 * Where the radio is, and what that puts within reach.
 *
 * Everything here comes from the radio itself - this phone's own location is never read,
 * so the app needs no location permission.
 */
@Composable
fun GpsScreen() {
    val s by AppState.session.collectAsState()
    val session = s ?: return NotConnected()
    val me by session.self.collectAsState()
    val contacts by session.contacts.collectAsState()
    val scope = rememberCoroutineScope()

    var editing by remember { mutableStateOf(false) }
    var lat by remember { mutableStateOf("") }
    var lon by remember { mutableStateOf("") }

    val set = me?.let { it.lat != 0.0 || it.lon != 0.0 } ?: false

    // every node that shares a position, nearest first
    val placed = remember(contacts, me) {
        val m = me
        if (m == null || !set) emptyList()
        else contacts.filter { it.lat != 0.0 || it.lon != 0.0 }
            .map { it to distanceBetween(m.lat, m.lon, it.lat, it.lon) }
            .sortedBy { it.second }
    }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Text("RADIO POSITION", style = MaterialTheme.typography.labelSmall,
                         color = MaterialTheme.colorScheme.outline)
                    Text(
                        if (set) "%.5f, %.5f".format(me!!.lat, me!!.lon) else "Not set",
                        style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold,
                    )
                    Text(
                        if (set) "What it tells the mesh, and where the map centres"
                        else "Without one the map has nowhere to centre and distances cannot be worked out",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(onClick = {
                        lat = me?.lat?.takeIf { set }?.toString() ?: ""
                        lon = me?.lon?.takeIf { set }?.toString() ?: ""
                        editing = true
                    }) { Text(if (set) "Change it" else "Set it") }
                }
            }
        }

        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Text("SHARING", style = MaterialTheme.typography.labelSmall,
                         color = MaterialTheme.colorScheme.outline)
                    Text(
                        if (me?.advertLocPolicy == 0) "Kept to yourself" else "Sent with adverts",
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        if (me?.advertLocPolicy == 0)
                            "Others cannot place this node on their map."
                        else "Others can place this node on their map.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        }

        item {
            Text(
                if (placed.isEmpty()) "Nodes nearby" else "Nodes nearby (${placed.size})",
                style = MaterialTheme.typography.titleSmall,
            )
        }

        if (placed.isEmpty()) {
            item {
                GlassCard(Modifier.fillMaxWidth()) {
                    Text(
                        if (!set) "Set this radio's position to see how far away the others are."
                        else "No node has shared a position yet.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        } else {
            placed.forEach { (c, metres) ->
                item {
                    GlassCard(Modifier.fillMaxWidth()) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(c.name, style = MaterialTheme.typography.titleSmall)
                                Text(
                                    "${c.typeName} · ${pathLabel(c)}",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.outline,
                                )
                            }
                            Text(
                                if (metres < 1000) "%.0f m".format(metres) else "%.1f km".format(metres / 1000),
                                style = MaterialTheme.typography.titleMedium,
                            )
                        }
                    }
                }
            }
        }
    }

    if (editing) {
        AlertDialog(
            onDismissRequest = { editing = false },
            title = { Text("Radio position") },
            text = {
                Column {
                    Text(
                        "Degrees, as a decimal. South and west are negative.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(lat, { lat = it }, Modifier.fillMaxWidth(), singleLine = true,
                                      label = { Text("Latitude") })
                    Spacer(Modifier.height(6.dp))
                    OutlinedTextField(lon, { lon = it }, Modifier.fillMaxWidth(), singleLine = true,
                                      label = { Text("Longitude") })
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val la = lat.trim().toDoubleOrNull()
                    val lo = lon.trim().toDoubleOrNull()
                    if (la == null || lo == null || la < -90 || la > 90 || lo < -180 || lo > 180) {
                        AppState.say("Latitude -90 to 90, longitude -180 to 180")
                    } else {
                        editing = false
                        scope.launch {
                            runCatching { session.setLocation(la, lo) }
                                .onSuccess { AppState.say("Position saved") }
                                .onFailure { AppState.say(it.message ?: "failed") }
                        }
                    }
                }) { Text("Save") }
            },
            dismissButton = { TextButton(onClick = { editing = false }) { Text("Cancel") } },
        )
    }
}

/** Great-circle distance in metres. */
private fun distanceBetween(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val r = 6371000.0
    val p = Math.PI / 180
    val a = 0.5 - Math.cos((lat2 - lat1) * p) / 2 +
        Math.cos(lat1 * p) * Math.cos(lat2 * p) * (1 - Math.cos((lon2 - lon1) * p)) / 2
    return 2 * r * Math.asin(Math.sqrt(a))
}
