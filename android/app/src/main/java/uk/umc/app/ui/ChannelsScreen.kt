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
import uk.umc.app.proto.toHex
import uk.umc.app.proto.hexToBytes
import java.security.MessageDigest

/** Channels: public, hashtag, private and shared-secret group chats. */
@Composable
fun ChannelsScreen() {
    val session by AppState.session.collectAsState()
    val s = session ?: return NotConnected()
    val channels by s.channels.collectAsState()
    val scope = rememberCoroutineScope()
    var kind by remember { mutableStateOf("hashtag") }
    var name by remember { mutableStateOf("") }
    var secret by remember { mutableStateOf("") }
    var showSecret by remember { mutableStateOf<Int?>(null) }

    fun freeSlot(): Int = (0 until 40).firstOrNull { idx -> channels.none { it.idx == idx } } ?: -1

    LazyColumn(Modifier.fillMaxSize()) {
        items(channels) { ch ->
            ListItem(
                headlineContent = { Text(ch.name) },
                supportingContent = { Text(if (showSecret == ch.idx) ch.secret.toHex() else "slot ${ch.idx}") },
                trailingContent = {
                    Row {
                        TextButton(onClick = { showSecret = if (showSecret == ch.idx) null else ch.idx }) { Text(if (showSecret == ch.idx) "Hide" else "Key") }
                        TextButton(onClick = {
                            scope.launch {
                                runCatching { s.setChannel(ch.idx, "", ByteArray(16)) }
                                    .onSuccess { AppState.say("Channel removed") }
                                    .onFailure { AppState.say(it.message ?: "failed") }
                            }
                        }) { Text("Remove") }
                    }
                },
            )
            HorizontalDivider()
        }
        item {
            SectionCard("Add a channel", "Everyone with the same key sees the same messages.") {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("hashtag", "private", "join", "public").forEach { k ->
                        FilterChip(selected = kind == k, onClick = { kind = k }, label = { Text(k) })
                    }
                }
                when (kind) {
                    "hashtag" -> Text("Anyone who types the same #name joins.", style = MaterialTheme.typography.bodySmall)
                    "private" -> Text("A random key you share with the people you choose.", style = MaterialTheme.typography.bodySmall)
                    "join" -> Text("Paste the 32-character key someone shared with you.", style = MaterialTheme.typography.bodySmall)
                    else -> Text("The standard MeshCore public channel.", style = MaterialTheme.typography.bodySmall)
                }
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("Name") }, singleLine = true)
                if (kind == "join") OutlinedTextField(secret, { secret = it }, Modifier.fillMaxWidth(), label = { Text("Key (hex)") }, singleLine = true)
                Button(onClick = {
                    val idx = freeSlot()
                    if (idx < 0) return@Button AppState.say("All 40 channel slots are in use")
                    var n = name.trim()
                    val key: ByteArray? = when (kind) {
                        "hashtag" -> {
                            if (n.isEmpty()) null else {
                                if (!n.startsWith("#")) n = "#$n"
                                n = n.lowercase()
                                MessageDigest.getInstance("SHA-256").digest(n.toByteArray()).copyOfRange(0, 16)
                            }
                        }
                        "private" -> if (n.isEmpty()) null else ByteArray(16).also { java.security.SecureRandom().nextBytes(it) }
                        "join" -> secret.trim().hexToBytes().takeIf { it.size == 16 }
                        else -> android.util.Base64.decode("izOH6cXN6mrJ5e26oRXNcg==", android.util.Base64.DEFAULT)
                    }
                    if (key == null || n.isEmpty()) return@Button AppState.say("Enter a name (and a 32-character key to join)")
                    val finalName = n
                    scope.launch {
                        runCatching { s.setChannel(idx, finalName, key) }
                            .onSuccess { AppState.say("Added $finalName"); name = ""; secret = "" }
                            .onFailure { AppState.say(it.message ?: "failed") }
                    }
                }) { Text("Add channel") }
            }
        }
    }
}
