package uk.umc.app.tools

import uk.umc.app.net.MiniJson
import uk.umc.app.net.NetMessage
import uk.umc.app.proto.ChatMessage
import uk.umc.app.proto.Contact
import java.time.Instant

/** What an export is built from: a snapshot taken when the user taps the button. */
data class ExportData(
    val contacts: List<Contact>,
    val radioMessages: List<ChatMessage>,
    val netMessages: List<NetMessage>,
    val fences: List<Geofence>,
    val events: List<FenceHit>,
    val regions: List<String>,
    val scopes: Map<String, String>,
    val nowMs: Long,
)

/** What a restore puts back: only the phone's own settings. */
data class Restored(val fences: List<Geofence>, val events: List<FenceHit>, val regions: List<String>, val scopes: Map<String, String>)

/**
 * CSV and JSON exports. Secrets are left out by construction: the exporters read named public fields
 * only (never a contact's raw record or path, a channel key, the UMC Net login, its identity seed,
 * a broker password or a radio control key), and [FORBIDDEN_WORDS] lets tests prove nothing like that slipped in.
 *
 * Restore covers geofences, their history, regions and channel region scopes. Contacts live on the radio
 * and message history is not something to inject into the live session, so those are export-only.
 */
object Backup {
    const val FORMAT = "umc-backup"
    const val VERSION = 1L
    const val MAX_RESTORE_BYTES = 5_000_000
    const val MAX_REGIONS = 100
    const val MAX_SCOPES = 100

    /** Key names that must never appear in an export. */
    val FORBIDDEN_WORDS = listOf("password", "passwd", "seed", "secret", "psk", "privatekey", "private_key", "token", "credential", "broker")

    fun iso(ms: Long): String = Instant.ofEpochMilli(ms).toString()
    private fun isoSec(s: Long): String = if (s <= 0) "" else Instant.ofEpochSecond(s).toString()
    private fun place(lat: Double, lon: Double): Boolean = Geo.validPosition(lat, lon)

    // ---------------------------------------------------------------- CSV

    fun contactsCsv(d: ExportData): String = Csv.document(
        listOf("name", "public_key", "type", "hops", "latitude", "longitude", "last_advert_utc", "favourite"),
        d.contacts.sortedBy { it.name.lowercase() }.map { c ->
            listOf(c.name, c.publicKey, c.typeName, if (c.hops < 0) null else c.hops,
                if (place(c.lat, c.lon)) c.lat else null, if (place(c.lat, c.lon)) c.lon else null,
                isoSec(c.lastAdvert), c.favourite)
        },
    )

    /** Radio and UMC Net messages together, oldest first. */
    fun messagesCsv(d: ExportData): String {
        class Row(val at: Long, val cells: List<Any?>)
        val rows = ArrayList<Row>()
        for (m in d.radioMessages) rows.add(Row(m.timestamp * 1000, listOf("radio", m.conversation, if (m.outgoing) "out" else "in",
            isoSec(m.timestamp), m.from, m.text, m.hops, m.snr, m.status)))
        for (m in d.netMessages) rows.add(Row(m.ts * 1000, listOf("net", m.channel + (if (m.region.isNotEmpty()) " / " + m.region else ""),
            if (m.outgoing) "out" else "in", isoSec(m.ts), m.sender, m.text, m.heard.filter { !it.sent }.minOfOrNull { it.hops }, null, null)))
        return Csv.document(
            listOf("source", "conversation", "direction", "time_utc", "sender", "text", "hops", "snr_db", "status"),
            rows.sortedBy { it.at }.map { it.cells },
        )
    }

    fun eventsCsv(d: ExportData): String = Csv.document(
        listOf("time_utc", "fence", "node", "event", "latitude", "longitude", "distance_m"),
        d.events.map { listOf(iso(it.atMs), it.fenceName, it.nodeName, it.event.name.lowercase(), it.lat, it.lon, Math.round(it.distanceM)) },
    )

    // ---------------------------------------------------------------- JSON

    private fun arr(items: List<String>) = items.joinToString(",", "[", "]")

    fun json(d: ExportData): String {
        val contacts = arr(d.contacts.map { c ->
            MiniJson.obj("name" to c.name, "publicKey" to c.publicKey, "type" to c.typeName, "hops" to c.hops.toLong(),
                "lat" to c.lat.takeIf { place(c.lat, c.lon) }, "lon" to c.lon.takeIf { place(c.lat, c.lon) },
                "lastAdvert" to c.lastAdvert, "favourite" to c.favourite)
        })
        val radio = arr(d.radioMessages.map { m ->
            MiniJson.obj("conversation" to m.conversation, "outgoing" to m.outgoing, "from" to m.from, "text" to m.text,
                "timestamp" to m.timestamp, "hops" to m.hops?.toLong(), "snr" to m.snr?.takeIf { it.isFinite() }, "status" to m.status)
        })
        val net = arr(d.netMessages.map { m ->
            MiniJson.obj("channel" to m.channel, "region" to m.region, "sender" to m.sender, "text" to m.text,
                "timestamp" to m.ts, "outgoing" to m.outgoing)
        })
        val scopes = d.scopes.entries.joinToString(",", "{", "}") { MiniJson.quote(it.key) + ":" + MiniJson.quote(it.value) }
        return "{\"format\":\"$FORMAT\",\"version\":$VERSION,\"created\":${MiniJson.quote(iso(d.nowMs))}," +
            "\"contacts\":$contacts,\"radioMessages\":$radio,\"netMessages\":$net," +
            "\"geofences\":${GeoStore.fencesJson(d.fences)},\"geofenceEvents\":${GeoStore.eventsJson(d.events)}," +
            "\"regions\":${arr(d.regions.map { MiniJson.quote(it) })},\"regionScopes\":$scopes}"
    }

    // ---------------------------------------------------------------- restore

    fun validRegion(name: String) =
        name.isNotEmpty() && name.length <= 29 && name.all { it in 'a'..'z' || it in '0'..'9' || it == '-' }

    /** The settings in a backup, or an error in plain words. Anything invalid inside is skipped, never trusted. */
    fun parse(text: String): Result<Restored> {
        if (text.length > MAX_RESTORE_BYTES) return Result.failure(IllegalArgumentException("that file is too big to be a backup"))
        val root = MiniJson.parseObject(text.removePrefix("﻿")) ?: return Result.failure(IllegalArgumentException("that is not a backup file (not JSON)"))
        if (root["format"] != FORMAT) return Result.failure(IllegalArgumentException("that is not an Ultimate MeshCore backup"))
        if ((root["version"] as? Number)?.toLong() != VERSION) return Result.failure(IllegalArgumentException("that backup is from a different version of the app"))
        val regions = (root["regions"] as? List<*> ?: emptyList<Any?>()).mapNotNull { it as? String }.filter { validRegion(it) }.distinct().take(MAX_REGIONS)
        val scopes = LinkedHashMap<String, String>()
        (root["regionScopes"] as? Map<*, *>)?.forEach { (k, v) ->
            if (k is String && v is String && k.isNotBlank() && k.length <= 64 && validRegion(v) && scopes.size < MAX_SCOPES) scopes[k] = v
        }
        return Result.success(Restored(GeoStore.parseFences(root["geofences"]), GeoStore.parseEvents(root["geofenceEvents"]), regions, scopes))
    }
}
