package uk.umc.app.net

import org.junit.Assert.*
import org.junit.Test

/** Setup-code, broker JSON, de-duplication and delivery wording. Packet vectors are from umcnet_msgs.py (see MsgCodecTest). */
class NetBookTest {
    private val ID = "03A107BFF3CE10BE1D70DD18E74BC09967E4D6309BA50D5F1DDC8664125531B8"
    private val CODE = "umcclient1:eyJoIjoibmV0LmV4YW1wbGUudWsiLCJ1IjoiZGFyZW4tYXBwIiwicCI6InMzY3JldC1wdyIsImkiOiIwM0ExMDdCRkYzQ0UxMEJFMUQ3MEREMThFNzRCQzA5OTY3RTRENjMwOUJBNTBENUYxRERDODY2NDEyNTUzMUI4IiwiYSI6IkxCQSJ9"
    private val WIRE_PATH1 = "1502AABB80151BA8DC8FEBAADFB47F1409B053BEEBF14D89CBF5DA68EEA7C19A2C036DC5476C43"
    private val WIRE_PATH2 = "1542AABBCCDD80151BA8DC8FEBAADFB47F1409B053BEEBF14D89CBF5DA68EEA7C19A2C036DC5476C43"
    private val RAW_YORK_REGION = "1465FC00000080151BA8DC8FEBAADFB47F1409B053BEEBF14D89CBF5DA68EEA7C19A2C036DC5476C43"
    private val york = NetChannel.of("#yorkshire")
    private val A = "A".repeat(64); private val B = "B".repeat(64)
    private fun hex(s: String) = MsgCodec.fromHex(s)!!

    // ---- setup code
    @Test fun parsesTheSetupCode() =
        assertEquals(UmcAccount("net.example.uk", "daren-app", "s3cret-pw", ID, "LBA"), SetupCode.parse("  $CODE\n").getOrThrow())

    @Test fun setupCodeRoundTrips() {
        val a = UmcAccount("net.example.uk", "u", "p\"w\\x", ID, "LBA")
        assertEquals(a, SetupCode.parse(a.toSetupCode()).getOrThrow())
        assertTrue(a.toSetupCode().startsWith("umcclient1:")); assertFalse(a.toSetupCode().contains("="))
    }

    @Test fun badSetupCodesGiveReasons() {
        assertTrue(SetupCode.parse("hello").isFailure)
        assertTrue(SetupCode.parse("umcclient1:!!!").isFailure)
        assertTrue(SetupCode.parse("umcclient1:" + MsgCodec.b64urlEncode("[1]".toByteArray())).isFailure)
        assertTrue(SetupCode.parse(UmcAccount("net.example.uk", "u", "p", "abc", "LBA").toSetupCode()).isFailure)           // id too short
        assertTrue(SetupCode.parse(UmcAccount("https://net.example.uk/", "u", "p", ID, "LBA").toSetupCode()).isFailure)    // host with scheme
    }

    @Test fun manualValuesAreValidatedTheSameWay() {
        assertNull(SetupCode.validate(UmcAccount("net.example.uk", "u", "p", ID, "LBA")))
        assertNotNull(SetupCode.validate(UmcAccount("net.example.uk", "", "p", ID, "LBA")))
        assertNotNull(SetupCode.validate(UmcAccount("net.example.uk", "u", "p", ID.lowercase(), "LBA")))
        assertTrue(SetupCode.validHost("net.2e0lxy.uk")); assertFalse(SetupCode.validHost("net/x"))
    }

    // ---- broker JSON
    @Test fun topics() {
        assertEquals(listOf("meshcore/LBA/+/raw", "meshcore/LBA/+/status", "meshcore/LBA/+/packets"), Protocol.subscriptions("LBA"))
        assertEquals("meshcore/LBA/$ID/raw", Protocol.publishTopic("LBA", ID))
        assertEquals("raw", Protocol.parseTopic("meshcore/LBA/${A.lowercase()}/raw")!!.kind); assertEquals(A, Protocol.parseTopic("meshcore/LBA/${A.lowercase()}/raw")!!.deviceId)
        assertNull(Protocol.parseTopic("meshcore/LBA/short/raw"))
    }

    @Test fun readsAnRxReportWithSnr() {
        val r = Protocol.parseReport("meshcore/LBA/$A/raw", """{"origin":"Hill Top","origin_id":"$A","timestamp":"2023-11-14T22:13:20.000Z","type":"RAW","SNR":"6.5","RSSI":-90,"data":"$WIRE_PATH1"}""".toByteArray())!!
        assertEquals("Hill Top", r.name); assertEquals(6.5, r.snr!!, 0.0); assertEquals(-90, r.rssi); assertEquals("rx", r.direction); assertEquals(WIRE_PATH1, MsgCodec.toHex(r.raw!!))
    }

    @Test fun readsATxPacketsReportAndAStatus() {
        val t = Protocol.parseReport("meshcore/LBA/$A/packets", """{"direction":"tx","raw":"$RAW_YORK_REGION"}""".toByteArray())!!
        assertEquals("tx", t.direction); assertEquals(RAW_YORK_REGION, MsgCodec.toHex(t.raw!!))
        val s = Protocol.parseReport("meshcore/LBA/$A/status", """{"status":"online","origin":"Hill Top","firmware_version":"1"}""".toByteArray())!!
        assertEquals("online", s.status); assertNull(s.raw)
        assertNull(Protocol.parseReport("meshcore/LBA/$A/raw", "nonsense".toByteArray()))
    }

    @Test fun buildsTheTxJsonLikeTheDash() {
        val raw = hex(RAW_YORK_REGION)
        assertEquals("""{"origin":"UMC App","origin_id":"$ID","timestamp":"2023-11-14T22:13:20.000Z","type":"RAW","data":"$RAW_YORK_REGION"}""",
            Protocol.txJson("UMC App", ID, 1700000000, "", raw))
        assertEquals("""{"origin":"UMC App","origin_id":"$ID","timestamp":"2023-11-14T22:13:20.000Z","type":"RAW","target":"$A","data":"$RAW_YORK_REGION"}""",
            Protocol.txJson("UMC App", ID, 1700000000, A, raw))
    }

    // ---- book
    @Test fun oneMessageReportedByTwoRepeatersIsShownOnce() {
        val book = NetBook(); val ch = listOf(york); val regions = listOf("yorkshire")
        assertTrue(book.onHeard(A, hex(WIRE_PATH2), 4.0, -100, 1000, ch, regions))      // 2 hops
        assertTrue(book.onHeard(B, hex(WIRE_PATH1), -2.5, null, 1200, ch, regions))     // 2 hops, different repeater
        assertFalse(book.onHeard(A, hex(WIRE_PATH2), 4.0, -100, 1300, ch, regions))     // the same repeater again: nothing new
        val m = book.messages().single()
        assertEquals("2E0LXY", m.sender); assertEquals("Test 1 2 3", m.text); assertEquals("#yorkshire", m.channel); assertEquals("", m.region)
        assertEquals(setOf(A, B), m.heard.map { it.id }.toSet())
    }

    @Test fun aScopedPacketNamesItsRegionAndFewerHopsReplaceMore() {
        val book = NetBook()
        book.onHeard(A, hex(WIRE_PATH1), null, null, 1000, listOf(york), listOf("yorkshire"))
        book.onHeard(A, hex(RAW_YORK_REGION), 7.0, null, 1100, listOf(york), listOf("yorkshire"))        // same payload, direct this time
        val m = book.messages().single()
        assertEquals(1, m.heard.size); assertEquals(0, m.heard[0].hops); assertEquals(7.0, m.heard[0].snr!!, 0.0)
        val scoped = NetBook(); scoped.onHeard(A, hex(RAW_YORK_REGION), null, null, 1, listOf(york), listOf("uk", "yorkshire"))
        assertEquals("yorkshire", scoped.messages().single().region)
        val unknown = NetBook(); unknown.onHeard(A, hex(RAW_YORK_REGION), null, null, 1, listOf(york), listOf("uk"))
        assertEquals("?", unknown.messages().single().region)
    }

    @Test fun packetsWeCannotReadAreIgnored() {
        val book = NetBook()
        assertFalse(book.onHeard(A, hex(WIRE_PATH1), null, null, 1, listOf(MsgCodec.publicChannel()), emptyList()))
        assertTrue(book.messages().isEmpty())
    }

    @Test fun anOutgoingMessageCollectsSentByAndHeardBack() {
        val book = NetBook(); val raw = hex(RAW_YORK_REGION)
        val key = book.addOutgoing(raw, "#yorkshire", "yorkshire", "2E0LXY", "Test 1 2 3", 1700000123, 10_000)
        assertEquals("49b009c8ba837f2d9246", key)
        val names = mapOf(A to "Hill Top", B to "Moor").let { m -> { id: String -> m[id] ?: id } }
        assertEquals(Pair("waiting for a repeater to send it", false), Delivery.text(book.messages().single(), 20_000, names))
        assertEquals(Pair("no repeater has confirmed sending this", true), Delivery.text(book.messages().single(), 50_000, names))
        assertTrue(book.onSent(A, raw, 11_000)); assertFalse(book.onSent(A, raw, 12_000))
        assertEquals(Pair("sent by Hill Top · not heard back by another repeater (it may still have reached people)", false), Delivery.text(book.messages().single(), 50_000, names))
        book.onHeard(B, hex(WIRE_PATH1), 3.0, null, 13_000, listOf(york), listOf("yorkshire"))
        val m = book.messages().single()
        assertEquals(1, m.heard.count { !it.sent }); assertTrue(m.outgoing)
        assertEquals("sent by Hill Top · heard back by 1 repeater: Moor 2 hops · 3 dB", Delivery.text(m, 50_000, names).first)
        assertFalse(book.onSent(B, MsgCodec.buildGroupText(york, "X", "another", 5), 1))        // a packet we did not send
    }

    @Test fun replyPicksFewestHopsThenBestSnr() {
        fun m(vararg h: Heard) = NetMessage("k", "c", "", "s", "t", 0, 0, false, h.toList())
        assertEquals(B, Delivery.replyVia(m(Heard(A, 2, 9.0, null, 0), Heard(B, 1, -5.0, null, 0))))
        assertEquals(A, Delivery.replyVia(m(Heard(A, 1, 2.0, null, 0), Heard(B, 1, -5.0, null, 0))))
        assertEquals(B, Delivery.replyVia(m(Heard(A, 1, null, null, 0), Heard(B, 1, 1.0, null, 0))))
        assertNull(Delivery.replyVia(m(Heard(A, 0, null, null, 0, sent = true))))
    }

    @Test fun repeaterOnlineRules() {
        assertTrue(Repeater(A, "x", "online", 0).online(1_000_000))
        assertFalse(Repeater(A, "x", "offline", 999_999).online(1_000_000))
        assertTrue(Repeater(A, "x", "unknown", 999_000).online(1_000_000)); assertFalse(Repeater(A, "x", "unknown", 100).online(1_000_000))
        assertEquals("AAAAAAAA", Repeater(A, "", "online", 0).label)
    }
}
