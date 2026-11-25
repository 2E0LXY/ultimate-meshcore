package uk.umc.app.net

import org.junit.Assert.*
import org.junit.Test
import uk.umc.app.net.MqttPacket.Packet

/* Golden bytes worked out by hand from the MQTT 3.1.1 spec (sections 2.2.3, 3.1, 3.3, 3.8). */
class MqttPacketTest {
    private fun hex(b: ByteArray) = b.joinToString("") { "%02X".format(it) }
    private fun bytes(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }

    @Test fun connectWithUserAndPassword() {
        // 10 | len 0x14 | 0004 "MQTT" 04 C2 001E | 0002 "id" | 0001 "u" | 0001 "p"
        assertEquals("1014" + "00044D515454" + "04C2001E" + "00026964" + "000175" + "000170", hex(MqttPacket.connect("id", "u", "p")))
    }

    @Test fun subscribeQos0() {
        // 82 | len 8 | id 0001 | 0003 "a/#" | qos 0
        assertEquals("82080001" + "0003612F23" + "00", hex(MqttPacket.subscribe(1, listOf("a/#"))))
    }

    @Test fun publishQos0SmallAndLarge() {
        assertEquals("3005000161" + "0102", hex(MqttPacket.publish("a", byteArrayOf(1, 2))))
        // 200-byte payload: remaining length 2 + 1 + 200 = 203 -> CB 01
        val out = MqttPacket.publish("a", ByteArray(200) { 7 })
        assertEquals("30CB010001" + "61", hex(out.copyOfRange(0, 6)))
        assertEquals(206, out.size)
    }

    @Test fun pingDisconnectPuback() {
        assertEquals("C000", hex(MqttPacket.pingReq()))
        assertEquals("E000", hex(MqttPacket.disconnect()))
        assertEquals("40020102", hex(MqttPacket.puback(0x0102)))
    }

    @Test fun decodesPublishSplitAcrossChunks() {
        val pkt = bytes("3107" + "0003612F62" + "6869")  // retain, "a/b", payload "hi"
        val d = MqttPacket.Decoder()
        assertTrue(d.feed(pkt.copyOfRange(0, 1)).isEmpty())
        assertTrue(d.feed(pkt.copyOfRange(1, 5)).isEmpty())
        val r = d.feed(pkt.copyOfRange(5, pkt.size))
        assertEquals(1, r.size)
        val p = r[0] as Packet.Publish
        assertEquals("a/b", p.topic); assertEquals("hi", String(p.payload)); assertTrue(p.retain); assertEquals(0, p.qos)
    }

    @Test fun decodesTwoPacketsInOneChunkAndLargePayload() {
        val big = MqttPacket.publish("t", ByteArray(300) { it.toByte() })
        val d = MqttPacket.Decoder()
        val r = d.feed(bytes("D000") + big + bytes("2002" + "0000"))
        assertEquals(3, r.size)
        assertTrue(r[0] is Packet.PingResp)
        val p = r[1] as Packet.Publish
        assertEquals("t", p.topic); assertEquals(300, p.payload.size); assertFalse(p.retain); assertEquals(43, p.payload[300 - 1].toInt() and 0xFF)
        assertEquals(Packet.ConnAck(false, 0), r[2])
    }

    @Test fun qos1PublishCarriesPacketId() {
        val r = MqttPacket.Decoder().feed(bytes("3206" + "000174" + "0A0B" + "AB"))
        val p = r[0] as Packet.Publish
        assertEquals(1, p.qos); assertEquals(0x0A0B, p.packetId); assertEquals("t", p.topic); assertEquals(1, p.payload.size)
    }

    @Test fun connackRefusedAndSuback() {
        val r = MqttPacket.Decoder().feed(bytes("20020005" + "90030001" + "00"))
        assertEquals(Packet.ConnAck(false, 5), r[0])
        assertEquals(Packet.SubAck(1, listOf(0)), r[1])
    }

    @Test(expected = IllegalStateException::class) fun overlongRemainingLengthIsRejected() {
        MqttPacket.Decoder().feed(bytes("30FFFFFFFF7F"))
    }
}
