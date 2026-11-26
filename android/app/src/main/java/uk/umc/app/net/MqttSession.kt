package uk.umc.app.net

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/**
 * One MQTT 3.1.1 connection to the UMC Net broker over WebSocket (wss://host:443/mqtt), using OkHttp and the small
 * codec in [MqttPacket]. It reconnects by itself with a growing delay (1 s up to 60 s) and subscribes again after every reconnect.
 * [onState] gets short plain-words states; [refused] is true when the broker rejected the login (no point retrying).
 */
class MqttSession(
    private val host: String, private val user: String, private val password: String, private val clientId: String,
    private val subscriptions: List<String>,
    private val onMessage: (topic: String, payload: ByteArray, retained: Boolean) -> Unit,
    private val onState: (state: String, connected: Boolean, refused: Boolean) -> Unit,
    private val onConnected: () -> Unit = {},
) {
    private val lock = Any()
    @Volatile private var closed = false
    @Volatile private var everConnected = false
    @Volatile private var failedOnce = false                 // a failure with a real reason has been shown: the watchdog must not overwrite it
    private var retryDelayS = 1L
    private var socket: WebSocket? = null          // current attempt (guarded by lock)
    private var connected = false                   // CONNACK 0 received on [socket]
    private var lastTraffic = 0L                    // uptime ms of the last inbound frame
    private var pingTask: ScheduledFuture<*>? = null
    private var retryTask: ScheduledFuture<*>? = null
    private var dog: ScheduledFuture<*>? = null
    private var attempt = 0

    private val scheduler: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor { r -> Thread(r, "umc-mqtt").also { it.isDaemon = true } }
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .pingInterval(0, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)
        .build()

    fun start() {
        onState("connecting…", false, false)
        // say so after 20 s instead of showing "connecting…" for ever, while nothing has connected yet
        dog = scheduler.scheduleWithFixedDelay({
            if (!closed && !everConnected && !failedOnce) onState("no answer from $host:443 after ${++waited * 20}s (still trying)", false, false)
        }, 20, 20, TimeUnit.SECONDS)
        synchronized(lock) { connect() }
    }
    private var waited = 0

    private fun now() = System.nanoTime() / 1_000_000

    /** Caller holds [lock]. */
    private fun connect() {
        if (closed) return
        val id = ++attempt
        val req = Request.Builder().url("https://$host/mqtt").header("Sec-WebSocket-Protocol", "mqtt").build()
        socket = http.newWebSocket(req, Listener(id))
    }

    private inner class Listener(private val id: Int) : WebSocketListener() {
        private val decoder = MqttPacket.Decoder()

        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (!current(id)) return
            synchronized(lock) { lastTraffic = now() }
            webSocket.send(MqttPacket.connect(clientId, user, password, 30).toByteString())
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            if (!current(id)) return
            synchronized(lock) { lastTraffic = now() }
            val packets = try { decoder.feed(bytes.toByteArray()) } catch (e: Exception) { lost(id, e); return }
            for (p in packets) when (p) {
                is MqttPacket.Packet.ConnAck -> {
                    if (p.returnCode != 0) {
                        synchronized(lock) { if (!current(id)) return; closed = true }
                        onState("the broker refused this login (code ${p.returnCode})", false, true)
                        shutdown(); return
                    }
                    synchronized(lock) {
                        if (!current(id)) return
                        connected = true; retryDelayS = 1; everConnected = true
                        webSocket.send(MqttPacket.subscribe(1, subscriptions).toByteString())
                        pingTask?.cancel(false)
                        pingTask = scheduler.scheduleWithFixedDelay({ keepAlive(id) }, 20, 20, TimeUnit.SECONDS)
                    }
                    onState("connected", true, false)
                    onConnected()
                }
                is MqttPacket.Packet.Publish -> {
                    if (p.qos == 1) webSocket.send(MqttPacket.puback(p.packetId).toByteString())
                    if (p.qos <= 1) onMessage(p.topic, p.payload, p.retain)
                }
                else -> {}
            }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
            lost(id, java.io.IOException("closed by broker ($code${if (reason.isEmpty()) "" else " $reason"})"))
        }
        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { lost(id, java.io.IOException("closed ($code)")) }
        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { lost(id, t) }
    }

    private fun current(id: Int) = synchronized(lock) { !closed && id == attempt }

    private fun keepAlive(id: Int) {
        val dead: Boolean
        synchronized(lock) {
            if (closed || id != attempt || !connected) return
            val ws = socket ?: return
            dead = now() - lastTraffic > 60_000
            if (!dead) ws.send(MqttPacket.pingReq().toByteString())
        }
        if (dead) lost(id, java.io.IOException("no traffic for 60 s"))
    }

    /** The attempt [id] has failed or ended: tear it down and schedule a retry. */
    private fun lost(id: Int, t: Throwable) {
        val wait: Long
        val old: WebSocket?
        synchronized(lock) {
            if (closed || id != attempt) return
            attempt++                       // invalidates the old listener
            old = socket; socket = null; connected = false
            pingTask?.cancel(false); pingTask = null
            wait = retryDelayS; retryDelayS = minOf(60, retryDelayS * 2)
            retryTask = try { scheduler.schedule({ synchronized(lock) { connect() } }, wait, TimeUnit.SECONDS) } catch (e: Exception) { null }
        }
        runCatching { old?.cancel() }
        failedOnce = true
        val why = if (t is java.net.UnknownHostException) "no internet on this network (airplane mode, or a Wi-Fi without internet)"
                  else "${t.javaClass.simpleName} ${t.message ?: ""}".trim()
        onState("cannot reach $host: $why (retrying in ${wait}s)", false, false)
    }

    /** A network has just come up: try now instead of waiting out the retry delay. */
    fun retryNow() {
        synchronized(lock) {
            if (closed || connected || socket != null) return
            retryTask?.cancel(false); retryDelayS = 1
            connect()
        }
    }

    /** QoS 0. Reports a failure (not connected, for one) through [onFail]. */
    fun publish(topic: String, payload: ByteArray, onFail: (String) -> Unit = {}) {
        val ws = synchronized(lock) { if (connected && !closed) socket else null }
        if (ws == null) { onFail("not connected"); return }
        val ok = try { ws.send(MqttPacket.publish(topic, payload).toByteString()) } catch (e: Exception) { false }
        if (!ok) onFail("publish failed")
    }

    fun close() {
        val ws: WebSocket?
        synchronized(lock) { closed = true; ws = socket; socket = null; connected = false; attempt++ }
        runCatching { ws?.send(MqttPacket.disconnect().toByteString()) }
        runCatching { ws?.close(1000, null) }
        shutdown()
    }

    private fun shutdown() {
        synchronized(lock) { val ws = socket; if (closed && ws != null) { socket = null; runCatching { ws.close(1000, null) } } }
        runCatching { scheduler.shutdownNow() }
        runCatching { http.dispatcher.executorService.shutdown() }
        runCatching { http.connectionPool.evictAll() }
    }
}
