package uk.umc.app.net

import org.junit.Assert.*
import org.junit.Test

/** The phone's saved copy of the messages: round trip, the 24 hour and 500 message limits, damaged files, ordering. */
class NetStoreTest {
    private val A = "A".repeat(64); private val B = "B".repeat(64)
    private val NOW = 1_700_000_000_000L
    private fun msg(key: String, ts: Long, seen: Long = ts * 1000, text: String = "hi", outgoing: Boolean = false, heard: List<Heard> = emptyList()) =
        NetMessage(key, "#yorkshire", "yorkshire", "2E0LXY", text, ts, seen, outgoing, heard)

    @Test fun roundTripKeepsEverything() {
        val m1 = msg("k1", 1_699_999_000, text = "Quote \" slash \\ tab\t é 😀 line\nbreak",
            heard = listOf(Heard(A, 2, 4.5, -98, 1_699_999_001_000), Heard(B, 0, null, null, 1_699_999_002_000), Heard(A, 0, null, null, 1_699_999_003_000, sent = true)))
        val m2 = msg("k2", 1_699_999_500, outgoing = true).copy(region = "?", sender = "")
        val back = NetStore.decode(NetStore.encode(listOf(m2, m1), NOW), NOW)
        assertEquals(listOf(m1, m2), back)
    }

    @Test fun dropsOlderThan24HoursAndCapsAt500() {
        val old = msg("old", 1, seen = NOW - NetStore.MAX_AGE_MS - 1)
        val edge = msg("edge", 2, seen = NOW - NetStore.MAX_AGE_MS)
        assertEquals(listOf("edge"), NetStore.decode(NetStore.encode(listOf(old, edge), NOW), NOW).map { it.key })
        val many = (1..600).map { msg("k$it", 1_699_990_000L + it) }
        val back = NetStore.decode(NetStore.encode(many, NOW), NOW)
        assertEquals(500, back.size); assertEquals("k101", back.first().key); assertEquals("k600", back.last().key)
        // time moves on between save and load: old ones are dropped on load too
        assertTrue(NetStore.decode(NetStore.encode(listOf(edge), NOW), NOW + 10).isEmpty())
    }

    @Test fun damagedOrUnknownFilesGiveNothingAndBadEntriesAreSkipped() {
        assertTrue(NetStore.decode("", NOW).isEmpty())
        assertTrue(NetStore.decode("nonsense", NOW).isEmpty())
        assertTrue(NetStore.decode("""{"v":1,"m":[{"k":"a","c":"x","t""", NOW).isEmpty())      // truncated
        assertTrue(NetStore.decode("""{"v":2,"m":[]}""", NOW).isEmpty())
        val good = NetStore.encode(listOf(msg("ok", 1_699_999_000)), NOW)
        val mixed = good.replace("\"m\":[", "\"m\":[{\"k\":\"bad\"},5,")
        assertEquals(listOf("ok"), NetStore.decode(mixed, NOW).map { it.key })
    }

    @Test fun restoredBookOrdersByMessageTimeAndKeepsHeard() {
        val book = NetBook()
        book.restore(NetStore.decode(NetStore.encode(listOf(
            msg("late", 1_699_999_900, heard = listOf(Heard(A, 1, 2.0, null, 5))),
            msg("early", 1_699_999_100)), NOW), NOW))
        assertEquals(listOf("early", "late"), book.messages().map { it.key })
        assertEquals(1, book.messages()[1].heard.size)
    }

    @Test fun orderIsByMessageTimeThenSeenTime() {
        val book = NetBook()
        book.restore(listOf(msg("b", 100, seen = 5_000), msg("a", 100, seen = 4_000), msg("c", 50, seen = 9_000_000)))
        assertEquals(listOf("c", "a", "b"), book.messages().map { it.key })
    }

    @Test fun overTheLimitTheOldestMessageGoes() {
        val book = NetBook(2)
        book.restore(listOf(msg("new", 300), msg("old", 100), msg("mid", 200)))
        assertEquals(listOf("mid", "new"), book.messages().map { it.key })
    }

    @Test fun restoreDoesNotOverwriteWhatIsAlreadyHeld() {
        val book = NetBook(); book.restore(listOf(msg("k", 1, text = "first"))); book.restore(listOf(msg("k", 1, text = "second")))
        assertEquals("first", book.messages().single().text)
    }
}
