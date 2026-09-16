package uk.umc.app.proto

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * The MeshCore companion protocol: the frames a radio exchanges with an app.
 *
 * Commands are what we send, responses and pushes are what the radio sends back. This is the
 * same protocol the radio speaks over Bluetooth, USB and TCP, so one implementation serves
 * every connection type.
 */
object Cmd {
    const val APP_START = 1
    const val SEND_TXT_MSG = 2
    const val SEND_CHANNEL_TXT_MSG = 3
    const val GET_CONTACTS = 4
    const val GET_DEVICE_TIME = 5
    const val SET_DEVICE_TIME = 6
    const val SEND_SELF_ADVERT = 7
    const val SET_ADVERT_NAME = 8
    const val ADD_UPDATE_CONTACT = 9
    const val SYNC_NEXT_MESSAGE = 10
    const val SET_RADIO_PARAMS = 11
    const val SET_RADIO_TX_POWER = 12
    const val RESET_PATH = 13
    const val SET_ADVERT_LATLON = 14
    const val REMOVE_CONTACT = 15
    const val SHARE_CONTACT = 16
    const val EXPORT_CONTACT = 17
    const val IMPORT_CONTACT = 18
    const val REBOOT = 19
    const val GET_BATT_AND_STORAGE = 20
    const val SET_TUNING_PARAMS = 21
    const val DEVICE_QUERY = 22
    const val SEND_LOGIN = 26
    const val SEND_STATUS_REQ = 27
    const val LOGOUT = 29
    const val GET_CONTACT_BY_KEY = 30
    const val GET_CHANNEL = 31
    const val SET_CHANNEL = 32
    const val SEND_TRACE_PATH = 36
    const val SET_DEVICE_PIN = 37
    const val SET_OTHER_PARAMS = 38
    const val SEND_TELEMETRY_REQ = 39
    const val GET_TUNING_PARAMS = 43
    const val SEND_BINARY_REQ = 50
    const val FACTORY_RESET = 51
    const val SEND_PATH_DISCOVERY_REQ = 52
    const val GET_STATS = 56
    const val SET_AUTOADD_CONFIG = 58
    const val GET_AUTOADD_CONFIG = 59
    const val SET_PATH_HASH_MODE = 61
    const val SET_FLOOD_SCOPE_KEY = 54
    const val SET_DEFAULT_FLOOD_SCOPE = 63
    const val GET_DEFAULT_FLOOD_SCOPE = 64
}

object Resp {
    const val OK = 0
    const val ERR = 1
    const val CONTACTS_START = 2
    const val CONTACT = 3
    const val END_OF_CONTACTS = 4
    const val SELF_INFO = 5
    const val SENT = 6
    const val MSG_DIRECT_OLD = 7
    const val MSG_CHANNEL_OLD = 8
    const val CURR_TIME = 9
    const val NO_MORE_MESSAGES = 10
    const val EXPORT_CONTACT = 11
    const val BATT_AND_STORAGE = 12
    const val DEVICE_INFO = 13
    const val PRIVATE_KEY = 14
    const val DISABLED = 15
    const val MSG_DIRECT = 16
    const val MSG_CHANNEL = 17
    const val CHANNEL_INFO = 18
    const val STATS = 24
    const val AUTOADD_CONFIG = 25
    const val DEFAULT_FLOOD_SCOPE = 28
}

object Push {
    const val ADVERT = 0x80
    const val PATH_UPDATED = 0x81
    const val SEND_CONFIRMED = 0x82
    const val MSG_WAITING = 0x83
    const val RAW_DATA = 0x84
    const val LOGIN_SUCCESS = 0x85
    const val LOGIN_FAIL = 0x86
    const val STATUS_RESPONSE = 0x87
    const val LOG_RX_DATA = 0x88
    const val TRACE_DATA = 0x89
    const val NEW_ADVERT = 0x8A
    const val TELEMETRY_RESPONSE = 0x8B
    const val BINARY_RESPONSE = 0x8C
    const val PATH_DISCOVERY_RESPONSE = 0x8D
    const val CONTACT_DELETED = 0x8F
    const val CONTACTS_FULL = 0x90
}

object ErrCode {
    fun text(code: Int): String = when (code) {
        1 -> "not supported by this radio"
        2 -> "not found"
        3 -> "no space / busy - try again"
        4 -> "the radio is busy"
        5 -> "storage error"
        6 -> "invalid value"
        else -> "error $code"
    }
}

const val ADV_TYPE_CHAT = 1
const val ADV_TYPE_REPEATER = 2
const val ADV_TYPE_ROOM = 3
const val ADV_TYPE_SENSOR = 4

const val TXT_TYPE_PLAIN = 0
const val TXT_TYPE_CLI_DATA = 1
const val TXT_TYPE_SIGNED_PLAIN = 2

const val MAX_TEXT_BYTES = 160

/** Little-endian frame writer. */
class FrameBuilder(code: Int) {
    private val out = java.io.ByteArrayOutputStream()

    init {
        out.write(code)
    }

    fun u8(v: Int) = apply { out.write(v and 0xFF) }
    fun u16(v: Int) = apply { out.write(v and 0xFF); out.write((v shr 8) and 0xFF) }
    fun u32(v: Long) = apply {
        out.write((v and 0xFF).toInt()); out.write(((v shr 8) and 0xFF).toInt())
        out.write(((v shr 16) and 0xFF).toInt()); out.write(((v shr 24) and 0xFF).toInt())
    }
    fun i32(v: Int) = u32(v.toLong() and 0xFFFFFFFFL)
    fun bytes(b: ByteArray) = apply { out.write(b) }
    fun text(s: String) = apply { out.write(s.toByteArray(Charsets.UTF_8)) }
    fun fixed(s: String, len: Int) = apply {
        val b = ByteArray(len)
        val src = s.toByteArray(Charsets.UTF_8)
        System.arraycopy(src, 0, b, 0, minOf(src.size, len - 1))
        out.write(b)
    }
    fun build(): ByteArray = out.toByteArray()
}

/** Little-endian frame reader. */
class FrameReader(private val b: ByteArray, var pos: Int = 0) {
    val remaining get() = b.size - pos
    fun u8(): Int = b[pos++].toInt() and 0xFF
    fun i8(): Int = b[pos++].toInt()
    fun u16(): Int = u8() or (u8() shl 8)
    fun i16(): Int = u16().let { if (it > 32767) it - 65536 else it }
    fun u32(): Long {
        val v = ByteBuffer.wrap(b, pos, 4).order(ByteOrder.LITTLE_ENDIAN).int.toLong() and 0xFFFFFFFFL
        pos += 4
        return v
    }
    fun i32(): Int {
        val v = ByteBuffer.wrap(b, pos, 4).order(ByteOrder.LITTLE_ENDIAN).int
        pos += 4
        return v
    }
    fun bytes(n: Int): ByteArray {
        val out = b.copyOfRange(pos, minOf(pos + n, b.size))
        pos += n
        return out
    }
    fun str(n: Int): String = bytes(n).toKString()
    fun rest(): ByteArray = bytes(remaining)
    fun restText(): String = rest().toKString()
}

fun ByteArray.toKString(): String {
    val end = indexOfFirst { it == 0.toByte() }.let { if (it < 0) size else it }
    return String(this, 0, end, Charsets.UTF_8)
}

/** Hashtag channel keys and region keys: SHA-256 of "#name" exactly as written, first 16 bytes. */
fun hashtagKey(name: String): ByteArray {
    val n = if (name.startsWith("#")) name else "#$name"
    return java.security.MessageDigest.getInstance("SHA-256").digest(n.toByteArray(Charsets.UTF_8)).copyOfRange(0, 16)
}

fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

fun String.hexToBytes(): ByteArray {
    val clean = filter { it.isDigit() || it in 'a'..'f' || it in 'A'..'F' }
    return ByteArray(clean.length / 2) { clean.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
}

// ---------------------------------------------------------------- decoded types

data class SelfInfo(
    val advType: Int, val txPower: Int, val maxTxPower: Int, val publicKey: String,
    val lat: Double, val lon: Double, val multiAcks: Int, val advertLocPolicy: Int,
    val telemetryMode: Int, val manualAddContacts: Int,
    val freqKhz: Long, val bwKhz: Long, val sf: Int, val cr: Int, val name: String,
)

data class DeviceInfo(
    val firmwareCode: Int, val maxContacts: Int, val maxChannels: Int, val blePin: Long,
    val buildDate: String, val model: String, val version: String, val repeatEnabled: Boolean,
)

data class Contact(
    val publicKey: String, val type: Int, val flags: Int, val outPathLen: Int,
    val path: ByteArray, val name: String, val lastAdvert: Long,
    val lat: Double, val lon: Double, val lastMod: Long, val raw: ByteArray,
) {
    val prefix get() = publicKey.substring(0, 12)
    val hops get() = if (outPathLen == 0xFF) -1 else outPathLen and 63
    val hashSize get() = if (outPathLen == 0xFF) 1 else (outPathLen shr 6) + 1
    val favourite get() = (flags and 1) != 0
    val typeName get() = when (type) {
        ADV_TYPE_REPEATER -> "repeater"
        ADV_TYPE_ROOM -> "room server"
        ADV_TYPE_SENSOR -> "sensor"
        ADV_TYPE_CHAT -> "chat"
        else -> "unknown"
    }
    override fun equals(other: Any?) = other is Contact && other.publicKey == publicKey
    override fun hashCode() = publicKey.hashCode()
}

data class Channel(val idx: Int, val name: String, val secret: ByteArray) {
    override fun equals(other: Any?) = other is Channel && other.idx == idx
    override fun hashCode() = idx
}

data class RepeaterStatus(
    val batteryMv: Int, val txQueue: Int, val noiseFloor: Int, val lastRssi: Int,
    val packetsRecv: Long, val packetsSent: Long, val txAirSecs: Long, val uptimeSecs: Long,
    val sentFlood: Long, val sentDirect: Long, val recvFlood: Long, val recvDirect: Long,
    val errors: Int, val lastSnr: Double?, val directDups: Int?, val floodDups: Int?, val rxAirSecs: Long?,
)

data class TraceResult(val hops: List<String>, val snrs: List<Double>, val finalSnr: Double?)

data class TelemetryValue(val channel: Int, val name: String, val value: String)

object Decode {
    fun selfInfo(f: ByteArray): SelfInfo {
        val r = FrameReader(f, 1)
        val advType = r.u8(); val tx = r.i8(); val maxTx = r.i8()
        val key = r.bytes(32).toHex()
        val lat = r.i32() / 1e6
        val lon = r.i32() / 1e6
        val multi = r.u8(); val loc = r.u8(); val telem = r.u8(); val manual = r.u8()
        val freq = r.u32(); val bw = r.u32(); val sf = r.u8(); val cr = r.u8()
        return SelfInfo(advType, tx, maxTx, key, lat, lon, multi, loc, telem, manual, freq, bw, sf, cr, r.restText())
    }

    fun deviceInfo(f: ByteArray): DeviceInfo {
        val r = FrameReader(f, 1)
        val code = r.u8(); val maxContacts = r.u8() * 2; val maxChannels = r.u8()
        val pin = r.u32()
        val build = r.str(12); val model = r.str(40); val version = r.str(20)
        val repeat = if (r.remaining > 0) r.u8() == 1 else false
        return DeviceInfo(code, maxContacts, maxChannels, pin, build, model, version, repeat)
    }

    fun contact(f: ByteArray): Contact {
        val raw = f.copyOfRange(1, f.size)
        val r = FrameReader(f, 1)
        val key = r.bytes(32).toHex()
        val type = r.u8(); val flags = r.u8(); val pathLen = r.u8()
        val path = r.bytes(64)
        val name = r.str(32)
        val lastAdvert = r.u32()
        var lat = 0.0; var lon = 0.0; var lastMod = 0L
        if (r.remaining >= 12) {
            lat = r.i32() / 1e6; lon = r.i32() / 1e6; lastMod = r.u32()
        }
        return Contact(key, type, flags, pathLen, path, name, lastAdvert, lat, lon, lastMod, raw)
    }

    fun channel(f: ByteArray): Channel {
        val r = FrameReader(f, 1)
        return Channel(r.u8(), r.str(32), r.bytes(16))
    }

    fun status(f: ByteArray): RepeaterStatus {
        val r = FrameReader(f, 8)
        return RepeaterStatus(
            r.u16(), r.u16(), r.i16(), r.i16(), r.u32(), r.u32(), r.u32(), r.u32(),
            r.u32(), r.u32(), r.u32(), r.u32(), r.u16(),
            if (r.remaining >= 2) r.i16() / 4.0 else null,
            if (r.remaining >= 2) r.u16() else null,
            if (r.remaining >= 2) r.u16() else null,
            if (r.remaining >= 4) r.u32() else null,
        )
    }

    fun trace(f: ByteArray): TraceResult {
        val r = FrameReader(f, 2)
        val pathLen = r.u8(); val flags = r.u8()
        r.u32(); r.u32()
        val hashSize = 1 shl (flags and 3)
        val hashes = r.bytes(pathLen)
        val snrs = ArrayList<Double>()
        repeat(pathLen shr (flags and 3)) { if (r.remaining > 0) snrs.add(r.i8() / 4.0) }
        val finalSnr = if (r.remaining > 0) r.i8() / 4.0 else null
        val hops = ArrayList<String>()
        var i = 0
        while (i < pathLen) {
            hops.add(hashes.copyOfRange(i, minOf(i + hashSize, hashes.size)).toHex())
            i += hashSize
        }
        return TraceResult(hops, snrs, finalSnr)
    }

    /** Cayenne LPP, as MeshCore uses it for telemetry. */
    fun telemetry(data: ByteArray): List<TelemetryValue> {
        val out = ArrayList<TelemetryValue>()
        var o = 0
        fun be(off: Int, n: Int, signed: Boolean): Double {
            var v = 0L
            for (i in 0 until n) v = (v shl 8) or (data[off + i].toLong() and 0xFF)
            if (signed && v >= (1L shl (n * 8 - 1))) v -= (1L shl (n * 8))
            return v.toDouble()
        }
        data class T(val name: String, val size: Int, val mult: Double, val unit: String, val signed: Boolean = false)
        val types = mapOf(
            0 to T("Digital in", 1, 1.0, ""), 1 to T("Digital out", 1, 1.0, ""),
            2 to T("Analog in", 2, 0.01, "", true), 3 to T("Analog out", 2, 0.01, "", true),
            100 to T("Sensor", 4, 1.0, ""), 101 to T("Light", 2, 1.0, " lux"), 102 to T("Presence", 1, 1.0, ""),
            103 to T("Temperature", 2, 0.1, " °C", true), 104 to T("Humidity", 1, 0.5, " %"),
            115 to T("Pressure", 2, 0.1, " hPa"), 116 to T("Voltage", 2, 0.01, " V"), 117 to T("Current", 2, 0.001, " A"),
            118 to T("Frequency", 4, 1.0, " Hz"), 120 to T("Percentage", 1, 1.0, " %"), 121 to T("Altitude", 2, 1.0, " m", true),
            125 to T("Concentration", 2, 1.0, " ppm"), 128 to T("Power", 2, 1.0, " W"), 130 to T("Distance", 4, 0.001, " m"),
            131 to T("Energy", 4, 0.001, " kWh"), 132 to T("Direction", 2, 1.0, "°"), 142 to T("Switch", 1, 1.0, ""),
        )
        while (o + 2 <= data.size) {
            val ch = data[o].toInt() and 0xFF
            val type = data[o + 1].toInt() and 0xFF
            o += 2
            val t = types[type]
            when {
                t != null -> {
                    if (o + t.size > data.size) return out
                    val v = be(o, t.size, t.signed) * t.mult
                    o += t.size
                    out.add(TelemetryValue(ch, t.name, "${"%.3f".format(v).trimEnd('0').trimEnd('.')}${t.unit}"))
                }
                type == 133 -> {
                    if (o + 4 > data.size) return out
                    val secs = be(o, 4, false).toLong(); o += 4
                    out.add(TelemetryValue(ch, "Time", java.util.Date(secs * 1000).toString()))
                }
                type == 136 -> {
                    if (o + 9 > data.size) return out
                    val lat = be(o, 3, true) / 1e4
                    val lon = be(o + 3, 3, true) / 1e4
                    val alt = be(o + 6, 3, true) / 100.0
                    o += 9
                    out.add(TelemetryValue(ch, "Location", "%.4f, %.4f · %.0f m".format(lat, lon, alt)))
                }
                type == 113 || type == 134 -> {
                    if (o + 6 > data.size) return out
                    val m = if (type == 113) 0.001 else 0.01
                    val v = (0..4 step 2).joinToString(", ") { "%.2f".format(be(o + it, 2, true) * m) }
                    o += 6
                    out.add(TelemetryValue(ch, if (type == 113) "Accelerometer" else "Gyro", v))
                }
                else -> return out
            }
        }
        return out
    }
}
