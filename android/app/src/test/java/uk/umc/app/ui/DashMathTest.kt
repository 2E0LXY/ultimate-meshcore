package uk.umc.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DashMathTest {
    private val now = 1_760_000_000L

    private fun sample(t: Long, rx: Long = 0, tx: Long = 0, txAir: Long = 0, rxAir: Long = 0, noise: Int = -100) =
        DashSample(t, rx, tx, 0, 0, 0, noise, -90, 5.0, 4000, txAir, rxAir)

    /** One sample a minute for [minutes] minutes ending now; rx rises by [perMin] each minute. */
    private fun minutes(minutes: Int, perMin: Long = 6, from: Long = now): List<DashSample> =
        (0..minutes).map { sample(from - (minutes - it) * 60L, rx = it * perMin) }

    @Test fun ratePerMinuteIsTheCounterRise() {
        val s = DashMath.series(minutes(30, 6), now, 3600, 60, SeriesMode.RATE) { it.rx.toDouble() }
        assertTrue(s.isNotEmpty())
        s.forEach { assertEquals(6.0, it.second, 1e-9) }
    }

    @Test fun airtimeIsAShareOfElapsedTime() {
        val rows = (0..10).map { sample(now - (10 - it) * 60L, txAir = it * 3L) }          // 3 s of 60 s on air
        val s = DashMath.series(rows, now, 3600, 60, SeriesMode.PCT) { it.txAir.toDouble() }
        assertEquals(5.0, s.first().second, 1e-9)
    }

    @Test fun aRestartIsSkippedNotPlottedAsANegativeRate() {
        val rows = listOf(sample(now - 240, rx = 100), sample(now - 180, rx = 106), sample(now - 120, rx = 3), sample(now - 60, rx = 9), sample(now, rx = 15))
        val s = DashMath.series(rows, now, 3600, 60, SeriesMode.RATE) { it.rx.toDouble() }
        assertEquals(3, s.size)                                                           // 100>106, 3>9, 9>15; the restart is skipped
        s.forEach { assertEquals(6.0, it.second, 1e-9) }
    }

    @Test fun aLongGapIsSkipped() {
        val rows = listOf(sample(now - 4000, rx = 0), sample(now - 2000, rx = 500), sample(now - 1940, rx = 506))
        val s = DashMath.series(rows, now, 7200, 60, SeriesMode.RATE) { it.rx.toDouble() }
        assertEquals(1, s.size)
        assertEquals(6.0, s[0].second, 1e-9)
    }

    @Test fun averagesAreBucketed() {
        val rows = listOf(sample(now - 50, noise = -100), sample(now - 40, noise = -110))
        val s = DashMath.series(rows, now, 3600, 3600, SeriesMode.AVG) { it.noise.toDouble() }
        assertEquals(1, s.size)
        assertEquals(-105.0, s[0].second, 1e-9)
    }

    @Test fun nothingOutsideTheWindowIsKept() {
        val s = DashMath.series(minutes(30), now, 600, 60, SeriesMode.RATE) { it.rx.toDouble() }
        assertTrue(s.all { it.first >= now - 600 })
    }

    @Test fun totalNeedsRealCoverage() {
        assertNull(DashMath.total(minutes(2), now - 3600, now) { it.rx.toDouble() })
        val t = DashMath.total(minutes(30, 6), now - 3600, now) { it.rx.toDouble() }
        assertNotNull(t)
        assertEquals(180.0, t!!, 1e-9)
    }

    @Test fun trendComparesWithTheHourBefore() {
        val rows = (0..120).map { m ->
            val t = now - (120 - m) * 60L
            sample(t, rx = if (m <= 60) m * 3L else 180L + (m - 60) * 6L)               // 3 a minute, then 6 a minute
        }
        val tr = DashMath.trend(rows, now) { it.rx.toDouble() }
        assertEquals(360.0, tr.cur!!, 1e-9)
        assertEquals(180.0, tr.prev!!, 1e-9)
        assertEquals(100.0, tr.pct!!, 1e-9)
    }

    @Test fun trendHasNoPercentageWithoutAPreviousHour() {
        val tr = DashMath.trend(minutes(30), now) { it.rx.toDouble() }
        assertNotNull(tr.cur)
        assertNull(tr.pct)
    }

    @Test fun niceMaxPicksTidyAxisTops() {
        assertEquals(10.0, DashMath.niceMax(7.3), 1e-9)
        assertEquals(2.0, DashMath.niceMax(1.4), 1e-9)
        assertEquals(50.0, DashMath.niceMax(33.0), 1e-9)
        assertEquals(1.0, DashMath.niceMax(0.0), 1e-9)
        assertEquals(500.0, DashMath.niceMax(420.0), 1e-9)
    }

    @Test fun batteryPercentIsClamped() {
        assertEquals(100, DashMath.batteryPercent(4300))
        assertEquals(0, DashMath.batteryPercent(3000))
        assertEquals(66, DashMath.batteryPercent(3900))
        assertNull(DashMath.batteryPercent(0))
    }

    @Test fun numbersAreFormattedCompactly() {
        assertEquals("153", DashMath.fmt(153.4))
        assertEquals("12", DashMath.fmt(12.0))
        assertEquals("7.5", DashMath.fmt(7.5))
        assertEquals("3", DashMath.fmt(3.0))
    }
}
