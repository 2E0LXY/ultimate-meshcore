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

    /** A safe name for the copy kept in the app's own storage: no path parts, no odd characters. */
    fun localName(displayName: String): String {
        val ext = extension(displayName).takeIf { it in EXTENSIONS } ?: "zip"
        val base = displayName.substringBeforeLast('.', displayName).substringAfterLast('/').substringAfterLast('\\')
        val clean = base.map { if (it.isLetterOrDigit() || it == '-' || it == '_') it else '_' }.joinToString("").trim('_').take(MAX_NAME)
        return (clean.ifEmpty { "tiles" }) + "." + ext
    }
}
