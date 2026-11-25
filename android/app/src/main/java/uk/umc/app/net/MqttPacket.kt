package uk.umc.app.net

import java.io.ByteArrayOutputStream

/** Minimal MQTT 3.1.1 packet codec (pure Kotlin, no Android imports). Client side only, QoS 0 out, QoS 0/1 in. */
object MqttPacket {
    private fun ByteArrayOutputStream.u16(v: Int) { write((v shr 8) and 0xFF); write(v and 0xFF) }
    private fun ByteArrayOutputStream.str(s: String) { val b = s.toByteArray(Charsets.UTF_8); u16(b.size); write(b) }
    private fun ByteArrayOutputStream.bin(b: ByteArray) { u16(b.size); write(b) }

    private fun frame(firstByte: Int, body: ByteArray): ByteArray {
        val out = ByteArrayOutputStream(body.size + 5)
        out.write(firstByte)
        var n = body.size
        do {
            var d = n % 128
            n /= 128
            if (n > 0) d = d or 0x80
            out.write(d)
        } while (n > 0)
        out.write(body)
        return out.toByteArray()
    }

    /** CONNECT, protocol level 4, clean session, username + password. */
    fun connect(clientId: String, user: String, password: String, keepAliveS: Int = 30): ByteArray {
        val b = ByteArrayOutputStream()
        b.str("MQTT"); b.write(4); b.write(0xC2); b.u16(keepAliveS)
        b.str(clientId); b.str(user); b.bin(password.toByteArray(Charsets.UTF_8))
        return frame(0x10, b.toByteArray())
    }

    /** SUBSCRIBE for the given filters, all QoS 0. */
    fun subscribe(packetId: Int, topics: List<String>): ByteArray {
        val b = ByteArrayOutputStream()
        b.u16(packetId)
        for (t in topics) { b.str(t); b.write(0) }
        return frame(0x82, b.toByteArray())
    }

    /** PUBLISH, QoS 0, not retained. */
    fun publish(topic: String, payload: ByteArray): ByteArray {
        val b = ByteArrayOutputStream(payload.size + topic.length + 2)
        b.str(topic); b.write(payload)
        return frame(0x30, b.toByteArray())
    }

    fun puback(packetId: Int): ByteArray = byteArrayOf(0x40, 2, (packetId shr 8).toByte(), packetId.toByte())
    fun pingReq(): ByteArray = byteArrayOf(0xC0.toByte(), 0)
    fun disconnect(): ByteArray = byteArrayOf(0xE0.toByte(), 0)

    sealed class Packet {
        data class ConnAck(val sessionPresent: Boolean, val returnCode: Int) : Packet()
        class Publish(val topic: String, val payload: ByteArray, val retain: Boolean, val qos: Int, val packetId: Int) : Packet()
        data class SubAck(val packetId: Int, val codes: List<Int>) : Packet()
        object PingResp : Packet()
        data class Other(val type: Int) : Packet()
    }

    /** Accumulates bytes (a WebSocket message may hold part of a packet or several) and yields whole packets. */
    class Decoder {
        private var buf = ByteArray(0)

        /** Throws IllegalStateException on a malformed stream. */
        @Synchronized fun feed(data: ByteArray): List<Packet> {
            buf = if (buf.isEmpty()) data.copyOf() else buf + data
            val out = ArrayList<Packet>()
            var pos = 0
            while (true) {
                // fixed header: 1 byte + varint remaining length
                if (buf.size - pos < 2) break
                var mul = 1; var len = 0; var i = pos + 1; var complete = false
                while (true) {
                    if (i >= buf.size) break
                    val d = buf[i++].toInt() and 0xFF
                    len += (d and 0x7F) * mul
                    if (d and 0x80 == 0) { complete = true; break }
                    mul *= 128
                    if (mul > 128 * 128 * 128) throw IllegalStateException("bad MQTT remaining length")
                }
                if (!complete || buf.size - i < len) break
                out.add(parse(buf[pos].toInt() and 0xFF, buf, i, len))
                pos = i + len
            }
            if (pos > 0) buf = buf.copyOfRange(pos, buf.size)
            return out
        }

        private fun u16(b: ByteArray, o: Int) = ((b[o].toInt() and 0xFF) shl 8) or (b[o + 1].toInt() and 0xFF)

        private fun parse(first: Int, b: ByteArray, o: Int, len: Int): Packet {
            val end = o + len
            return when (first shr 4) {
                2 -> { if (len < 2) throw IllegalStateException("short CONNACK"); Packet.ConnAck(b[o].toInt() and 1 == 1, b[o + 1].toInt() and 0xFF) }
                3 -> {
                    val qos = (first shr 1) and 3
                    if (len < 2) throw IllegalStateException("short PUBLISH")
                    val tl = u16(b, o)
                    var p = o + 2
                    if (p + tl > end) throw IllegalStateException("short PUBLISH")
                    val topic = String(b, p, tl, Charsets.UTF_8); p += tl
                    var id = 0
                    if (qos > 0) { if (p + 2 > end) throw IllegalStateException("short PUBLISH"); id = u16(b, p); p += 2 }
                    Packet.Publish(topic, b.copyOfRange(p, end), first and 1 == 1, qos, id)
                }
                9 -> { if (len < 2) throw IllegalStateException("short SUBACK"); Packet.SubAck(u16(b, o), (o + 2 until end).map { b[it].toInt() and 0xFF }) }
                13 -> Packet.PingResp
                else -> Packet.Other(first shr 4)
            }
        }
    }
}
