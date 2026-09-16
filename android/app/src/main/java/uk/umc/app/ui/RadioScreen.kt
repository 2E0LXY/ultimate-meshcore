package uk.umc.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import uk.umc.app.AppState

/** Regional presets, exactly as the firmware and other MeshCore apps use them. */
val PRESETS = listOf(
    Triple("EU/UK (Narrow)", listOf(869618L, 62500L), listOf(8, 8)),
    Triple("EU/UK (Medium Range)", listOf(869525L, 250000L), listOf(10, 5)),
    Triple("EU/UK (Long Range)", listOf(869525L, 250000L), listOf(11, 5)),
    Triple("US/Canada", listOf(910525L, 250000L), listOf(10, 5)),
    Triple("Australia/NZ", listOf(915800L, 250000L), listOf(10, 5)),
)

/** The radio's own settings: name, location, LoRa parameters and messaging behaviour. */
@Composable
fun RadioScreen() {
    val session by AppState.session.collectAsState()
    val s = session ?: return NotConnected()
    val self by s.self.collectAsState()
    val device by s.device.collectAsState()
    val scope = rememberCoroutineScope()
    val info = self ?: return Box(Modifier.fillMaxSize()) { CircularProgressIndicator(Modifier.align(androidx.compose.ui.Alignment.Center)) }

    var name by remember(info.name) { mutableStateOf(info.name) }
    var lat by remember(info.lat) { mutableStateOf(if (info.lat == 0.0) "" else "%.4f".format(info.lat)) }
    var lon by remember(info.lon) { mutableStateOf(if (info.lon == 0.0) "" else "%.4f".format(info.lon)) }
    var freq by remember(info.freqKhz) { mutableStateOf("%.3f".format(info.freqKhz / 1000.0)) }
    var bw by remember(info.bwKhz) { mutableStateOf("%.1f".format(info.bwKhz / 1000.0)) }
    var sf by remember(info.sf) { mutableStateOf(info.sf.toString()) }
    var cr by remember(info.cr) { mutableStateOf(info.cr.toString()) }
    var tx by remember(info.txPower) { mutableStateOf(info.txPower.toString()) }
    var pin by remember { mutableStateOf("") }

    LazyColumn(Modifier.fillMaxSize()) {
        item {
            SectionCard("Radio", "This node: ${device?.model ?: ""} ${device?.version ?: ""}") {
                Text("Presets", style = MaterialTheme.typography.labelLarge)
                PRESETS.forEach { (label, f, p) ->
                    OutlinedButton(onClick = {
                        freq = "%.3f".format(f[0] / 1000.0); bw = "%.1f".format(f[1] / 1000.0)
                        sf = p[0].toString(); cr = p[1].toString()
                    }, modifier = Modifier.fillMaxWidth()) { Text(label) }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedTextField(freq, { freq = it }, Modifier.weight(1f), label = { Text("MHz") }, singleLine = true)
                    OutlinedTextField(bw, { bw = it }, Modifier.weight(1f), label = { Text("kHz") }, singleLine = true)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedTextField(sf, { sf = it }, Modifier.weight(1f), label = { Text("SF") }, singleLine = true)
                    OutlinedTextField(cr, { cr = it }, Modifier.weight(1f), label = { Text("CR 4/x") }, singleLine = true)
                    OutlinedTextField(tx, { tx = it }, Modifier.weight(1f), label = { Text("dBm") }, singleLine = true)
                }
                Button(onClick = {
                    scope.launch {
                        runCatching {
                            s.setRadio(
                                (freq.toDouble() * 1000).toLong(), (bw.toDouble() * 1000).toLong(),
                                sf.toInt(), cr.toInt(), device?.repeatEnabled ?: false,
                            )
                            s.setTxPower(tx.toInt())
                        }.onSuccess { AppState.say("Radio updated") }.onFailure { AppState.say(it.message ?: "failed") }
                    }
                }, modifier = Modifier.fillMaxWidth()) { Text("Apply radio settings") }
                Text("Every node in a mesh must share frequency, bandwidth and spreading factor.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
            }
        }
        item {
            SectionCard("Identity") {
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("Node name") }, singleLine = true)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedTextField(lat, { lat = it }, Modifier.weight(1f), label = { Text("Latitude") }, singleLine = true)
                    OutlinedTextField(lon, { lon = it }, Modifier.weight(1f), label = { Text("Longitude") }, singleLine = true)
                }
                Button(onClick = {
                    scope.launch {
                        runCatching {
                            if (name.isNotBlank() && name != info.name) s.setName(name.trim())
                            val la = lat.toDoubleOrNull(); val lo = lon.toDoubleOrNull()
                            if (la != null && lo != null) s.setLocation(la, lo)
                        }.onSuccess { AppState.say("Saved") }.onFailure { AppState.say(it.message ?: "failed") }
                    }
                }, modifier = Modifier.fillMaxWidth()) { Text("Save identity") }
                KeyValue("Public key", info.publicKey.take(16) + "…")
            }
        }
        item {
            SectionCard("Messaging", "How this radio handles adverts, contacts and confirmations.") {
                var multi by remember(info.multiAcks) { mutableStateOf(info.multiAcks != 0) }
                var shareLoc by remember(info.advertLocPolicy) { mutableStateOf(info.advertLocPolicy != 0) }
                var manual by remember(info.manualAddContacts) { mutableStateOf(info.manualAddContacts != 0) }
                SwitchRow("Extra delivery confirmations", multi) { multi = it }
                SwitchRow("Share location in adverts", shareLoc) { shareLoc = it }
                SwitchRow("Add new contacts manually", manual) { manual = it }
                Button(onClick = {
                    scope.launch {
                        runCatching {
                            s.setOtherParams(if (manual) 1 else 0, info.telemetryMode, if (shareLoc) 1 else 0, if (multi) 1 else 0)
                        }.onSuccess { AppState.say("Saved") }.onFailure { AppState.say(it.message ?: "failed") }
                    }
                }, modifier = Modifier.fillMaxWidth()) { Text("Save messaging settings") }
            }
        }
        item {
            SectionCard("Bluetooth pairing", "0 gives a new random PIN at every start, shown on the radio's screen.") {
                OutlinedTextField(pin, { pin = it }, Modifier.fillMaxWidth(), label = { Text("Fixed PIN (6 digits, or 0)") }, singleLine = true)
                Button(onClick = {
                    val v = pin.toLongOrNull() ?: return@Button AppState.say("Enter a number")
                    scope.launch {
                        runCatching { s.setBlePin(v) }.onSuccess { AppState.say("Saved - applies after a restart") }
                            .onFailure { AppState.say(it.message ?: "failed") }
                    }
                }) { Text("Save PIN") }
            }
        }
        item {
            SectionCard("Radio actions") {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { scope.launch { runCatching { s.telemetry(null) }.onSuccess { AppState.say(it.joinToString { v -> "${v.name} ${v.value}" }) } } }) { Text("My telemetry") }
                    OutlinedButton(onClick = { scope.launch { runCatching { s.reboot() }.onSuccess { AppState.say("Rebooting") } } }) { Text("Reboot radio") }
                }
            }
        }
    }
}

@Composable
fun SwitchRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
        Text(label)
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
