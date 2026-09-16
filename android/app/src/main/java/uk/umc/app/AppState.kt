package uk.umc.app

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import uk.umc.app.link.BleLink
import uk.umc.app.link.Link
import uk.umc.app.link.LinkKind
import uk.umc.app.link.LinkState
import uk.umc.app.link.LinkTarget
import uk.umc.app.link.TcpLink
import uk.umc.app.proto.MeshSession

/**
 * Holds the connection to the radio for the whole app: which radios we know about, which
 * one is connected, and the session on top of it.
 */
object AppState {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    val linkState = MutableStateFlow<LinkState>(LinkState.Idle)
    val target = MutableStateFlow<LinkTarget?>(null)
    val session = MutableStateFlow<MeshSession?>(null)
    val savedDevices = MutableStateFlow<List<LinkTarget>>(emptyList())
    val toast = MutableStateFlow<String?>(null)

    private var link: Link? = null
    private lateinit var prefs: SharedPreferences
    private var appContext: Context? = null

    fun init(context: Context) {
        if (appContext != null) return
        appContext = context.applicationContext
        prefs = context.getSharedPreferences("umc", Context.MODE_PRIVATE)
        loadDevices()
        val last = prefs.getString("last", null)
        savedDevices.value.firstOrNull { it.key() == last }?.let { connect(it) }
    }

    fun say(message: String) {
        toast.value = message
    }

    // ---------------------------------------------------------------- devices

    private fun loadDevices() {
        val raw = prefs.getString("devices", "[]") ?: "[]"
        val arr = runCatching { JSONArray(raw) }.getOrNull() ?: JSONArray()
        val out = ArrayList<LinkTarget>()
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            out.add(LinkTarget(LinkKind.valueOf(o.getString("kind")), o.getString("address"), o.optString("label", o.getString("address"))))
        }
        savedDevices.value = out
    }

    fun rememberDevice(t: LinkTarget) {
        val list = (savedDevices.value.filter { it.key() != t.key() } + t)
        savedDevices.value = list
        val arr = JSONArray()
        list.forEach { arr.put(JSONObject().put("kind", it.kind.name).put("address", it.address).put("label", it.label)) }
        prefs.edit().putString("devices", arr.toString()).apply()
    }

    fun forgetDevice(t: LinkTarget) {
        savedDevices.value = savedDevices.value.filter { it.key() != t.key() }
        val arr = JSONArray()
        savedDevices.value.forEach { arr.put(JSONObject().put("kind", it.kind.name).put("address", it.address).put("label", it.label)) }
        prefs.edit().putString("devices", arr.toString()).apply()
    }

    // ---------------------------------------------------------------- connection

    fun connect(t: LinkTarget) {
        disconnect()
        val ctx = appContext ?: return
        target.value = t
        rememberDevice(t)
        prefs.edit().putString("last", t.key()).apply()

        val l: Link = when (t.kind) {
            LinkKind.BLUETOOTH -> BleLink(ctx, t.address, scope)
            LinkKind.WIFI -> {
                val host = t.address.substringBefore(':')
                val port = t.address.substringAfter(':', "5000").toIntOrNull() ?: 5000
                TcpLink(host, port, scope)
            }
        }
        link = l
        val s = MeshSession(l, scope)
        session.value = s
        s.start()
        scope.launch { l.state.collect { linkState.value = it } }
        scope.launch { s.events.collect { say(it) } }
        scope.launch { l.connect() }
    }

    fun disconnect() {
        link?.close()
        link = null
        session.value = null
        linkState.value = LinkState.Idle
    }

    fun reconnect() {
        target.value?.let { connect(it) }
    }

    /** Web address of the connected radio, when we reached it over WiFi. */
    fun webHost(): String? = target.value?.let { if (it.kind == LinkKind.WIFI) it.address.substringBefore(':') else null }
}
