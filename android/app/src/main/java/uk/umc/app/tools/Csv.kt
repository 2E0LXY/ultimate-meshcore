package uk.umc.app.tools

/**
 * CSV for spreadsheets (RFC 4180, CRLF line ends). Text cells that a spreadsheet could read as a
 * formula (first character = + - @, tab or CR) get a leading apostrophe so they stay text.
 * Numbers are written as they are, so a negative longitude is still a number; NaN and Infinity become blank cells.
 *
 * The apostrophe is literal: when the file is imported as CSV (or read by a script) a guarded cell keeps its
 * leading apostrophe. Excel and Sheets hide it only in some import paths. Strip it if you load the file programmatically.
 */
object Csv {
    const val BOM = "﻿"      // so Excel reads the file as UTF-8

    private val FORMULA_START = setOf('=', '+', '-', '@', '\t', '\r')

    /** One cell. Null is empty; Number and Boolean are written raw; anything else is text. */
    fun cell(v: Any?): String = when (v) {
        null -> ""
        is Double -> if (v.isFinite()) v.toString() else ""        // NaN and Infinity mean "no value"
        is Float -> if (v.isFinite()) v.toString() else ""
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
