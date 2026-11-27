package uk.umc.app.tools

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.flow.MutableStateFlow
import org.osmdroid.tileprovider.MapTileProviderBasic
import org.osmdroid.tileprovider.modules.OfflineTileProvider
import org.osmdroid.tileprovider.tilesource.FileBasedTileSource
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.tileprovider.util.SimpleRegisterReceiver
import org.osmdroid.views.MapView
import java.io.File

/**
 * A tile pack the user chose (zip, sqlite, mbtiles or gemf), copied into the app's own storage and
 * drawn by osmdroid's offline provider. Nothing is downloaded: the online map's tiles come from
 * openstreetmap.org, whose usage policy rules out bulk downloads.
 */
object OfflineMaps {
    /** File name of the pack in use, or null for the online map. */
    val pack = MutableStateFlow<String?>(null)

    private fun prefs(c: Context) = c.getSharedPreferences("umc", Context.MODE_PRIVATE)
    private fun dir(c: Context) = File(c.filesDir, "maps")

    fun init(context: Context) {
        val name = prefs(context).getString("tilePack", null)
        pack.value = name?.takeIf { File(dir(context), it).isFile }
    }

    fun file(context: Context): File? = pack.value?.let { File(dir(context), it) }?.takeIf { it.isFile }

    /** Copies the picked file in and starts using it. Blocking: call from a background thread. An error in plain words, or null. */
    fun importPack(context: Context, uri: Uri): String? {
        var name = "tiles.zip"; var size = -1L
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                c.getString(0)?.let { name = it }
                if (!c.isNull(1)) size = c.getLong(1)
            }
        }
        TilePack.check(name, size)?.let { return it }
        val d = dir(context).apply { mkdirs() }
        val local = TilePack.localName(name)
        val part = File(d, "$local.part")
        return try {
            var copied = 0L
            val input = context.contentResolver.openInputStream(uri) ?: return "could not open the file"
            input.use { i ->
                part.outputStream().use { o ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = i.read(buf)
                        if (n < 0) break
                        copied += n
                        if (copied > TilePack.MAX_BYTES) throw java.io.IOException("that file is bigger than the ${TilePack.MAX_BYTES / (1024 * 1024 * 1024)} GB limit")
                        o.write(buf, 0, n)
                    }
                }
            }
            if (copied == 0L) throw java.io.IOException("that file is empty")
            val target = File(d, local)
            pack.value?.takeIf { it != local }?.let { File(d, it).delete() }
            target.delete()
            if (!part.renameTo(target)) throw java.io.IOException("could not save the tile pack")
            prefs(context).edit().putString("tilePack", local).apply()
            pack.value = local
            null
        } catch (e: Exception) {
            part.delete()
            e.message ?: "could not copy the tile pack"
        }
    }

    fun remove(context: Context) {
        pack.value?.let { File(dir(context), it).delete() }
        prefs(context).edit().remove("tilePack").apply()
        pack.value = null
    }

    /** Points [map] at the pack. False (map left online) if osmdroid cannot read it. */
    fun useOn(map: MapView, file: File): Boolean = try {
        val provider = OfflineTileProvider(SimpleRegisterReceiver(map.context), arrayOf(file))
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
