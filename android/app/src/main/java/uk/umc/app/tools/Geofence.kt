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
            if (st.lastEventMs != Long.MIN_VALUE && nowMs - st.lastEventMs < minIntervalMs) continue
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

    /** Fences from a backup replace those with the same id; the rest stay. */
    fun mergeFences(old: List<Geofence>, incoming: List<Geofence>): List<Geofence> =
        (old.filter { o -> incoming.none { it.id == o.id } } + incoming).take(Fences.MAX_FENCES)

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

    fun decode(text: String): Pair<List<Geofence>, List<FenceHit>> {
        val root = MiniJson.parseObject(text) ?: return Pair(emptyList(), emptyList())
        return Pair(parseFences(root["fences"]), parseEvents(root["events"]))
    }

    /** Skips anything damaged or invalid, and anything past the limits. */
    fun parseFences(v: Any?): List<Geofence> =
        (v as? List<*> ?: emptyList<Any?>()).mapNotNull { e ->
            val o = e as? Map<*, *> ?: return@mapNotNull null
            runCatching {
                Geofence(o["id"] as String, o["n"] as String, (o["lat"] as Number).toDouble(), (o["lon"] as Number).toDouble(), (o["r"] as Number).toDouble())
            }.getOrNull()?.takeIf { it.id.isNotEmpty() && Fences.validate(it) == null }
        }.distinctBy { it.id }.take(Fences.MAX_FENCES)

    fun parseEvents(v: Any?): List<FenceHit> =
        (v as? List<*> ?: emptyList<Any?>()).mapNotNull { e ->
            val o = e as? Map<*, *> ?: return@mapNotNull null
            runCatching {
                FenceHit(o["f"] as String, o["fn"] as String, o["k"] as String, o["kn"] as String, FenceEvent.valueOf(o["e"] as String),
                    (o["at"] as Number).toLong(), (o["lat"] as Number).toDouble(), (o["lon"] as Number).toDouble(), (o["d"] as Number).toDouble())
            }.getOrNull()
        }.takeLast(MAX_EVENTS)
}
