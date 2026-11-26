package uk.umc.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import uk.umc.app.net.Lpp
import uk.umc.app.net.UmcNet

/** Sensors: the newest readings every repeater reports to UMC Net (battery, temperature, humidity and so on). */
@Composable
fun SensorsScreen() {
    val sets by UmcNet.sensors.collectAsState()
    val connected by UmcNet.connected.collectAsState()
    val list = sets.values.sortedBy { it.label.lowercase() }
    LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        if (list.isEmpty()) item {
            SectionCard("Sensors", if (connected) "waiting for a repeater to report" else "not connected to UMC Net") {
                Text(
                    "A repeater reports its sensors when they change, and at least every 15 minutes. " +
                        "Nothing has arrived yet. Join UMC Net from the UMC Net tile if you have not.",
                )
            }
        }
        items(list, key = { it.deviceId }) { set ->
            val quiet = System.currentTimeMillis() - set.atMs > 30 * 60_000L
            SectionCard(set.label, if (quiet) "quiet for ${agoMillis(set.atMs)}" else "updated ${agoMillis(set.atMs)}") {
                set.readings.forEach { r -> KeyValue(r.name + if (r.channel > 1) " #${r.channel}" else "", Lpp.format(r)) }
            }
        }
    }
}
