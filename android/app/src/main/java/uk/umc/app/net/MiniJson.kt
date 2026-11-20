package uk.umc.app.net

/** A small JSON reader and writer so the protocol code stays pure Kotlin (org.json is not available in JVM unit tests).
 *  Objects become Map<String, Any?>, arrays List<Any?>, integers Long, other numbers Double. */
object MiniJson {
    fun parse(text: String): Any? {
        val p = Parser(text); val v = p.value(); p.ws()
        if (p.i != text.length) throw IllegalArgumentException("trailing data")
        return v
    }

    @Suppress("UNCHECKED_CAST")
    fun parseObject(text: String): Map<String, Any?>? = try { parse(text) as? Map<String, Any?> } catch (e: Exception) { null }

    fun quote(s: String): String {
        val sb = StringBuilder("\"")
        for (c in s) when {
            c == '"' -> sb.append("\\\""); c == '\\' -> sb.append("\\\\")
            c == '\n' -> sb.append("\\n"); c == '\r' -> sb.append("\\r"); c == '\t' -> sb.append("\\t")
            c.code < 32 -> sb.append("\\u%04x".format(c.code))
            else -> sb.append(c)
        }
        return sb.append('"').toString()
    }

    /** Compact object of string keys to String / Number / Boolean / null values, in the order given. */
    fun obj(vararg pairs: Pair<String, Any?>): String = pairs.joinToString(",", "{", "}") { (k, v) ->
        quote(k) + ":" + when (v) { null -> "null"; is String -> quote(v); is Number, is Boolean -> v.toString(); else -> quote(v.toString()) }
    }

    private class Parser(val s: String) {
        var i = 0
        fun ws() { while (i < s.length && s[i].isWhitespace()) i++ }
        fun value(): Any? {
            ws(); if (i >= s.length) throw IllegalArgumentException("unexpected end")
            return when (val c = s[i]) {
                '{' -> { i++; val m = LinkedHashMap<String, Any?>(); ws()
                    if (s[i] == '}') { i++; return m }
                    while (true) { ws(); val k = str(); ws(); expect(':'); m[k] = value(); ws()
                        if (s[i] == ',') { i++; continue }; expect('}'); return m } ; @Suppress("UNREACHABLE_CODE") m }
                '[' -> { i++; val l = ArrayList<Any?>(); ws()
                    if (s[i] == ']') { i++; return l }
                    while (true) { l.add(value()); ws(); if (s[i] == ',') { i++; continue }; expect(']'); return l }; @Suppress("UNREACHABLE_CODE") l }
                '"' -> str()
                't' -> lit("true", true); 'f' -> lit("false", false); 'n' -> lit("null", null)
                else -> if (c == '-' || c.isDigit()) num() else throw IllegalArgumentException("bad character at $i")
            }
        }
        fun expect(c: Char) { if (i >= s.length || s[i] != c) throw IllegalArgumentException("expected $c at $i"); i++ }
        fun lit(w: String, v: Any?): Any? { if (!s.startsWith(w, i)) throw IllegalArgumentException("bad literal at $i"); i += w.length; return v }
        fun num(): Any {
            val st = i; i++
            while (i < s.length && (s[i].isDigit() || s[i] in ".eE+-")) i++
            val t = s.substring(st, i)
            return t.toLongOrNull() ?: t.toDouble()
        }
        fun str(): String {
            expect('"'); val sb = StringBuilder()
            while (true) {
                if (i >= s.length) throw IllegalArgumentException("unterminated string")
                val c = s[i++]
                if (c == '"') return sb.toString()
                if (c != '\\') { sb.append(c); continue }
                when (val e = s[i++]) {
                    'n' -> sb.append('\n'); 'r' -> sb.append('\r'); 't' -> sb.append('\t'); 'b' -> sb.append('\b'); 'f' -> sb.append('\u000c')
                    'u' -> { sb.append(s.substring(i, i + 4).toInt(16).toChar()); i += 4 }
                    else -> sb.append(e)
                }
            }
        }
    }
}
