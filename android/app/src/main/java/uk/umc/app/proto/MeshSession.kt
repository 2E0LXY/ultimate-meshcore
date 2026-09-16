package uk.umc.app.proto

import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.async
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.CopyOnWriteArrayList
import uk.umc.app.link.Link
import uk.umc.app.link.LinkState

class MeshError(message: String) : Exception(message)

/** A message as the app shows it. */
data class ChatMessage(
    val id: Long,
    val conversation: String,        // "ch:<idx>" or "c:<key prefix>"
    val outgoing: Boolean,
    val text: String,
    val from: String = "",
    val timestamp: Long,             // sender clock, seconds
    val received: Long = System.currentTimeMillis(),
    val hops: Int? = null,
    val snr: Double? = null,
    val cli: Boolean = false,
    var status: String = "",         // sending / sent / delivered / failed
    var ackCode: String? = null,
    var roundTripMs: Long? = null,
    var error: String? = null,
)

/**
 * Talks to one radio: sends commands, waits for the matching reply, and keeps contacts,
 * channels and messages up to date from the pushes that arrive at any time.
 */
class MeshSession(private val link: Link, private val scope: CoroutineScope) {

    val self = MutableStateFlow<SelfInfo?>(null)
    val device = MutableStateFlow<DeviceInfo?>(null)
    val contacts = MutableStateFlow<List<Contact>>(emptyList())
    val channels = MutableStateFlow<List<Channel>>(emptyList())
    val messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val pendingAdverts = MutableStateFlow<List<Contact>>(emptyList())
    val events = MutableSharedFlow<String>(extraBufferCapacity = 32)
    val newMessages = MutableSharedFlow<ChatMessage>(extraBufferCapacity = 32)

    private val lock = Mutex()
    private val awaitingAck = HashMap<String, ChatMessage>()
    private var nextId = 1L

    /** Someone waiting for a particular frame to arrive. */
    private class Waiter(val match: (ByteArray) -> Boolean, val cont: CancellableContinuation<ByteArray>)

    private val waiters = CopyOnWriteArrayList<Waiter>()

    private fun deliver(f: ByteArray) {
        for (w in waiters) {
            if (w.match(f)) {
                waiters.remove(w)
                if (w.cont.isActive) w.cont.resumeWith(Result.success(f))
                return
            }
        }
    }

    /** Suspends until a frame matching [match] arrives, or the timeout passes. */
    private suspend fun awaitFrame(timeoutMs: Long, match: (ByteArray) -> Boolean): ByteArray? =
        withTimeoutOrNull(timeoutMs) {
            suspendCancellableCoroutine { cont ->
                val w = Waiter(match, cont)
                waiters.add(w)
                cont.invokeOnCancellation { waiters.remove(w) }
            }
        }

    fun start() {
        scope.launch {
            link.frames.collect { f ->
                if (f.isEmpty()) return@collect
                handlePush(f)
                deliver(f)
            }
        }
        scope.launch {
            link.state.collect { st ->
                if (st is LinkState.Connected) {
                    runCatching { handshake() }.onFailure { events.emit("Connect failed: ${it.message}") }
                }
            }
        }
    }

    /**
     * Sends a frame and waits for the first reply with one of [expect]. One request at a
     * time, so a reply is never confused with another command's. Errors raise MeshError.
     */
    private suspend fun request(frame: ByteArray, vararg expect: Int, timeoutMs: Long = 12000): ByteArray =
        lock.withLock {
            val pending = scope.async {
                awaitFrame(timeoutMs) { f ->
                    val code = f[0].toInt() and 0xFF
                    code == Resp.ERR || expect.contains(code)
                }
            }
            if (!link.send(frame)) {
                pending.cancel()
                throw MeshError("could not send to the radio")
            }
            val r = pending.await() ?: throw MeshError("no reply from the radio")
            if ((r[0].toInt() and 0xFF) == Resp.ERR) throw MeshError(ErrCode.text(r[1].toInt() and 0xFF))
            r
        }

    /** Waits for a push that arrives later (login result, status, telemetry, trace). */
    private suspend fun waitPush(code: Int, keyPrefix: String?, timeoutMs: Long): ByteArray? =
        awaitFrame(timeoutMs) { f ->
            val c = f[0].toInt() and 0xFF
            if (c != code && !(code == Push.LOGIN_SUCCESS && c == Push.LOGIN_FAIL)) return@awaitFrame false
            if (keyPrefix == null) return@awaitFrame true
            val pfx = f.copyOfRange(2, minOf(8, f.size)).toHex()
            keyPrefix.startsWith(pfx)
        }

    suspend fun handshake() {
        device.value = Decode.deviceInfo(request(FrameBuilder(Cmd.DEVICE_QUERY).u8(3).build(), Resp.DEVICE_INFO))
        val s = request(FrameBuilder(Cmd.APP_START).u8(1).bytes(ByteArray(6)).text("UMC App").build(), Resp.SELF_INFO)
        self.value = Decode.selfInfo(s)
        syncTime()
        refreshContacts()
        refreshChannels()
        drainQueuedMessages()
        events.emit("Connected to ${self.value?.name ?: "radio"}")
    }

    private suspend fun syncTime() {
        runCatching {
            val now = System.currentTimeMillis() / 1000
            val t = request(FrameBuilder(Cmd.GET_DEVICE_TIME).build(), Resp.CURR_TIME)
            val devTime = FrameReader(t, 1).u32()
            if (devTime < now - 30) {
                request(FrameBuilder(Cmd.SET_DEVICE_TIME).u32(now).build(), Resp.OK)
                events.emit("Radio clock set from this phone")
            }
        }
    }

    suspend fun refreshContacts() {
        lock.withLock {
            val list = ArrayList<Contact>()
            val started = scope.async { awaitFrame(12000) { (it[0].toInt() and 0xFF) == Resp.CONTACTS_START } }
            if (!link.send(FrameBuilder(Cmd.GET_CONTACTS).build())) {
                started.cancel()
                throw MeshError("could not ask for contacts")
            }
            started.await() ?: throw MeshError("no contact list from the radio")
            while (true) {
                val f = awaitFrame(15000) {
                    val c = it[0].toInt() and 0xFF
                    c == Resp.CONTACT || c == Resp.END_OF_CONTACTS
                } ?: break
                if ((f[0].toInt() and 0xFF) == Resp.END_OF_CONTACTS) break
                list.add(Decode.contact(f))
            }
            contacts.value = list
            pendingAdverts.value = pendingAdverts.value.filter { p -> list.none { it.publicKey == p.publicKey } }
        }
    }

    suspend fun refreshChannels() {
        val out = ArrayList<Channel>()
        for (i in 0 until 40) {
            val f = runCatching { request(FrameBuilder(Cmd.GET_CHANNEL).u8(i).build(), Resp.CHANNEL_INFO, timeoutMs = 6000) }.getOrNull()
                ?: break
            val ch = Decode.channel(f)
            if (ch.name.isNotEmpty()) out.add(ch)
        }
        channels.value = out
    }

    /** Takes messages the radio kept while no app was connected. */
    suspend fun drainQueuedMessages() {
        repeat(64) {
            val f = runCatching { request(FrameBuilder(Cmd.SYNC_NEXT_MESSAGE).build(), Resp.MSG_DIRECT, Resp.MSG_CHANNEL, Resp.MSG_DIRECT_OLD, Resp.MSG_CHANNEL_OLD, Resp.NO_MORE_MESSAGES, timeoutMs = 6000) }.getOrNull()
                ?: return
            if ((f[0].toInt() and 0xFF) == Resp.NO_MORE_MESSAGES) return
            handleIncomingMessage(f)
        }
    }

    // ---------------------------------------------------------------- pushes

    private fun handlePush(f: ByteArray) {
        when (f[0].toInt() and 0xFF) {
            Push.MSG_WAITING -> scope.launch { drainQueuedMessages() }
            Push.SEND_CONFIRMED -> {
                val ack = f.copyOfRange(1, 5).toHex()
                val trip = FrameReader(f, 5).u32()
                awaitingAck.remove(ack)?.let { m ->
                    update(m) { it.status = "delivered"; it.roundTripMs = trip }
                }
            }
            Push.NEW_ADVERT -> {
                val c = Decode.contact(f)
                if (contacts.value.none { it.publicKey == c.publicKey }) {
                    pendingAdverts.value = (pendingAdverts.value + c).distinctBy { it.publicKey }
                }
                scope.launch { refreshContacts() }
            }
            Push.PATH_UPDATED, Push.CONTACT_DELETED -> scope.launch { refreshContacts() }
            Push.CONTACTS_FULL -> scope.launch { events.emit("The radio's contact list is full") }
        }
    }

    private fun handleIncomingMessage(f: ByteArray) {
        val code = f[0].toInt() and 0xFF
        val r = FrameReader(f, 1)
        var snr: Double? = null
        if (code == Resp.MSG_DIRECT || code == Resp.MSG_CHANNEL) {
            snr = r.i8() / 4.0
            r.pos += 2
        }
        if (code == Resp.MSG_DIRECT || code == Resp.MSG_DIRECT_OLD) {
            val prefix = r.bytes(6).toHex()
            val pathLen = r.u8()
            val txtType = r.u8()
            val ts = r.u32()
            var from = contacts.value.firstOrNull { it.publicKey.startsWith(prefix) }?.name ?: prefix
            if (txtType == TXT_TYPE_SIGNED_PLAIN) {
                val sender = r.bytes(4).toHex()
                from = contacts.value.firstOrNull { it.publicKey.startsWith(sender) }?.name ?: sender
            }
            add(ChatMessage(
                id = nextId++, conversation = "c:$prefix", outgoing = false, text = r.restText(), from = from,
                timestamp = ts, hops = if (pathLen == 0xFF) null else pathLen and 63, snr = snr,
                cli = txtType == TXT_TYPE_CLI_DATA,
            ))
        } else if (code == Resp.MSG_CHANNEL || code == Resp.MSG_CHANNEL_OLD) {
            val idx = r.u8()
            val pathLen = r.u8()
            r.u8()
            val ts = r.u32()
            val full = r.restText()
            val cut = full.indexOf(": ")
            add(ChatMessage(
                id = nextId++, conversation = "ch:$idx", outgoing = false,
                text = if (cut > 0) full.substring(cut + 2) else full,
                from = if (cut > 0) full.substring(0, cut) else "",
                timestamp = ts, hops = if (pathLen == 0xFF) null else pathLen and 63, snr = snr,
            ))
        }
    }

    private fun add(m: ChatMessage) {
        messages.value = (messages.value + m).takeLast(1000)
        scope.launch { newMessages.emit(m) }
    }

    private fun update(m: ChatMessage, block: (ChatMessage) -> Unit) {
        block(m)
        messages.value = messages.value.toList()
    }

    // ---------------------------------------------------------------- actions

    suspend fun sendText(conversation: String, text: String, retry: ChatMessage? = null) {
        val ts = retry?.timestamp ?: (System.currentTimeMillis() / 1000)
        if (conversation.startsWith("ch:")) {
            val idx = conversation.removePrefix("ch:").toInt()
            val m = retry ?: ChatMessage(nextId++, conversation, true, text, self.value?.name ?: "", ts, status = "sending").also { add(it) }
            try {
                request(FrameBuilder(Cmd.SEND_CHANNEL_TXT_MSG).u8(TXT_TYPE_PLAIN).u8(idx).u32(ts).text(text).build(), Resp.OK)
                update(m) { it.status = "sent" }
            } catch (e: Exception) {
                update(m) { it.status = "failed"; it.error = e.message }
            }
            return
        }
        val prefix = conversation.removePrefix("c:")
        val m = retry ?: ChatMessage(nextId++, conversation, true, text, "", ts, status = "sending").also { add(it) }
        update(m) { it.status = "sending" }
        try {
            val f = request(
                FrameBuilder(Cmd.SEND_TXT_MSG).u8(TXT_TYPE_PLAIN).u8(0).u32(ts).bytes(prefix.hexToBytes()).text(text).build(),
                Resp.SENT,
            )
            val r = FrameReader(f, 1)
            r.u8()
            val ack = r.bytes(4).toHex()
            val est = r.u32()
            update(m) { it.status = "sent"; it.ackCode = ack }
            awaitingAck[ack] = m
            scope.launch {
                kotlinx.coroutines.delay(maxOf(est * 2, 8000L))
                if (awaitingAck.remove(ack) != null && m.status == "sent") {
                    update(m) { it.status = "failed"; it.error = "no delivery confirmation" }
                }
            }
        } catch (e: Exception) {
            update(m) { it.status = "failed"; it.error = e.message }
        }
    }

    suspend fun sendCli(contact: Contact, command: String) {
        val ts = System.currentTimeMillis() / 1000
        add(ChatMessage(nextId++, "c:${contact.prefix}", true, command, "", ts, cli = true, status = "sent"))
        request(
            FrameBuilder(Cmd.SEND_TXT_MSG).u8(TXT_TYPE_CLI_DATA).u8(0).u32(ts).bytes(contact.prefix.hexToBytes()).text(command).build(),
            Resp.SENT,
        )
    }

    suspend fun login(contact: Contact, password: String): Boolean {
        val sent = request(FrameBuilder(Cmd.SEND_LOGIN).bytes(contact.publicKey.hexToBytes()).text(password).build(), Resp.SENT)
        val est = FrameReader(sent, 6).u32()
        val push = waitPush(Push.LOGIN_SUCCESS, contact.publicKey, maxOf(est * 2, 15000L) + 15000)
            ?: throw MeshError("no answer from ${contact.name}")
        if ((push[0].toInt() and 0xFF) == Push.LOGIN_FAIL) throw MeshError("login refused (wrong password?)")
        return (push[1].toInt() and 1) != 0
    }

    suspend fun status(contact: Contact): RepeaterStatus {
        val sent = request(FrameBuilder(Cmd.SEND_STATUS_REQ).bytes(contact.publicKey.hexToBytes()).build(), Resp.SENT)
        val est = FrameReader(sent, 6).u32()
        val push = waitPush(Push.STATUS_RESPONSE, contact.publicKey, maxOf(est * 2, 15000L) + 15000)
            ?: throw MeshError("no status from ${contact.name} (log in first?)")
        return Decode.status(push)
    }

    suspend fun telemetry(contact: Contact?): List<TelemetryValue> {
        if (contact == null) {
            val f = request(FrameBuilder(Cmd.SEND_TELEMETRY_REQ).u8(0).u8(0).u8(0).build(), Push.TELEMETRY_RESPONSE)
            return Decode.telemetry(f.copyOfRange(8, f.size))
        }
        val sent = request(
            FrameBuilder(Cmd.SEND_TELEMETRY_REQ).u8(0).u8(0).u8(0).bytes(contact.publicKey.hexToBytes()).build(), Resp.SENT,
        )
        val est = FrameReader(sent, 6).u32()
        val push = waitPush(Push.TELEMETRY_RESPONSE, contact.publicKey, maxOf(est * 2, 15000L) + 15000)
            ?: throw MeshError("no telemetry from ${contact.name}")
        return Decode.telemetry(push.copyOfRange(8, push.size))
    }

    suspend fun discoverPath(contact: Contact): String {
        val sent = request(FrameBuilder(Cmd.SEND_PATH_DISCOVERY_REQ).u8(0).bytes(contact.publicKey.hexToBytes()).build(), Resp.SENT)
        val est = FrameReader(sent, 6).u32()
        val push = waitPush(Push.PATH_DISCOVERY_RESPONSE, contact.publicKey, maxOf(est * 2, 20000L) + 20000)
            ?: throw MeshError("no path discovered")
        val r = FrameReader(push, 8)
        fun leg(): String {
            val l = r.u8()
            val n = l and 63
            val sz = (l shr 6) + 1
            val hashes = r.bytes(n * sz)
            if (n == 0) return "direct"
            return (0 until n).joinToString(" > ") { i -> hashes.copyOfRange(i * sz, (i + 1) * sz).toHex() }
        }
        val out = leg()
        val back = leg()
        refreshContacts()
        return "out: $out\nback: $back"
    }

    suspend fun trace(contact: Contact): TraceResult {
        if (contact.hops < 0) throw MeshError("no known path yet - discover the path first")
        if (contact.hops == 0) throw MeshError("direct neighbour - nothing to trace")
        val hashSize = contact.hashSize
        if (hashSize != 1 && hashSize != 2) throw MeshError("trace supports 1 or 2 byte path hashes")
        val szCode = if (hashSize == 2) 1 else 0
        val hops = (0 until contact.hops).map { contact.path.copyOfRange(it * hashSize, (it + 1) * hashSize) }
        val route = (hops + hops.dropLast(1).reversed()).reduce { a, b -> a + b }
        val tag = (Math.random() * 4_000_000_000L).toLong()
        val sent = request(FrameBuilder(Cmd.SEND_TRACE_PATH).u32(tag).u32(0).u8(szCode).bytes(route).build(), Resp.SENT)
        val est = FrameReader(sent, 6).u32()
        val push = awaitFrame(maxOf(est * 2, 15000L) + 15000) { f ->
            (f[0].toInt() and 0xFF) == Push.TRACE_DATA && FrameReader(f, 4).u32() == tag
        } ?: throw MeshError("trace timed out (a hop may be out of range)")
        return Decode.trace(push)
    }

    suspend fun advert(flood: Boolean) {
        request(if (flood) FrameBuilder(Cmd.SEND_SELF_ADVERT).u8(1).build() else FrameBuilder(Cmd.SEND_SELF_ADVERT).build(), Resp.OK)
    }

    suspend fun resetPath(contact: Contact) {
        request(FrameBuilder(Cmd.RESET_PATH).bytes(contact.publicKey.hexToBytes()).build(), Resp.OK)
        refreshContacts()
    }

    suspend fun shareContact(contact: Contact) =
        request(FrameBuilder(Cmd.SHARE_CONTACT).bytes(contact.publicKey.hexToBytes()).build(), Resp.OK)

    suspend fun removeContact(contact: Contact) {
        request(FrameBuilder(Cmd.REMOVE_CONTACT).bytes(contact.publicKey.hexToBytes()).build(), Resp.OK)
        refreshContacts()
    }

    suspend fun setFavourite(contact: Contact, favourite: Boolean) {
        val raw = contact.raw.copyOf()
        raw[33] = if (favourite) (raw[33].toInt() or 1).toByte() else (raw[33].toInt() and 1.inv()).toByte()
        request(FrameBuilder(Cmd.ADD_UPDATE_CONTACT).bytes(raw.copyOfRange(0, 147)).build(), Resp.OK)
        refreshContacts()
    }

    suspend fun addContact(contact: Contact) {
        request(FrameBuilder(Cmd.ADD_UPDATE_CONTACT).bytes(contact.raw.copyOfRange(0, 147)).build(), Resp.OK)
        pendingAdverts.value = pendingAdverts.value.filter { it.publicKey != contact.publicKey }
        refreshContacts()
    }

    suspend fun exportContact(contact: Contact?): String {
        val f = if (contact == null) request(FrameBuilder(Cmd.EXPORT_CONTACT).build(), Resp.EXPORT_CONTACT)
        else request(FrameBuilder(Cmd.EXPORT_CONTACT).bytes(contact.publicKey.hexToBytes()).build(), Resp.EXPORT_CONTACT)
        return "meshcore://" + f.copyOfRange(1, f.size).toHex()
    }

    suspend fun importContact(uri: String) {
        val raw = uri.removePrefix("meshcore://").hexToBytes()
        if (raw.size < 100) throw MeshError("that doesn't look like a shared contact")
        request(FrameBuilder(Cmd.IMPORT_CONTACT).bytes(raw).build(), Resp.OK)
        refreshContacts()
    }

    suspend fun setChannel(idx: Int, name: String, secret: ByteArray) {
        request(FrameBuilder(Cmd.SET_CHANNEL).u8(idx).fixed(name, 32).bytes(secret).build(), Resp.OK)
        refreshChannels()
    }

    suspend fun setName(name: String) {
        request(FrameBuilder(Cmd.SET_ADVERT_NAME).text(name).build(), Resp.OK)
        self.value = self.value?.copy(name = name)
    }

    suspend fun setLocation(lat: Double, lon: Double) {
        request(FrameBuilder(Cmd.SET_ADVERT_LATLON).i32((lat * 1e6).toInt()).i32((lon * 1e6).toInt()).build(), Resp.OK)
        self.value = self.value?.copy(lat = lat, lon = lon)
    }

    suspend fun setRadio(freqKhz: Long, bwKhz: Long, sf: Int, cr: Int, repeat: Boolean) {
        request(FrameBuilder(Cmd.SET_RADIO_PARAMS).u32(freqKhz).u32(bwKhz).u8(sf).u8(cr).u8(if (repeat) 1 else 0).build(), Resp.OK)
        self.value = self.value?.copy(freqKhz = freqKhz, bwKhz = bwKhz, sf = sf, cr = cr)
    }

    suspend fun setTxPower(dbm: Int) {
        request(FrameBuilder(Cmd.SET_RADIO_TX_POWER).u8(dbm).build(), Resp.OK)
        self.value = self.value?.copy(txPower = dbm)
    }

    suspend fun setOtherParams(manualAdd: Int, telemetryMode: Int, advertLoc: Int, multiAcks: Int) {
        request(FrameBuilder(Cmd.SET_OTHER_PARAMS).u8(manualAdd).u8(telemetryMode).u8(advertLoc).u8(multiAcks).build(), Resp.OK)
        self.value = self.value?.copy(manualAddContacts = manualAdd, telemetryMode = telemetryMode, advertLocPolicy = advertLoc, multiAcks = multiAcks)
    }

    suspend fun setBlePin(pin: Long) = request(FrameBuilder(Cmd.SET_DEVICE_PIN).u32(pin).build(), Resp.OK)

    suspend fun reboot() {
        link.send(FrameBuilder(Cmd.REBOOT).text("reboot").build())
    }

    suspend fun battery(): Pair<Int, Pair<Long, Long>> {
        val f = request(FrameBuilder(Cmd.GET_BATT_AND_STORAGE).build(), Resp.BATT_AND_STORAGE)
        val r = FrameReader(f, 1)
        return r.u16() to (r.u32() to r.u32())
    }
}
