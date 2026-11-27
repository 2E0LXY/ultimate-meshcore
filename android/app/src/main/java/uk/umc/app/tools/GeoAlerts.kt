package uk.umc.app.tools

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uk.umc.app.AppState
import uk.umc.app.MainActivity
import uk.umc.app.proto.Contact
import java.io.File

/**
 * Watches the positions the radio reports for contacts and raises a notification when one crosses a
 * geofence. Fences and the event history live in a file in the app's own storage. This phone's own
 * location is never read.
 */
object GeoAlerts {
    val fences = MutableStateFlow<List<Geofence>>(emptyList())
    val events = MutableStateFlow<List<FenceHit>>(emptyList())

    private val engine = GeofenceEngine()
    private var appContext: Context? = null
    private val lock = Any()

    fun init(context: Context) {
        if (appContext != null) return
        appContext = context.applicationContext
        runCatching {
            val f = file()
            val b = backupFile()
            val main = f?.takeIf { it.exists() }?.let { runCatching { it.readText(Charsets.UTF_8) }.getOrNull() }
            val bak = b?.takeIf { it.exists() }?.let { runCatching { it.readText(Charsets.UTF_8) }.getOrNull() }
            val loaded = GeoStore.load(main, bak)
            // keep a damaged main file for inspection instead of letting the next save overwrite it
            if (main != null && loaded.source != GeoStore.Source.MAIN && f != null) runCatching { f.renameTo(File(f.parentFile, f.name + ".corrupt")) }
            fences.value = loaded.fences; events.value = loaded.events
            if (loaded.source == GeoStore.Source.BACKUP) AppState.say("Geofence file was damaged: restored the last good copy")
        }
        AppState.scope.launch {
            AppState.session.collectLatest { s -> s?.contacts?.collect { process(it) } }
        }
    }

    private fun file() = appContext?.let { File(it.filesDir, "umc_geofences.json") }
    private fun backupFile() = file()?.let { File(it.parentFile, it.name + ".bak") }

    private fun save() {
        val f = file() ?: return
        synchronized(lock) {
            runCatching {
                // the current file becomes the last good copy, but only if it is itself readable
                val bak = backupFile()
                if (bak != null && f.exists()) {
                    val cur = runCatching { f.readText(Charsets.UTF_8) }.getOrNull()
                    if (cur != null && GeoStore.decodeOrNull(cur) != null) f.copyTo(bak, overwrite = true)
                }
                val tmp = File(f.parentFile, f.name + ".tmp")
                tmp.writeText(GeoStore.encode(fences.value, events.value), Charsets.UTF_8)
                if (!tmp.renameTo(f)) { f.delete(); tmp.renameTo(f) }
            }
        }
    }

    /** An error in plain words, or null once added. */
    fun add(name: String, lat: Double, lon: Double, radiusM: Double): String? {
        val f = Geofence(java.util.UUID.randomUUID().toString(), name.trim(), lat, lon, radiusM)
        Fences.validate(f)?.let { return it }
        var full = false
        fences.update { cur -> if (cur.size >= Fences.MAX_FENCES) { full = true; cur } else { full = false; cur + f } }
        if (full) return "at most ${Fences.MAX_FENCES} fences"
        save()
        return null
    }

    fun remove(id: String) { fences.update { cur -> cur.filter { it.id != id } }; save() }

    fun clearEvents() { events.value = emptyList(); save() }

    /** Merges a restored backup in; the result says how many fences were added, replaced or left out. */
    fun restore(r: Restored): GeoStore.FenceMerge {
        var merge = GeoStore.FenceMerge(emptyList(), 0, 0, 0)
        fences.update { cur -> GeoStore.mergeFencesReport(cur, r.fences).also { merge = it }.fences }
        events.update { cur -> GeoStore.mergeEvents(cur, r.events) }
        save()
        return merge
    }

    private fun process(contacts: List<Contact>) {
        val fs = fences.value
        if (fs.isEmpty()) { engine.reset(); return }
        val now = System.currentTimeMillis()
        val hits = ArrayList<FenceHit>()
        for (c in contacts) hits.addAll(engine.update(c.publicKey, c.name, c.lat, c.lon, now, fs))
        if (hits.isEmpty()) return
        events.update { GeoStore.appendEvents(it, hits) }
        save()
        hits.forEach { notify(it) }
    }

    private fun notify(hit: FenceHit) {
        val ctx = appContext ?: return
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val open = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val n = NotificationCompat.Builder(ctx, "messages")        // the app's existing channel
            .setSmallIcon(android.R.drawable.ic_dialog_map)
            .setContentTitle("Geofence: ${hit.fenceName}")
            .setContentText(hit.summary)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        runCatching { NotificationManagerCompat.from(ctx).notify((hit.fenceId + hit.node + hit.atMs).hashCode(), n) }
    }
}
