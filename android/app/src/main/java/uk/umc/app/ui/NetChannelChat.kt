package uk.umc.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import uk.umc.app.AppState
import uk.umc.app.net.*

/**
 * One UMC Net (internet) channel as a conversation: its messages, the region and repeater choosers, and the send box.
 * Opened from Messages as "net:<channelName>".
 */
@Composable
fun NetChannelChat(channelName: String, onBack: () -> Unit) {
    val status by UmcNet.status.collectAsState()
    val connected by UmcNet.connected.collectAsState()
    val messages by UmcNet.messages.collectAsState()
    val repeaters by UmcNet.repeaters.collectAsState()
    val regions by AppState.regions.collectAsState()
    val sender by UmcNet.senderName.collectAsState()
    // the network has one region: start on it; otherwise "no region" until chosen. Kept across rotation.
    var region by rememberSaveable(channelName) { mutableStateOf(regions.singleOrNull() ?: "") }
    var via by rememberSaveable(channelName) { mutableStateOf("") }                       // "" = all repeaters
    var draft by rememberSaveable(channelName) { mutableStateOf("") }
    var result by rememberSaveable(channelName) { mutableStateOf("") }
    var help by remember { mutableStateOf(false) }
    var now by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { delay(5000); now = System.currentTimeMillis() } }

    val shown = messages.filter { it.channel == channelName }
    val listState = rememberLazyListState()
    var scrolled by remember { mutableStateOf(false) }
    LaunchedEffect(shown.size) {
        if (shown.isEmpty()) return@LaunchedEffect
        val last = shown.size - 1
        val lastVisible = listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
        // first time: jump to the newest; after that follow new messages unless the reader has scrolled up
        if (!scrolled) { listState.scrollToItem(last); scrolled = true }
        else if (lastVisible >= last - 2 || shown[last].outgoing) listState.animateScrollToItem(last)
    }
    val online = repeaters.values.filter { it.online(now) }.sortedBy { it.label.lowercase() }
    fun nameOf(id: String) = repeaters[id]?.label ?: id.take(8)
    val bytes = draft.toByteArray(Charsets.UTF_8).size
    val tooLong = bytes > MsgCodec.MAX_TEXT_BYTES

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ShButton(variant = ShVariant.Ghost, onClick = onBack) { Text("Back") }
            Column(Modifier.weight(1f)) {
                Text(channelName, style = MaterialTheme.typography.titleMedium, maxLines = 1)
                Text(if (connected) "UMC Net · ${online.size} repeater${if (online.size == 1) "" else "s"} online" else "UMC Net · $status",
                    style = MaterialTheme.typography.labelSmall, maxLines = 2)
            }
            ShBadge(if (connected) "connected" else "offline", kind = if (connected) ShBadgeKind.Success else ShBadgeKind.Warning)
            ShButton(variant = ShVariant.Ghost, onClick = { help = true }) { Text("?") }
        }
        ShSeparator(Modifier.padding(top = 6.dp))
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = listState) {
            items(shown, key = { it.key }) { m ->
                NetBubble(m, now, ::nameOf) {
                    // Reply: same region, through the repeater that heard it best
                    region = m.region.takeIf { it in regions } ?: ""
                    via = Delivery.replyVia(m)?.takeIf { id -> online.any { it.id == id } } ?: ""
                }
            }
            if (shown.isEmpty()) item { Text("No messages in $channelName yet. They appear as repeaters hear them.", Modifier.padding(16.dp), style = MaterialTheme.typography.bodySmall) }
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
                    val err = UmcNet.send(channelName, region.ifEmpty { null }, draft, via.ifEmpty { null })
                    result = err ?: ""; if (err == null) draft = ""
                }) { Text("Send") }
            }
        }
    }

    if (help) AlertDialog(onDismissRequest = { help = false }, confirmButton = { ShButton(variant = ShVariant.Ghost, onClick = { help = false }) { Text("OK") } },
        title = { Text("About delivery") }, text = { Text(Delivery.TOOLTIP) })
}

@Composable
private fun NetBubble(m: NetMessage, now: Long, name: (String) -> String, onReply: () -> Unit) {
    val (foot, none) = Delivery.text(m, now, name)
    val scheme = MaterialTheme.colorScheme
    val glass = onGlass()
    val bubble = when { glass && m.outgoing -> androidx.compose.ui.graphics.Color(0xFF2E7D5B).copy(alpha = 0.55f); glass -> androidx.compose.ui.graphics.Color.White.copy(alpha = 0.12f)
                        m.outgoing -> scheme.primaryContainer; else -> scheme.surfaceVariant }
    val ink = when { glass -> androidx.compose.ui.graphics.Color.White; m.outgoing -> scheme.onPrimaryContainer; else -> scheme.onSurfaceVariant }
    // the footer under the bubble: "heard by" lists one repeater per line so a long list wraps cleanly
    val footer = foot.replace("  |  ", "\n")
    val footInk = if (none) scheme.error else if (glass) androidx.compose.ui.graphics.Color.White.copy(alpha = 0.72f) else scheme.outline
    Column(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 3.dp), horizontalAlignment = if (m.outgoing) Alignment.End else Alignment.Start) {
        Column(Modifier.clip(RoundedCornerShape(12.dp)).background(bubble).padding(horizontal = 10.dp, vertical = 6.dp)) {
            Text(m.sender.ifEmpty { "?" }, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold, color = ink)
            Text(m.text, color = ink)
            val meta = listOfNotNull(clock(m.seenMs / 1000), m.region.takeIf { it.isNotEmpty() }?.let { if (it == "?") "other region" else it }).joinToString(" · ")
            Text(meta, style = MaterialTheme.typography.labelSmall, color = ink.copy(alpha = 0.72f))
        }
        if (footer.isNotEmpty()) Text(footer, style = MaterialTheme.typography.labelSmall, color = footInk, modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp),
            textAlign = if (m.outgoing) androidx.compose.ui.text.style.TextAlign.End else androidx.compose.ui.text.style.TextAlign.Start)
        if (!m.outgoing) ShButton(variant = ShVariant.Ghost, onClick = onReply) { Text("Reply") }
    }
}

/** A button that opens a menu of (value, label) choices. */
@Composable
internal fun Pick(label: String, choices: List<Pair<String, String>>, onPick: (String) -> Unit, modifier: Modifier = Modifier) {
    var open by remember { mutableStateOf(false) }
    Box(modifier) {
        ShButton(variant = ShVariant.Outline, onClick = { open = true }, modifier = Modifier.fillMaxWidth()) { Text(label, maxLines = 1) }
        DropdownMenu(open, { open = false }) {
            choices.forEach { (v, l) -> DropdownMenuItem(text = { Text(l) }, onClick = { onPick(v); open = false }) }
        }
    }
}
