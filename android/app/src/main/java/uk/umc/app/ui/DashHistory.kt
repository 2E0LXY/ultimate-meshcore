package uk.umc.app.ui

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import org.json.JSONArray
import uk.umc.app.AppState
import uk.umc.app.proto.MeshSession

/**
 * The dashboard's history. The radio keeps counters, not a time series, so while the app is
 * connected it reads them once a minute and keeps 24 hours per radio on the phone.
 */
object DashHistory {
    private var prefs: SharedPreferences? = null
    private var radioKey = ""
    private var lastSave = 0L

    val samples = MutableStateFlow<List<DashSample>>(emptyList())

    /** Flash used / total, in the units the radio reports; null until the first reading. */
    val storage = MutableStateFlow<Pair<Long, Long>?>(null)

    fun init(context: Context) {
        if (prefs == null) prefs = context.applicationContext.getSharedPreferences("umc_hist", Context.MODE_PRIVATE)
    }

    private fun now() = System.currentTimeMillis() / 1000

    private fun load(key: String) {
        radioKey = key
        val raw = prefs?.getString("h:$key", null)
        val out = ArrayList<DashSample>()
        val cut = now() - 86400
        runCatching {
            val a = JSONArray(raw ?: "[]")
            for (i in 0 until a.length()) {
                val r = a.getJSONArray(i)
                val t = r.getLong(0)
                if (t >= cut) out.add(DashSample(t, r.getLong(1), r.getLong(2), r.getLong(3), r.getLong(4), r.getLong(5),
                    r.getInt(6), r.getInt(7), r.getDouble(8), r.getInt(9), r.getLong(10), r.getLong(11)))
            }
        }
        samples.value = out
    }

    @Synchronized
    private fun save() {
        val p = prefs ?: return
        if (radioKey.isEmpty()) return
        val a = JSONArray()
        samples.value.forEach {
            a.put(JSONArray().put(it.t).put(it.rx).put(it.tx).put(it.rxFlood).put(it.txFlood).put(it.err)
                .put(it.noise).put(it.rssi).put(it.snr).put(it.battMv).put(it.txAir).put(it.rxAir))
        }
        p.edit().putString("h:$radioKey", a.toString()).apply()
        lastSave = System.currentTimeMillis()
    }

    @Synchronized
    private fun add(s: DashSample) {
        val cur = samples.value
        if (cur.isNotEmpty() && s.t - cur.last().t < 45) return          // too soon after the last one
        val cut = s.t - 86400
        samples.value = cur.filter { it.t >= cut } + s
        if (System.currentTimeMillis() - lastSave > 300_000) save()
    }

    /** Reads the radio now and records it. Safe to call from a refresh button. */
    suspend fun sample(session: MeshSession) {
        session.refreshRadioStats()
        val st = session.radioStats.value ?: return
        val batt = runCatching { session.battery() }.getOrNull()
        batt?.let { storage.value = it.second }
        add(DashSample(now(), st.recvFlood + st.recvDirect, st.sentFlood + st.sentDirect, st.recvFlood, st.sentFlood,
            st.recvErrors, st.noiseFloor, st.lastRssi, st.lastSnr, batt?.first ?: 0, st.txAirSecs, st.rxAirSecs))
    }

    /** Runs for as long as this session is the connected one: one reading a minute. */
    suspend fun run(session: MeshSession) {
        var me = session.self.value
        while (me == null) {
            delay(1000)
            if (AppState.session.value !== session) return
            me = session.self.value
        }
        load(me.publicKey.take(16))
        while (AppState.session.value === session) {
            runCatching { sample(session) }
            delay(60_000)
        }
        save()
    }

    fun flush() = save()
}
