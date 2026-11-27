package uk.umc.app.net

import org.junit.Assert.*
import org.junit.Test

class MiniJsonTest {
    @Test fun depthLimitGivesAPlainError() {
        val deep = "[".repeat(MiniJson.MAX_DEPTH + 1) + "]".repeat(MiniJson.MAX_DEPTH + 1)
        val e = assertThrows(IllegalArgumentException::class.java) { MiniJson.parse(deep) }
        assertTrue(e.message!!.contains("nested too deeply"))
        assertNull(MiniJson.parseObject("{\"a\":$deep}"))
        val ok = "[".repeat(MiniJson.MAX_DEPTH) + "]".repeat(MiniJson.MAX_DEPTH)
        assertNotNull(MiniJson.parse(ok))
    }

    @Test fun hugeNestingDoesNotCrash() {
        assertNull(MiniJson.parseObject("{\"a\":" + "[".repeat(200_000)))
        assertNull(MiniJson.parseObject("{\"a\":" + "{\"a\":".repeat(100_000)))
    }

    @Test fun truncatedInputIsAnErrorNotACrash() {
        for (t in listOf("{", "[", "{\"a\"", "{\"a\":1", "[1,", "[1", "{\"a\":1,", "\"x", "tru", "-")) assertNull(t, MiniJson.parseObject(t))
    }

    @Test fun objWritesNullForNonFiniteNumbers() {
        val j = MiniJson.obj("a" to Double.POSITIVE_INFINITY, "b" to Double.NaN, "c" to Float.NEGATIVE_INFINITY, "d" to 1.5, "e" to 7L, "f" to true)
        assertEquals("{\"a\":null,\"b\":null,\"c\":null,\"d\":1.5,\"e\":7,\"f\":true}", j)
        assertNotNull(MiniJson.parseObject(j))
    }

    @Test fun readsBareInfinityTokensWithoutFailing() {
        val m = MiniJson.parseObject("{\"a\":Infinity,\"b\":-Infinity,\"c\":NaN,\"d\":1e999}")!!
        assertEquals(Double.POSITIVE_INFINITY, m["a"]); assertEquals(Double.NEGATIVE_INFINITY, m["b"])
        assertTrue((m["c"] as Double).isNaN()); assertEquals(Double.POSITIVE_INFINITY, m["d"])
    }
}
