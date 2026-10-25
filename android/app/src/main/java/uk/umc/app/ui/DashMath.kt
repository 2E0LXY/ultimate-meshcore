package uk.umc.app.ui

import java.util.TreeMap
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.pow

/** One reading of the radio's counters. Times are seconds; counters are as the radio reports them. */
data class DashSample(
    val t: Long, val rx: Long, val tx: Long, val rxFlood: Long, val txFlood: Long, val err: Long,
    val noise: Int, val rssi: Int, val snr: Double, val battMv: Int, val txAir: Long, val rxAir: Long,
)

enum class SeriesMode { RATE, PCT, AVG }

/** A point on a chart: seconds since the epoch, and a value. */
typealias Point = Pair<Double, Double>

data class Trend(val cur: Double?, val prev: Double?) {
    /** Change since the hour before, in percent; null when there is nothing to compare. */
    val pct: Double? get() = if (cur != null && prev != null && prev > 0.0) (cur - prev) / prev * 100.0 else null
}

/** The numbers behind the dashboard: no screen and no radio in here, so it is unit tested. */
object DashMath {
    /**
     * RATE: how much a counter rose, per minute. PCT: how much of the elapsed time a seconds-counter
     * rose (airtime), as a percentage. AVG: the value itself. Samples are averaged into buckets.
     * A gap of more than 15 minutes, or a counter that went backwards (a restart), is skipped.
     */
    fun series(
        rows: List<DashSample>, now: Long, windowSec: Long, bucketSec: Long, mode: SeriesMode,
        pick: (DashSample) -> Double?,
    ): List<Point> {
        val from = now - windowSec
        val bins = TreeMap<Long, DoubleArray>()
        fun put(t: Long, v: Double?) {
            if (t < from || v == null || v.isNaN() || v.isInfinite()) return
            val b = (t / bucketSec) * bucketSec
            val a = bins.getOrPut(b) { DoubleArray(2) }
            a[0] += v
            a[1] += 1.0
        }
        val use = rows.filter { it.t >= from - 1800 }
        if (mode == SeriesMode.AVG) {
            use.forEach { put(it.t, pick(it)) }
        } else {
            for (i in 1 until use.size) {
                val p = use[i - 1]
                val c = use[i]
                val dt = c.t - p.t
                val a = pick(p)
                val b = pick(c)
                if (dt <= 0 || dt > 900 || a == null || b == null || b < a) continue
                put(c.t, if (mode == SeriesMode.RATE) (b - a) / dt * 60.0 else minOf(100.0, (b - a) / dt * 100.0))
            }
        }
        return bins.map { (t, a) -> minOf(now.toDouble(), t + bucketSec / 2.0) to a[0] / a[1] }
    }

    /** How much a counter rose between two times; null when the history does not really cover it. */
    fun total(rows: List<DashSample>, from: Long, to: Long, pick: (DashSample) -> Double?): Double? {
        val use = rows.filter { it.t >= from - 900 && it.t <= to }
        var sum = 0.0
        var n = 0
        for (i in 1 until use.size) {
            if (use[i].t <= from) continue                          // count only the intervals that end inside the window
            val dt = use[i].t - use[i - 1].t
            val a = pick(use[i - 1])
            val b = pick(use[i])
            if (dt in 1..900 && a != null && b != null && b >= a) {
                sum += b - a
                n++
            }
        }
        return if (n >= 3) sum else null
    }

    fun trend(rows: List<DashSample>, now: Long, pick: (DashSample) -> Double?): Trend =
        Trend(total(rows, now - 3600, now, pick), total(rows, now - 7200, now - 3600, pick))

    /** A tidy top for a chart axis: 1, 2, 5 or 10 times a power of ten. */
    fun niceMax(v: Double): Double {
        if (v <= 0.0) return 1.0
        val p = 10.0.pow(floor(log10(v)))
        return listOf(1.0, 2.0, 5.0, 10.0).first { it * p >= v } * p
    }

    /** Rough single-cell battery gauge, the same curve the old tile used. */
    fun batteryPercent(mv: Int): Int? = if (mv <= 0) null else ((mv - 3300) * 100 / 900).coerceIn(0, 100)

    /** Formats a number compactly for an axis or a tile: 153, 12, 7.5. */
    fun fmt(v: Double): String = when {
        v >= 100 -> v.toLong().toString()
        v >= 10 -> "%.0f".format(v)
        else -> "%.1f".format(v).removeSuffix(".0")
    }
}
