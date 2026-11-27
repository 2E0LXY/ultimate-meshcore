package uk.umc.app.ui

import kotlin.math.pow

/**
 * The UMC theme tokens as plain values (0xAARRGGBB longs), so they can be unit-tested without Compose.
 * Single source of truth is docs/umc/theme/tokens.json; UmcTokensTest compares every value against it.
 * Keep this file in step with that JSON. UmcPalette.kt turns these into Compose colours.
 */
enum class UmcThemeId(val key: String, val label: String, val blurb: String) {
    OVERVIEW("overview", "Overview", "Near-black with navy and a blue accent"),
    ANALYTICS("analytics", "Analytics", "Graphite with multi-colour charts");

    companion object {
        val DEFAULT = OVERVIEW
        fun fromKey(key: String?): UmcThemeId = entries.firstOrNull { it.key == key } ?: DEFAULT
    }
}

data class UmcTokens(
    val id: UmcThemeId,
    val label: String,
    val page: Long, val surface: Long, val surface2: Long, val sidebar: Long, val card: Long,
    val border: Long, val chip: Long, val track: Long,
    val ink: Long, val muted: Long, val faint: Long,
    val accent: Long, val accentInk: Long, val navActive: Long, val navActiveInk: Long,
    val ok: Long, val okBg: Long, val warn: Long, val warnBg: Long, val bad: Long, val badBg: Long,
    val series: List<Long>,
    val radius: Int, val radiusSm: Int, val radiusPill: Int,
) {
    /** True when the nav-active fill is the accent itself (Overview) rather than a quiet chip (Analytics). */
    val navIsAccent: Boolean get() = navActive == accent

    /**
     * Phones draw the app on `surface`, never on `page`: Analytics' page is a light grey meant for wide screens
     * behind the dark app frame. Overview fades from `surface` (navy) at the top to its near-black `page` at the bottom.
     */
    val hasGradient: Boolean get() = page != surface && Contrast.luminance(page) < 0.2
    val mainTop: Long get() = surface
    val mainBottom: Long get() = if (hasGradient) page else surface
}

object UmcThemes {
    private fun rgb(v: Long): Long = 0xFF000000L or v

    val overview = UmcTokens(
        id = UmcThemeId.OVERVIEW, label = "Overview",
        page = rgb(0x05070c), surface = rgb(0x0e1626), surface2 = rgb(0x131c2e), sidebar = rgb(0x0f1522), card = rgb(0x0a0c11),
        border = rgb(0x1a2030), chip = rgb(0x1a1d24), track = rgb(0x23262d),
        ink = rgb(0xffffff), muted = rgb(0x8a93a6), faint = rgb(0x5b6475),
        accent = rgb(0x2563eb), accentInk = rgb(0xffffff), navActive = rgb(0x2563eb), navActiveInk = rgb(0xffffff),
        ok = rgb(0x22c55e), okBg = rgb(0x0d2a1b), warn = rgb(0xf59e0b), warnBg = rgb(0x2b2108), bad = rgb(0xef4444), badBg = rgb(0x2b0f15),
        series = listOf(0x4f46e5L, 0x3b82f6L, 0x06b6d4L, 0x22d3eeL, 0xa78bfaL, 0xf59e0bL).map(::rgb),
        radius = 14, radiusSm = 8, radiusPill = 999,
    )

    val analytics = UmcTokens(
        id = UmcThemeId.ANALYTICS, label = "Analytics",
        page = rgb(0xf3f4f6), surface = rgb(0x0b0b0d), surface2 = rgb(0x0b0b0d), sidebar = rgb(0x0b0b0d), card = rgb(0x111114),
        border = rgb(0x1c1c21), chip = rgb(0x17171b), track = rgb(0x232329),
        ink = rgb(0xf4f4f5), muted = rgb(0x8f8f98), faint = rgb(0x5d5d66),
        accent = rgb(0x3b5bff), accentInk = rgb(0xffffff), navActive = rgb(0x17171b), navActiveInk = rgb(0xffffff),
        ok = rgb(0x22c55e), okBg = rgb(0x0d2417), warn = rgb(0xf5a524), warnBg = rgb(0x2a2008), bad = rgb(0xef4444), badBg = rgb(0x2b0f15),
        series = listOf(0x3b5bffL, 0x29b6f6L, 0x22c55eL, 0xf2784bL, 0x7c5cffL, 0xec4899L, 0xf5a524L, 0x14b8a6L).map(::rgb),
        radius = 16, radiusSm = 8, radiusPill = 999,
    )

    val all: List<UmcTokens> = listOf(overview, analytics)
    fun of(id: UmcThemeId): UmcTokens = if (id == UmcThemeId.ANALYTICS) analytics else overview
}

/** WCAG 2.x relative luminance and contrast ratio, on 0xAARRGGBB longs (alpha ignored; colours are opaque tokens). */
object Contrast {
    private fun channel(c8: Int): Double {
        val s = c8 / 255.0
        return if (s <= 0.03928) s / 12.92 else ((s + 0.055) / 1.055).pow(2.4)
    }

    fun luminance(argb: Long): Double {
        val r = ((argb shr 16) and 0xFF).toInt()
        val g = ((argb shr 8) and 0xFF).toInt()
        val b = (argb and 0xFF).toInt()
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    }

    fun ratio(a: Long, b: Long): Double {
        val la = luminance(a); val lb = luminance(b)
        val hi = maxOf(la, lb); val lo = minOf(la, lb)
        return (hi + 0.05) / (lo + 0.05)
    }

    const val AA_BODY = 4.5
    const val AA_LARGE = 3.0
}
