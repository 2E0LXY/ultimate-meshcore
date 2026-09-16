package uk.umc.app.web

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * The web interface of an Ultimate MeshCore device on the same network: every setting and
 * command the browser page can reach, including repeaters the app isn't connected to over
 * the mesh, plus firmware updates.
 */
class UmcWeb(private val host: String) {
    var token: String? = null
        private set

    private fun open(path: String, method: String): HttpURLConnection {
        val c = URL("http://$host$path").openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = 6000
        c.readTimeout = 20000
        token?.let { c.setRequestProperty("X-Auth-Token", it) }
        return c
    }

    private fun body(c: HttpURLConnection): String {
        val stream = if (c.responseCode in 200..299) c.inputStream else c.errorStream
        return stream?.bufferedReader()?.use { it.readText() } ?: ""
    }

    suspend fun info(): JSONObject = withContext(Dispatchers.IO) {
        val c = open("/api/info", "GET")
        JSONObject(body(c))
    }

    /** Returns true when the password was accepted. */
    suspend fun login(password: String): Boolean = withContext(Dispatchers.IO) {
        val c = open("/api/login", "POST")
        c.doOutput = true
        c.outputStream.use { it.write(password.toByteArray()) }
        val text = body(c)
        if (c.responseCode !in 200..299) {
            throw Exception(runCatching { JSONObject(text).optString("error") }.getOrNull()?.ifEmpty { "sign-in failed" } ?: "sign-in failed")
        }
        token = JSONObject(text).optString("token")
        !token.isNullOrEmpty()
    }

    /** Runs commands on the device and returns one reply per command. */
    suspend fun cli(commands: List<String>): List<String> = withContext(Dispatchers.IO) {
        val out = ArrayList<String>()
        commands.chunked(12).forEach { batch ->
            val c = open("/api/cli", "POST")
            c.doOutput = true
            c.outputStream.use { it.write(batch.joinToString("\n").toByteArray()) }
            val text = body(c)
            if (c.responseCode !in 200..299) throw Exception(runCatching { JSONObject(text).optString("error") }.getOrNull() ?: "request failed")
            val arr = JSONArray(text)
            for (i in 0 until arr.length()) out.add(arr.getString(i))
        }
        out
    }

    suspend fun one(command: String): String = cli(listOf(command)).firstOrNull() ?: ""

    companion object {
        fun value(reply: String): String = reply.trim().removePrefix(">").trim()
        fun isError(reply: String): Boolean =
            Regex("^\\s*(err|error|\\?\\?|unknown|invalid|bad )", RegexOption.IGNORE_CASE).containsMatchIn(reply)
    }
}
