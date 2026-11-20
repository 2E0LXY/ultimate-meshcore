package uk.umc.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import uk.umc.app.AppState
import uk.umc.app.net.*

/** UMC Net (internet) mode: channel messages through the broker, with no radio attached. */
@Composable
fun UmcNetScreen(onBack: () -> Unit) {
    val phase by UmcNet.phase.collectAsState()
    val storageError by UmcNet.storageError.collectAsState()
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            ShButton(variant = ShVariant.Ghost, onClick = onBack) { Text("Back") }
            Text("UMC Net (internet)", style = MaterialTheme.typography.titleMedium)
        }
        if (storageError != null) { ShAlert("Cannot keep an account", storageError, Modifier.padding(12.dp), destructive = true); return@Column }
        if (phase == JoinPhase.JOINED) NetChat() else JoinNet()
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

// ------------------------------------------------------------------------------------------------ messages

@Composable
private fun NetChat() {
    val account by UmcNet.account.collectAsState()
    val status by UmcNet.status.collectAsState()
    val connected by UmcNet.connected.collectAsState()
    val channels by UmcNet.channels.collectAsState()
    val messages by UmcNet.messages.collectAsState()
    val repeaters by UmcNet.repeaters.collectAsState()
    val regions by AppState.regions.collectAsState()
    val sender by UmcNet.senderName.collectAsState()
    var channel by remember { mutableStateOf(channels.firstOrNull()?.name ?: "") }
    var region by remember { mutableStateOf("") }
    var via by remember { mutableStateOf("") }                       // "" = all repeaters
    var draft by remember { mutableStateOf("") }
    var result by remember { mutableStateOf("") }
    var help by remember { mutableStateOf(false) }
    var adding by remember { mutableStateOf(false) }
    var account_ by remember { mutableStateOf(false) }
    var now by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { delay(5000); now = System.currentTimeMillis() } }
    LaunchedEffect(channels) { if (channels.none { it.name == channel }) channel = channels.firstOrNull()?.name ?: "" }

    val shown = messages.filter { it.channel == channel }
    val listState = rememberLazyListState()
    LaunchedEffect(shown.size) { if (shown.isNotEmpty()) listState.animateScrollToItem(shown.size - 1) }
    val online = repeaters.values.filter { it.online(now) }.sortedBy { it.label.lowercase() }
    fun nameOf(id: String) = repeaters[id]?.label ?: id.take(8)
    val bytes = draft.toByteArray(Charsets.UTF_8).size
    val tooLong = bytes > MsgCodec.MAX_TEXT_BYTES

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ShBadge(if (connected) "connected" else "offline", kind = if (connected) ShBadgeKind.Success else ShBadgeKind.Warning)
            Text(if (connected) "${online.size} repeater${if (online.size == 1) "" else "s"} online" else status, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, maxLines = 2)
            if (connected) ShButton(variant = ShVariant.Ghost, onClick = { UmcNet.disconnect() }) { Text("Disconnect") }
            else ShButton(variant = ShVariant.Ghost, onClick = { UmcNet.connect() }) { Text("Connect") }
            ShButton(variant = ShVariant.Ghost, onClick = { account_ = true }) { Text("Account") }
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Pick(channel.ifEmpty { "channel" }, channels.map { it.name to it.name }, { channel = it }, Modifier.weight(1f))
            ShButton(variant = ShVariant.Outline, onClick = { adding = true }) { Text("Add") }
            ShButton(variant = ShVariant.Ghost, onClick = { help = true }) { Text("?") }
        }
        ShSeparator(Modifier.padding(top = 6.dp))
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = listState) {
            items(shown, key = { it.key }) { m ->
                NetBubble(m, now, ::nameOf) {
                    // Reply: same channel and region, through the repeater that heard it best
                    channel = m.channel; region = m.region.takeIf { it in regions } ?: ""
                    via = Delivery.replyVia(m)?.takeIf { id -> online.any { it.id == id } } ?: ""
                }
            }
            if (shown.isEmpty()) item { Text("No messages in $channel yet. They appear as repeaters hear them.", Modifier.padding(16.dp), style = MaterialTheme.typography.bodySmall) }
        }
        Column(Modifier.fillMaxWidth().padding(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Pick(if (region.isEmpty()) "no region" else region, listOf("" to "no region") + regions.map { it to it }, { region = it }, Modifier.weight(1f))
                Pick(if (via.isEmpty()) "via all repeaters" else "via " + nameOf(via), listOf("" to "via all repeaters") + online.map { it.id to "via " + it.label }, { via = it }, Modifier.weight(1f))
            }
            Row(verticalAlignment = Alignment.Top) {
                OutlinedTextField(draft, { draft = it.replace("\n", " ") }, Modifier.weight(1f), placeholder = { Text("Message as $sender") },
                    supportingText = { Text(if (result.isNotEmpty()) result else "$bytes/${MsgCodec.MAX_TEXT_BYTES} bytes") }, isError = tooLong)
                Spacer(Modifier.width(8.dp))
                ShButton(enabled = connected && draft.isNotBlank() && !tooLong, onClick = {
                    val err = UmcNet.send(channel, region.ifEmpty { null }, draft, via.ifEmpty { null })
                    result = err ?: ""; if (err == null) draft = ""
                }) { Text("Send") }
            }
        }
    }

    if (help) AlertDialog(onDismissRequest = { help = false }, confirmButton = { ShButton(variant = ShVariant.Ghost, onClick = { help = false }) { Text("OK") } },
        title = { Text("About delivery") }, text = { Text(Delivery.TOOLTIP) })
    if (adding) AddChannelDialog({ adding = false }) { n, k -> UmcNet.addChannel(n, k).also { if (it == null) { channel = n.trim(); adding = false } } }
    if (account_) AccountDialog(account, sender, { account_ = false })
}

@Composable
private fun NetBubble(m: NetMessage, now: Long, name: (String) -> String, onReply: () -> Unit) {
    val (foot, none) = Delivery.text(m, now, name)
    val scheme = MaterialTheme.colorScheme
    val glass = onGlass()
    val bubble = when { glass && m.outgoing -> androidx.compose.ui.graphics.Color(0xFF2E7D5B).copy(alpha = 0.55f); glass -> androidx.compose.ui.graphics.Color.White.copy(alpha = 0.12f)
                        m.outgoing -> scheme.primaryContainer; else -> scheme.surfaceVariant }
    val ink = when { glass -> androidx.compose.ui.graphics.Color.White; m.outgoing -> scheme.onPrimaryContainer; else -> scheme.onSurfaceVariant }
    Column(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 3.dp), horizontalAlignment = if (m.outgoing) Alignment.End else Alignment.Start) {
        Column(Modifier.clip(RoundedCornerShape(12.dp)).background(bubble).padding(horizontal = 10.dp, vertical = 6.dp)) {
            Text(m.sender.ifEmpty { "?" }, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold, color = ink)
            Text(m.text, color = ink)
            val meta = listOfNotNull(clock(m.seenMs / 1000), m.region.takeIf { it.isNotEmpty() }?.let { if (it == "?") "other region" else it }).joinToString(" · ")
            Text(meta, style = MaterialTheme.typography.labelSmall, color = ink.copy(alpha = 0.72f))
        }
        if (foot.isNotEmpty()) Text(foot, style = MaterialTheme.typography.labelSmall, color = if (none) scheme.error else scheme.outline, modifier = Modifier.padding(horizontal = 4.dp))
        if (!m.outgoing) ShButton(variant = ShVariant.Ghost, onClick = onReply) { Text("Reply") }
    }
}

/** A button that opens a menu of (value, label) choices. */
@Composable
private fun Pick(label: String, choices: List<Pair<String, String>>, onPick: (String) -> Unit, modifier: Modifier = Modifier) {
    var open by remember { mutableStateOf(false) }
    Box(modifier) {
        ShButton(variant = ShVariant.Outline, onClick = { open = true }, modifier = Modifier.fillMaxWidth()) { Text(label, maxLines = 1) }
        DropdownMenu(open, { open = false }) {
            choices.forEach { (v, l) -> DropdownMenuItem(text = { Text(l) }, onClick = { onPick(v); open = false }) }
        }
    }
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
