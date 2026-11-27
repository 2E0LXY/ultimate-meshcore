package uk.umc.app.tools

import org.junit.Assert.*
import org.junit.Test

class TilePackTest {
    @Test fun acceptsKnownTypesCaseInsensitively() {
        assertNull(TilePack.check("Yorkshire.MBTILES", 1000))
        assertNull(TilePack.check("a.zip", -1))
        assertNull(TilePack.check("a.sqlite", 5))
        assertNull(TilePack.check("a.gemf", 5))
    }

    @Test fun rejectsOtherTypesEmptyAndHuge() {
        assertNotNull(TilePack.check("a.png", 10))
        assertNotNull(TilePack.check("noext", 10))
        assertNotNull(TilePack.check("a.zip", 0))
        assertNotNull(TilePack.check("a.zip", TilePack.MAX_BYTES + 1))
        assertNull(TilePack.check("a.zip", TilePack.MAX_BYTES))
    }

    @Test fun localNameIsSafe() {
        assertTrue(TilePack.localName("Yorkshire 2026.mbtiles").matches(Regex("Yorkshire_2026-[0-9a-f]{8}\\.mbtiles")))
        assertEquals("passwd.zip", TilePack.localName("../../etc/passwd.zip"))
        assertTrue(TilePack.localName("....zip").matches(Regex("tiles-[0-9a-f]{8}\\.zip")))
        assertEquals("noext.zip", TilePack.localName("noext"))
        assertTrue(TilePack.localName("x".repeat(500) + ".zip").length <= TilePack.MAX_NAME + 4 + 9)
    }

    @Test fun namesThatCleanToTheSameStemDoNotCollide() {
        val a = TilePack.localName("a b.zip"); val b = TilePack.localName("a_b.zip"); val c = TilePack.localName("a-b.zip"); val d = TilePack.localName("a.b.zip")
        assertEquals(4, setOf(a, b, c, d).size)
        assertEquals("a_b.zip", b)
        assertEquals(a, TilePack.localName("a b.zip"))            // same name again replaces the same file
    }

    private fun b(vararg v: Int) = ByteArray(v.size) { v[it].toByte() }
    private val SQLITE = "SQLite format 3\u0000".toByteArray(Charsets.ISO_8859_1)

    @Test fun headerChecks() {
        assertNull(TilePack.headerError("a.zip", b(0x50, 0x4B, 0x03, 0x04, 0, 0)))
        assertNotNull(TilePack.headerError("a.zip", "<html>".toByteArray()))
        assertNotNull(TilePack.headerError("a.zip", ByteArray(0)))
        assertNull(TilePack.headerError("a.MBTILES", SQLITE)); assertNull(TilePack.headerError("a.sqlite", SQLITE))
        assertNotNull(TilePack.headerError("a.sqlite", SQLITE.copyOf(10)))
        assertNotNull(TilePack.headerError("a.mbtiles", b(0x50, 0x4B, 0x03, 0x04)))
        assertNull(TilePack.headerError("a.gemf", b(0, 0, 0, 4, 0, 0, 1, 0)))
        assertNotNull(TilePack.headerError("a.gemf", b(0, 0, 0, 3)))
        assertNotNull(TilePack.headerError("a.png", b(1, 2, 3)))
    }

    @Test fun freeSpaceCheck() {
        val mb = 1024L * 1024
        assertNull(TilePack.spaceError(100 * mb, 200 * mb))
        assertNotNull(TilePack.spaceError(100 * mb, 150 * mb))        // declared size plus the margin does not fit
        assertNotNull(TilePack.spaceError(-1, 10 * mb))               // unknown size still needs the margin
        assertNull(TilePack.spaceError(-1, 100 * mb))
    }
}
