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

/** [code] is the radio's own error number when it refused a command, otherwise 0. */
class MeshError(message: String, val code: Int = 0) : Exception(message)

/** A message as the app shows it. */
/**
 * A packet the radio heard, as it came off the air.
 *
 * The radio pushes one of these for every packet it receives, whether or not it was meant
 * for us, which is what makes a picture of the channel possible.
 */
data class HeardPacket(
    val at: Long,                    // when we were told, device clock
    val snr: Double,
    val rssi: Int,
    val kind: String,                // ADV, MSG, ACK, TRC, PTH, GRP, REQ, RSP or RAW
    val size: Int,
    val flood: Boolean,
    val info: PacketInfo? = null,    // who it came from and by which repeater, as far as the packet says
)

/** The radio's own view of its channel: noise, airtime and what it has sent and heard. */
data class RadioStats(
    val noiseFloor: Int,
    val lastRssi: Int,
    val lastSnr: Double,
    val txAirSecs: Long,
    val rxAirSecs: Long,
    val upSecs: Long,
    val sentFlood: Long,
    val sentDirect: Long,
    val recvFlood: Long,
    val recvDirect: Long,
    val recvErrors: Long,
    val queueLen: Int = -1,          // packets waiting to be sent; -1 when the radio does not say
    val errFlags: Int = 0,
)

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
    val status: String = "",         // sending / sent / delivered / failed
    val ackCode: String? = null,
    val roundTripMs: Long? = null,
    val error: String? = null,
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

    /** The last few minutes of packets the radio heard, newest last. */
    val heard = MutableStateFlow<List<HeardPacket>>(emptyList())
    val radioStats = MutableStateFlow<RadioStats?>(null)
    val pendingAdverts = MutableStateFlow<List<Contact>>(emptyList())
    val events = MutableSharedFlow<String>(extraBufferCapacity = 32)
    val newMessages = MutableSharedFlow<ChatMessage>(extraBufferCapacity = 32)

    /** Region scope per channel name (like "Set Region Scope" in the MeshCore apps). */
    var scopeFor: (String) -> String? = { null }

    private val lock = Mutex()
    private val awaitingAck = HashMap<String, Long>()   // delivery code -> message id
    private var nextId = 1L

    /** Someone waiting for a particular frame to arrive. */
    private class Waiter(val match: (ByteArray) -> Boolean, val cont: CancellableContinuation<ByteArray>)

    private val waiters = CopyOnWriteArrayList<Waiter>()

    /**
     * Frames that arrived with nobody waiting for them. A radio answers a contact list as a
     * burst, so the next frames are often already here before we ask for them.
     */
    private val spare = java.util.ArrayDeque<ByteArray>()

    private fun deliver(f: ByteArray) {
        for (w in waiters) {
            if (w.match(f)) {
                waiters.remove(w)
                if (w.cont.isActive) {
                    w.cont.resumeWith(Result.success(f))
                    return
                }
            }
        }
        if ((f[0].toInt() and 0xFF) < 0x80) {   // keep replies, not pushes (already handled)
            synchronized(spare) {
                spare.addLast(f)
                while (spare.size > 64) spare.removeFirst()
            }
        }
    }

    /** Suspends until a frame matching [match] arrives, or the timeout passes. */
    private suspend fun awaitFrame(timeoutMs: Long, match: (ByteArray) -> Boolean): ByteArray? {
        synchronized(spare) {
            val it = spare.iterator()
            while (it.hasNext()) {
                val f = it.next()
                if (match(f)) {
                    it.remove()
                    return f
                }
            }
        }
        return withTimeoutOrNull(timeoutMs) {
            suspendCancellableCoroutine { cont ->
                val w = Waiter(match, cont)
                waiters.add(w)
                cont.invokeOnCancellation { waiters.remove(w) }
            }
        }
    }

    /** Anything left from an earlier exchange is stale once a new command goes out. */
    private fun clearSpare() = synchronized(spare) { spare.clear() }

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
                    runCatching { handshake() }.onFailure {
                        android.util.Log.w("UMC", "handshake failed", it)
                        events.emit("Connect failed: ${it.message}")
                    }
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
            clearSpare()
            val pending = scope.async {
                awaitFrame(timeoutMs) { f ->
                    val code = f[0].toInt() and 0xFF
                    code == Resp.ERR || expect.contains(code)
                }
            }
            if (!link.send(frame)) {
                pending.cancel()
                throw MeshError("could not send to the radio (" + link.diagnostics().ifEmpty { "no link detail" } + ")")
            }
            val r = pending.await() ?: throw MeshError("no reply from the radio")
            if ((r[0].toInt() and 0xFF) == Resp.ERR) {
                val code = if (r.size > 1) r[1].toInt() and 0xFF else 0
                throw MeshError(ErrCode.text(code), code)
            }
            r
        }

    /**
     * For commands that are safe to repeat (an advert, setting a channel, a name): when the radio says it
     * has no space or is busy, it is usually only for a moment, so wait and ask again before giving up.
     */
    private suspend fun requestAgain(frame: ByteArray, vararg expect: Int, tries: Int = 4): ByteArray {
        var wait = 1000L
        var last: MeshError? = null
        for (i in 0 until tries) {
            try {
                return request(frame, *expect)
            } catch (e: MeshError) {
                last = e
                if (!ErrCode.isTransient(e.code) || i == tries - 1) throw e
                kotlinx.coroutines.delay(wait)
                wait = wait * 2
            }
        }
        throw last ?: MeshError("failed")
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
        android.util.Log.i("UMC", "handshake: device query")
        device.value = Decode.deviceInfo(request(FrameBuilder(Cmd.DEVICE_QUERY).u8(3).build(), Resp.DEVICE_INFO))
        android.util.Log.i("UMC", "handshake: app start")
        val s = request(FrameBuilder(Cmd.APP_START).u8(1).bytes(ByteArray(6)).text("UMC App").build(), Resp.SELF_INFO)
        self.value = Decode.selfInfo(s)
        android.util.Log.i("UMC", "handshake: self=${self.value?.name}")
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
            clearSpare()
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
                awaitingAck.remove(ack)?.let { id ->
                    update(id) { it.copy(status = "delivered", roundTripMs = trip) }
                }
            }
            Push.NEW_ADVERT -> {
                val c = Decode.contact(f)
                if (contacts.value.none { it.publicKey == c.publicKey }) {
                    pendingAdverts.value = (pendingAdverts.value + c).distinctBy { it.publicKey }
                }
                scope.launch { refreshContacts() }
            }
            Push.LOG_RX_DATA -> noteHeard(f)
            Push.PATH_UPDATED, Push.CONTACT_DELETED -> scope.launch { refreshContacts() }
            Push.CONTACTS_FULL -> scope.launch { events.emit("The radio's contact list is full") }
        }
    }

/**
     * A packet the radio heard. The first byte of the raw packet carries its routing and
     * payload type, which is enough to say what kind of traffic it was.
     */
    private fun noteHeard(f: ByteArray) {
        if (f.size < 4) return
        val snr = (f[1].toInt()) / 4.0
        val rssi = f[2].toInt()
        val header = f[3].toInt() and 0xFF
        val route = header and 0x03                  // 0 and 1 flood, 2 and 3 direct
        val payload = (header shr 2) and 0x0F
        // these are the firmware's own payload types, in its order
        val kind = when (payload) {
            0 -> "REQ"
            1 -> "RSP"
            2 -> "MSG"
            3 -> "ACK"
            4 -> "ADV"
            5 -> "GRP"
            6 -> "GDAT"
            7 -> "ANON"
            8 -> "PATH"
            9 -> "TRACE"
            10 -> "PART"
            11 -> "CTRL"
            else -> "RAW"
        }
        val p = HeardPacket(System.currentTimeMillis(), snr, rssi, kind, f.size - 3, route == 1 || route == 0, PacketInfo.parse(f.copyOfRange(3, f.size)))
        // an hour of traffic is plenty to draw, and keeps the list from growing without end
        heard.value = (heard.value + p).takeLast(600)
    }

    /** Asks the radio for its own radio and packet counters. */
    suspend fun refreshRadioStats() {
        val radio = request(byteArrayOf(Cmd.GET_STATS.toByte(), 1), Resp.STATS, timeoutMs = 6000)
        val packets = request(byteArrayOf(Cmd.GET_STATS.toByte(), 2), Resp.STATS, timeoutMs = 6000)
        val core = request(byteArrayOf(Cmd.GET_STATS.toByte(), 0), Resp.STATS, timeoutMs = 6000)
        if (radio.size < 14 || packets.size < 30 || core.size < 9) return
        val hasQueue = core.size >= 11            // type, battery 2, uptime 4, error flags 2, queue length 1 after the code
        val r = FrameReader(radio, 2)
        val noise = r.i16()
        val lastRssi = r.i8()
        val lastSnr = r.i8() / 4.0
        val txAir = r.u32()
        val rxAir = r.u32()
        val c = FrameReader(core, 2)
        c.u16()                                       // battery, already shown elsewhere
        val up = c.u32()
        val errFlags = if (core.size >= 10) c.u16() else 0
        val queueLen = if (hasQueue) c.u8() else -1
        val p = FrameReader(packets, 2)
        p.u32(); p.u32()                              // totals, we want the breakdown
        radioStats.value = RadioStats(
            noiseFloor = noise, lastRssi = lastRssi, lastSnr = lastSnr,
            txAirSecs = txAir, rxAirSecs = rxAir, upSecs = up,
            sentFlood = p.u32(), sentDirect = p.u32(), recvFlood = p.u32(), recvDirect = p.u32(),
            recvErrors = p.u32(), queueLen = queueLen, errFlags = errFlags,
        )
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

    /** Messages are immutable, so a change means a new object: that is what tells the UI to redraw. */
    private fun update(id: Long, transform: (ChatMessage) -> ChatMessage) {
        messages.value = messages.value.map { if (it.id == id) transform(it) else it }
    }

    private fun current(id: Long): ChatMessage? = messages.value.firstOrNull { it.id == id }

    // ---------------------------------------------------------------- actions

    suspend fun sendText(conversation: String, text: String, retry: ChatMessage? = null) {
        val ts = retry?.timestamp ?: (System.currentTimeMillis() / 1000)
        val id = retry?.id ?: nextId++
        if (retry == null) {
            add(ChatMessage(id, conversation, true, text, if (conversation.startsWith("ch:")) self.value?.name ?: "" else "", ts, status = "sending"))
        } else {
            update(id) { it.copy(status = "sending", error = null) }
        }
        if (conversation.startsWith("ch:")) {
            val idx = conversation.removePrefix("ch:").toInt()
            val scope = channels.value.firstOrNull { it.idx == idx }?.let { scopeFor(it.name) }.orEmpty()
            try {
                if (scope.isNotEmpty()) {
                    request(FrameBuilder(Cmd.SET_FLOOD_SCOPE_KEY).u8(0).bytes(hashtagKey(scope)).build(), Resp.OK)
                }
                request(FrameBuilder(Cmd.SEND_CHANNEL_TXT_MSG).u8(TXT_TYPE_PLAIN).u8(idx).u32(ts).text(text).build(), Resp.OK)
                update(id) { it.copy(status = "sent") }
            } catch (e: Exception) {
                update(id) { it.copy(status = "failed", error = e.message) }
            }
            if (scope.isNotEmpty()) {
                runCatching { request(FrameBuilder(Cmd.SET_FLOOD_SCOPE_KEY).u8(0).build(), Resp.OK) }   // back to the device default
            }
            return
        }
        val prefix = conversation.removePrefix("c:")
        try {
            val f = request(
                FrameBuilder(Cmd.SEND_TXT_MSG).u8(TXT_TYPE_PLAIN).u8(0).u32(ts).bytes(prefix.hexToBytes()).text(text).build(),
                Resp.SENT,
            )
            val r = FrameReader(f, 1)
            r.u8()
            val ack = r.bytes(4).toHex()
            val est = r.u32()
            update(id) { it.copy(status = "sent", ackCode = ack) }
            awaitingAck[ack] = id
            scope.launch {
                kotlinx.coroutines.delay(maxOf(est * 2, 8000L))
                if (awaitingAck.remove(ack) != null && current(id)?.status == "sent") {
                    update(id) { it.copy(status = "failed", error = "no delivery confirmation") }
                }
            }
        } catch (e: Exception) {
            update(id) { it.copy(status = "failed", error = e.message) }
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

    /** Fixes the route direct messages take to [contact]; an empty list floods and learns a new one. */
    suspend fun setRoute(contact: Contact, hops: List<String>) {
        if (hops.isEmpty()) {
            resetPath(contact)
            return
        }
        val size = hops[0].length / 2
        if (size !in 1..3 || hops.any { it.length != size * 2 }) throw MeshError("hop ids must all be 2, 4 or 6 hex characters")
        if (hops.size * size > 64) throw MeshError("route too long")
        val raw = contact.raw.copyOf()
        raw[34] = ((hops.size and 63) or ((size - 1) shl 6)).toByte()
        java.util.Arrays.fill(raw, 35, 35 + 64, 0)
        val path = hops.joinToString("").hexToBytes()
        System.arraycopy(path, 0, raw, 35, path.size)
        request(FrameBuilder(Cmd.ADD_UPDATE_CONTACT).bytes(raw.copyOfRange(0, 147)).build(), Resp.OK)
        refreshContacts()
    }

    fun routeHops(contact: Contact): List<String> =
        if (contact.hops <= 0) emptyList()
        else (0 until contact.hops).map { contact.path.copyOfRange(it * contact.hashSize, (it + 1) * contact.hashSize).toHex() }

    /** Repeater name for a hop id, from the contacts we know. */
    fun hopName(id: String): String =
        contacts.value.filter { it.publicKey.startsWith(id.lowercase()) && it.type != ADV_TYPE_CHAT }.joinToString(" / ") { it.name }

    suspend fun advert(flood: Boolean) {
        try {
            requestAgain(if (flood) FrameBuilder(Cmd.SEND_SELF_ADVERT).u8(1).build() else FrameBuilder(Cmd.SEND_SELF_ADVERT).build(), Resp.OK)
        } catch (e: MeshError) {
            if (e.code != 3) throw e
            // "no free packet space" for an advert means the radio is holding on to packets it cannot get out
            runCatching { refreshRadioStats() }
            val q = radioStats.value?.queueLen?.takeIf { it >= 0 }
            throw MeshError("the radio has no free packet space (error 3)" + (q?.let { ": $it packet(s) are waiting to be sent" } ?: "") +
                ". It cannot get its packets out. Look at the Dashboard's noise floor and channel-busy dials, and restart the radio if it stays like this.", 3)
        }
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
        requestAgain(FrameBuilder(Cmd.SET_CHANNEL).u8(idx).fixed(name, 32).bytes(secret).build(), Resp.OK)
        runCatching { refreshChannels() }                        // the channel is set; a hiccup reading the list back must not undo that
    }

    suspend fun setName(name: String) {
        requestAgain(FrameBuilder(Cmd.SET_ADVERT_NAME).text(name).build(), Resp.OK)
        self.value = self.value?.copy(name = name)
    }

    suspend fun setLocation(lat: Double, lon: Double) {
        requestAgain(FrameBuilder(Cmd.SET_ADVERT_LATLON).i32((lat * 1e6).toInt()).i32((lon * 1e6).toInt()).build(), Resp.OK)
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
