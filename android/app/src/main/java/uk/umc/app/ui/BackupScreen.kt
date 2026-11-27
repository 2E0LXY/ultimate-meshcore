package uk.umc.app.ui

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import uk.umc.app.AppState
import uk.umc.app.net.UmcNet
import uk.umc.app.tools.Backup
import uk.umc.app.tools.ExportData
import uk.umc.app.tools.GeoAlerts
import uk.umc.app.tools.Saf

/** Export contacts and messages to CSV, back the app's own settings up to JSON, and restore them. Files go where the user picks. */
@Composable
fun BackupScreen() {
    val context = LocalContext.current.applicationContext
    val session by AppState.session.collectAsState()
    val today = java.time.LocalDate.now().toString()

    fun snapshot() = ExportData(
        contacts = session?.contacts?.value ?: emptyList(),
        radioMessages = session?.messages?.value ?: emptyList(),
        netMessages = UmcNet.messages.value,
        fences = GeoAlerts.fences.value,
        events = GeoAlerts.events.value,
        regions = AppState.regions.value,
        scopes = AppState.scopes.value,
        nowMs = System.currentTimeMillis(),
    )

    fun save(uri: Uri?, what: String, build: (ExportData) -> String) {
        if (uri == null) return
        val data = snapshot()
        AppState.scope.launch(Dispatchers.IO) {
            Saf.write(context, uri, build(data))
                .onSuccess { AppState.say("$what saved") }
                .onFailure { AppState.say("Could not save: ${it.message}") }
        }
    }

    val contactsOut = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { save(it, "Contacts", Backup::contactsCsv) }
    val messagesOut = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { save(it, "Messages", Backup::messagesCsv) }
    val eventsOut = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { save(it, "Geofence events", Backup::eventsCsv) }
    val backupOut = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { save(it, "Backup", Backup::json) }
    val backupIn = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) AppState.scope.launch(Dispatchers.IO) {
            Saf.read(context, uri, Backup.MAX_RESTORE_BYTES).mapCatching { Backup.parse(it).getOrThrow() }
                .onSuccess { r ->
                    GeoAlerts.restore(r)
                    r.regions.forEach { AppState.addRegion(it) }
                    r.scopes.forEach { (ch, region) -> AppState.setChannelScope(ch, region) }
                    AppState.say("Restored ${r.fences.size} geofences, ${r.regions.size} regions, ${r.scopes.size} channel scopes")
                }
                .onFailure { AppState.say("Could not restore: ${it.message}") }
        }
    }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Export to CSV", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Opens a spreadsheet-ready file. You choose where it is saved; the app needs no storage permission. " +
                            "Cells that start with = + - or @ get a leading apostrophe so a spreadsheet cannot run them as formulas.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                    ShButton(onClick = { contactsOut.launch("umc-contacts-$today.csv") }) { Text("Contacts and nodes") }
                    ShButton(variant = ShVariant.Outline, onClick = { messagesOut.launch("umc-messages-$today.csv") }) { Text("Message history") }
                    ShButton(variant = ShVariant.Outline, onClick = { eventsOut.launch("umc-geofence-events-$today.csv") }) { Text("Geofence events") }
                    Text("Contacts and radio messages need a connected radio. UMC Net keeps the last 24 hours.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
                }
            }
        }
        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Full backup (JSON)", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Contacts, messages, geofences with their history, regions and channel scopes. " +
                            "Never included: radio or channel keys, the UMC Net login, its identity key or any password. " +
                            "Restore brings back geofences, their history, regions and channel scopes. Contacts live on the radio and message history is read-only, so those are not restored.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                    ShButton(onClick = { backupOut.launch("umc-backup-$today.json") }) { Text("Save backup") }
                    ShButton(variant = ShVariant.Outline, onClick = { backupIn.launch(arrayOf("application/json", "text/plain", "*/*")) }) { Text("Restore from backup") }
                }
            }
        }
    }
}
