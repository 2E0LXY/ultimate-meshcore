package uk.umc.app.tools

/**
 * Rules for a map tile pack the user supplies (a file osmdroid can read offline). The app never
 * downloads tiles in bulk: the online map uses openstreetmap.org's own servers, whose usage policy forbids it.
 */
object TilePack {
    /** Archive types osmdroid reads: zip, sqlite (osmdroid/MOBAC), mbtiles and gemf. */
    val EXTENSIONS = listOf("zip", "sqlite", "mbtiles", "gemf")
    const val MAX_BYTES = 2L * 1024 * 1024 * 1024
    const val MAX_NAME = 80

    fun extension(displayName: String): String = displayName.substringAfterLast('.', "").lowercase()

    /** An error in plain words, or null if the file may be used. [sizeBytes] is -1 when unknown. */
    fun check(displayName: String, sizeBytes: Long): String? = when {
        extension(displayName) !in EXTENSIONS -> "a tile pack ends in " + EXTENSIONS.joinToString(", ") { ".$it" }
        sizeBytes == 0L -> "that file is empty"
        sizeBytes > MAX_BYTES -> "that file is bigger than ${MAX_BYTES / (1024 * 1024 * 1024)} GB"
        else -> null
    }

    /**
     * A safe name for the copy kept in the app's own storage: no path parts, no odd characters. If cleaning
     * changed the name, a short hash of the original is added so "a b.zip" and "a_b.zip" do not overwrite each
     * other. The same display name always gives the same local name, so choosing a pack again replaces it.
     */
    fun localName(displayName: String): String {
        val ext = extension(displayName).takeIf { it in EXTENSIONS } ?: "zip"
        val base = displayName.substringBeforeLast('.', displayName).substringAfterLast('/').substringAfterLast('\\')
        val clean = base.map { if (it.isLetterOrDigit() || it == '-' || it == '_') it else '_' }.joinToString("").trim('_').take(MAX_NAME)
        val changed = clean != base
        val stem = clean.ifEmpty { "tiles" }
        return if (changed) "$stem-${hash8(displayName)}.$ext" else "$stem.$ext"
    }

    private fun hash8(s: String): String {
        val c = java.util.zip.CRC32(); c.update(s.toByteArray(Charsets.UTF_8))
        return "%08x".format(java.util.Locale.ROOT, c.value)
    }

    /** Spare space to leave on the device beyond the pack itself. */
    const val FREE_MARGIN_BYTES = 64L * 1024 * 1024
    const val HEADER_BYTES = 16

    /** An error in plain words if the declared size will not fit in [freeBytes], else null. An unknown size ([sizeBytes] < 0) only needs the margin. */
    fun spaceError(sizeBytes: Long, freeBytes: Long): String? {
        val need = (if (sizeBytes > 0) sizeBytes else 0L) + FREE_MARGIN_BYTES
        return if (freeBytes < need) "not enough free space on this phone (needs about ${(need + 1_048_575) / 1_048_576} MB, ${freeBytes / 1_048_576} MB free)" else null
    }

    /** Checks the first bytes of the file against what its extension claims. Error in plain words, or null. */
    fun headerError(displayName: String, header: ByteArray): String? {
        fun starts(vararg b: Int) = header.size >= b.size && b.indices.all { header[it] == b[it].toByte() }
        return when (extension(displayName)) {
            "zip" -> if (starts(0x50, 0x4B, 0x03, 0x04)) null else "that is not a zip file"
            "sqlite", "mbtiles" ->
                if (starts(0x53, 0x51, 0x4C, 0x69, 0x74, 0x65, 0x20, 0x66, 0x6F, 0x72, 0x6D, 0x61, 0x74, 0x20, 0x33, 0x00)) null else "that is not an SQLite database"
            "gemf" -> if (starts(0, 0, 0, 4)) null else "that is not a GEMF file"
            else -> "unknown tile pack type"
        }
    }
}
