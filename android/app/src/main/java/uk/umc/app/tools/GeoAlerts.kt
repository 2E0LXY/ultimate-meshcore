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
            if (f != null && f.exists()) {
                val (fs, ev) = GeoStore.decode(f.readText(Charsets.UTF_8))
                fences.value = fs; events.value = ev
            }
        }
        AppState.scope.launch {
            AppState.session.collectLatest { s -> s?.contacts?.collect { process(it) } }
        }
    }

    private fun file() = appContext?.let { File(it.filesDir, "umc_geofences.json") }

    private fun save() {
        val f = file() ?: return
        synchronized(lock) {
            runCatching {
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
        if (fences.value.size >= Fences.MAX_FENCES) return "at most ${Fences.MAX_FENCES} fences"
        fences.value = fences.value + f
        save()
        return null
    }

    fun remove(id: String) { fences.value = fences.value.filter { it.id != id }; save() }

    fun clearEvents() { events.value = emptyList(); save() }

    fun restore(r: Restored) {
        fences.value = GeoStore.mergeFences(fences.value, r.fences)
        events.value = GeoStore.mergeEvents(events.value, r.events)
        save()
    }

    private fun process(contacts: List<Contact>) {
        val fs = fences.value
        if (fs.isEmpty()) { engine.reset(); return }
        val now = System.currentTimeMillis()
        val hits = ArrayList<FenceHit>()
        for (c in contacts) hits.addAll(engine.update(c.publicKey, c.name, c.lat, c.lon, now, fs))
        if (hits.isEmpty()) return
        events.value = GeoStore.appendEvents(events.value, hits)
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
