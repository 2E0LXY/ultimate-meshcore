package uk.umc.app.net

/** One sensor reading from a repeater (Cayenne LPP). Pure Kotlin. */
data class SensorReading(val channel: Int, val type: Int, val name: String, val value: Double, val unit: String)

/** The newest readings of one repeater, and when they arrived. */
data class SensorSet(val deviceId: String, val name: String, val atMs: Long, val readings: List<SensorReading>) {
    val label get() = name.ifBlank { deviceId.take(8) }
}

object Lpp {
    private class T(val name: String, val size: Int, val div: Int, val signed: Boolean, val unit: String)
    private val TYPES = mapOf(
        0 to T("digital in", 1, 1, false, ""), 1 to T("digital out", 1, 1, false, ""),
        2 to T("analog in", 2, 100, true, ""), 3 to T("analog out", 2, 100, true, ""),
        100 to T("generic", 4, 1, false, ""), 101 to T("light", 2, 1, false, "lx"), 102 to T("presence", 1, 1, false, ""),
        103 to T("temperature", 2, 10, true, "°C"), 104 to T("humidity", 1, 2, false, "%"), 115 to T("pressure", 2, 10, false, "hPa"),
        116 to T("voltage", 2, 100, false, "V"), 117 to T("current", 2, 1000, true, "A"), 118 to T("frequency", 4, 1, false, "Hz"),
        120 to T("percent", 1, 1, false, "%"), 121 to T("altitude", 2, 1, true, "m"), 125 to T("concentration", 2, 1, false, "ppm"),
        128 to T("power", 2, 1, false, "W"), 130 to T("distance", 4, 1000, false, "m"), 131 to T("energy", 4, 1000, false, "kWh"),
        132 to T("direction", 2, 1, false, "°"), 133 to T("time", 4, 1, false, ""), 142 to T("switch", 1, 1, false, ""))
    private val SKIP = mapOf(113 to 6, 134 to 6, 135 to 3, 136 to 9)      // accelerometer, gyrometer, colour, GPS: skipped, not shown

    /** Reads what it can; stops quietly at anything unknown or cut short. Never throws. */
    fun decode(b: ByteArray): List<SensorReading> {
        val out = ArrayList<SensorReading>()
        var i = 0
        while (i + 2 <= b.size) {
            val ch = b[i].toInt() and 0xFF
            val t = b[i + 1].toInt() and 0xFF
            if (ch == 0 && t == 0) break
            val skip = SKIP[t]
            if (skip != null) { i += 2 + skip; continue }
            val ty = TYPES[t] ?: break
            if (i + 2 + ty.size > b.size) break
            var v = 0L
            for (k in 0 until ty.size) v = (v shl 8) or (b[i + 2 + k].toLong() and 0xFF)
            if (ty.signed) { val bit = 1L shl (ty.size * 8 - 1); if (v and bit != 0L) v -= (bit shl 1) }
            out.add(SensorReading(ch, t, ty.name, Math.round(v.toDouble() / ty.div * 1000) / 1000.0, ty.unit))
            i += 2 + ty.size
        }
        return out
    }

    fun format(r: SensorReading): String {
        val digits = if (r.type == 116 || r.type == 117) 2 else if (Math.abs(r.value) >= 100) 0 else 1
        val num = String.format(java.util.Locale.UK, "%.${digits}f", r.value)
        return if (r.unit.isEmpty()) num else "$num ${r.unit}"
    }
}
