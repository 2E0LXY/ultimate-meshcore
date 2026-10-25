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
import uk.umc.app.ui.Background
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
        loadScopes()
        loadRegions()
        loadLook()
        uk.umc.app.ui.DashHistory.init(context)
        ackDisplay.value = prefs.getString("ackShow", "count") ?: "count"
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
        s.scopeFor = { channel -> channelScope(channel) }
        session.value = s
        s.start()
        scope.launch { uk.umc.app.ui.DashHistory.run(s) }
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

    // ---------------------------------------------------------------- how it looks

    val background = MutableStateFlow(Background.SYSTEM)
    val backgroundColour = MutableStateFlow(0)          // which entry of backgroundPalette
    val backgroundPhoto = MutableStateFlow<String?>(null)   // content URI of a chosen picture

    fun setBackground(kind: Background) {
        background.value = kind
        prefs.edit().putString("bg", kind.name).apply()
    }

    fun setBackgroundColour(index: Int) {
        backgroundColour.value = index
        prefs.edit().putInt("bgColour", index).apply()
    }

    fun setBackgroundPhoto(uri: String?) {
        backgroundPhoto.value = uri
        prefs.edit().putString("bgPhoto", uri).apply()
        if (uri != null) setBackground(Background.PHOTO)
    }

    private fun loadLook() {
        background.value = runCatching { Background.valueOf(prefs.getString("bg", "SYSTEM") ?: "SYSTEM") }
            .getOrDefault(Background.SYSTEM)
        backgroundColour.value = prefs.getInt("bgColour", 0)
        backgroundPhoto.value = prefs.getString("bgPhoto", null)
    }

    // ---------------------------------------------------------------- delivery marks

    /** How much a sent message says about where it got to: "off", "mark" or "count".
     *  The same three the radio itself offers, so both ends agree. */
    val ackDisplay = MutableStateFlow("count")

    fun setAckDisplay(mode: String) {
        if (mode !in listOf("off", "mark", "count")) return
        ackDisplay.value = mode
        prefs.edit().putString("ackShow", mode).apply()
    }

    // ---------------------------------------------------------------- regions

    /** Region names this phone knows, shared across every channel's scope picker.
     *  Communities agree these between themselves, so they are typed in, not built in. */
    val regions = MutableStateFlow(listOf("yorkshire", "eng-ne", "northwest", "uk"))

    /** The mesh only accepts up to 29 bytes of lowercase letters, digits and hyphens, and
     *  names have to match exactly between nodes for filtering to work at all. */
    fun isValidRegion(name: String): Boolean =
        name.isNotEmpty() && name.length <= 29 && name.all { it in 'a'..'z' || it in '0'..'9' || it == '-' }

    fun addRegion(name: String): Boolean {
        val n = name.trim()
        if (!isValidRegion(n) || n in regions.value) return false
        regions.value = regions.value + n
        saveRegions()
        return true
    }

    fun removeRegion(name: String) {
        regions.value = regions.value.filter { it != name }
        saveRegions()
    }

    private fun saveRegions() {
        prefs.edit().putString("regions", JSONArray(regions.value).toString()).apply()
    }

    private fun loadRegions() {
        val raw = prefs.getString("regions", null) ?: return
        val arr = runCatching { JSONArray(raw) }.getOrNull() ?: return
        regions.value = (0 until arr.length()).map { arr.getString(it) }
    }

    // ---------------------------------------------------------------- region scopes

    val scopes = MutableStateFlow<Map<String, String>>(emptyMap())

    fun channelScope(channel: String): String? = scopes.value[channel]

    fun setChannelScope(channel: String, region: String) {
        val next = scopes.value.toMutableMap()
        if (region.isBlank()) next.remove(channel) else next[channel] = region.trim()
        scopes.value = next
        val o = JSONObject()
        next.forEach { (k, v) -> o.put(k, v) }
        prefs.edit().putString("scopes", o.toString()).apply()
    }

    private fun loadScopes() {
        val o = runCatching { JSONObject(prefs.getString("scopes", "{}") ?: "{}") }.getOrNull() ?: return
        scopes.value = o.keys().asSequence().associateWith { o.getString(it) }
    }

    /** Web address of the connected radio, when we reached it over WiFi. */
    fun webHost(): String? = target.value?.let { if (it.kind == LinkKind.WIFI) it.address.substringBefore(':') else null }
}
