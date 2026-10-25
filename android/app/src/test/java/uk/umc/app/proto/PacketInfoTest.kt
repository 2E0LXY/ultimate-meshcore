package uk.umc.app.proto

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PacketInfoTest {
    private fun advert(name: String, flags: Int = 0x81, hops: List<Int> = emptyList()): ByteArray {
        val header = (4 shl 2) or 1                                   // ADVERT, flood
        val body = ByteArray(32) { (0xA0 + it).toByte() } + ByteArray(4) + ByteArray(64) + byteArrayOf(flags.toByte()) + name.toByteArray()
        return byteArrayOf(header.toByte(), hops.size.toByte()) + hops.map { it.toByte() }.toByteArray() + body
    }

    @Test fun anAdvertGivesItsSendersNameAndKey() {
        val i = PacketInfo.parse(advert("MRLM-HA", hops = listOf(0xD5)))!!
        assertEquals("ADV", i.kind)
        assertEquals("MRLM-HA", i.name)
        assertEquals("A0A1A2A3", i.key)
        assertEquals(0xD5, i.via)
        assertEquals(1, i.hops)
        assertTrue(i.flood)
    }

    @Test fun anAdvertWithLocationAndFeaturesSkipsToTheName() {
        val body = ByteArray(32) + ByteArray(4) + ByteArray(64) + byteArrayOf(0xF1.toByte()) + ByteArray(8) + ByteArray(2) + ByteArray(2) + "Hill".toByteArray()
        val i = PacketInfo.parse(byteArrayOf(((4 shl 2) or 1).toByte(), 0) + body)!!
        assertEquals("Hill", i.name)
    }

    @Test fun anAdvertWithoutANameHasOnlyAKey() {
        val i = PacketInfo.parse(advert("", flags = 0x01))!!
        assertEquals("", i.name)
        assertNotNull(i.key)
    }

    @Test fun aResponseGivesDestinationThenSourceAndTheLastHop() {
        val header = (1 shl 2) or 1                                   // RSP, flood
        val raw = byteArrayOf(header.toByte(), 2, 0x11, 0x3F, 0xA1.toByte(), 0xB0.toByte(), 9, 9, 9)
        val i = PacketInfo.parse(raw)!!
        assertEquals("RSP", i.kind)
        assertEquals(0xA1, i.dst)
        assertEquals(0xB0, i.src)
        assertEquals(0x3F, i.via)
        assertEquals(2, i.hops)
    }

    @Test fun aChannelPacketGivesItsHash() {
        val i = PacketInfo.parse(byteArrayOf(((5 shl 2) or 1).toByte(), 0, 0x8A.toByte(), 1, 2, 3))!!
        assertEquals("GRP", i.kind)
        assertEquals(0x8A, i.chan)
        assertNull(i.via)
        assertEquals(0, i.hops)
    }

    @Test fun transportCodesAreSkipped() {
        val raw = byteArrayOf(((2 shl 2) or 0).toByte(), 1, 2, 3, 4, 1, 0x77, 0x10, 0x20, 5)   // MSG, transport flood
        val i = PacketInfo.parse(raw)!!
        assertEquals(0x77, i.via)
        assertEquals(0x10, i.dst)
        assertEquals(0x20, i.src)
        assertTrue(i.flood)
    }

    @Test fun directPacketsAreNotFlood() {
        val i = PacketInfo.parse(byteArrayOf(((3 shl 2) or 2).toByte(), 0, 1, 2, 3, 4))!!
        assertFalse(i.flood)
        assertEquals("ACK", i.kind)
    }

    @Test fun twoByteHashesUseTheLastHash() {
        val raw = byteArrayOf(((5 shl 2) or 1).toByte(), (0x40 or 2).toByte(), 1, 2, 0x33, 0x44, 0x9C.toByte())   // two 2-byte hashes
        val i = PacketInfo.parse(raw)!!
        assertEquals(0x33, i.via)
        assertEquals(2, i.hops)
    }

    @Test fun truncatedPacketsAreRejectedNotGuessed() {
        assertNull(PacketInfo.parse(ByteArray(0)))
        assertNull(PacketInfo.parse(byteArrayOf(5)))
        assertNull(PacketInfo.parse(byteArrayOf(((5 shl 2) or 1).toByte(), 3, 1)))
    }
}
