package uk.umc.app.tools

import org.junit.Assert.*
import org.junit.Test

class CsvTest {
    @Test fun plainTextIsUnquoted() = assertEquals("hello", Csv.text("hello"))

    @Test fun quotesCommasAndNewlinesAreEscaped() {
        assertEquals("\"a,b\"", Csv.text("a,b"))
        assertEquals("\"say \"\"hi\"\"\"", Csv.text("say \"hi\""))
        assertEquals("\"line1\nline2\"", Csv.text("line1\nline2"))
        assertEquals("\"a\r\nb\"", Csv.text("a\r\nb"))
        assertEquals("\" pad\"", Csv.text(" pad"))
    }

    @Test fun formulaPrefixesAreDefused() {
        for (p in listOf("=", "+", "-", "@")) assertEquals("'${p}1+1", Csv.text("${p}1+1"))
        assertEquals("'=HYPERLINK(\"x\")".let { "\"" + it.replace("\"", "\"\"") + "\"" }, Csv.text("=HYPERLINK(\"x\")"))
        assertEquals("'\tcmd", Csv.text("\tcmd"))
        assertTrue(Csv.text("\r=1").startsWith("\"'"))
    }

    @Test fun numbersStayRawSoNegativesAreNotMangled() {
        assertEquals("-1.5,2,true,", Csv.row(-1.5, 2L, true, null))
        assertEquals("'-1.5", Csv.cell("-1.5"))   // the same value as text is defused
    }

    @Test fun documentHasBomHeaderAndCrlf() {
        val d = Csv.document(listOf("a", "b"), listOf(listOf("x", 1L), listOf("y,z", null)))
        assertEquals("﻿a,b\r\nx,1\r\n\"y,z\",\r\n", d)
    }

    @Test fun nonFiniteNumbersAreBlank() {
        assertEquals("", Csv.cell(Double.NaN)); assertEquals("", Csv.cell(Double.POSITIVE_INFINITY)); assertEquals("", Csv.cell(Float.NEGATIVE_INFINITY))
        assertEquals("5.5", Csv.cell(5.5)); assertEquals("-1.5", Csv.cell(-1.5)); assertEquals("3", Csv.cell(3))
        assertEquals("a,,b", Csv.row("a", Double.NaN, "b"))
    }
}
