package uk.umc.app

import uk.umc.app.net.MiniJson

/** Pure parts of the in-app updater (no Android classes, so they run in JVM unit tests). */
object UpdateLogic {
    const val ASSET_NAME = "ultimate-meshcore-app-latest.apk"
    const val RELEASE_URL = "https://api.github.com/repos/2E0LXY/ultimate-meshcore/releases/tags/app-latest"

    /** The newest published build: its 7-character commit, the APK link and its size in bytes (0 when unknown). */
    data class Release(val sha: String, val url: String, val size: Long)

    private val BUILT_FROM = Regex("built from ([0-9a-fA-F]{7,40})")

    /** The commit named by 'built from <sha>' in the release notes, cut to 7 characters, or null. */
    fun shaFromBody(body: String?): String? =
        body?.let { BUILT_FROM.find(it)?.groupValues?.get(1)?.take(7)?.lowercase() }

    /** Reads the GitHub release JSON. Null when it is malformed, names no commit or has no APK asset. */
    fun parseRelease(json: String): Release? {
        val root = MiniJson.parseObject(json) ?: return null
        val sha = shaFromBody(root["body"] as? String) ?: return null
        val assets = root["assets"] as? List<*> ?: return null
        for (a in assets) {
            val m = a as? Map<*, *> ?: continue
            if (m["name"] != ASSET_NAME) continue
            val url = m["browser_download_url"] as? String ?: continue
            if (url.isBlank()) continue
            val size = (m["size"] as? Number)?.toLong() ?: 0L
            return Release(sha, url, size)
        }
        return null
    }

    /** An update is offered when the published commit differs from this build. Debug ("dev") builds are never nagged. */
    fun isUpdateAvailable(current: String, latest: String?): Boolean {
        if (latest.isNullOrBlank() || current.isBlank() || current == "dev") return false
        return !latest.take(7).equals(current.take(7), ignoreCase = true)
    }

    const val SIGNATURE_MESSAGE =
        "This build is signed with a different key; uninstall once, then updates will work (this loses the UMC Net login)."

    // PackageInstaller.STATUS_* values, kept numeric so this file stays pure
    private const val FAILURE_ABORTED = 3
    private const val FAILURE_CONFLICT = 5
    private const val FAILURE_INCOMPATIBLE = 7

    /** A readable reason for a failed install. */
    fun failureMessage(status: Int, message: String?): String {
        val m = message.orEmpty()
        return when {
            status == FAILURE_CONFLICT || status == FAILURE_INCOMPATIBLE ||
                m.contains("INCOMPATIBLE", true) || m.contains("signature", true) -> SIGNATURE_MESSAGE
            status == FAILURE_ABORTED -> "Install cancelled"
            m.isNotBlank() -> "Install failed: $m"
            else -> "Install failed (code $status)"
        }
    }
}
