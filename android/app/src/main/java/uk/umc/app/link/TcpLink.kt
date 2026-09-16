package uk.umc.app.link

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket

/**
 * WiFi link: the MeshCore app connection on TCP port 5000, as served by an Ultimate MeshCore
 * client or repeater. Frames are '<' len16 payload out, '>' len16 payload in.
 */
class TcpLink(private val host: String, private val port: Int, private val scope: CoroutineScope) : Link {
    // replay: the radio can answer before the session has finished subscribing, and a
    // dropped first frame would leave the connection half-started
    override val frames = MutableSharedFlow<ByteArray>(replay = 32, extraBufferCapacity = 64)
    override val state = MutableStateFlow<LinkState>(LinkState.Idle)

    private var socket: Socket? = null
    private var out: OutputStream? = null

    override suspend fun connect() {
        state.value = LinkState.Connecting("$host:$port")
        withContext(Dispatchers.IO) {
            try {
                val s = Socket()
                s.connect(InetSocketAddress(host, port), 8000)
                s.tcpNoDelay = true
                socket = s
                out = s.getOutputStream()
                state.value = LinkState.Connected("$host:$port")
                scope.launch(Dispatchers.IO) { readLoop(s.getInputStream()) }
            } catch (e: Exception) {
                state.value = LinkState.Failed(e.message ?: "could not connect")
            }
        }
    }

    private suspend fun readLoop(input: InputStream) {
        val header = ByteArray(3)
        try {
            while (true) {
                if (!readFully(input, header, 3)) break
                if (header[0] != '>'.code.toByte()) continue
                val len = (header[1].toInt() and 0xFF) or ((header[2].toInt() and 0xFF) shl 8)
                if (len <= 0 || len > 1024) continue
                val payload = ByteArray(len)
                if (!readFully(input, payload, len)) break
                frames.emit(payload)
            }
        } catch (_: Exception) {
        }
        if (state.value is LinkState.Connected) state.value = LinkState.Failed("connection closed")
    }

    private fun readFully(input: InputStream, buf: ByteArray, len: Int): Boolean {
        var got = 0
        while (got < len) {
            val n = input.read(buf, got, len - got)
            if (n < 0) return false
            got += n
        }
        return true
    }

    override suspend fun send(frame: ByteArray): Boolean = withContext(Dispatchers.IO) {
        try {
            val o = out ?: return@withContext false
            val head = byteArrayOf('<'.code.toByte(), (frame.size and 0xFF).toByte(), ((frame.size shr 8) and 0xFF).toByte())
            o.write(head)
            o.write(frame)
            o.flush()
            true
        } catch (e: Exception) {
            state.value = LinkState.Failed(e.message ?: "send failed")
            false
        }
    }

    override fun close() {
        try { socket?.close() } catch (_: Exception) {}
        socket = null
        out = null
        state.value = LinkState.Idle
    }
}
