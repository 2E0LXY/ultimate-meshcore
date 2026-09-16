package uk.umc.app.ui

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.delay
import uk.umc.app.AppState
import uk.umc.app.link.BleLink
import uk.umc.app.link.LinkKind
import uk.umc.app.link.LinkState
import uk.umc.app.link.LinkTarget

@SuppressLint("MissingPermission")
@Composable
fun ConnectScreen() {
    val context = LocalContext.current
    val saved by AppState.savedDevices.collectAsState()
    val state by AppState.linkState.collectAsState()
    var found by remember { mutableStateOf(listOf<Pair<String, String>>()) }   // name to address
    var scanning by remember { mutableStateOf(false) }
    var host by remember { mutableStateOf("") }
    var port by remember { mutableStateOf("5000") }

    val permissions = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S)
        arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
    else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)

    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        if (granted.values.all { it }) scanning = true else AppState.say("Bluetooth permission is needed to find radios")
    }

    LaunchedEffect(scanning) {
        if (!scanning) return@LaunchedEffect
        val adapter = BluetoothAdapter.getDefaultAdapter()
        val scanner = adapter?.bluetoothLeScanner
        if (scanner == null) {
            AppState.say("Bluetooth is off")
            scanning = false
            return@LaunchedEffect
        }
        val cb = object : ScanCallback() {
            override fun onScanResult(type: Int, result: ScanResult) {
                val name = result.device.name ?: result.scanRecord?.deviceName ?: return
                if (!name.startsWith(BleLink.NAME_PREFIX)) return
                if (found.none { it.second == result.device.address }) {
                    found = found + (name to result.device.address)
                }
            }
        }
        // Paired radios are usually what people want, so list them straight away.
        runCatching {
            adapter.bondedDevices.filter { it.name?.startsWith(BleLink.NAME_PREFIX) == true }
                .forEach { d -> if (found.none { it.second == d.address }) found = found + ((d.name ?: d.address) to d.address) }
        }
        scanner.startScan(null, ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), cb)
        delay(12000)
        runCatching { scanner.stopScan(cb) }
        scanning = false
    }

    LazyColumn(Modifier.fillMaxSize()) {
        item {
            SectionCard("Connection", when (val s = state) {
                is LinkState.Connected -> "Connected to ${s.what}"
                is LinkState.Connecting -> "Connecting to ${s.what}…"
                is LinkState.Failed -> "Not connected: ${s.reason}"
                else -> "Not connected"
            }) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { AppState.reconnect() }, enabled = AppState.target.value != null) { Text("Reconnect") }
                    OutlinedButton(onClick = { AppState.disconnect() }) { Text("Disconnect") }
                }
            }
        }
        if (saved.isNotEmpty()) {
            item {
                SectionCard("Your radios") {
                    saved.forEach { t ->
                        ListItem(
                            headlineContent = { Text(t.label) },
                            supportingContent = { Text(t.describe()) },
                            trailingContent = {
                                Row {
                                    TextButton(onClick = { AppState.connect(t) }) { Text("Connect") }
                                    TextButton(onClick = { AppState.forgetDevice(t) }) { Text("Forget") }
                                }
                            },
                        )
                    }
                }
            }
        }
        item {
            SectionCard("Bluetooth", "Pair with the PIN shown on the radio's screen.") {
                Button(onClick = {
                    val missing = permissions.any { ContextCompat.checkSelfPermission(context, it) != PackageManager.PERMISSION_GRANTED }
                    if (missing) ask.launch(permissions) else scanning = true
                }, enabled = !scanning) { Text(if (scanning) "Scanning…" else "Scan for radios") }
            }
        }
        items(found) { (name, address) ->
            ListItem(
                headlineContent = { Text(name) },
                supportingContent = { Text(address) },
                trailingContent = {
                    TextButton(onClick = {
                        AppState.connect(LinkTarget(LinkKind.BLUETOOTH, address, name))
                    }) { Text("Connect") }
                },
            )
        }
        item {
            SectionCard("WiFi", "An Ultimate MeshCore client or repeater on your network, port 5000.") {
                OutlinedTextField(host, { host = it }, label = { Text("Address, e.g. 192.168.1.50 or umc-node.local") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(port, { port = it }, label = { Text("Port") }, singleLine = true,
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = KeyboardType.Number))
                Button(onClick = {
                    if (host.isNotBlank()) AppState.connect(LinkTarget(LinkKind.WIFI, "${host.trim()}:${port.trim()}", host.trim()))
                }) { Text("Connect over WiFi") }
            }
        }
    }
}
