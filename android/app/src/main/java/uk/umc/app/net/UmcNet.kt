package uk.umc.app.net

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import uk.umc.app.AppState

/** A channel the phone can read and write in UMC Net mode. [psk] is base64, or empty for a #hashtag channel. */
data class NetChannelDef(val name: String, val psk: String)

enum class JoinPhase { NONE, KNOCKING, JOINED }

/**
 * UMC Net (internet) mode: channel messages through the MQTT broker with no radio attached.
 * Lives for the whole app like AppState; the connection runs while the app process does and is dropped
 * with it (there is no background service). Credentials and keys sit in EncryptedSharedPreferences.
 */
object UmcNet {
    private val scope get() = AppState.scope
    private var prefs: SharedPreferences? = null
    private var appContext: Context? = null
    private var identity: Identity? = null
    private var session: MqttSession? = null
    private var hellos: Job? = null
    private val book = NetBook()
    private val limiter = SendLimiter()

    val phase = MutableStateFlow(JoinPhase.NONE)
    val account = MutableStateFlow<UmcAccount?>(null)
    val host = MutableStateFlow(Enrol.DEFAULT_HOST)
    val clientId = MutableStateFlow("")
    val status = MutableStateFlow("not connected")
    val connected = MutableStateFlow(false)
    val channels = MutableStateFlow(listOf(NetChannelDef("Public", MsgCodec.PUBLIC_PSK)))
    val senderName = MutableStateFlow("UMC-App")
    val messages = MutableStateFlow<List<NetMessage>>(emptyList())
    val repeaters = MutableStateFlow<Map<String, Repeater>>(emptyMap())
    /** Set when secure storage cannot be opened: nothing is saved and nothing is sent. */
    val storageError = MutableStateFlow<String?>(null)

    fun init(context: Context) {
        if (appContext != null) return
        appContext = context.applicationContext
        val p = try {
            val key = MasterKey.Builder(context.applicationContext).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
            EncryptedSharedPreferences.create(context.applicationContext, "umcnet_secure", key,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV, EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM)
        } catch (e: Exception) { storageError.value = "Secure storage is not available on this phone: ${e.message}"; return }
        prefs = p
        val seed = p.getString("seed", null)?.let { MsgCodec.fromHex(it) }?.takeIf { it.size == 32 }
        val id = Identity(seed ?: Identity.generate().seed.also { p.edit().putString("seed", MsgCodec.toHex(it)).apply() })
        identity = id; clientId.value = id.id
        host.value = p.getString("host", Enrol.DEFAULT_HOST) ?: Enrol.DEFAULT_HOST
        senderName.value = p.getString("sender", "UMC-App") ?: "UMC-App"
        p.getString("channels", null)?.let { loadChannels(it) }
        p.getString("account", null)?.let { SetupCode.parse(it).getOrNull() }?.takeIf { it.clientId == id.id }?.let { account.value = it }
        when {
            account.value != null -> { phase.value = JoinPhase.JOINED; if (p.getBoolean("on", true)) startAccount() }
            p.getBoolean("knocking", false) -> startKnocking()
        }
    }

    private fun loadChannels(json: String) {
        val a = runCatching { JSONArray(json) }.getOrNull() ?: return
        val out = (0 until a.length()).mapNotNull { runCatching { a.getJSONObject(it).let { o -> NetChannelDef(o.getString("n"), o.optString("k", "")) } }.getOrNull() }
        if (out.isNotEmpty()) channels.value = out
    }

    private fun saveChannels() {
        val a = JSONArray(); channels.value.forEach { a.put(JSONObject().put("n", it.name).put("k", it.psk)) }
        prefs?.edit()?.putString("channels", a.toString())?.apply()
    }

    private fun decoded(): List<NetChannel> = channels.value.mapNotNull { runCatching { NetChannel.of(it.name, it.psk.ifBlank { null }) }.getOrNull() }

    // ---------------------------------------------------------------- joining (enrolment)

    fun setHost(h: String) { host.value = h.trim(); prefs?.edit()?.putString("host", host.value)?.apply() }

    /** Knock on the doorbell as the public `enrol` account and ask to join; the grant arrives when the administrator approves. */
    fun requestAccess() {
        if (storageError.value != null || identity == null) return AppState.say(storageError.value ?: "Not ready yet")
        if (!SetupCode.validHost(host.value)) return AppState.say("The host must be a name such as net.example.uk, with no https:// or path")
        prefs?.edit()?.putBoolean("knocking", true)?.apply()
        startKnocking()
    }

    fun cancelRequest() {
        stopSession(); prefs?.edit()?.putBoolean("knocking", false)?.apply()
        phase.value = if (account.value != null) JoinPhase.JOINED else JoinPhase.NONE; status.value = "not connected"
    }

    private fun startKnocking() {
        val id = identity ?: return
        stopSession(); phase.value = JoinPhase.KNOCKING
        val s = MqttSession(host.value, Enrol.DOORBELL_USER, Enrol.DOORBELL_PASSWORD, Enrol.doorbellClientId(id.id), listOf(Enrol.grantTopic(id.id)),
            onMessage = { _, payload, _ -> if (payload.isNotEmpty()) onGrant(String(payload, Charsets.UTF_8)) },
            onState = { t, c, _ -> status.value = if (c) "Waiting for the administrator to approve" else t; connected.value = c },
            onConnected = { startHellos() })
        session = s; s.start()
    }

    /** The first five requests a minute apart, then one every five minutes, as the repeater firmware does. */
    private fun startHellos() {
        hellos?.cancel()
        hellos = scope.launch {
            var n = 0
            while (true) {
                sendHello()
                n++; delay(if (n < 5) 60_000L else 300_000L)
            }
        }
    }

    private fun sendHello() {
        val id = identity ?: return; val s = session ?: return
        val name = senderName.value
        val ver = runCatching { appContext!!.packageManager.getPackageInfo(appContext!!.packageName, 0).versionName }.getOrNull() ?: "app"
        val json = Enrol.helloJson(id, name, ver, "UMC Android app", System.currentTimeMillis() / 1000, Enrol.newNonce())
        s.publish(Enrol.TOPIC_HELLO, json.toByteArray(Charsets.UTF_8)) { status.value = "could not send the request: $it" }
    }

    private fun onGrant(text: String) {
        val id = identity ?: return
        val code = Enrol.openGrant(id, text.trim())
        if (code == null) { status.value = "A grant arrived but could not be opened (it is not for this phone, or is damaged)"; return }
        val r = SetupCode.parse(code)
        val a = r.getOrNull()
        if (a == null) { status.value = "The grant did not hold a usable account: ${r.exceptionOrNull()?.message}"; return }
        if (a.clientId != id.id) { status.value = "The grant was for a different client id, so it was ignored"; return }
        adopt(a)
    }

    /** Stores the account (from a grant, a pasted setup code or manual entry), leaves the doorbell and connects with it. */
    fun adopt(a: UmcAccount): String? {
        val id = identity ?: return "Not ready yet"
        SetupCode.validate(a)?.let { return it }
        if (a.clientId != id.id) return "That account is for client id ${a.clientId.take(8)}…, not this phone (${id.id.take(8)}…)"
        val p = prefs ?: return storageError.value ?: "Secure storage is not available"
        p.edit().putString("account", a.toSetupCode()).putBoolean("knocking", false).putBoolean("on", true).apply()
        hellos?.cancel(); account.value = a; phase.value = JoinPhase.JOINED
        startAccount(); return null
    }

    /** Fallback: a pasted setup code. An error in plain words, or null. */
    fun useSetupCode(code: String): String? {
        val r = SetupCode.parse(code); val a = r.getOrNull() ?: return r.exceptionOrNull()?.message
        return adopt(a)
    }

    fun forgetAccount() {
        stopSession(); account.value = null; phase.value = JoinPhase.NONE; status.value = "not connected"
        prefs?.edit()?.remove("account")?.putBoolean("knocking", false)?.apply(); book.clear(); messages.value = emptyList(); repeaters.value = emptyMap()
    }

    // ---------------------------------------------------------------- the account connection

    fun connect() { if (account.value != null) { prefs?.edit()?.putBoolean("on", true)?.apply(); startAccount() } }
    fun disconnect() { stopSession(); prefs?.edit()?.putBoolean("on", false)?.apply(); status.value = "not connected" }

    private fun stopSession() { hellos?.cancel(); session?.close(); session = null; connected.value = false }

    private fun startAccount() {
        val a = account.value ?: return
        stopSession()
        val s = MqttSession(a.host, a.user, a.password, a.clientId, Protocol.subscriptions(a.area),
            onMessage = { topic, payload, retained -> onBroker(topic, payload, retained) },
            onState = { t, c, _ -> status.value = t; connected.value = c })
        session = s; s.start()
    }

    private fun onBroker(topic: String, payload: ByteArray, retained: Boolean) {
        val me = identity?.id ?: return
        val t = Protocol.parseTopic(topic) ?: return
        if (t.deviceId == me) return                                     // our own packets echoed back
        val r = Protocol.parseReport(topic, payload) ?: return
        if (r.originId == me) return
        val now = System.currentTimeMillis()
        val old = repeaters.value[r.deviceId]
        val rep = Repeater(r.deviceId, r.name.ifBlank { old?.name ?: "" }, if (r.kind == "status") (r.status ?: "unknown") else (old?.status ?: "unknown"),
            if (retained) (old?.lastMs ?: 0L) else now)
        if (old != rep) repeaters.value = repeaters.value + (r.deviceId to rep)
        if (r.kind == "status") return
        val raw = r.raw ?: return
        val changed = if (r.direction == "tx") book.onSent(r.deviceId, raw, now)
                      else book.onHeard(r.deviceId, raw, r.snr, r.rssi, now, decoded(), AppState.regions.value)
        if (changed) messages.value = book.messages()
    }

    // ---------------------------------------------------------------- channels

    /** Adds a channel; an error in plain words, or null. A #name needs no key; any other name needs a base64 16-byte key. */
    fun addChannel(name: String, psk: String): String? {
        val n = name.trim()
        try { NetChannel.of(n, psk.trim().ifBlank { null }) } catch (e: IllegalArgumentException) { return e.message }
        if (channels.value.any { it.name == n }) return "that channel is already in the list"
        channels.value = channels.value + NetChannelDef(n, psk.trim()); saveChannels(); return null
    }

    fun removeChannel(name: String) { channels.value = channels.value.filter { it.name != name }; saveChannels() }

    fun setSender(n: String) { senderName.value = n.trim(); prefs?.edit()?.putString("sender", senderName.value)?.apply() }

    // ---------------------------------------------------------------- sending

    /** Publishes a channel message. [via] is a repeater id, or null for every bridging repeater. An error in plain words, or null. */
    fun send(channelName: String, region: String?, text: String, via: String?): String? {
        val a = account.value ?: return "join UMC Net first"
        val s = session ?: return "not connected"
        if (!connected.value) return "not connected to the broker"
        val def = channels.value.firstOrNull { it.name == channelName } ?: return "that channel is not set up"
        val ch = try { NetChannel.of(def.name, def.psk.ifBlank { null }) } catch (e: IllegalArgumentException) { return e.message }
        val sender = senderName.value.trim(); val body = text.trim(); val reg = region?.trimStart('#').orEmpty()
        SendRules.check(body, sender, reg, AppState.regions.value)?.let { return it }
        val now = System.currentTimeMillis()
        val live = repeaters.value.values.filter { it.online(now) }
        if (live.isEmpty()) return "no repeater is online to send it"
        if (via != null && live.none { it.id == via }) return "the repeater you chose is not online"
        if (!limiter.tryAcquire(now)) return "at most ${MsgCodec.MAX_PER_MINUTE} messages a minute"
        val ts = now / 1000
        val raw = try { MsgCodec.buildGroupText(ch, sender, body, ts, reg.ifEmpty { null }) } catch (e: IllegalArgumentException) { return e.message }
        val json = Protocol.txJson("UMC App", a.clientId, ts, via ?: "", raw)
        book.addOutgoing(raw, ch.name, reg, sender, body, ts, now); messages.value = book.messages()
        s.publish(Protocol.publishTopic(a.area, a.clientId), json.toByteArray(Charsets.UTF_8)) { status.value = "send failed: $it" }
        return null
    }
}
