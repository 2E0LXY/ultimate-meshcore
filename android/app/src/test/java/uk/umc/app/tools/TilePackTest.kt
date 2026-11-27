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
        assertEquals("Yorkshire_2026.mbtiles", TilePack.localName("Yorkshire 2026.mbtiles"))
        assertEquals("passwd.zip", TilePack.localName("../../etc/passwd.zip"))
        assertEquals("tiles.zip", TilePack.localName("....zip"))
        assertEquals("noext.zip", TilePack.localName("noext"))
        assertTrue(TilePack.localName("x".repeat(500) + ".zip").length <= TilePack.MAX_NAME + 4)
    }
}
