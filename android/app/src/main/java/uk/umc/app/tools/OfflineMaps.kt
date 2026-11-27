package uk.umc.app.tools

import android.content.Context
import android.net.Uri
import android.os.StatFs
import android.provider.OpenableColumns
import kotlinx.coroutines.flow.MutableStateFlow
import org.osmdroid.tileprovider.MapTileProviderBasic
import org.osmdroid.tileprovider.modules.OfflineTileProvider
import org.osmdroid.tileprovider.tilesource.FileBasedTileSource
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.tileprovider.util.SimpleRegisterReceiver
import org.osmdroid.views.MapView
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * A tile pack the user chose (zip, sqlite, mbtiles or gemf), copied into the app's own storage and
 * drawn by osmdroid's offline provider. Nothing is downloaded: the online map's tiles come from
 * openstreetmap.org, whose usage policy rules out bulk downloads.
 */
object OfflineMaps {
    /** File name of the pack in use, or null for the online map. */
    val pack = MutableStateFlow<String?>(null)

    /** Bytes copied so far and the declared total (-1 if unknown); null when no import is running. */
    data class Progress(val copied: Long, val total: Long)
    val importing = MutableStateFlow<Progress?>(null)

    /** Bumped whenever the pack's content changes (including a same-name replacement), so the map reloads. */
    val version = MutableStateFlow(0L)

    private val running = AtomicBoolean(false)

    private fun prefs(c: Context) = c.getSharedPreferences("umc", Context.MODE_PRIVATE)
    private fun dir(c: Context) = File(c.filesDir, "maps")

    fun init(context: Context) {
        // an import that was cut short (app killed) leaves a .part file behind
        dir(context).listFiles { f -> f.name.endsWith(".part") }?.forEach { it.delete() }
        val name = prefs(context).getString("tilePack", null)
        pack.value = name?.takeIf { File(dir(context), it).isFile }
    }

    fun file(context: Context): File? = pack.value?.let { File(dir(context), it) }?.takeIf { it.isFile }

    /**
     * Copies the picked file in and starts using it. Blocking: call from a background thread. An error in plain
     * words, or null. Only one import runs at a time. The new file is moved into place before the old one is
     * deleted, so a failure leaves whatever worked before untouched.
     */
    fun importPack(context: Context, uri: Uri): String? {
        if (!running.compareAndSet(false, true)) return "another tile pack is still being copied"
        importing.value = Progress(0, -1)
        var part: File? = null
        try {
            var name = "tiles.zip"; var size = -1L
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    c.getString(0)?.let { name = it }
                    if (!c.isNull(1)) size = c.getLong(1)
                }
            }
            TilePack.check(name, size)?.let { return it }
            val d = dir(context).apply { mkdirs() }
            runCatching { StatFs(d.path).availableBytes }.getOrNull()?.let { free -> TilePack.spaceError(size, free)?.let { return it } }
            importing.value = Progress(0, size)
            val local = TilePack.localName(name)
            val p = File(d, "$local.part").also { part = it }
            var copied = 0L
            val raw = context.contentResolver.openInputStream(uri) ?: return "could not open the file"
            raw.buffered(128 * 1024).use { i ->
                i.mark(TilePack.HEADER_BYTES)
                val head = ByteArray(TilePack.HEADER_BYTES)
                var got = 0
                while (got < head.size) { val n = i.read(head, got, head.size - got); if (n < 0) break; got += n }
                TilePack.headerError(name, head.copyOf(got))?.let { return it }
                i.reset()
                p.outputStream().use { o ->
                    val buf = ByteArray(64 * 1024)
                    var lastReport = 0L
                    while (true) {
                        val n = i.read(buf)
                        if (n < 0) break
                        copied += n
                        if (copied > TilePack.MAX_BYTES) return "that file is bigger than the ${TilePack.MAX_BYTES / (1024 * 1024 * 1024)} GB limit"
                        o.write(buf, 0, n)
                        if (copied - lastReport >= 1_048_576) { lastReport = copied; importing.value = Progress(copied, size) }
                    }
                }
            }
            if (copied == 0L) return "that file is empty"
            val target = File(d, local)
            // new file first (rename replaces a same-named pack atomically), old file only afterwards
            if (!moveInto(p, target)) return "could not save the tile pack"
            val old = pack.value
            prefs(context).edit().putString("tilePack", local).apply()
            pack.value = local
            version.value = version.value + 1
            if (old != null && old != local) File(d, old).delete()
            return null
        } catch (e: Throwable) {
            return e.message?.takeIf { it.isNotBlank() } ?: "could not copy the tile pack"
        } finally {
            part?.let { if (it.exists()) it.delete() }
            importing.value = null
            running.set(false)
        }
    }

    private fun moveInto(from: File, to: File): Boolean = try {
        java.nio.file.Files.move(from.toPath(), to.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING)
        true
    } catch (e: Exception) { from.renameTo(to) }

    /** Back to the online map. Refused (false) while an import is running, so the two cannot fight over the files. */
    fun remove(context: Context): Boolean {
        if (running.get()) return false
        pack.value?.let { File(dir(context), it).delete() }
        prefs(context).edit().remove("tilePack").apply()
        pack.value = null
        version.value = version.value + 1
        return true
    }

    /** Points [map] at the pack. False (map left online) if osmdroid cannot read it, including when it finds no usable archive in it. */
    fun useOn(map: MapView, file: File): Boolean = try {
        val provider = OfflineTileProvider(SimpleRegisterReceiver(map.context), arrayOf(file))
        if (provider.archives.isNullOrEmpty()) {
            provider.detach()
            throw java.io.IOException("no readable tiles in the pack")
        }
        map.setTileProvider(provider)
        val source = provider.archives.firstOrNull()?.tileSources?.firstOrNull()
        map.setTileSource(if (source != null) FileBasedTileSource.getSource(source) else TileSourceFactory.MAPNIK)
        map.setUseDataConnection(false)
        true
    } catch (e: Throwable) {
        map.setTileProvider(MapTileProviderBasic(map.context))
        map.setTileSource(TileSourceFactory.MAPNIK)
        map.setUseDataConnection(true)
        false
    }
}
