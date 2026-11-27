package uk.umc.app.tools

import org.junit.Assert.*
import org.junit.Test
import uk.umc.app.net.Heard
import uk.umc.app.net.MiniJson
import uk.umc.app.net.NetMessage
import uk.umc.app.proto.ChatMessage
import uk.umc.app.proto.Contact
import uk.umc.app.proto.toHex

class BackupTest {
    private val RAW = byteArrayOf(0x5e, 0x11, 0x77, 0x42, 0x13, 0x37, 0x6a, 0x6b)     // stands for a record with private material
    private val PATH = byteArrayOf(0x7a, 0x7b, 0x7c)
    private val KEY = "ab".repeat(32)

    private fun contact(name: String, lat: Double = 53.7, lon: Double = -1.5, hops: Int = 2, flags: Int = 0) =
        Contact(KEY, 1, flags, hops, PATH, name, 1_700_000_000L, lat, lon, 0L, RAW)

    private fun data(
        contacts: List<Contact> = listOf(contact("Alice")),
        radio: List<ChatMessage> = emptyList(), net: List<NetMessage> = emptyList(),
        fences: List<Geofence> = emptyList(), events: List<FenceHit> = emptyList(),
        regions: List<String> = listOf("yorkshire"), scopes: Map<String, String> = mapOf("Public" to "uk"),
    ) = ExportData(contacts, radio, net, fences, events, regions, scopes, 1_700_000_000_000L)

    private fun chat(text: String, from: String = "Bob", ts: Long = 1_700_000_100L) =
        ChatMessage(1, "c:abcdef", false, text, from, ts, hops = 1, snr = 5.5, status = "sent")

    private fun netMsg(text: String, ts: Long = 1_700_000_050L) =
        NetMessage("k", "Public", "yorkshire", "Carol", text, ts, ts * 1000, false, listOf(Heard("A".repeat(64), 3, 2.0, -90, 1L)))

    @Test fun contactsCsvHasHeaderAndRow() {
        val lines = Backup.contactsCsv(data()).removePrefix("\uFEFF").trimEnd().split("\r\n")
        assertEquals("name,public_key,type,hops,latitude,longitude,last_advert_utc,favourite", lines[0])
        assertEquals("Alice,$KEY,chat,2,53.7,-1.5,2023-11-14T22:13:20Z,false", lines[1])
    }

    @Test fun contactWithoutFixHasBlankPlaceAndFloodHops() {
        val line = Backup.contactsCsv(data(listOf(contact("Z", 0.0, 0.0, hops = 0xFF)))).trimEnd().split("\r\n")[1]
        assertEquals("Z,$KEY,chat,,,,2023-11-14T22:13:20Z,false", line)
    }

    @Test fun hostileNamesAndTextAreDefusedInCsv() {
        val d = data(listOf(contact("=cmd|' /C calc'!A0")), radio = listOf(chat("+1 \"quoted\", yes\nnext line")), net = listOf(netMsg("@SUM(1)")))
        val c = Backup.contactsCsv(d)
        assertTrue(c.contains("\r\n'=cmd"))
        val m = Backup.messagesCsv(d)
        assertTrue(m.contains("\"'+1 \"\"quoted\"\", yes\nnext line\""))
        assertTrue(m.contains(",'@SUM(1),"))
        assertFalse(Regex("(^|\r\n|,)[=+@]").containsMatchIn(m.removePrefix("\uFEFF").lines().drop(1).joinToString("\r\n").substringBefore("\"'+1")))
    }

    @Test fun messagesAreMergedOldestFirst() {
        val lines = Backup.messagesCsv(data(radio = listOf(chat("later", ts = 1_700_000_100L)), net = listOf(netMsg("earlier", 1_700_000_050L)))).trimEnd().split("\r\n")
        assertEquals(3, lines.size)
        assertTrue(lines[1].startsWith("net,Public / yorkshire,in,"))
        assertTrue(lines[1].endsWith(",3,,"))
        assertTrue(lines[2].startsWith("radio,c:abcdef,in,"))
        assertTrue(lines[2].endsWith(",1,5.5,sent"))
    }

    @Test fun jsonHasNoSecrets() {
        val d = data(
            radio = listOf(chat("hello")), net = listOf(netMsg("hi")),
            fences = listOf(Geofence("f", "Home", 53.7, -1.5, 500.0)),
            events = listOf(FenceHit("f", "Home", KEY, "Alice", FenceEvent.ENTER, 5L, 53.7, -1.5, 3.0)),
        )
        for (out in listOf(Backup.json(d), Backup.contactsCsv(d), Backup.messagesCsv(d), Backup.eventsCsv(d))) {
            val low = out.lowercase()
            for (w in Backup.FORBIDDEN_WORDS) assertFalse("found $w", low.contains(w))
            assertFalse(low.contains(RAW.toHex().lowercase())); assertFalse(low.contains(PATH.toHex().lowercase()))
            assertFalse(low.contains("a".repeat(64)))      // the repeater id in the heard list is not exported
        }
        // the JSON must parse and carry only the documented top-level keys
        val root = MiniJson.parseObject(Backup.json(d))!!
        assertEquals(setOf("format", "version", "created", "contacts", "radioMessages", "netMessages", "geofences", "geofenceEvents", "regions", "regionScopes"), root.keys)
    }

    @Test fun restoreRoundTrip() {
        val fences = listOf(Geofence("f", "Home \"1\"", 53.7, -1.5, 500.0))
        val events = listOf(FenceHit("f", "Home", KEY, "Alice", FenceEvent.EXIT, 5L, 53.7, -1.5, 3.0))
        val r = Backup.parse(Backup.json(data(fences = fences, events = events, regions = listOf("yorkshire", "uk"), scopes = mapOf("Public" to "uk")))).getOrThrow()
        assertEquals(fences, r.fences); assertEquals(events, r.events)
        assertEquals(listOf("yorkshire", "uk"), r.regions); assertEquals(mapOf("Public" to "uk"), r.scopes)
    }

    @Test fun restoreRejectsWrongFilesAndSkipsBadEntries() {
        assertTrue(Backup.parse("nonsense").isFailure)
        assertTrue(Backup.parse("{\"format\":\"other\",\"version\":1}").isFailure)
        assertTrue(Backup.parse("{\"format\":\"umc-backup\",\"version\":2}").isFailure)
        assertTrue(Backup.parse("x".repeat(Backup.MAX_RESTORE_BYTES + 1)).isFailure)
        val r = Backup.parse("{\"format\":\"umc-backup\",\"version\":1,\"regions\":[\"ok-1\",\"BAD\",\"has space\",5,\"" + "x".repeat(30) + "\"],\"regionScopes\":{\"Public\":\"uk\",\"X\":\"Bad Region\"}}").getOrThrow()
        assertEquals(listOf("ok-1"), r.regions); assertEquals(mapOf("Public" to "uk"), r.scopes)
        assertTrue(r.fences.isEmpty())
    }

    @Test fun restoreIgnoresSecretsEvenIfAFileCarriesThem() {
        val r = Backup.parse("{\"format\":\"umc-backup\",\"version\":1,\"password\":\"hunter2\",\"seed\":\"00\",\"regions\":[\"uk\"]}").getOrThrow()
        assertEquals(listOf("uk"), r.regions)
    }

    @Test fun eventsCsv() {
        val e = FenceHit("f", "Home", KEY, "=Evil", FenceEvent.ENTER, 1_700_000_000_000L, 53.7, -1.5, 12.6)
        val lines = Backup.eventsCsv(data(events = listOf(e))).trimEnd().split("\r\n")
        assertEquals("2023-11-14T22:13:20Z,Home,'=Evil,enter,53.7,-1.5,13", lines[1])
    }
}
