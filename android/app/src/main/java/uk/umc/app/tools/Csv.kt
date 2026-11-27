package uk.umc.app.tools

/**
 * CSV for spreadsheets (RFC 4180, CRLF line ends). Text cells that a spreadsheet could read as a
 * formula (first character = + - @, tab or CR) get a leading apostrophe so they stay text.
 * Numbers are written as they are, so a negative longitude is still a number.
 */
object Csv {
    const val BOM = "﻿"      // so Excel reads the file as UTF-8

    private val FORMULA_START = setOf('=', '+', '-', '@', '\t', '\r')

    /** One cell. Null is empty; Number and Boolean are written raw; anything else is text. */
    fun cell(v: Any?): String = when (v) {
        null -> ""
        is Number, is Boolean -> v.toString()
        else -> text(v.toString())
    }

    fun text(raw: String): String {
        val safe = if (raw.isNotEmpty() && raw[0] in FORMULA_START) "'$raw" else raw
        val needsQuotes = safe.any { it == ',' || it == '"' || it == '\n' || it == '\r' } || safe.startsWith(" ") || safe.endsWith(" ")
        return if (needsQuotes) "\"" + safe.replace("\"", "\"\"") + "\"" else safe
    }

    fun row(vararg cells: Any?): String = cells.joinToString(",") { cell(it) }

    fun document(header: List<String>, rows: List<List<Any?>>): String {
        val sb = StringBuilder(BOM)
        sb.append(header.joinToString(",") { text(it) }).append("\r\n")
        for (r in rows) sb.append(r.joinToString(",") { cell(it) }).append("\r\n")
        return sb.toString()
    }
}
