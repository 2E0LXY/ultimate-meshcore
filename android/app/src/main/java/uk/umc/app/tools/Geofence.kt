package uk.umc.app.tools

import uk.umc.app.net.MiniJson
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/** A circle on the map that raises an alert when a node crosses it. */
data class Geofence(val id: String, val name: String, val lat: Double, val lon: Double, val radiusM: Double)

enum class FenceEvent { ENTER, EXIT }

/** One crossing: [node] is the contact's public key, [nodeName] its name when it happened. */
data class FenceHit(
    val fenceId: String, val fenceName: String, val node: String, val nodeName: String,
    val event: FenceEvent, val atMs: Long, val lat: Double, val lon: Double, val distanceM: Double,
) {
    val summary get() = "$nodeName ${if (event == FenceEvent.ENTER) "entered" else "left"} $fenceName"
}

object Geo {
    private const val EARTH_M = 6_371_008.8

    fun haversineM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val p1 = Math.toRadians(lat1); val p2 = Math.toRadians(lat2)
        val dp = p2 - p1; val dl = Math.toRadians(lon2 - lon1)
        val a = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
        return 2 * EARTH_M * asin(min(1.0, sqrt(a)))
    }

    /** A usable position: finite, in range, and not the 0,0 a node reports when it has no fix. */
    fun validPosition(lat: Double, lon: Double): Boolean =
        lat.isFinite() && lon.isFinite() && lat in -90.0..90.0 && lon in -180.0..180.0 && !(lat == 0.0 && lon == 0.0)
}

object Fences {
    const val MAX_FENCES = 50
    const val MAX_NAME = 40
    const val MIN_RADIUS_M = 10.0
    const val MAX_RADIUS_M = 500_000.0

    const val MAX_ID = 128

    /** A decimal number as typed on a phone: accepts a comma as the decimal separator ("53,7"). Null if not a finite number. */
    fun parseNumber(text: String): Double? {
        val t = text.trim()
        val n = when {
            t.count { it == ',' } == 1 && '.' !in t -> t.replace(',', '.')
            ',' in t -> return null            // "1,234.5": ambiguous, ask the user to retype
            else -> t
        }
        return n.toDoubleOrNull()?.takeIf { it.isFinite() }
    }

    /** An error in plain words, or null if the fence is usable. */
    fun validate(f: Geofence): String? = when {
        f.name.isBlank() -> "give the fence a name"
        f.name.length > MAX_NAME -> "the name is longer than $MAX_NAME characters"
        !Geo.validPosition(f.lat, f.lon) -> "the position is not valid (latitude -90 to 90, longitude -180 to 180, not 0,0)"
        !f.radiusM.isFinite() || f.radiusM < MIN_RADIUS_M || f.radiusM > MAX_RADIUS_M -> "the radius must be ${MIN_RADIUS_M.toInt()} m to ${(MAX_RADIUS_M / 1000).toInt()} km"
        else -> null
    }
}

/**
 * Decides when a node has entered or left a fence. A node is inside from the moment it is first seen
 * within the radius; it must then be more than [hysteresis] outside the radius to count as left, and
 * more than [hysteresis] inside to count as entered again, so a position wobbling at the edge
 * does not flap. [minIntervalMs] also limits each node and fence pair to one alert per interval:
 * a crossing that comes too soon is held back (not lost) and reported later if it still holds.
 * The first sighting of a node only sets its state: no alert, so a restart does not announce everyone.
 */
class GeofenceEngine(private val hysteresis: Double = 0.10, private val minIntervalMs: Long = 60_000L) {
    private class State(var inside: Boolean, var lastEventMs: Long)
    private val states = HashMap<String, State>()

    @Synchronized
    fun update(node: String, nodeName: String, lat: Double, lon: Double, nowMs: Long, fences: List<Geofence>): List<FenceHit> {
        val ids = fences.mapTo(HashSet()) { it.id }
        states.keys.removeAll { it.substringAfter('\u0000') !in ids }       // fences that were deleted
        if (!Geo.validPosition(lat, lon)) return emptyList()
        val hits = ArrayList<FenceHit>()
        for (f in fences) {
            if (Fences.validate(f) != null) continue
            val d = Geo.haversineM(lat, lon, f.lat, f.lon)
            val k = node + '\u0000' + f.id
            val st = states[k]
            if (st == null) { states[k] = State(d <= f.radiusM, Long.MIN_VALUE); continue }
            val event = when {
                st.inside && d > f.radiusM * (1 + hysteresis) -> FenceEvent.EXIT
                !st.inside && d < f.radiusM * (1 - hysteresis) -> FenceEvent.ENTER
                else -> null
            } ?: continue
            // a negative gap (the phone's clock went back) counts as time elapsed, so it cannot silence a fence
            if (st.lastEventMs != Long.MIN_VALUE && nowMs - st.lastEventMs in 0 until minIntervalMs) continue
            st.inside = event == FenceEvent.ENTER
            st.lastEventMs = nowMs
            hits.add(FenceHit(f.id, f.name, node, nodeName, event, nowMs, lat, lon, d))
        }
        return hits
    }

    @Synchronized fun reset() = states.clear()
}

/** The fences and the bounded event history, as text for the phone's own file (and the backup). */
object GeoStore {
    const val MAX_EVENTS = 500
    private const val VERSION = 1L

    /** The outcome of merging fences: [added] are new, [replaced] had the same id, [skipped] were invalid or did not fit under the cap. */
    data class FenceMerge(val fences: List<Geofence>, val added: Int, val replaced: Int, val skipped: Int)

    /**
     * Fences from a backup replace those with the same id; the rest stay. New ones are added while there is room
     * under [Fences.MAX_FENCES]; the rest are counted as skipped rather than lost silently.
     */
    fun mergeFencesReport(old: List<Geofence>, incoming: List<Geofence>): FenceMerge {
        val inc = incoming.distinctBy { it.id }
        val oldIds = old.mapTo(HashSet()) { it.id }
        var added = 0; var replaced = 0; var skipped = 0
        val usable = inc.filter { (Fences.validate(it) == null && it.id.isNotEmpty() && it.id.length <= Fences.MAX_ID).also { ok -> if (!ok) skipped++ } }
        val result = old.filter { o -> usable.none { it.id == o.id } }.toMutableList()      // an invalid replacement never deletes the fence it names
        // replacements first: they take the slot of the fence they replace, so they must never be crowded out by new ones
        for (f in usable) if (f.id in oldIds) { result.add(f); replaced++ }
        for (f in usable) if (f.id !in oldIds) { if (result.size < Fences.MAX_FENCES) { result.add(f); added++ } else skipped++ }
        return FenceMerge(result, added, replaced, skipped)
    }

    fun mergeFences(old: List<Geofence>, incoming: List<Geofence>): List<Geofence> = mergeFencesReport(old, incoming).fences

    fun mergeEvents(old: List<FenceHit>, incoming: List<FenceHit>): List<FenceHit> =
        (old + incoming).distinctBy { listOf(it.fenceId, it.node, it.event, it.atMs) }.sortedBy { it.atMs }.takeLast(MAX_EVENTS)

    fun appendEvents(old: List<FenceHit>, add: List<FenceHit>): List<FenceHit> = (old + add).takeLast(MAX_EVENTS)

    fun fencesJson(fences: List<Geofence>): String =
        fences.joinToString(",", "[", "]") { MiniJson.obj("id" to it.id, "n" to it.name, "lat" to it.lat, "lon" to it.lon, "r" to it.radiusM) }

    fun eventsJson(events: List<FenceHit>): String =
        events.takeLast(MAX_EVENTS).joinToString(",", "[", "]") {
            MiniJson.obj("f" to it.fenceId, "fn" to it.fenceName, "k" to it.node, "kn" to it.nodeName, "e" to it.event.name,
                "at" to it.atMs, "lat" to it.lat, "lon" to it.lon, "d" to it.distanceM)
        }

    fun encode(fences: List<Geofence>, events: List<FenceHit>): String =
        "{\"v\":$VERSION,\"fences\":${fencesJson(fences)},\"events\":${eventsJson(events)}}"

    fun decode(text: String): Pair<List<Geofence>, List<FenceHit>> = decodeOrNull(text) ?: Pair(emptyList(), emptyList())

    /** Null if the text is not a readable store at all (damaged file), as opposed to a readable one with nothing in it. */
    fun decodeOrNull(text: String): Pair<List<Geofence>, List<FenceHit>>? {
        val root = MiniJson.parseObject(text) ?: return null
        return Pair(parseFences(root["fences"]), parseEvents(root["events"]))
    }

    /** Which copy [load] used. */
    enum class Source { MAIN, BACKUP, NONE }
    data class Loaded(val fences: List<Geofence>, val events: List<FenceHit>, val source: Source)

    /** The main file if it is readable, else the last good copy, else nothing. A damaged file never hides a good backup copy. */
    fun load(main: String?, backup: String?): Loaded {
        main?.let { m -> decodeOrNull(m)?.let { return Loaded(it.first, it.second, Source.MAIN) } }
        backup?.let { b -> decodeOrNull(b)?.let { return Loaded(it.first, it.second, Source.BACKUP) } }
        return Loaded(emptyList(), emptyList(), Source.NONE)
    }

    private const val MAX_TEXT = 64
    private const val MIN_AT_MS = 0L
    private const val MAX_AT_MS = 32_503_680_000_000L      // year 3000

    private fun finite(n: Any?): Double? = (n as? Number)?.toDouble()?.takeIf { it.isFinite() }

    /** Skips anything damaged or invalid, and anything past the limits. */
    fun parseFences(v: Any?): List<Geofence> =
        (v as? List<*> ?: emptyList<Any?>()).mapNotNull { e ->
            val o = e as? Map<*, *> ?: return@mapNotNull null
            runCatching {
                Geofence(o["id"] as String, o["n"] as String, (o["lat"] as Number).toDouble(), (o["lon"] as Number).toDouble(), (o["r"] as Number).toDouble())
            }.getOrNull()?.takeIf { it.id.isNotEmpty() && it.id.length <= Fences.MAX_ID && Fences.validate(it) == null }
        }.distinctBy { it.id }.take(Fences.MAX_FENCES)

    /** Skips entries that are damaged, non-finite, out of range or oversized; names are cut to a sane length. */
    fun parseEvents(v: Any?): List<FenceHit> =
        (v as? List<*> ?: emptyList<Any?>()).mapNotNull { e ->
            val o = e as? Map<*, *> ?: return@mapNotNull null
            runCatching {
                val at = finite(o["at"]) ?: return@runCatching null
                val lat = finite(o["lat"]) ?: return@runCatching null
                val lon = finite(o["lon"]) ?: return@runCatching null
                val d = finite(o["d"]) ?: return@runCatching null
                val fid = o["f"] as String; val node = o["k"] as String
                if (at < MIN_AT_MS || at > MAX_AT_MS || lat !in -90.0..90.0 || lon !in -180.0..180.0 || d < 0.0 || d > 40_100_000.0) return@runCatching null
                if (fid.isEmpty() || fid.length > Fences.MAX_ID || node.isEmpty() || node.length > Fences.MAX_ID) return@runCatching null
                FenceHit(fid, (o["fn"] as String).take(MAX_TEXT), node, (o["kn"] as String).take(MAX_TEXT),
                    FenceEvent.valueOf(o["e"] as String), at.toLong(), lat, lon, d)
            }.getOrNull()
        }.takeLast(MAX_EVENTS)
}
