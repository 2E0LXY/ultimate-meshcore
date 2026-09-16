package uk.umc.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import uk.umc.app.AppState
import uk.umc.app.web.UmcWeb

/**
 * The full settings of any Ultimate MeshCore device on the same WiFi - repeater or client -
 * through its web interface: every command, plus firmware updates.
 */
@Composable
fun UmcDeviceScreen() {
    val scope = rememberCoroutineScope()
    var host by remember { mutableStateOf(AppState.webHost() ?: "") }
    var password by remember { mutableStateOf("") }
    var web by remember { mutableStateOf<UmcWeb?>(null) }
    var info by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    var busy by remember { mutableStateOf(false) }
    var command by remember { mutableStateOf("") }
    var log by remember { mutableStateOf(listOf<String>()) }

    fun push(line: String) {
        log = (log + line).takeLast(200)
    }

    fun run(vararg commands: String) {
        val w = web ?: return AppState.say("Sign in to the device first")
        busy = true
        scope.launch {
            runCatching { w.cli(commands.toList()) }
                .onSuccess { replies -> commands.forEachIndexed { i, c -> push("> $c"); push(replies.getOrElse(i) { "" }) } }
                .onFailure { push("error: ${it.message}") }
            busy = false
        }
    }

    LazyColumn(Modifier.fillMaxSize()) {
        item {
            SectionCard("Ultimate MeshCore device", "Manage a repeater or client over WiFi, exactly as the web page does.") {
                OutlinedTextField(host, { host = it }, Modifier.fillMaxWidth(), label = { Text("Address or IP") }, singleLine = true)
                OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), label = { Text("Admin password") }, singleLine = true)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = {
                        busy = true
                        scope.launch {
                            val w = UmcWeb(host.trim())
                            runCatching {
                                val i = w.info()
                                val map = LinkedHashMap<String, String>()
                                map["Name"] = i.optString("name")
                                map["Role"] = i.optString("role")
                                map["Board"] = i.optString("board")
                                map["Firmware"] = "${i.optString("fw")} ${i.optString("umc")} (${i.optString("commit")})"
                                map["Last restart"] = i.optString("reset", "-")
                                info = map
                                if (password.isNotBlank()) w.login(password)
                                web = w
                                push("Signed in to ${i.optString("name")}")
                            }.onFailure { push("error: ${it.message}") }
                            busy = false
                        }
                    }, enabled = host.isNotBlank() && !busy) { Text("Sign in") }
                    if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                }
                info.forEach { (k, v) -> KeyValue(k, v) }
            }
        }
        if (web != null) {
            item {
                SectionCard("Quick actions") {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        OutlinedButton(onClick = { run("get radio", "get tx", "stats-core", "stats-radio") }, Modifier.weight(1f)) { Text("Status") }
                        OutlinedButton(onClick = { run("get net.status") }, Modifier.weight(1f)) { Text("Network") }
                        OutlinedButton(onClick = { run("neighbors") }, Modifier.weight(1f)) { Text("Neighbours") }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        OutlinedButton(onClick = { run("update check") }, Modifier.weight(1f)) { Text("Check update") }
                        OutlinedButton(onClick = { run("get update.status") }, Modifier.weight(1f)) { Text("Update status") }
                        OutlinedButton(onClick = { run("update install") }, Modifier.weight(1f)) { Text("Install") }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        OutlinedButton(onClick = { run("advert") }, Modifier.weight(1f)) { Text("Advert") }
                        OutlinedButton(onClick = { run("clock", "time ${System.currentTimeMillis() / 1000}") }, Modifier.weight(1f)) { Text("Set clock") }
                        OutlinedButton(onClick = { run("reboot") }, Modifier.weight(1f)) { Text("Reboot") }
                    }
                }
            }
            item {
                SectionCard("Console", "Any command the device understands.") {
                    OutlinedTextField(command, { command = it }, Modifier.fillMaxWidth(), label = { Text("Command") }, singleLine = true)
                    Button(onClick = {
                        val c = command.trim()
                        command = ""
                        if (c.isNotEmpty()) run(c)
                    }) { Text("Send") }
                }
            }
            items(log.reversed()) { line ->
                Text(line, Modifier.padding(horizontal = 16.dp, vertical = 2.dp), style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
