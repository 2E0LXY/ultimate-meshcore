package uk.umc.app.net

import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/** Topics and JSON of the UMC Net broker, as the dashboard uses them (umcnet_dash.py on_publish and send_message). Pure Kotlin. */
object Protocol {
    class Topic(val area: String, val deviceId: String, val kind: String)

    private val TOPIC = Regex("^meshcore/([^/]+)/([0-9A-Fa-f]{64})/(raw|packets|status)$")
    fun parseTopic(t: String): Topic? = TOPIC.matchEntire(t)?.let { Topic(it.groupValues[1], it.groupValues[2].uppercase(), it.groupValues[3]) }

    fun subscriptions(area: String) = listOf("meshcore/$area/+/raw", "meshcore/$area/+/status", "meshcore/$area/+/packets")
    fun publishTopic(area: String, clientId: String) = "meshcore/$area/$clientId/raw"

    /** What a repeater reported: a packet it heard ("rx") or sent ("tx"), or its status. */
    class Report(val kind: String, val deviceId: String, val name: String, val status: String?, val direction: String,
                 val raw: ByteArray?, val snr: Double?, val rssi: Int?, val originId: String)

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
