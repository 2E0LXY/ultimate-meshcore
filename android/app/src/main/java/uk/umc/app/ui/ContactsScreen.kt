package uk.umc.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import uk.umc.app.AppState
import uk.umc.app.proto.Contact
import uk.umc.app.proto.MeshSession

/** Everyone the radio knows, and everything you can do with them over the mesh. */
@Composable
fun ContactsScreen(onMessage: (String) -> Unit, onMap: (Contact) -> Unit) {
    val session by AppState.session.collectAsState()
    val s = session ?: return NotConnected()
    val contacts by s.contacts.collectAsState()
    val pending by s.pendingAdverts.collectAsState()
    val scope = rememberCoroutineScope()
    var filter by remember { mutableStateOf("") }
    var open by remember { mutableStateOf<Contact?>(null) }
    var importing by remember { mutableStateOf(false) }
    var importText by remember { mutableStateOf("") }
    var shareText by remember { mutableStateOf<String?>(null) }

    val shown = contacts.filter { filter.isBlank() || it.name.contains(filter, true) || it.publicKey.startsWith(filter.lowercase()) }
        .sortedWith(compareByDescending<Contact> { it.favourite }.thenByDescending { it.lastAdvert })

    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.fillMaxWidth().padding(12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(filter, { filter = it }, Modifier.weight(1f), label = { Text("Search") }, singleLine = true)
            }
            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { scope.launch { runCatching { s.advert(false) }.onSuccess { AppState.say("Advert sent") }.onFailure { AppState.say(it.message ?: "failed") } } }) { Text("Advert") }
                OutlinedButton(onClick = { scope.launch { runCatching { s.advert(true) }.onSuccess { AppState.say("Flood advert sent") }.onFailure { AppState.say(it.message ?: "failed") } } }) { Text("Flood") }
                OutlinedButton(onClick = { scope.launch { runCatching { shareText = s.exportContact(null) }.onFailure { AppState.say(it.message ?: "failed") } } }) { Text("Share me") }
                OutlinedButton(onClick = { importing = true }) { Text("Add") }
            }
        }
        if (pending.isNotEmpty()) {
            item {
                SectionCard("New adverts waiting", "Manual add is on, so these are not saved yet.") {
                    pending.forEach { c ->
                        ListItem(
                            headlineContent = { Text(c.name) },
                            supportingContent = { Text(c.typeName) },
                            trailingContent = {
                                TextButton(onClick = { scope.launch { runCatching { s.addContact(c) }.onFailure { AppState.say(it.message ?: "failed") } } }) { Text("Add") }
                            },
                        )
                    }
                }
            }
        }
        items(shown) { c ->
            ListItem(
                modifier = Modifier.clickable { open = c },
                headlineContent = { Text((if (c.favourite) "★ " else "") + c.name, fontWeight = FontWeight.SemiBold) },
                supportingContent = { Text("${c.typeName} · ${pathLabel(c)}") },
                trailingContent = { Text(if (c.lastAdvert > 0) ago(System.currentTimeMillis() / 1000 - c.lastAdvert) else "") },
            )
            HorizontalDivider()
        }
    }

    open?.let { c -> ContactSheet(c, s, scope, onMessage, onMap, onShare = { shareText = it }) { open = null } }

    if (importing) {
        AlertDialog(
            onDismissRequest = { importing = false },
            title = { Text("Add a contact") },
            text = {
                Column {
                    Text("Paste a meshcore:// contact someone shared with you.")
                    OutlinedTextField(importText, { importText = it }, Modifier.fillMaxWidth())
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val t = importText
                    importing = false
                    importText = ""
                    scope.launch { runCatching { s.importContact(t) }.onSuccess { AppState.say("Contact added") }.onFailure { AppState.say(it.message ?: "failed") } }
                }) { Text("Add") }
            },
            dismissButton = { TextButton(onClick = { importing = false }) { Text("Cancel") } },
        )
    }

    shareText?.let { text ->
        AlertDialog(
            onDismissRequest = { shareText = null },
            title = { Text("Share this contact") },
            text = { SelectionText(text) },
            confirmButton = { TextButton(onClick = { shareText = null }) { Text("Done") } },
        )
    }
}

@Composable
private fun SelectionText(text: String) {
    androidx.compose.foundation.text.selection.SelectionContainer {
        Text(text, style = MaterialTheme.typography.bodySmall)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ContactSheet(
    c: Contact,
    s: MeshSession,
    scope: kotlinx.coroutines.CoroutineScope,
    onMessage: (String) -> Unit,
    onMap: (Contact) -> Unit,
    onShare: (String) -> Unit,
    onClose: () -> Unit,
) {
    var busy by remember { mutableStateOf<String?>(null) }
    var result by remember { mutableStateOf<String?>(null) }
    var askPassword by remember { mutableStateOf(false) }
    var password by remember { mutableStateOf("") }
    var console by remember { mutableStateOf(false) }

    fun run(label: String, block: suspend () -> String) {
        busy = label
        scope.launch {
            val r = runCatching { block() }
            busy = null
            result = r.getOrElse { it.message ?: "failed" }
        }
    }

    ModalBottomSheet(onDismissRequest = onClose) {
        Column(Modifier.padding(16.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(c.name, style = MaterialTheme.typography.titleLarge)
            Text("${c.typeName} · ${pathLabel(c)}", color = MaterialTheme.colorScheme.outline)
            Text(c.publicKey, style = MaterialTheme.typography.labelSmall)
            if (c.lat != 0.0 || c.lon != 0.0) Text("Location %.4f, %.4f".format(c.lat, c.lon))

            FlowButtons(
                listOfNotNull(
                    "Message" to { onMessage("c:${c.prefix}"); onClose() },
                    if (c.type != uk.umc.app.proto.ADV_TYPE_CHAT) ("Log in" to { askPassword = true }) else null,
                    if (c.type != uk.umc.app.proto.ADV_TYPE_CHAT) ("Status" to {
                        run("Asking for status…") {
                            val st = s.status(c)
                            buildString {
                                appendLine("Battery ${"%.2f".format(st.batteryMv / 1000.0)} V")
                                appendLine("Uptime ${st.uptimeSecs / 3600} h ${(st.uptimeSecs % 3600) / 60} m")
                                appendLine("Noise floor ${st.noiseFloor} dBm, last RSSI ${st.lastRssi}, SNR ${st.lastSnr ?: "-"}")
                                appendLine("Packets received ${st.packetsRecv}, sent ${st.packetsSent}")
                                appendLine("Flood rx/tx ${st.recvFlood}/${st.sentFlood}, direct rx/tx ${st.recvDirect}/${st.sentDirect}")
                                appendLine("Airtime tx ${st.txAirSecs} s, rx ${st.rxAirSecs ?: "-"} s")
                                append("Queue ${st.txQueue}, errors ${st.errors}")
                            }
                        }
                    }) else null,
                    "Telemetry" to {
                        run("Asking for telemetry…") {
                            val t = s.telemetry(c)
                            if (t.isEmpty()) "No telemetry shared with you." else t.joinToString("\n") { "${it.name} (ch ${it.channel}): ${it.value}" }
                        }
                    },
                    "Trace path" to {
                        run("Tracing…") {
                            val t = s.trace(c)
                            t.hops.mapIndexed { i, h -> "${i + 1}. $h  ${t.snrs.getOrNull(i)?.let { "SNR $it" } ?: ""}" }
                                .joinToString("\n") + (t.finalSnr?.let { "\nback here: SNR $it" } ?: "")
                        }
                    },
                    "Discover path" to { run("Discovering…") { s.discoverPath(c) } },
                    "Reset path" to { run("Resetting…") { s.resetPath(c); "Path reset - the next message finds a new route." } },
                    "Share" to { run("Sharing…") { s.shareContact(c); "Shared with radios in direct range." } },
                    "Export" to { run("Exporting…") { val uri = s.exportContact(c); onShare(uri); uri } },
                    (if (c.favourite) "Unfavourite" else "Favourite") to {
                        run("Saving…") { s.setFavourite(c, !c.favourite); "Saved." }
                    },
                    "Remove" to { run("Removing…") { s.removeContact(c); "Removed." } },
                    if (c.type != uk.umc.app.proto.ADV_TYPE_CHAT) ("Admin console" to { console = true }) else null,
                )
            )

            busy?.let {
                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                    Text(it)
                }
            }
            result?.let { SelectionText(it) }
            Spacer(Modifier.height(20.dp))
        }
    }

    if (askPassword) {
        AlertDialog(
            onDismissRequest = { askPassword = false },
            title = { Text("Log in to ${c.name}") },
            text = {
                Column {
                    Text("The node's admin password (leave blank for guest access).")
                    OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), singleLine = true)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val pw = password
                    askPassword = false
                    password = ""
                    run("Logging in…") { if (s.login(c, pw)) "Logged in as admin." else "Logged in." }
                }) { Text("Log in") }
            },
            dismissButton = { TextButton(onClick = { askPassword = false }) { Text("Cancel") } },
        )
    }

    if (console) AdminConsole(c, s, onClose = { console = false })
}

@Composable
private fun FlowButtons(actions: List<Pair<String, () -> Unit>>) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        actions.chunked(3).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                row.forEach { (label, action) ->
                    OutlinedButton(onClick = action, modifier = Modifier.weight(1f)) {
                        Text(label, style = MaterialTheme.typography.labelMedium, maxLines = 1)
                    }
                }
                repeat(3 - row.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

/** Remote admin over the mesh: commands go to the node, replies come back as CLI messages. */
@Composable
private fun AdminConsole(c: Contact, s: MeshSession, onClose: () -> Unit) {
    val messages by s.messages.collectAsState()
    val scope = rememberCoroutineScope()
    var command by remember { mutableStateOf("") }
    val lines = messages.filter { it.conversation == "c:${c.prefix}" && it.cli }

    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("${c.name} console") },
        text = {
            Column(Modifier.heightIn(max = 380.dp)) {
                Text("Log in first. Try: ver, get radio, neighbors, advert", style = MaterialTheme.typography.labelSmall)
                LazyColumn(Modifier.weight(1f)) {
                    items(lines) { m ->
                        Text((if (m.outgoing) "> " else "") + m.text, style = MaterialTheme.typography.bodySmall)
                    }
                }
                OutlinedTextField(command, { command = it }, Modifier.fillMaxWidth(), label = { Text("Command") }, singleLine = true)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val cmd = command.trim()
                command = ""
                if (cmd.isNotEmpty()) scope.launch { runCatching { s.sendCli(c, cmd) }.onFailure { AppState.say(it.message ?: "failed") } }
            }) { Text("Send") }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Close") } },
    )
}
