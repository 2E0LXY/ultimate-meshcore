package uk.umc.app.proto

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ErrCodeTest {
    @Test fun busyAndNoSpaceAreWorthTryingAgain() {
        assertTrue(ErrCode.isTransient(3)); assertTrue(ErrCode.isTransient(4))
    }

    @Test fun realRefusalsAreNotRetried() {
        for (c in listOf(0, 1, 2, 5, 6, 99)) assertFalse("code $c", ErrCode.isTransient(c))
    }

    @Test fun everyMessageNamesItsNumberSoItCanBeReported() {
        assertTrue(ErrCode.text(3).contains("error 3")); assertTrue(ErrCode.text(4).contains("error 4"))
        assertEquals("error 42", ErrCode.text(42))
    }

    @Test fun theRadiosErrorNumberTravelsWithTheException() {
        assertEquals(4, MeshError("x", 4).code); assertEquals(0, MeshError("x").code)
    }
}
