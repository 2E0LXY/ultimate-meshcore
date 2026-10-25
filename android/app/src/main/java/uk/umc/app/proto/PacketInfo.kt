package uk.umc.app.proto

/**
 * What a received packet says about itself, read from its bytes without decrypting anything:
 * an advert's sender (key and name), the one-byte hashes of the sender and destination of requests,
 * responses, messages and paths, a channel's hash, and the repeater that handed it to us (the last
 * hash in its path). Layout: header, optional 4 transport bytes, path length, path, payload.
 */
data class PacketInfo(
    val kind: String,
    val flood: Boolean,
    val hops: Int,
    val via: Int?,          // first byte of the last hash in the path
    val src: Int?,
    val dst: Int?,
    val chan: Int?,
    val key: String?,       // first four bytes of an advertiser's key, in hex
    val name: String,       // an advertiser's name, or empty
) {
    companion object {
        private val KINDS = arrayOf("REQ", "RSP", "MSG", "ACK", "ADV", "GRP", "GDAT", "ANON", "PATH", "TRACE", "PART", "CTRL")

        /** [raw] starts at the packet's header byte. Returns null when it is too short to read. */
        fun parse(raw: ByteArray): PacketInfo? {
            if (raw.isEmpty()) return null
            val header = raw[0].toInt() and 0xFF
            val route = header and 0x03
            val type = (header shr 2) and 0x0F
            var i = 1
            if (route == 0 || route == 3) i += 4                       // transport codes
            if (i >= raw.size) return null
            val pathLen = raw[i++].toInt() and 0xFF
            val count = pathLen and 63
            val size = (pathLen shr 6) + 1
            if (size > 3 || i + count * size > raw.size) return null
            val via = if (count > 0) raw[i + (count - 1) * size].toInt() and 0xFF else null
            i += count * size
            val p = raw.copyOfRange(i, raw.size)
            var src: Int? = null; var dst: Int? = null; var chan: Int? = null; var key: String? = null; var name = ""
            when (type) {
                0, 1, 2, 8 -> if (p.size >= 2) { dst = p[0].toInt() and 0xFF; src = p[1].toInt() and 0xFF }
                5, 6 -> if (p.isNotEmpty()) chan = p[0].toInt() and 0xFF
                4 -> if (p.size > 100) {
                    key = (0 until 4).joinToString("") { "%02X".format(p[it].toInt() and 0xFF) }
                    var j = 100                                                  // key 32, time 4, signature 64
                    val flags = p[j++].toInt() and 0xFF
                    if (flags and 0x10 != 0) j += 8
                    if (flags and 0x20 != 0) j += 2
                    if (flags and 0x40 != 0) j += 2
                    if (flags and 0x80 != 0 && j < p.size) name = String(p, j, p.size - j, Charsets.UTF_8).trimEnd('\u0000').trim()
                }
            }
            return PacketInfo(KINDS.getOrElse(type) { "RAW" }, route == 0 || route == 1, count, via, src, dst, chan, key, name)
        }
    }
}
