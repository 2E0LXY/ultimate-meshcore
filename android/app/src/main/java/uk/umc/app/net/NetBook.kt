package uk.umc.app.net

/** One repeater's report of a message: it heard it ([sent] false) or transmitted it ([sent] true). */
data class Heard(val id: String, val hops: Int, val snr: Double?, val rssi: Int?, val atMs: Long, val sent: Boolean = false)

data class NetMessage(
    val key: String, val channel: String, val region: String, val sender: String, val text: String,
    val ts: Long, val seenMs: Long, val outgoing: Boolean, val heard: List<Heard>,
)

data class Repeater(val id: String, val name: String, val status: String, val lastMs: Long) {
    /** Online if it said so (its status is retained), or if it is not marked offline and has been heard from lately. */
    fun online(nowMs: Long) = status == "online" || (status != "offline" && lastMs > 0 && nowMs - lastMs < 10 * 60_000)
    val label get() = name.ifBlank { id.take(8) }
}

/** The pure bookkeeping of UMC Net messages: de-duplicates what several repeaters report, keeps who heard and who sent. */
class NetBook(private val maxMessages: Int = 500) {
    private val byKey = LinkedHashMap<String, NetMessage>()

    @Synchronized fun messages(): List<NetMessage> = byKey.values.sortedWith(compareBy({ it.seenMs }, { it.ts }))

    /** A repeater [deviceId] heard [raw] on the air. Returns true if the book changed. Packets we cannot read are ignored. */
    @Synchronized fun onHeard(deviceId: String, raw: ByteArray, snr: Double?, rssi: Int?, nowMs: Long, channels: List<NetChannel>, regions: List<String>): Boolean {
        val p = MsgCodec.parseWire(raw) ?: return false
        if (p.ptype != MsgCodec.PTYPE_GROUP_TEXT || p.payload.size < 19) return false
        val key = MsgCodec.pktKey(p.payload)
        val entry = Heard(deviceId, p.path.size, snr, rssi, nowMs)
        val old = byKey[key]
        if (old != null) {
            val region = if (old.region.isEmpty() || old.region == "?") regionOf(p, regions) else old.region
            val mine = old.heard.firstOrNull { it.id == deviceId && !it.sent }
            val heard = when {
                mine == null -> old.heard + entry
                entry.hops < mine.hops -> old.heard.map { if (it === mine) entry else it }
                else -> return false
            }
            byKey[key] = old.copy(heard = heard, region = region); return true
        }
        val g = MsgCodec.decryptGroup(channels, p.payload) ?: return false
        val (sender, body) = MsgCodec.splitSender(g.text)
        byKey[key] = NetMessage(key, g.channel.name, regionOf(p, regions), sender, body, g.timestamp, nowMs, false, listOf(entry))
        trim(); return true
    }

    private fun regionOf(p: WirePacket, regions: List<String>) = if (p.codes == null) "" else MsgCodec.findRegion(regions, p).ifEmpty { "?" }

    /** Records a message this app just built and published. */
    @Synchronized fun addOutgoing(raw: ByteArray, channel: String, region: String, sender: String, text: String, ts: Long, nowMs: Long): String {
        val p = MsgCodec.parseWire(raw) ?: throw IllegalArgumentException("not a packet")
        val key = MsgCodec.pktKey(p.payload)
        byKey[key] = NetMessage(key, channel, region, sender, text, ts, nowMs, true, emptyList()); trim(); return key
    }

    /** A repeater reports it transmitted [raw]: if that is one of our messages, record it as sent by that repeater. */
    @Synchronized fun onSent(deviceId: String, raw: ByteArray, nowMs: Long): Boolean {
        val p = MsgCodec.parseWire(raw) ?: return false
        if (p.ptype != MsgCodec.PTYPE_GROUP_TEXT || p.payload.size < 19) return false
        val m = byKey[MsgCodec.pktKey(p.payload)] ?: return false
        if (!m.outgoing || m.heard.any { it.id == deviceId && it.sent }) return false
        byKey[m.key] = m.copy(heard = m.heard + Heard(deviceId, 0, null, null, nowMs, true)); return true
    }

    @Synchronized fun clear() = byKey.clear()

    private fun trim() { while (byKey.size > maxMessages) byKey.remove(byKey.keys.first()) }
}

/** The words under a bubble, following the dashboard's wording (dash.html). */
object Delivery {
    fun hopWords(h: Int) = if (h == 0) "direct" else if (h == 1) "1 hop" else "$h hops"
    private fun one(h: Heard, name: (String) -> String) = name(h.id) + " " + hopWords(h.hops) + (h.snr?.let { " · ${trimNum(it)} dB" } ?: "")
    private fun trimNum(d: Double) = if (d == Math.floor(d)) d.toLong().toString() else d.toString()
    const val AGED_MS = 30_000L
    const val TOOLTIP = "Channel messages have no read receipt. 'sent by' means that repeater put it on the air; 'heard back' means another repeater picked it up. Neither shows whether a person read it."

    /** (text, nothingConfirmed). For a message we sent: who sent it and who heard it back; for one we heard: who heard it. */
    fun text(m: NetMessage, nowMs: Long, name: (String) -> String): Pair<String, Boolean> {
        val sentBy = m.heard.filter { it.sent }; val heard = m.heard.filter { !it.sent }
        if (!m.outgoing) return Pair(if (heard.isEmpty()) "" else "heard by " + heard.joinToString("  |  ") { one(it, name) }, false)
        val aged = nowMs - m.seenMs > AGED_MS
        val parts = ArrayList<String>(); var none = false
        if (sentBy.isNotEmpty()) parts.add("sent by " + sentBy.joinToString(", ") { name(it.id) })
        if (heard.isNotEmpty()) parts.add("heard back by ${heard.size} repeater${if (heard.size == 1) "" else "s"}: " + heard.joinToString("  |  ") { one(it, name) })
        else if (sentBy.isNotEmpty() && aged) parts.add("not heard back by another repeater (it may still have reached people)")
        else if (sentBy.isEmpty()) { parts.add(if (aged) "no repeater has confirmed sending this" else "waiting for a repeater to send it"); none = aged }
        return Pair(parts.joinToString(" · "), none)
    }

    /** The repeater to reply through: of those that heard the message, the fewest hops, then the best SNR. Null if none. */
    fun replyVia(m: NetMessage): String? =
        m.heard.filter { !it.sent }.sortedWith(compareBy<Heard>({ it.hops }, { -(it.snr ?: -99.0) })).firstOrNull()?.id
}
