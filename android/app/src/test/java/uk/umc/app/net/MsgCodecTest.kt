package uk.umc.app.net

import org.junit.Assert.*
import org.junit.Test

/*
 * Golden vectors were produced by running the Python reference, server/umcnet/dash/umcnet_msgs.py, in the sandbox:
 *   Channel("Public", PUBLIC_PSK), Channel("#yorkshire"), Channel("Club", base64(bytes(range(16))))
 *   build_group_text(channel, sender, text, ts, region)  -> RAW_* (hex)
 *   parse_wire / decrypt_group / find_region / sha1(payload)[:20] -> the expected values asserted here.
 * Encryption is deterministic (AES-ECB, truncated HMAC), so the Kotlin output must match byte for byte.
 */
class MsgCodecTest {
    private val RAW_PUB_PLAIN = "15001154BFD096CA18AE16261CE7E411CE8D9E44E11AA3B0345687BBA334753BBA95FB7A18"            // Public, "Daren", "Hello from the net", 1700000000
    private val RAW_YORK_REGION = "1465FC00000080151BA8DC8FEBAADFB47F1409B053BEEBF14D89CBF5DA68EEA7C19A2C036DC5476C43" // #yorkshire, "2E0LXY", "Test 1 2 3", 1700000123, region yorkshire
    private val RAW_CLUB_UNICODE = "1500BE5DF7639F56844F6F991DCB800F277A405F56F473798265E3FED129588CA0D509AA5776F25C8D94372409D34E08CF8C5EA4F990623DB7FCE2E4CA3280C3AE9D4D3CE7"
    private val RAW_PUB_REGION = "141D8000000011954F198455786ACB84286612BD2F0A6AB15F"                                     // Public, "Daren", "Hi", 1700000789, region eng-ne
    private val WIRE_PATH1 = "1502AABB80151BA8DC8FEBAADFB47F1409B053BEEBF14D89CBF5DA68EEA7C19A2C036DC5476C43"            // york packet, flood, 2 one-byte hops
    private val WIRE_PATH2 = "1542AABBCCDD80151BA8DC8FEBAADFB47F1409B053BEEBF14D89CBF5DA68EEA7C19A2C036DC5476C43"        // two-byte hops

    private val pub = MsgCodec.publicChannel()
    private val york = NetChannel.of("#yorkshire")
    private val club = NetChannel.of("Club", java.util.Base64.getEncoder().encodeToString(ByteArray(16) { it.toByte() }))
    private fun hex(s: String) = MsgCodec.fromHex(s)!!

    @Test fun keysAndHashesMatchThePythonReference() {
        assertEquals("8B3387E9C5CDEA6AC9E5EDBAA115CD72", MsgCodec.toHex(pub.key)); assertEquals(0x11, pub.hash)
        assertEquals("EA19E9567EEC1B148C174F0CB9D04DD7", MsgCodec.toHex(york.key)); assertEquals(0x80, york.hash)
        assertEquals("000102030405060708090A0B0C0D0E0F", MsgCodec.toHex(club.key)); assertEquals(0xBE, club.hash)
    }

    @Test fun hashtagKeyIsSha256OfTheNameAndARegionKeyIsTheSameThing() {
        assertEquals(MsgCodec.toHex(york.key), MsgCodec.toHex(MsgCodec.hashtagKey("#yorkshire")))
        assertEquals(MsgCodec.toHex(york.key), MsgCodec.toHex(MsgCodec.regionKey("yorkshire")))
        assertEquals(MsgCodec.toHex(york.key), MsgCodec.toHex(MsgCodec.regionKey("#yorkshire")))
    }

    @Test fun aChannelNeedsAKeyOrAHashtag() {
        assertThrows(IllegalArgumentException::class.java) { NetChannel.of("Club") }
        assertThrows(IllegalArgumentException::class.java) { NetChannel.of("#") }
        assertThrows(IllegalArgumentException::class.java) { NetChannel.of("Club", "AAAA") }     // 3 bytes
    }

    @Test fun buildsTheSamePacketsAsTheReference() {
        assertEquals(RAW_PUB_PLAIN, MsgCodec.toHex(MsgCodec.buildGroupText(pub, "Daren", "Hello from the net", 1700000000)))
        assertEquals(RAW_YORK_REGION, MsgCodec.toHex(MsgCodec.buildGroupText(york, "2E0LXY", "Test 1 2 3", 1700000123, "yorkshire")))
        assertEquals(RAW_CLUB_UNICODE, MsgCodec.toHex(MsgCodec.buildGroupText(club, "Daz", "café ☕ ok, a message long enough to take two blocks", 1700000456)))
        assertEquals(RAW_PUB_REGION, MsgCodec.toHex(MsgCodec.buildGroupText(pub, "Daren", "Hi", 1700000789, "eng-ne")))
    }

    @Test fun parsesAndDecryptsWhatTheReferenceBuilt() {
        val p = MsgCodec.parseWire(hex(RAW_YORK_REGION))!!
        assertEquals(0, p.route); assertEquals(5, p.ptype); assertEquals(Pair(64613, 0), p.codes); assertEquals(0, p.path.size)
        val g = MsgCodec.decryptGroup(listOf(pub, york), p.payload)!!
        assertEquals("#yorkshire", g.channel.name); assertEquals(1700000123L, g.timestamp); assertEquals(0, g.flags)
        assertEquals("2E0LXY: Test 1 2 3", g.text)
        assertEquals("yorkshire", MsgCodec.findRegion(listOf("uk", "yorkshire", "eng-ne"), p))
        assertEquals("", MsgCodec.findRegion(listOf("uk"), p))
        assertEquals(Pair("2E0LXY", "Test 1 2 3"), MsgCodec.splitSender(g.text))
    }

    @Test fun decryptsPublicUnicodeAndRegionVectors() {
        val a = MsgCodec.decryptGroup(listOf(pub), MsgCodec.parseWire(hex(RAW_PUB_PLAIN))!!.payload)!!
        assertEquals("Daren: Hello from the net", a.text); assertEquals(1700000000L, a.timestamp)
        val b = MsgCodec.decryptGroup(listOf(club), MsgCodec.parseWire(hex(RAW_CLUB_UNICODE))!!.payload)!!
        assertEquals("Daz: café ☕ ok, a message long enough to take two blocks", b.text)
        val c = MsgCodec.parseWire(hex(RAW_PUB_REGION))!!
        assertEquals(Pair(32797, 0), c.codes); assertEquals("eng-ne", MsgCodec.findRegion(listOf("uk", "yorkshire", "eng-ne"), c))
        assertEquals("Daren: Hi", MsgCodec.decryptGroup(listOf(pub), c.payload)!!.text)
    }

    @Test fun aWrongKeyOrDamagedPacketIsNotReadable() {
        val payload = MsgCodec.parseWire(hex(RAW_YORK_REGION))!!.payload
        assertNull(MsgCodec.decryptGroup(listOf(pub, club), payload))
        val bad = payload.copyOf(); bad[bad.size - 1] = (bad[bad.size - 1].toInt() xor 1).toByte()
        assertNull(MsgCodec.decryptGroup(listOf(york), bad))
        assertNull(MsgCodec.decryptGroup(listOf(york), ByteArray(10)))
    }

    @Test fun parseWireReadsPathsAndRejectsGarbage() {
        val one = MsgCodec.parseWire(hex(WIRE_PATH1))!!
        assertEquals(listOf("AA", "BB"), one.path.map { MsgCodec.toHex(it) }); assertNull(one.codes)
        val two = MsgCodec.parseWire(hex(WIRE_PATH2))!!
        assertEquals(listOf("AABB", "CCDD"), two.path.map { MsgCodec.toHex(it) })
        assertEquals("49b009c8ba837f2d9246", MsgCodec.pktKey(one.payload))
        assertEquals(MsgCodec.pktKey(one.payload), MsgCodec.pktKey(two.payload))                 // same message, however it was relayed
        assertNull(MsgCodec.parseWire(hex("150301" + "02")))                                    // path longer than the packet
        assertNull(MsgCodec.parseWire(ByteArray(0)))
        assertNull(MsgCodec.parseWire(hex("15C0AABBCCDD")))                                     // 4-byte hops are not valid
    }

    @Test fun dedupeKeysMatchThePythonSha1() {
        assertEquals("28a3060284da294f3d77", MsgCodec.pktKey(MsgCodec.parseWire(hex(RAW_PUB_PLAIN))!!.payload))
        assertEquals("49b009c8ba837f2d9246", MsgCodec.pktKey(MsgCodec.parseWire(hex(RAW_YORK_REGION))!!.payload))
        assertEquals("a4998145f7059512cab3", MsgCodec.pktKey(MsgCodec.parseWire(hex(RAW_CLUB_UNICODE))!!.payload))
        assertEquals("2efeb3ec33f249d235de", MsgCodec.pktKey(MsgCodec.parseWire(hex(RAW_PUB_REGION))!!.payload))
    }

    @Test fun aTooLongMessageIsRefused() {
        assertThrows(IllegalArgumentException::class.java) { MsgCodec.buildGroupText(pub, "Daren", "x".repeat(170), 1700000000) }
    }

    @Test fun sendRulesFollowTheDashboard() {
        val r = listOf("yorkshire")
        assertNull(SendRules.check("hello", "Daren", "yorkshire", r)); assertNull(SendRules.check("hello", "Daren", null, r))
        assertNull(SendRules.check("x".repeat(130), "Daren", null, r))
        assertNotNull(SendRules.check("x".repeat(131), "Daren", null, r))
        assertNull(SendRules.check("é".repeat(65), "Daren", null, r))                       // 130 bytes
        assertNotNull(SendRules.check("é".repeat(66), "Daren", null, r))                    // 132 bytes
        assertNotNull(SendRules.check("  ", "Daren", null, r)); assertNotNull(SendRules.check("a\nb", "Daren", null, r))
        assertNotNull(SendRules.check("hi", "", null, r)); assertNotNull(SendRules.check("hi", "-x", null, r)); assertNotNull(SendRules.check("hi", "a".repeat(25), null, r))
        assertNotNull(SendRules.check("hi", "Daren", "unknown", r))
    }

    @Test fun sixMessagesAMinute() {
        val l = SendLimiter()
        for (i in 0 until 6) assertTrue(l.tryAcquire(1000L + i * 100))
        assertFalse(l.tryAcquire(30_000))
        assertFalse(l.tryAcquire(61_000))              // the first one (at 1000 ms) is exactly 60 s old at 61000: still inside? 60 000 is not more than 60 000
        assertTrue(l.tryAcquire(61_100 + 1))           // now the first has aged out
    }
}
