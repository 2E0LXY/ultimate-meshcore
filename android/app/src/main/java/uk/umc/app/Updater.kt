package uk.umc.app

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.os.Build
import android.provider.Settings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit

/** In-app updater: checks the app-latest GitHub release, downloads the APK and installs it through PackageInstaller. */
object Updater {
    sealed class State {
        object Idle : State()
        data class Available(val sha: String) : State()
        data class Downloading(val percent: Int) : State()
        object Ready : State()
        data class Failed(val reason: String) : State()
    }

    val state = MutableStateFlow<State>(State.Idle)
    /** The newer build, while one is known; the button stays visible after a failure so it can be retried. */
    val latest = MutableStateFlow<UpdateLogic.Release?>(null)

    private const val CHECK_EVERY_MS = 6L * 60 * 60 * 1000
    private var started = false
    private var busy = false

    private val http by lazy {
        OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build()
    }

    /** Checks now and then every 6 hours while the app runs. */
    fun start(context: Context) {
        if (started) return
        started = true
        val app = context.applicationContext
        AppState.scope.launch {
            while (true) {
                check(app, manual = false)
                delay(CHECK_EVERY_MS)
            }
        }
    }

    suspend fun check(context: Context, manual: Boolean) {
        if (busy) return
        if (BuildConfig.GIT_SHA == "dev") {
            if (manual) AppState.say("Debug build: update checks are off")
            return
        }
        val release = try {
            withContext(Dispatchers.IO) { fetch() }
        } catch (e: Exception) {
            if (manual) AppState.say("Update check failed: ${e.message ?: "no connection"}")
            return
        }
        if (release == null) {
            if (manual) AppState.say("Update check failed: no build information in the release")
            return
        }
        if (UpdateLogic.isUpdateAvailable(BuildConfig.GIT_SHA, release.sha)) {
            latest.value = release
            if (state.value !is State.Downloading && state.value !is State.Ready) state.value = State.Available(release.sha)
        } else {
            latest.value = null
            state.value = State.Idle
            if (manual) AppState.say("Up to date (${BuildConfig.GIT_SHA})")
        }
    }

    fun checkNow(context: Context) {
        val app = context.applicationContext
        AppState.scope.launch { check(app, manual = true) }
    }

    private fun fetch(): UpdateLogic.Release? {
        val req = Request.Builder().url(UpdateLogic.RELEASE_URL)
            .header("Accept", "application/vnd.github+json")
            .header("User-Agent", "UltimateMeshCoreApp")
            .build()
        http.newCall(req).execute().use { r ->
            if (!r.isSuccessful) throw java.io.IOException("HTTP ${r.code}")
            return UpdateLogic.parseRelease(r.body?.string() ?: return null)
        }
    }

    /** Button action: ask for the install permission if needed, then download and install. */
    fun downloadAndInstall(context: Context) {
        val app = context.applicationContext
        val release = latest.value ?: return
        if (busy) return
        if (!app.packageManager.canRequestPackageInstalls()) {
            app.startActivity(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + app.packageName))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
            AppState.say("Allow installs from this app, then press Update again")
            return
        }
        busy = true
        AppState.scope.launch {
            try {
                state.value = State.Downloading(0)
                val file = withContext(Dispatchers.IO) { download(app, release) }
                state.value = State.Ready
                withContext(Dispatchers.IO) { install(app, file) }
            } catch (e: Exception) {
                fail("Update failed: ${e.message ?: e.javaClass.simpleName}")
            } finally {
                busy = false
            }
        }
    }

    private fun download(context: Context, release: UpdateLogic.Release): File {
        val dir = File(context.cacheDir, "updates").apply { mkdirs() }
        val file = File(dir, "update.apk")
        if (file.exists()) file.delete()
        val req = Request.Builder().url(release.url).header("User-Agent", "UltimateMeshCoreApp").build()
        http.newCall(req).execute().use { r ->
            if (!r.isSuccessful) throw java.io.IOException("download HTTP ${r.code}")
            val body = r.body ?: throw java.io.IOException("empty download")
            val total = if (body.contentLength() > 0) body.contentLength() else release.size
            var done = 0L
            var lastPercent = -1
            body.byteStream().use { input ->
                file.outputStream().use { out ->
                    val buf = ByteArray(32 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        out.write(buf, 0, n)
                        done += n
                        if (total > 0) {
                            val p = ((done * 100) / total).toInt().coerceIn(0, 100)
                            if (p != lastPercent) { lastPercent = p; state.value = State.Downloading(p) }
                        }
                    }
                }
            }
            if (total > 0 && done != total) throw java.io.IOException("download incomplete")
        }
        return file
    }

    private fun install(context: Context, file: File) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        params.setAppPackageName(context.packageName)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            // an update of an app this installer installed can go through without another prompt
            params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
        }
        val id = installer.createSession(params)
        val session = installer.openSession(id)
        try {
            session.openWrite("update.apk", 0, file.length()).use { out ->
                file.inputStream().use { it.copyTo(out) }
                session.fsync(out)
            }
            val intent = Intent(context, UpdateReceiver::class.java).setAction(UpdateReceiver.ACTION)
            var flags = PendingIntent.FLAG_UPDATE_CURRENT
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) flags = flags or PendingIntent.FLAG_MUTABLE
            val pending = PendingIntent.getBroadcast(context, id, intent, flags)
            session.commit(pending.intentSender)
        } catch (e: Exception) {
            session.abandon()
            throw e
        } finally {
            session.close()
        }
    }

    internal fun fail(reason: String) {
        state.value = State.Failed(reason)
        AppState.say(reason)
    }
}

/** Receives the PackageInstaller result: shows the confirmation screen when needed, reports the outcome. */
class UpdateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        val message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION")
                val confirm = if (Build.VERSION.SDK_INT >= 33) {
                    intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                } else {
                    intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                }
                if (confirm != null) {
                    confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    context.startActivity(confirm)
                } else {
                    Updater.fail("Update needs confirmation but no prompt was given")
                }
            }
            PackageInstaller.STATUS_SUCCESS -> {
                Updater.latest.value = null
                Updater.state.value = Updater.State.Idle
                AppState.say("Update installed")
            }
            else -> Updater.fail(UpdateLogic.failureMessage(status, message))
        }
    }

    companion object {
        const val ACTION = "uk.umc.app.UPDATE_STATUS"
    }
}
