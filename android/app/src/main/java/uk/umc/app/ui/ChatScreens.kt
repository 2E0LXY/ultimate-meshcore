package uk.umc.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import uk.umc.app.AppState
import uk.umc.app.proto.ChatMessage
import uk.umc.app.proto.MAX_TEXT_BYTES
import uk.umc.app.proto.MeshSession

/** Conversations: every channel, plus contacts we can chat to. */
@Composable
fun ChatsScreen(onOpen: (String) -> Unit) {
    val session by AppState.session.collectAsState()
    val s = session ?: return NotConnected()
    val channels by s.channels.collectAsState()
    val contacts by s.contacts.collectAsState()
    val messages by s.messages.collectAsState()

    data class Row(val conversation: String, val title: String, val subtitle: String, val last: ChatMessage?)

    val rows = buildList {
        channels.forEach { ch ->
            val last = messages.lastOrNull { it.conversation == "ch:${ch.idx}" }
            add(Row("ch:${ch.idx}", ch.name, "channel", last))
        }
        contacts.filter { it.type == uk.umc.app.proto.ADV_TYPE_CHAT || it.type == uk.umc.app.proto.ADV_TYPE_ROOM }.forEach { c ->
            val last = messages.lastOrNull { it.conversation == "c:${c.prefix}" }
            add(Row("c:${c.prefix}", c.name, c.typeName + " · " + pathLabel(c), last))
        }
    }.sortedByDescending { it.last?.received ?: 0 }

    LazyColumn(Modifier.fillMaxSize()) {
        items(rows) { r ->
            ListItem(
                modifier = Modifier.clickable { onOpen(r.conversation) },
                headlineContent = { Text(r.title, fontWeight = FontWeight.SemiBold) },
                supportingContent = {
                    Text(r.last?.let { (if (it.outgoing) "You: " else if (it.from.isNotEmpty()) "${it.from}: " else "") + it.text } ?: r.subtitle,
                        maxLines = 1)
                },
                trailingContent = { r.last?.let { Text(agoMillis(it.received), style = MaterialTheme.typography.labelSmall) } },
            )
            HorizontalDivider()
        }
        if (rows.isEmpty()) item { SectionCard("No conversations yet", "Channels and contacts appear here once the radio has them.") {} }
    }
}

/** One conversation. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(conversation: String, onBack: () -> Unit) {
    val session by AppState.session.collectAsState()
    val s = session ?: return NotConnected()
    val messages by s.messages.collectAsState()
    val channels by s.channels.collectAsState()
    val contacts by s.contacts.collectAsState()
    val scope = rememberCoroutineScope()
    var draft by remember { mutableStateOf("") }
    val listState = rememberLazyListState()

    val title = when {
        conversation.startsWith("ch:") -> channels.firstOrNull { it.idx == conversation.removePrefix("ch:").toInt() }?.name ?: conversation
        else -> contacts.firstOrNull { it.prefix == conversation.removePrefix("c:") }?.name ?: conversation.removePrefix("c:")
    }
    val mine = messages.filter { it.conversation == conversation }
    val limit = if (conversation.startsWith("ch:")) MAX_TEXT_BYTES - ((s.self.value?.name?.toByteArray()?.size ?: 0) + 2) else MAX_TEXT_BYTES

    LaunchedEffect(mine.size) { if (mine.isNotEmpty()) listState.animateScrollToItem(mine.size - 1) }

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(title) },
            navigationIcon = { ShButton(variant = ShVariant.Ghost, onClick = onBack) { Text("Back") } },
        )
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = listState) {
            items(mine) { m -> MessageBubble(m, s, scope) }
        }
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.Bottom) {
            OutlinedTextField(
                value = draft,
                onValueChange = { draft = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Message") },
                supportingText = { Text("${draft.toByteArray().size}/$limit bytes") },
                isError = draft.toByteArray().size > limit,
            )
            Spacer(Modifier.width(8.dp))
            ShButton(
                onClick = {
                    val text = draft.trim()
                    if (text.isEmpty()) return@ShButton
                    draft = ""
                    scope.launch { s.sendText(conversation, text) }
                },
                enabled = draft.isNotBlank() && draft.toByteArray().size <= limit,
            ) { Text("Send") }
        }
    }
}

@Composable
private fun MessageBubble(m: ChatMessage, s: MeshSession, scope: kotlinx.coroutines.CoroutineScope) {
    // ACK delivery and a reply's return path are separate protocol facts. Never present
    // the return-hop count as though it described the original outbound packet.
    val show by AppState.ackDisplay.collectAsState()
    var showWhy by remember(m.id) { mutableStateOf(false) }
    val status = when (m.status) {
        "queued" -> "queued"
        "sending" -> "submitting to radio…"
        "pending" -> "sent · pending delivery ACK"
        "sent" -> "sent · broadcast has no recipient ACK"
        "delivered" -> "delivered" + (m.roundTripMs?.let { " in ${"%.1f".format(it / 1000.0)} s" } ?: "")
        "replied" -> "reply received (delivery evidenced)"
        "failed" -> "failed: ${m.error ?: "no answer"}"
        else -> ""
    }
    val mark = when (m.status) {
        "delivered" -> "✓"
        "replied" -> "↩"
        "failed" -> "✕"
        "queued", "sending", "pending", "sent" -> "•"
        else -> ""
    }
    val markColour = when (m.status) {
        "delivered", "replied" -> Color(0xFF2E7D32)
        "failed" -> Color(0xFFC62828)
        "queued", "sending", "pending", "sent" -> Color(0xFFEF6C00)
        else -> MaterialTheme.colorScheme.outline
    }
    Column(
        Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 3.dp),
        horizontalAlignment = if (m.outgoing) Alignment.End else Alignment.Start,
    ) {
        Column(
            Modifier
                .clip(RoundedCornerShape(12.dp))
                .background(if (m.outgoing) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant)
                .padding(horizontal = 10.dp, vertical = 6.dp),
        ) {
            if (!m.outgoing && m.from.isNotEmpty()) {
                Text(m.from, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
            }
            Text((if (m.cli) "⌨ " else "") + m.text)
            val meta = buildList {
                add(clock(m.timestamp))
                if (!m.outgoing) {
                    add(m.hops?.let { "returned via $it hop" + if (it == 1) "" else "s" } ?: "returned by flood")
                    m.snr?.let { add("SNR $it") }
                } else {
                    if (status.isNotEmpty() && show == "count") add(status)
                    when (m.routeKind) {
                        "route" -> add("via ${m.routeHops.size}-hop route ${m.routeHops.joinToString(" → ")}")
                        null -> Unit
                        else -> add("via ${m.routeKind}")
                    }
                    if (m.replyAt != null) {
                        add(m.replyHops?.let { "reply returned via $it hop" + if (it == 1) "" else "s" } ?: "reply returned by flood")
                        m.replySnr?.let { add("reply SNR $it") }
                    }
                }
            }.joinToString(" · ")
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(meta, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                if (m.outgoing && show != "off" && mark.isNotEmpty()) {
                    Text("  $mark", style = MaterialTheme.typography.labelSmall, color = markColour,
                         fontWeight = FontWeight.Bold)
                }
            }
            m.recovery?.let { Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary) }
            if (showWhy) Text(s.diagnoseMessage(m), style = MaterialTheme.typography.labelSmall)
        }
        if (m.status == "failed") {
            Row {
                ShButton(variant = ShVariant.Ghost, onClick = { scope.launch { s.sendText(m.conversation, m.text, m) } }) { Text("Retry same") }
                if (m.conversation.startsWith("c:")) {
                    ShButton(variant = ShVariant.Ghost, onClick = {
                        scope.launch {
                            runCatching { s.autoReroute(m) }.onFailure { AppState.say("Reroute failed: ${it.message}") }
                        }
                    }) { Text("Auto reroute") }
                }
            }
            Row {
                if (m.conversation.startsWith("c:")) {
                    ShButton(variant = ShVariant.Ghost, onClick = {
                        scope.launch {
                            runCatching { s.autoReroute(m, forceFlood = true) }.onFailure { AppState.say("Flood retry failed: ${it.message}") }
                        }
                    }) { Text("Flood + resend") }
                }
                ShButton(variant = ShVariant.Ghost, onClick = { showWhy = !showWhy }) { Text(if (showWhy) "Hide reason" else "Why?") }
            }
        }
    }
}

@Composable
fun NotConnected() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text("Connect to a radio first", style = MaterialTheme.typography.bodyLarge)
    }
}
