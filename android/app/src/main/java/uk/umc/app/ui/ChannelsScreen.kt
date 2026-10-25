package uk.umc.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.ui.Alignment
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
import uk.umc.app.proto.hashtagKey

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
    val scopes by AppState.scopes.collectAsState()
    var scoping by remember { mutableStateOf<String?>(null) }
    var scopeText by remember { mutableStateOf("") }

    fun freeSlot(): Int = (0 until 40).firstOrNull { idx -> channels.none { it.idx == idx } } ?: -1

    LazyColumn(Modifier.fillMaxSize()) {
        items(channels) { ch ->
            ListItem(
                headlineContent = { Text(ch.name) },
                supportingContent = {
                    Text(
                        (if (showSecret == ch.idx) ch.secret.toHex() else "slot ${ch.idx}") +
                            (scopes[ch.name]?.let { " · scope $it" } ?: ""),
                    )
                },
                trailingContent = {
                    Row {
                        ShButton(variant = ShVariant.Ghost, onClick = { scoping = ch.name; scopeText = scopes[ch.name] ?: "" }) { Text("Scope") }
                        ShButton(variant = ShVariant.Ghost, onClick = { showSecret = if (showSecret == ch.idx) null else ch.idx }) { Text(if (showSecret == ch.idx) "Hide" else "Key") }
                        ShButton(variant = ShVariant.Ghost, onClick = {
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
            SectionCard("Regional setup", "From the MeshCore Yorkshire guide: the #Yorkshire channel with the yorkshire region scope.") {
                ShButton(onClick = {
                    scope.launch {
                        runCatching {
                            if (channels.none { it.name == "#Yorkshire" }) {
                                val idx = freeSlot()
                                if (idx < 0) throw Exception("All 40 channel slots are in use")
                                s.setChannel(idx, "#Yorkshire", hashtagKey("#Yorkshire"))
                            }
                            AppState.setChannelScope("#Yorkshire", "yorkshire")
                        }.onSuccess { AppState.say("#Yorkshire added, scoped to yorkshire") }
                            .onFailure { AppState.say(it.message ?: "failed") }
                    }
                }) { Text("Set up Yorkshire") }
            }
        }
        item {
            SectionCard("Add a channel", "Everyone with the same key sees the same messages. Hashtag names are case-sensitive.") {
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
                ShButton(onClick = {
                    val idx = freeSlot()
                    if (idx < 0) return@ShButton AppState.say("All 40 channel slots are in use")
                    var n = name.trim()
                    val key: ByteArray? = when (kind) {
                        "hashtag" -> {
                            if (n.isEmpty()) null else {
                                if (!n.startsWith("#")) n = "#$n"
                                hashtagKey(n)
                            }
                        }
                        "private" -> if (n.isEmpty()) null else ByteArray(16).also { java.security.SecureRandom().nextBytes(it) }
                        "join" -> secret.trim().hexToBytes().takeIf { it.size == 16 }
                        else -> android.util.Base64.decode("izOH6cXN6mrJ5e26oRXNcg==", android.util.Base64.DEFAULT)
                    }
                    if (key == null || n.isEmpty()) return@ShButton AppState.say("Enter a name (and a 32-character key to join)")
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

    scoping?.let { name ->
        val regions by AppState.regions.collectAsState()
        AlertDialog(
            onDismissRequest = { scoping = null },
            title = { Text("Region scope for $name") },
            text = {
                Column {
                    Text("Messages on this channel only travel through repeaters that know this region. " +
                         "Names must match exactly between nodes, so pick one rather than retyping it. Blank = none.")
                    Spacer(Modifier.height(8.dp))
                    // the regions this phone knows, the one in use marked
                    regions.forEach { r ->
                        Row(
                            Modifier.fillMaxWidth().clickable { scopeText = r }.padding(vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(selected = scopeText == r, onClick = { scopeText = r })
                            Text(r, Modifier.weight(1f))
                            ShButton(variant = ShVariant.Ghost, onClick = { AppState.removeRegion(r) }) { Text("Forget") }
                        }
                    }
                    Spacer(Modifier.height(4.dp))
                    OutlinedTextField(
                        scopeText, { scopeText = it }, Modifier.fillMaxWidth(), singleLine = true,
                        label = { Text("Region name") },
                        supportingText = { Text("lowercase letters, digits and hyphens, up to 29") },
                        isError = scopeText.isNotBlank() && !AppState.isValidRegion(scopeText.trim()),
                    )
                    ShButton(variant = ShVariant.Ghost, 
                        enabled = scopeText.isNotBlank() && AppState.isValidRegion(scopeText.trim()) &&
                                  scopeText.trim() !in regions,
                        onClick = { if (!AppState.addRegion(scopeText)) AppState.say("Could not add that region") },
                    ) { Text("Remember this region") }
                }
            },
            confirmButton = {
                ShButton(variant = ShVariant.Ghost, 
                    enabled = scopeText.isBlank() || AppState.isValidRegion(scopeText.trim()),
                    onClick = { AppState.setChannelScope(name, scopeText); scoping = null },
                ) { Text("Save") }
            },
            dismissButton = { ShButton(variant = ShVariant.Ghost, onClick = { scoping = null }) { Text("Cancel") } },
        )
    }
}
