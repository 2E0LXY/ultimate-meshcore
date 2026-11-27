package uk.umc.app.tools

import android.content.Context
import android.net.Uri

/** Reads and writes the file the user picked through the system file picker (no storage permission needed). */
object Saf {
    fun write(context: Context, uri: Uri, text: String): Result<Unit> = runCatching {
        val out = context.contentResolver.openOutputStream(uri, "wt") ?: throw java.io.IOException("could not open the file")
        out.use { it.write(text.toByteArray(Charsets.UTF_8)) }
    }

    /** At most [maxBytes] of text; a bigger file is an error rather than a memory problem. */
    fun read(context: Context, uri: Uri, maxBytes: Int): Result<String> = runCatching {
        val input = context.contentResolver.openInputStream(uri) ?: throw java.io.IOException("could not open the file")
        input.use {
            val buf = java.io.ByteArrayOutputStream()
            val chunk = ByteArray(8192)
            while (true) {
                val n = it.read(chunk)
                if (n < 0) break
                buf.write(chunk, 0, n)
                if (buf.size() > maxBytes) throw java.io.IOException("that file is too big to be a backup")
            }
            String(buf.toByteArray(), Charsets.UTF_8)
        }
    }
}
