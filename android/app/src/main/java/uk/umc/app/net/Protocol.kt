package uk.umc.app.net

import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/** Topics and JSON of the UMC Net broker, as the dashboard uses them (umcnet_dash.py on_publish and send_message). Pure Kotlin. */
object Protocol {
    class Topic(val area: String, val deviceId: String, val kind: String)

    private val TOPIC = Regex("^meshcore/([^/]+)/([0-9A-Fa-f]{64})/(raw|packets|status|telemetry)$")
    fun parseTopic(t: String): Topic? = TOPIC.matchEntire(t)?.let { Topic(it.groupValues[1], it.groupValues[2].uppercase(), it.groupValues[3]) }

    fun subscriptions(area: String, clientId: String) =
        listOf("meshcore/$area/+/raw", "meshcore/$area/+/status", "meshcore/$area/+/packets", "meshcore/$area/+/telemetry", replayTopic(area, clientId))
    fun publishTopic(area: String, clientId: String) = "meshcore/$area/$clientId/raw"

    /** Store-and-forward catch-up: we publish a request on [replayRequestTopic]; the dashboard answers on [replayTopic]. */
    const val REPLAY_WINDOW_S = 3600L
    fun replayRequestTopic(area: String, clientId: String) = "umcnet/v1/$area/replay/req/$clientId"
    fun replayTopic(area: String, clientId: String) = "umcnet/v1/$area/replay/$clientId"
    fun buildReplayRequest(since: Long) = MiniJson.obj("since" to since)
    /** The "since" to ask for: our newest held packet time, but never more than an hour back. */
    fun replaySince(lastSeenS: Long, nowS: Long) = maxOf(lastSeenS, nowS - REPLAY_WINDOW_S)

    /** The Cayenne LPP bytes (hex) in a repeater's telemetry message, or null. */
    fun parseTelemetryHex(payload: ByteArray): String? =
        (MiniJson.parseObject(String(payload, Charsets.UTF_8))?.get("lpp") as? String)?.takeIf { it.length in 2..400 && it.length % 2 == 0 }

    /** What a repeater reported: a packet it heard ("rx") or sent ("tx"), or its status. */
    class Report(val kind: String, val deviceId: String, val name: String, val status: String?, val direction: String,
                 val raw: ByteArray?, val snr: Double?, val rssi: Int?, val originId: String,
                 /** True for a replayed (catch-up) packet; [timestampS] is then its own time, unix seconds (0 if absent). */
                 val replay: Boolean = false, val timestampS: Long = 0L,
                 /** For kind "done": the dashboard's count of replayed packets. */
                 val count: Int = 0)

    private fun num(v: Any?): Double? = when (v) { is Number -> v.toDouble(); is String -> v.trim().toDoubleOrNull(); else -> null }

    /** Reads one broker message. Null if the topic or JSON is not one we understand. */
    fun parseReport(topic: String, payload: ByteArray): Report? {
        val t = parseTopic(topic) ?: return null
        val j = MiniJson.parseObject(String(payload, Charsets.UTF_8)) ?: return null
        val hex = (if (t.kind == "raw") j["data"] else j["raw"]) as? String
        val raw = if (t.kind == "status") null else hex?.let { MsgCodec.fromHex(it) }
        val dir = if (t.kind == "packets") ((j["direction"] as? String) ?: "rx") else "rx"
        return Report(t.kind, t.deviceId, (j["origin"] as? String).orEmpty(), j["status"] as? String, dir, raw,
            num(j["SNR"]), num(j["RSSI"])?.toInt(), (j["origin_id"] as? String).orEmpty().uppercase())
    }

    /** Reads one message from the replay topic. A packet comes back as kind "raw" with replay = true and deviceId = the repeater (origin_id);
     *  the final {"done":1,"n":N} comes back as kind "done". Null if it is neither. */
    fun parseReplay(payload: ByteArray): Report? {
        val j = MiniJson.parseObject(String(payload, Charsets.UTF_8)) ?: return null
        if (num(j["done"]) != null) return Report("done", "", "", null, "rx", null, null, null, "", true, 0L, num(j["n"])?.toInt() ?: 0)
        val id = (j["origin_id"] as? String).orEmpty().uppercase()
        if (!Regex("^[0-9A-F]{64}$").matches(id)) return null
        val raw = (j["data"] as? String)?.let { MsgCodec.fromHex(it) } ?: return null
        val dir = if ((j["direction"] as? String) == "tx") "tx" else "rx"
        return Report("raw", id, (j["origin"] as? String).orEmpty(), null, dir, raw, num(j["snr"] ?: j["SNR"]), num(j["rssi"] ?: j["RSSI"])?.toInt(),
            id, true, num(j["timestamp"])?.toLong() ?: 0L)
    }

    private val ISO = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'.000Z'").withZone(ZoneOffset.UTC)

    /** The message to publish on [publishTopic]. [target] is a comma-separated list of repeater ids, empty for every bridging repeater. */
    fun txJson(origin: String, clientId: String, epochSeconds: Long, target: String, raw: ByteArray): String {
        val ts = ISO.format(java.time.Instant.ofEpochSecond(epochSeconds))
        val base = arrayListOf<Pair<String, Any?>>("origin" to origin, "origin_id" to clientId, "timestamp" to ts, "type" to "RAW")
        if (target.isNotEmpty()) base.add("target" to target)
        base.add("data" to MsgCodec.toHex(raw))
        return MiniJson.obj(*base.toTypedArray())
    }
}
