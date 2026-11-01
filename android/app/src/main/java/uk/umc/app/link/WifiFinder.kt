package uk.umc.app.link

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.URL

/** An Ultimate MeshCore radio that answered on this WiFi network. */
data class FoundRadio(val ip: String, val name: String, val role: String, val firmware: String, val board: String)

/**
 * Finds Ultimate MeshCore radios on the WiFi network the phone is on: it asks every address in
 * the phone's own subnet for the radio's `/api/info` page (which every UMC client and repeater
 * serves without a login) and keeps the ones that say they are UMC. Nothing leaves the local network.
 */
object WifiFinder {
    /** The phone's own IPv4 address and prefix length on WiFi (or Ethernet), or null when it has none. */
    fun localNetwork(context: Context): Pair<Inet4Address, Int>? {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return null
        val net = cm.activeNetwork ?: return null
        val caps = cm.getNetworkCapabilities(net) ?: return null
        if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) && !caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) return null
        val link = cm.getLinkProperties(net) ?: return null
        val a = link.linkAddresses.firstOrNull { it.address is Inet4Address && !it.address.isLoopbackAddress } ?: return null
        return Pair(a.address as Inet4Address, a.prefixLength)
    }

    /** Every host address in the subnet, nearest first, at most 1022 of them (a /22). */
    fun hostsOf(ip: Inet4Address, prefix: Int): List<String> {
        val p = prefix.coerceIn(22, 30)
        val b = ip.address
        val me = ((b[0].toInt() and 255) shl 24) or ((b[1].toInt() and 255) shl 16) or ((b[2].toInt() and 255) shl 8) or (b[3].toInt() and 255)
        val mask = (-1) shl (32 - p)
        val base = me and mask
        val count = (1 shl (32 - p)) - 2
        return (1..count).map { base + it }.filter { it != me }
            .sortedBy { Math.abs((it.toLong() and 0xffffffffL) - (me.toLong() and 0xffffffffL)) }
            .map { "${(it ushr 24) and 255}.${(it ushr 16) and 255}.${(it ushr 8) and 255}.${it and 255}" }
    }

    /** Asks one address; returns the radio when it is a UMC one. */
    fun probe(ip: String, timeoutMs: Int = 700): FoundRadio? = try {
        val c = URL("http://$ip/api/info").openConnection() as HttpURLConnection
        c.connectTimeout = timeoutMs; c.readTimeout = timeoutMs * 2; c.instanceFollowRedirects = false
        try {
            if (c.responseCode != 200) null else {
                val j = JSONObject(c.inputStream.bufferedReader().use { it.readText() })
                if (!j.has("umc")) null
                else FoundRadio(ip, j.optString("name", ip), j.optString("role", ""), j.optString("umc", j.optString("fw", "")), j.optString("board", ""))
            }
        } finally { c.disconnect() }
    } catch (e: Exception) { null }

    /** Searches the subnet, reporting progress and each radio as it answers. */
    suspend fun search(context: Context, onProgress: (done: Int, total: Int) -> Unit, onFound: (FoundRadio) -> Unit): Int = withContext(Dispatchers.IO) {
        val net = localNetwork(context) ?: return@withContext -1
        val hosts = hostsOf(net.first, net.second)
        val gate = Semaphore(48)
        var done = 0
        coroutineScope {
            hosts.map { ip ->
                async {
                    gate.withPermit {
                        probe(ip)?.let { r -> withContext(Dispatchers.Main) { onFound(r) } }
                        val d = synchronized(this@WifiFinder) { ++done }
                        if (d % 16 == 0 || d == hosts.size) withContext(Dispatchers.Main) { onProgress(d, hosts.size) }
                    }
                }
            }.awaitAll()
        }
        hosts.size
    }
}
