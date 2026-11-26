package uk.umc.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import uk.umc.app.AppState
import uk.umc.app.net.*

/** UMC Net (internet): joining, the account, the connection and the channel list. The messages themselves are in Messages ([NetChannelChat]). */
@Composable
fun UmcNetScreen(onBack: () -> Unit, onMessages: () -> Unit = {}) {
    val phase by UmcNet.phase.collectAsState()
    val storageError by UmcNet.storageError.collectAsState()
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            ShButton(variant = ShVariant.Ghost, onClick = onBack) { Text("Back") }
            Text("UMC Net (internet)", style = MaterialTheme.typography.titleMedium)
        }
        if (storageError != null) { ShAlert("Cannot keep an account", storageError, Modifier.padding(12.dp), destructive = true); return@Column }
        if (phase == JoinPhase.JOINED) NetAccount(onMessages) else JoinNet()
    }
}

// ------------------------------------------------------------------------------------------------ joining

@Composable
private fun JoinNet() {
    val phase by UmcNet.phase.collectAsState()
    val host by UmcNet.host.collectAsState()
    val id by UmcNet.clientId.collectAsState()
    val status by UmcNet.status.collectAsState()
    val clipboard = LocalClipboardManager.current
    var code by remember { mutableStateOf("") }
    var manual by remember { mutableStateOf(false) }
    var mHost by remember { mutableStateOf("") }; var mUser by remember { mutableStateOf("") }
    var mPass by remember { mutableStateOf("") }; var mArea by remember { mutableStateOf("") }; var mId by remember { mutableStateOf("") }
    var problem by remember { mutableStateOf<String?>(null) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ShCard(title = "Join UMC Net", description = "Send and read channel messages over the internet, with no radio. The network's administrator has to approve this phone once.") {
            OutlinedTextField(host, { UmcNet.setHost(it) }, Modifier.fillMaxWidth(), label = { Text("Broker host") }, singleLine = true,
                enabled = phase == JoinPhase.NONE)
            ShRow("Client id", id.take(16) + "…")
            Text(id, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ShButton(variant = ShVariant.Outline, onClick = { clipboard.setText(AnnotatedString(id)); AppState.say("Client id copied") }) { Text("Copy client id") }
                if (phase == JoinPhase.KNOCKING) ShButton(variant = ShVariant.Ghost, onClick = { UmcNet.cancelRequest() }) { Text("Cancel") }
                else ShButton(onClick = { UmcNet.requestAccess() }, enabled = id.isNotEmpty()) { Text("Request access") }
            }
            if (phase == JoinPhase.KNOCKING) {
                ShBadge(status, kind = if (status.startsWith("Waiting")) ShBadgeKind.Warning else ShBadgeKind.Secondary)
                Text("The request is sent again from time to time. You can leave this screen: it keeps waiting while the app is open.", style = MaterialTheme.typography.bodySmall)
            }
        }
        ShCard(title = "Already have a login?", description = "Paste a setup code (umcclient1:…) or type the five values. This phone's client id must be the one the account was made for.") {
            OutlinedTextField(code, { code = it }, Modifier.fillMaxWidth(), label = { Text("Setup code") }, minLines = 2)
            ShButton(variant = ShVariant.Outline, enabled = code.isNotBlank(), onClick = { problem = UmcNet.useSetupCode(code); if (problem == null) code = "" }) { Text("Use setup code") }
            ShButton(variant = ShVariant.Ghost, onClick = { manual = !manual }) { Text(if (manual) "Hide manual entry" else "Type the values instead") }
            if (manual) {
                OutlinedTextField(mHost, { mHost = it }, Modifier.fillMaxWidth(), label = { Text("Host") }, singleLine = true)
                OutlinedTextField(mUser, { mUser = it }, Modifier.fillMaxWidth(), label = { Text("Username") }, singleLine = true)
                OutlinedTextField(mPass, { mPass = it }, Modifier.fillMaxWidth(), label = { Text("Password") }, singleLine = true,
                    visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation())
                OutlinedTextField(mId, { mId = it.uppercase() }, Modifier.fillMaxWidth(), label = { Text("Client id (64 hex digits)") }, singleLine = true)
                OutlinedTextField(mArea, { mArea = it }, Modifier.fillMaxWidth(), label = { Text("Area") }, singleLine = true)
                ShButton(variant = ShVariant.Outline, onClick = { problem = UmcNet.adopt(UmcAccount(mHost.trim(), mUser.trim(), mPass, mId.trim().ifEmpty { id }, mArea.trim())) }) { Text("Use these values") }
            }
            problem?.let { ShAlert("Could not use that", it, destructive = true) }
        }
    }
}

// ------------------------------------------------------------------------------------------------ account and connection

/** Joined: the connection, the account and the channel list. Messages are read and sent from Messages, not here. */
@Composable
private fun NetAccount(onMessages: () -> Unit) {
    val account by UmcNet.account.collectAsState()
    val status by UmcNet.status.collectAsState()
    val connected by UmcNet.connected.collectAsState()
    val channels by UmcNet.channels.collectAsState()
    val repeaters by UmcNet.repeaters.collectAsState()
    val sender by UmcNet.senderName.collectAsState()
    var help by rememberSaveable { mutableStateOf(false) }
    var adding by rememberSaveable { mutableStateOf(false) }
    var showAccount by rememberSaveable { mutableStateOf(false) }
    var now by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { delay(5000); now = System.currentTimeMillis() } }
    val online = repeaters.values.count { it.online(now) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ShCard(title = "Connection") {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ShBadge(if (connected) "connected" else "offline", kind = if (connected) ShBadgeKind.Success else ShBadgeKind.Warning)
                Text(if (connected) "$online repeater${if (online == 1) "" else "s"} online" else status, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, maxLines = 2)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (connected) ShButton(variant = ShVariant.Outline, onClick = { UmcNet.disconnect() }) { Text("Disconnect") }
                else ShButton(variant = ShVariant.Outline, onClick = { UmcNet.connect() }) { Text("Connect") }
                ShButton(variant = ShVariant.Outline, onClick = { showAccount = true }) { Text("Account") }
            }
        }
        ShCard(title = "Messages", description = "UMC Net channels are in Messages, with your radio's conversations. Messages from the last 24 hours are kept on this phone.") {
            ShButton(onClick = onMessages) { Text("Open messages") }
        }
        ShCard(title = "Channels") {
            channels.forEach { c -> Text(c.name, style = MaterialTheme.typography.bodyMedium) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ShButton(variant = ShVariant.Outline, onClick = { adding = true }) { Text("Add channel") }
                ShButton(variant = ShVariant.Ghost, onClick = { help = true }) { Text("Help") }
            }
        }
    }

    if (help) AlertDialog(onDismissRequest = { help = false }, confirmButton = { ShButton(variant = ShVariant.Ghost, onClick = { help = false }) { Text("OK") } },
        title = { Text("About delivery") }, text = { Text(Delivery.TOOLTIP) })
    if (adding) AddChannelDialog({ adding = false }) { n, k -> UmcNet.addChannel(n, k).also { if (it == null) adding = false } }
    if (showAccount) AccountDialog(account, sender, { showAccount = false })
}

@Composable
private fun AddChannelDialog(onDismiss: () -> Unit, onAdd: (String, String) -> String?) {
    var name by remember { mutableStateOf("") }; var key by remember { mutableStateOf("") }; var err by remember { mutableStateOf<String?>(null) }
    AlertDialog(onDismissRequest = onDismiss,
        title = { Text("Add a channel") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("A #hashtag channel needs no key: its name is the key. Names are case-sensitive. Any other channel needs its shared key (base64, 16 bytes).", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("Name, e.g. #yorkshire") }, singleLine = true)
                OutlinedTextField(key, { key = it }, Modifier.fillMaxWidth(), label = { Text("Shared key (not needed for #names)") }, singleLine = true)
                err?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            }
        },
        confirmButton = { ShButton(variant = ShVariant.Ghost, enabled = name.isNotBlank(), onClick = { err = onAdd(name, key) }) { Text("Add") } },
        dismissButton = { ShButton(variant = ShVariant.Ghost, onClick = onDismiss) { Text("Cancel") } })
}

@Composable
private fun AccountDialog(account: UmcAccount?, sender: String, onDismiss: () -> Unit) {
    var name by remember { mutableStateOf(sender) }
    val regions by AppState.regions.collectAsState()
    var newRegion by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onDismiss,
        title = { Text("UMC Net account") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                account?.let { ShRow("Host", it.host); ShRow("Area", it.area); ShRow("Login", it.user) }
                Text(account?.clientId ?: "", style = MaterialTheme.typography.labelSmall)
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("Your name on messages") }, singleLine = true,
                    isError = !Regex("^[A-Za-z0-9][A-Za-z0-9 ._-]{0,23}$").matches(name.trim()),
                    supportingText = { Text("1 to 24 letters, digits, spaces, dots, dashes or underscores") })
                Text("Regions", style = MaterialTheme.typography.titleSmall)
                regions.forEach { r -> Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(r, Modifier.weight(1f)); ShButton(variant = ShVariant.Ghost, onClick = { AppState.removeRegion(r) }) { Text("Forget") } } }
                OutlinedTextField(newRegion, { newRegion = it }, Modifier.fillMaxWidth(), label = { Text("Add a region") }, singleLine = true,
                    isError = newRegion.isNotBlank() && !AppState.isValidRegion(newRegion.trim()), supportingText = { Text("lowercase letters, digits and hyphens, up to 29") })
                ShButton(variant = ShVariant.Outline, enabled = AppState.isValidRegion(newRegion.trim()), onClick = { if (AppState.addRegion(newRegion)) newRegion = "" }) { Text("Add region") }
                Text("Channels", style = MaterialTheme.typography.titleSmall)
                UmcNet.channels.collectAsState().value.forEach { c -> Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(c.name, Modifier.weight(1f)); ShButton(variant = ShVariant.Ghost, onClick = { UmcNet.removeChannel(c.name) }) { Text("Remove") } } }
                ShButton(variant = ShVariant.Destructive, onClick = { UmcNet.forgetAccount(); onDismiss() }) { Text("Forget this account") }
            }
        },
        confirmButton = { ShButton(variant = ShVariant.Ghost, enabled = Regex("^[A-Za-z0-9][A-Za-z0-9 ._-]{0,23}$").matches(name.trim()), onClick = { UmcNet.setSender(name); onDismiss() }) { Text("Save") } },
        dismissButton = { ShButton(variant = ShVariant.Ghost, onClick = onDismiss) { Text("Close") } })
}
