package uk.umc.app.net

/**
 * The phone's own copy of the UMC Net messages, so history survives a restart or being offline.
 * Pure Kotlin: text in, text out. [UmcNet] does the file work. Only the last [MAX_AGE_MS], at most [MAX_MESSAGES], are kept.
 */
object NetStore {
    const val MAX_AGE_MS = 24 * 3600_000L
    const val MAX_MESSAGES = 500
    private const val VERSION = 1L

    fun encode(messages: List<NetMessage>, nowMs: Long): String {
        val keep = messages.filter { it.seenMs >= nowMs - MAX_AGE_MS }.sortedWith(compareBy({ it.ts }, { it.seenMs })).takeLast(MAX_MESSAGES)
        val items = keep.joinToString(",") { m ->
            val heard = m.heard.joinToString(",") { h ->
                MiniJson.obj("i" to h.id, "hp" to h.hops.toLong(), "snr" to h.snr?.takeIf { it.isFinite() }, "rssi" to h.rssi?.toLong(), "at" to h.atMs, "sent" to h.sent)
            }
            MiniJson.obj("k" to m.key, "c" to m.channel, "r" to m.region, "s" to m.sender, "t" to m.text, "ts" to m.ts, "seen" to m.seenMs, "o" to m.outgoing)
                .dropLast(1) + ",\"h\":[" + heard + "]}"
        }
        return "{\"v\":$VERSION,\"m\":[$items]}"
    }

    /** The kept messages, newest window only. Anything unreadable gives an empty list (or skips that one message). */
    fun decode(text: String, nowMs: Long): List<NetMessage> {
        val root = MiniJson.parseObject(text) ?: return emptyList()
        if ((root["v"] as? Number)?.toLong() != VERSION) return emptyList()
        val arr = root["m"] as? List<*> ?: return emptyList()
        val out = ArrayList<NetMessage>()
        for (e in arr) {
            val o = e as? Map<*, *> ?: continue
            val m = runCatching {
                val heard = (o["h"] as? List<*> ?: emptyList<Any?>()).mapNotNull { x ->
                    val h = x as? Map<*, *> ?: return@mapNotNull null
                    Heard(h["i"] as String, (h["hp"] as Number).toInt(), (h["snr"] as? Number)?.toDouble(), (h["rssi"] as? Number)?.toInt(),
                        (h["at"] as Number).toLong(), h["sent"] as? Boolean ?: false)
                }
                NetMessage(o["k"] as String, o["c"] as String, o["r"] as? String ?: "", o["s"] as? String ?: "", o["t"] as String,
                    (o["ts"] as Number).toLong(), (o["seen"] as Number).toLong(), o["o"] as? Boolean ?: false, heard)
            }.getOrNull() ?: continue
            if (m.seenMs >= nowMs - MAX_AGE_MS) out.add(m)
        }
        return out.sortedWith(compareBy({ it.ts }, { it.seenMs })).takeLast(MAX_MESSAGES)
    }
}
