package uk.umc.app.ui

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import uk.umc.app.AppState
import uk.umc.app.tools.GeoAlerts
import uk.umc.app.tools.Geo
import uk.umc.app.tools.Fences
import android.content.pm.PackageManager
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat

/**
 * Circles that alert you when a contact's reported position crosses them. Positions come from the
 * radio's contact list; this phone's own location is never read.
 */
@Composable
fun GeofenceScreen() {
    val fences by GeoAlerts.fences.collectAsState()
    val events by GeoAlerts.events.collectAsState()
    val session by AppState.session.collectAsState()
    val selfInfo by (session?.self ?: remember { kotlinx.coroutines.flow.MutableStateFlow<uk.umc.app.proto.SelfInfo?>(null) }).collectAsState()
    val self = selfInfo

    var name by remember { mutableStateOf("") }
    var lat by remember { mutableStateOf("") }
    var lon by remember { mutableStateOf("") }
    var radius by remember { mutableStateOf("500") }

    val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    val number = KeyboardOptions(keyboardType = KeyboardType.Decimal)
    // ask once when the screen opens, so alerts are not silently dropped for want of the permission
    val ctx = LocalContext.current
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("New geofence", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "You get a notification when a contact enters or leaves the circle. A node must be 10% past the edge to count, " +
                            "and each node and fence alerts at most once a minute. A node first seen inside does not alert.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                    OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("Name") }, singleLine = true)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(lat, { lat = it }, Modifier.weight(1f), label = { Text("Latitude") }, singleLine = true, keyboardOptions = number)
                        OutlinedTextField(lon, { lon = it }, Modifier.weight(1f), label = { Text("Longitude") }, singleLine = true, keyboardOptions = number)
                    }
                    OutlinedTextField(radius, { radius = it }, Modifier.fillMaxWidth(), label = { Text("Radius (metres)") }, singleLine = true, keyboardOptions = number)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        ShButton(onClick = {
                            val la = Fences.parseNumber(lat); val lo = Fences.parseNumber(lon); val r = Fences.parseNumber(radius)
                            if (la == null || lo == null || r == null) AppState.say("Latitude, longitude and radius must be numbers")
                            else {
                                val err = GeoAlerts.add(name, la, lo, r)
                                if (err != null) AppState.say(err.replaceFirstChar { it.uppercase() })
                                else {
                                    name = ""
                                    if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                                }
                            }
                        }) { Text("Add") }
                        ShButton(variant = ShVariant.Outline, enabled = self != null && Geo.validPosition(self.lat, self.lon), onClick = {
                            self?.let { lat = "%.6f".format(java.util.Locale.ROOT, it.lat); lon = "%.6f".format(java.util.Locale.ROOT, it.lon) }
                        }) { Text("Use radio position") }
                    }
                }
            }
        }
        item { Text("Fences", style = MaterialTheme.typography.titleMedium) }
        if (fences.isEmpty()) item { Text("None yet", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline) }
        items(fences, key = { it.id }) { f ->
            GlassCard(Modifier.fillMaxWidth()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(f.name, fontWeight = FontWeight.Bold)
                        Text("%.5f, %.5f · %s".format(java.util.Locale.ROOT, f.lat, f.lon, radiusText(f.radiusM)),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
                    }
                    ShButton(variant = ShVariant.Ghost, onClick = { GeoAlerts.remove(f.id) }) { Text("Delete") }
                }
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("History (last ${events.size})", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                if (events.isNotEmpty()) ShButton(variant = ShVariant.Outline, onClick = { GeoAlerts.clearEvents() }) { Text("Clear") }
            }
        }
        if (events.isEmpty()) item { Text("No crossings yet", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline) }
        items(events.asReversed()) { e ->
            Column {
                Text(e.summary, style = MaterialTheme.typography.bodyMedium)
                Text(agoMillis(e.atMs) + " ago", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
            }
        }
    }
}

private fun radiusText(m: Double) = if (m >= 1000) "%.1f km".format(java.util.Locale.ROOT, m / 1000) else "${m.toLong()} m"
