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
    fun parseObject(text: String): Map<String, Any?>? = try { parse(text) as? Map<String, Any?> } catch (e: Exception) { null } catch (e: StackOverflowError) { null }

    /** How deeply arrays and objects may nest. Real data here is 3 or 4 levels; this stops a hostile file blowing the stack. */
    const val MAX_DEPTH = 32

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
        quote(k) + ":" + when (v) { null -> "null"; is String -> quote(v); is Boolean -> v.toString()
            is Number -> if (v.toDouble().isFinite()) v.toString() else "null"       // NaN and Infinity are not valid JSON
            else -> quote(v.toString()) }
    }

    private class Parser(val s: String) {
        var i = 0
        var depth = 0
        fun enter() { if (++depth > MAX_DEPTH) throw IllegalArgumentException("nested too deeply (more than $MAX_DEPTH levels)") }
        fun ws() { while (i < s.length && s[i].isWhitespace()) i++ }
        fun value(): Any? {
            ws(); if (i >= s.length) throw IllegalArgumentException("unexpected end")
            return when (val c = s[i]) {
                '{' -> { enter(); i++; val m = LinkedHashMap<String, Any?>(); ws()
                    if (i < s.length && s[i] == '}') { i++; depth--; return m }
                    while (true) { ws(); val k = str(); ws(); expect(':'); m[k] = value(); ws()
                        if (i < s.length && s[i] == ',') { i++; continue }; expect('}'); depth--; return m } ; @Suppress("UNREACHABLE_CODE") m }
                '[' -> { enter(); i++; val l = ArrayList<Any?>(); ws()
                    if (i < s.length && s[i] == ']') { i++; depth--; return l }
                    while (true) { l.add(value()); ws(); if (i < s.length && s[i] == ',') { i++; continue }; expect(']'); depth--; return l }; @Suppress("UNREACHABLE_CODE") l }
                '"' -> str()
                't' -> lit("true", true); 'f' -> lit("false", false); 'n' -> lit("null", null)
                // tolerated on read only: an older build could write these bare tokens, and one bad number must not lose the file
                'I' -> lit("Infinity", Double.POSITIVE_INFINITY); 'N' -> lit("NaN", Double.NaN)
                else -> if (c == '-' || c.isDigit()) num() else throw IllegalArgumentException("bad character at $i")
            }
        }
        fun expect(c: Char) { if (i >= s.length || s[i] != c) throw IllegalArgumentException("expected $c at $i"); i++ }
        fun lit(w: String, v: Any?): Any? { if (!s.startsWith(w, i)) throw IllegalArgumentException("bad literal at $i"); i += w.length; return v }
        fun num(): Any {
            if (s.startsWith("-Infinity", i)) { i += 9; return Double.NEGATIVE_INFINITY }
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
