package uk.umc.app.link

import kotlinx.coroutines.flow.Flow

/** How the app is joined to a radio. */
enum class LinkKind { BLUETOOTH, WIFI }

data class LinkTarget(
    val kind: LinkKind,
    val address: String,          // BLE MAC, or host[:port] for WiFi
    val label: String = address,
) {
    fun describe(): String = when (kind) {
        LinkKind.BLUETOOTH -> "Bluetooth · $label"
        LinkKind.WIFI -> "WiFi · $label"
    }
    fun key(): String = "${kind.name}:$address"
}

sealed class LinkState {
    object Idle : LinkState()
    data class Connecting(val what: String) : LinkState()
    data class Connected(val what: String) : LinkState()
    data class Failed(val reason: String) : LinkState()
}

/**
 * A byte-frame link to a radio. Every transport delivers whole protocol frames, so the
 * session above it never deals with Bluetooth packets or TCP framing.
 */
interface Link {
    val frames: Flow<ByteArray>
    val state: Flow<LinkState>
    suspend fun connect()
    suspend fun send(frame: ByteArray): Boolean
    fun close()
}
