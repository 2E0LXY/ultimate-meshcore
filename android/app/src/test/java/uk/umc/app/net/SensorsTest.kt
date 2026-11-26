package uk.umc.app.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SensorsTest {
    private fun bytes(vararg v: Int) = ByteArray(v.size) { v[it].toByte() }
    // ch1 voltage 4.10 V, ch2 temperature -5.5 C (0xFFC9), ch3 humidity 50 %
    private val lpp = bytes(1, 116, 0x01, 0x9A, 2, 103, 0xFF, 0xC9, 3, 104, 100)

    @Test fun decodesValuesUnitsAndSigns() {
        val r = Lpp.decode(lpp)
        assertEquals(listOf("voltage", "temperature", "humidity"), r.map { it.name })
        assertEquals(4.1, r[0].value, 0.001); assertEquals(-5.5, r[1].value, 0.001); assertEquals(50.0, r[2].value, 0.001)
        assertEquals("°C", r[1].unit)
    }
    @Test fun neverThrowsOnJunk() {
        assertTrue(Lpp.decode(ByteArray(0)).isEmpty())
        assertTrue(Lpp.decode(bytes(1)).isEmpty())
        assertEquals(1, Lpp.decode(bytes(1, 116, 1, 0x9A, 2, 250, 0)).size)      // unknown type: keep what was read
        assertEquals(1, Lpp.decode(bytes(1, 116, 1, 0x9A, 2, 103, 0)).size)      // cut mid-value
    }
    @Test fun skipsMultiValueTypes() {
        val gps = bytes(9, 136, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 116, 1, 0x9A)
        assertEquals(listOf("voltage"), Lpp.decode(gps).map { it.name })
    }
    @Test fun formatsForTheScreen() {
        val r = Lpp.decode(lpp)
        assertEquals("4.10 V", Lpp.format(r[0])); assertEquals("-5.5 °C", Lpp.format(r[1])); assertEquals("50.0 %", Lpp.format(r[2]))
    }
    @Test fun topicAndPayloadAreRecognised() {
        val id = "AB".repeat(32)
        assertEquals("telemetry", Protocol.parseTopic("meshcore/LBA/$id/telemetry")?.kind)
        val hex = lpp.joinToString("") { "%02X".format(it) }
        assertEquals(hex, Protocol.parseTelemetryHex("""{"timestamp":"x","origin":"T","lpp":"$hex"}""".toByteArray()))
        assertEquals(null, Protocol.parseTelemetryHex("not json".toByteArray()))
        assertTrue("meshcore/LBA/+/telemetry" in Protocol.subscriptions("LBA", "C1"))
    }
}
