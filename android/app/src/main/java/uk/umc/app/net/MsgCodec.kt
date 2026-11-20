package uk.umc.app.net

import java.security.MessageDigest
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/*
 * UMC Net messaging codec: reads and builds MeshCore group (channel) packets exactly as they go over the air.
 * A Kotlin port of server/umcnet/dash/umcnet_msgs.py (the reference, tested against the firmware). Pure Kotlin on
 * the JVM, no Android imports, so it is unit-tested on a computer. AES and HMAC come from javax.crypto.
 */

/** A channel as the codec needs it: a 16-byte AES key, the 32-byte MAC secret and the 1-byte hash that names it on the air. */
class NetChannel private constructor(val name: String, val key: ByteArray, val secret: ByteArray, val hash: Int) {
    companion object {
        /** [pskBase64] is a 16 or 32 byte key; without it the name must be a #hashtag, whose key is derived from the name. */
        fun of(name: String, pskBase64: String? = null): NetChannel {
            val raw: ByteArray = if (!pskBase64.isNullOrBlank()) {
                val r = try { Base64.getDecoder().decode(pskBase64.trim()) } catch (e: IllegalArgumentException) { throw IllegalArgumentException("that key is not valid base64") }
                require(r.size == 16 || r.size == 32) { "a channel key is 16 or 32 bytes (base64)" }
                r
            } else if (name.startsWith("#") && name.length > 1) {
                MsgCodec.hashtagKey(name)
            } else throw IllegalArgumentException("a channel needs a key, or a name that starts with #")
            val secret = raw.copyOf(32)                                   // zero-padded, as the firmware keeps it
            val hash = MessageDigest.getInstance("SHA-256").digest(raw)[0].toInt() and 0xFF
            return NetChannel(name, raw.copyOf(16), secret, hash)
        }
    }
}

class WirePacket(val route: Int, val ptype: Int, val codes: Pair<Int, Int>?, val path: List<ByteArray>, val payload: ByteArray)

class GroupText(val channel: NetChannel, val timestamp: Long, val flags: Int, val text: String)

object MsgCodec {
    /** MeshCore's well-known Public channel key. */
    const val PUBLIC_PSK = "izOH6cXN6mrJ5e26oRXNcg=="
    const val PTYPE_GROUP_TEXT = 5
    const val MAX_TEXT_BYTES = 130
    const val MAX_PER_MINUTE = 6

    fun sha256(b: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(b)

    fun hmac(key: ByteArray, data: ByteArray): ByteArray {
        val m = Mac.getInstance("HmacSHA256"); m.init(SecretKeySpec(key, "HmacSHA256")); return m.doFinal(data)
    }

    /** A #hashtag channel's key (and a region's key): SHA-256 of the name as written, first 16 bytes. */
    fun hashtagKey(name: String): ByteArray = sha256(name.toByteArray(Charsets.UTF_8)).copyOf(16)

    fun regionKey(name: String): ByteArray = hashtagKey("#" + name.trimStart('#'))

    fun regionCode(key16: ByteArray, ptype: Int, payload: ByteArray): Int {
        val d = hmac(key16, byteArrayOf(ptype.toByte()) + payload)
        val c = (d[0].toInt() and 0xFF) or ((d[1].toInt() and 0xFF) shl 8)
        return if (c == 0) 1 else if (c == 0xFFFF) 0xFFFE else c
    }

    fun publicChannel(): NetChannel = NetChannel.of("Public", PUBLIC_PSK)

    // ---------------------------------------------------------------- AES-128 ECB, zero-padded like the firmware
    private fun aes(key: ByteArray, data: ByteArray, encrypt: Boolean): ByteArray {
        val c = Cipher.getInstance("AES/ECB/NoPadding")
        c.init(if (encrypt) Cipher.ENCRYPT_MODE else Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"))
        val d = if (encrypt && data.size % 16 != 0) data.copyOf(data.size + 16 - data.size % 16) else data
        val whole = d.size - d.size % 16
        return if (whole == 0) ByteArray(0) else c.doFinal(d, 0, whole)
    }

    // ---------------------------------------------------------------- reading
    /** Header, transport codes, path and payload of a packet as heard on the air, or null. */
    fun parseWire(raw: ByteArray): WirePacket? {
        try {
            if (raw.isEmpty()) return null
            val h = raw[0].toInt() and 0xFF
            val route = h and 3; val ptype = (h shr 2) and 15
            var i = 1; var codes: Pair<Int, Int>? = null
            if (route == 0 || route == 3) {
                if (raw.size < i + 4) return null
                codes = Pair(u16(raw, i), u16(raw, i + 2)); i += 4
            }
            if (i >= raw.size) return null
            val pl = raw[i].toInt() and 0xFF; i++
            val count = pl and 63; val size = (pl shr 6) + 1
            if (size > 3 || i + count * size > raw.size) return null
            val path = (0 until count).map { k -> raw.copyOfRange(i + k * size, i + (k + 1) * size) }
            i += count * size
            return WirePacket(route, ptype, codes, path, raw.copyOfRange(i, raw.size))
        } catch (e: Exception) { return null }
    }

    private fun u16(b: ByteArray, i: Int) = (b[i].toInt() and 0xFF) or ((b[i + 1].toInt() and 0xFF) shl 8)

    /** The first channel whose hash and MAC match, with the timestamp, flags and text; null if none can read it. */
    fun decryptGroup(channels: List<NetChannel>, payload: ByteArray): GroupText? {
        if (payload.size < 1 + 2 + 16) return null
        for (ch in channels) {
            if (ch.hash != (payload[0].toInt() and 0xFF)) continue
            val mac = payload.copyOfRange(1, 3); val cipher = payload.copyOfRange(3, payload.size)
            if (cipher.size % 16 != 0) continue
            if (!MessageDigest.isEqual(hmac(ch.secret, cipher).copyOf(2), mac)) continue
            val plain = aes(ch.key, cipher, false)
            if (plain.size < 6) continue
            val ts = (plain[0].toLong() and 0xFF) or ((plain[1].toLong() and 0xFF) shl 8) or ((plain[2].toLong() and 0xFF) shl 16) or ((plain[3].toLong() and 0xFF) shl 24)
            val flags = plain[4].toInt() and 0xFF
            var end = 5; while (end < plain.size && plain[end] != 0.toByte()) end++
            return GroupText(ch, ts, flags, String(plain, 5, end - 5, Charsets.UTF_8))
        }
        return null
    }

    /** MeshCore puts "sender: message" in the text. */
    fun splitSender(text: String): Pair<String, String> {
        val head = text.take(40)
        val at = head.indexOf(": ")
        return if (at >= 0) Pair(text.substring(0, at), text.substring(at + 2)) else Pair("", text)
    }

    /** Name of the region a scoped packet was sent into (from its transport code), or "". */
    fun findRegion(regions: List<String>, p: WirePacket): String {
        val c = p.codes ?: return ""
        return regions.firstOrNull { regionCode(regionKey(it), p.ptype, p.payload) == c.first } ?: ""
    }

    /** First 20 hex characters of the SHA-1 of the payload: what identifies one message however many repeaters report it. */
    fun pktKey(payload: ByteArray): String = toHex(MessageDigest.getInstance("SHA-1").digest(payload)).substring(0, 20).lowercase()

    // ---------------------------------------------------------------- sending
    /** The raw packet a radio would send for this group message (flood, or flood scoped to a region). */
    fun buildGroupText(ch: NetChannel, sender: String, text: String, ts: Long, region: String? = null): ByteArray {
        val msg = "$sender: $text".toByteArray(Charsets.UTF_8)
        val body = ByteArray(5 + msg.size)
        for (k in 0..3) body[k] = (ts shr (8 * k)).toByte()
        body[4] = 0
        System.arraycopy(msg, 0, body, 5, msg.size)
        require(body.size <= 5 + 160) { "that message is too long" }
        val cipher = aes(ch.key, body, true)
        val payload = byteArrayOf(ch.hash.toByte()) + hmac(ch.secret, cipher).copyOf(2) + cipher
        if (!region.isNullOrEmpty()) {
            val code = regionCode(regionKey(region), PTYPE_GROUP_TEXT, payload)
            return byteArrayOf(((PTYPE_GROUP_TEXT shl 2) or 0).toByte(), code.toByte(), (code shr 8).toByte(), 0, 0, 0) + payload
        }
        return byteArrayOf(((PTYPE_GROUP_TEXT shl 2) or 1).toByte(), 0) + payload
    }

    // ---------------------------------------------------------------- hex and base64url
    fun toHex(b: ByteArray): String { val sb = StringBuilder(b.size * 2); for (x in b) sb.append("%02X".format(x.toInt() and 0xFF)); return sb.toString() }

    /** Null if the text is not an even-length hex string. */
    fun fromHex(s: String): ByteArray? {
        val t = s.trim()
        if (t.length % 2 != 0 || !t.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }) return null
        return ByteArray(t.length / 2) { t.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    }

    fun b64urlDecode(s: String): ByteArray? = try { Base64.getUrlDecoder().decode(s.trim()) } catch (e: IllegalArgumentException) { null }
    fun b64urlEncode(b: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(b)
}

/** What the dash checks before it sends (send_message in umcnet_dash.py). Returns an error in plain words, or null if fine. */
object SendRules {
    private val SENDER = Regex("^[A-Za-z0-9][A-Za-z0-9 ._-]{0,23}$")
    fun check(text: String, sender: String, region: String?, regions: List<String>): String? {
        val t = text.trim()
        if (t.isEmpty()) return "type a message first"
        if (t.toByteArray(Charsets.UTF_8).size > MsgCodec.MAX_TEXT_BYTES) return "that message is too long (${MsgCodec.MAX_TEXT_BYTES} bytes at most)"
        if (t.any { it.code < 32 }) return "no line breaks"
        if (!SENDER.matches(sender.trim())) return "the sender name is 1 to 24 letters, digits, spaces, dots, dashes or underscores"
        if (!region.isNullOrEmpty() && region.trimStart('#') !in regions) return "that region is not in the list"
        return null
    }
}

/** At most [max] messages in any [windowMs]; the clock is passed in so it can be tested. */
class SendLimiter(private val max: Int = MsgCodec.MAX_PER_MINUTE, private val windowMs: Long = 60_000) {
    private val times = ArrayDeque<Long>()
    @Synchronized fun tryAcquire(nowMs: Long): Boolean {
        while (times.isNotEmpty() && nowMs - times.first() > windowMs) times.removeFirst()
        if (times.size >= max) return false
        times.addLast(nowMs); return true
    }
}
