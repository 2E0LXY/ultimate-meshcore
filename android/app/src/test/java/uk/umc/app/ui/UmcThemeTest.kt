package uk.umc.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import uk.umc.app.net.MiniJson
import java.io.File

/**
 * Keeps UmcThemes (the Kotlin copy of the tokens) in step with docs/umc/theme/tokens.json, and checks the
 * WCAG AA contrast of the pairs the UI relies on. If you change tokens.json, change UmcTokens.kt AND [expected] below.
 */
class UmcThemeTest {
    private val colourKeys = listOf(
        "page", "surface", "surface2", "sidebar", "card", "border", "chip", "track", "ink", "muted", "faint",
        "accent", "accentInk", "navActive", "navActiveInk", "ok", "okBg", "warn", "warnBg", "bad", "badBg",
    )

    private fun valueOf(t: UmcTokens, key: String): Long = when (key) {
        "page" -> t.page; "surface" -> t.surface; "surface2" -> t.surface2; "sidebar" -> t.sidebar; "card" -> t.card
        "border" -> t.border; "chip" -> t.chip; "track" -> t.track; "ink" -> t.ink; "muted" -> t.muted; "faint" -> t.faint
        "accent" -> t.accent; "accentInk" -> t.accentInk; "navActive" -> t.navActive; "navActiveInk" -> t.navActiveInk
        "ok" -> t.ok; "okBg" -> t.okBg; "warn" -> t.warn; "warnBg" -> t.warnBg; "bad" -> t.bad; "badBg" -> t.badBg
        else -> error("unknown token $key")
    }

    private fun hex(s: String): Long = 0xFF000000L or s.removePrefix("#").toLong(16)

    /** An independent copy of the token values, written as in tokens.json (used when the file is not reachable too). */
    private val expected: Map<String, Map<String, String>> = mapOf(
        "overview" to mapOf(
            "page" to "#05070c", "surface" to "#0e1626", "surface2" to "#131c2e", "sidebar" to "#0f1522", "card" to "#0a0c11",
            "border" to "#1a2030", "chip" to "#1a1d24", "track" to "#23262d", "ink" to "#ffffff", "muted" to "#8a93a6", "faint" to "#5b6475",
            "accent" to "#2563eb", "accentInk" to "#ffffff", "navActive" to "#2563eb", "navActiveInk" to "#ffffff",
            "ok" to "#22c55e", "okBg" to "#0d2a1b", "warn" to "#f59e0b", "warnBg" to "#2b2108", "bad" to "#ef4444", "badBg" to "#2b0f15",
        ),
        "analytics" to mapOf(
            "page" to "#f3f4f6", "surface" to "#0b0b0d", "surface2" to "#0b0b0d", "sidebar" to "#0b0b0d", "card" to "#111114",
            "border" to "#1c1c21", "chip" to "#17171b", "track" to "#232329", "ink" to "#f4f4f5", "muted" to "#8f8f98", "faint" to "#5d5d66",
            "accent" to "#3b5bff", "accentInk" to "#ffffff", "navActive" to "#17171b", "navActiveInk" to "#ffffff",
            "ok" to "#22c55e", "okBg" to "#0d2417", "warn" to "#f5a524", "warnBg" to "#2a2008", "bad" to "#ef4444", "badBg" to "#2b0f15",
        ),
    )
    private val expectedSeries = mapOf(
        "overview" to listOf("#4f46e5", "#3b82f6", "#06b6d4", "#22d3ee", "#a78bfa", "#f59e0b"),
        "analytics" to listOf("#3b5bff", "#29b6f6", "#22c55e", "#f2784b", "#7c5cff", "#ec4899", "#f5a524", "#14b8a6"),
    )
    private val expectedRadius = mapOf("overview" to 14, "analytics" to 16)

    private fun findTokensFile(): File? {
        var dir: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        while (dir != null) {
            val f = File(dir, "docs/umc/theme/tokens.json")
            if (f.isFile) return f
            dir = dir.parentFile
        }
        return null
    }

    @Test fun kotlinTokensMatchTheEmbeddedCopy() {
        UmcThemes.all.forEach { t ->
            val e = expected.getValue(t.id.key)
            colourKeys.forEach { k -> assertEquals("${t.id.key}.$k", hex(e.getValue(k)), valueOf(t, k)) }
            assertEquals("${t.id.key}.series", expectedSeries.getValue(t.id.key).map(::hex), t.series)
            assertEquals("${t.id.key}.radius", expectedRadius.getValue(t.id.key), t.radius)
            assertEquals(8, t.radiusSm)
            assertEquals(999, t.radiusPill)
        }
    }

    @Test fun kotlinTokensMatchTokensJson() {
        val file = findTokensFile()
        assumeTrue("docs/umc/theme/tokens.json not reachable from ${System.getProperty("user.dir")}", file != null)
        @Suppress("UNCHECKED_CAST")
        val root = MiniJson.parseObject(file!!.readText())!!
        assertEquals("overview", root["default"])
        assertEquals(UmcThemeId.DEFAULT.key, root["default"])
        @Suppress("UNCHECKED_CAST")
        val themes = root["themes"] as Map<String, Map<String, Any?>>
        assertEquals(UmcThemes.all.map { it.id.key }.toSet(), themes.keys)
        UmcThemes.all.forEach { t ->
            val j = themes.getValue(t.id.key)
            assertEquals(t.label, j["label"])
            colourKeys.forEach { k -> assertEquals("${t.id.key}.$k", hex(j[k] as String), valueOf(t, k)) }
            @Suppress("UNCHECKED_CAST")
            assertEquals("${t.id.key}.series", (j["series"] as List<String>).map(::hex), t.series)
            assertEquals("${t.id.key}.radius", (j["radius"] as Number).toInt(), t.radius)
            assertEquals("${t.id.key}.radiusSm", (j["radiusSm"] as Number).toInt(), t.radiusSm)
            assertEquals("${t.id.key}.radiusPill", (j["radiusPill"] as Number).toInt(), t.radiusPill)
        }
    }

    @Test fun jsonHasNoTokenTheKotlinCopyLacks() {
        val file = findTokensFile()
        assumeTrue(file != null)
        @Suppress("UNCHECKED_CAST")
        val themes = (MiniJson.parseObject(file!!.readText())!!["themes"] as Map<String, Map<String, Any?>>)
        val known = colourKeys.toSet() + setOf("label", "series", "radius", "radiusSm", "radiusPill")
        themes.forEach { (name, j) -> assertEquals("$name has unknown tokens", emptySet<String>(), j.keys - known) }
    }

    @Test fun themeIdsRoundTripAndFallBackToOverview() {
        assertEquals(UmcThemeId.OVERVIEW, UmcThemeId.DEFAULT)
        UmcThemeId.entries.forEach { assertEquals(it, UmcThemeId.fromKey(it.key)) }
        assertEquals(UmcThemeId.OVERVIEW, UmcThemeId.fromKey(null))
        assertEquals(UmcThemeId.OVERVIEW, UmcThemeId.fromKey("light"))
        assertEquals(UmcThemes.overview, UmcThemes.of(UmcThemeId.OVERVIEW))
        assertEquals(UmcThemes.analytics, UmcThemes.of(UmcThemeId.ANALYTICS))
    }

    @Test fun navAndGradientFollowTheTheme() {
        assertTrue(UmcThemes.overview.navIsAccent)
        assertFalse(UmcThemes.analytics.navIsAccent)
        assertTrue(UmcThemes.overview.hasGradient)
        assertFalse(UmcThemes.analytics.hasGradient)
        assertEquals(UmcThemes.analytics.surface, UmcThemes.analytics.mainBottom)   // never the light page on a phone
        assertEquals(UmcThemes.overview.page, UmcThemes.overview.mainBottom)
    }

    // ------------------------------------------------------------ contrast

    @Test fun contrastFunctionMatchesKnownValues() {
        assertEquals(21.0, Contrast.ratio(0xFF000000L, 0xFFFFFFFFL), 1e-9)
        assertEquals(1.0, Contrast.ratio(0xFF123456L, 0xFF123456L), 1e-9)
        assertEquals(Contrast.ratio(0xFF2563EBL, 0xFFFFFFFFL), Contrast.ratio(0xFFFFFFFFL, 0xFF2563EBL), 1e-12)
        assertEquals(4.54, Contrast.ratio(0xFF767676L, 0xFFFFFFFFL), 0.01)
    }

    private fun pairs(t: UmcTokens) = listOf(
        "ink on card" to (t.ink to t.card),
        "muted on card" to (t.muted to t.card),
        "accentInk on accent" to (t.accentInk to t.accent),
        "navActiveInk on navActive" to (t.navActiveInk to t.navActive),
        "ok on okBg" to (t.ok to t.okBg),
        "bad on badBg" to (t.bad to t.badBg),
        "warn on warnBg" to (t.warn to t.warnBg),
        "ink on surface" to (t.ink to t.surface),
        "muted on surface" to (t.muted to t.surface),
        "ink on chip" to (t.ink to t.chip),
        "muted on chip" to (t.muted to t.chip),
        "bad on card" to (t.bad to t.card),
        "ok on card" to (t.ok to t.card),
        "mainTop on bad (destructive button)" to (t.mainTop to t.bad),
        "warn on card" to (t.warn to t.card),
    )

    @Test fun everyTextPairMeetsAA() {
        val failures = UmcThemes.all.flatMap { t ->
            pairs(t).mapNotNull { (name, p) ->
                val r = Contrast.ratio(p.first, p.second)
                if (r < Contrast.AA_BODY) "${t.id.key}: $name = ${"%.2f".format(r)}" else null
            }
        }
        assertTrue("below AA 4.5:1: $failures", failures.isEmpty())
    }

    @Test fun overviewPairs() = checkTheme(UmcThemes.overview)
    @Test fun analyticsPairs() = checkTheme(UmcThemes.analytics)

    private fun checkTheme(t: UmcTokens) {
        assertTrue(Contrast.ratio(t.ink, t.card) >= Contrast.AA_BODY)
        assertTrue(Contrast.ratio(t.muted, t.card) >= Contrast.AA_BODY)
        assertTrue(Contrast.ratio(t.accentInk, t.accent) >= Contrast.AA_BODY)
        assertTrue(Contrast.ratio(t.navActiveInk, t.navActive) >= Contrast.AA_BODY)
        assertTrue(Contrast.ratio(t.ok, t.okBg) >= Contrast.AA_BODY)
        assertTrue(Contrast.ratio(t.bad, t.badBg) >= Contrast.AA_BODY)
    }
}
