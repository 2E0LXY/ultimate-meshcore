package uk.umc.app.tools

import org.junit.Assert.*
import org.junit.Test

class GeofenceTest {
    // 1 degree of latitude is about 111,195 m, so 0.001 degrees is about 111 m
    private val fence = Geofence("f1", "Home", 53.7000, -1.5000, 1000.0)
    private fun north(m: Double) = 53.7000 + m / 111_195.0
    private fun eng() = GeofenceEngine(hysteresis = 0.10, minIntervalMs = 60_000L)
    private fun GeofenceEngine.at(m: Double, t: Long, node: String = "n1") = update(node, "Node", north(m), -1.5, t, listOf(fence))

    @Test fun haversineKnownDistances() {
        assertEquals(111_195.0, Geo.haversineM(0.0, 0.0, 1.0, 0.0), 200.0)
        assertEquals(0.0, Geo.haversineM(53.7, -1.5, 53.7, -1.5), 0.001)
        // London to Paris is about 344 km
        assertEquals(344_000.0, Geo.haversineM(51.5074, -0.1278, 48.8566, 2.3522), 2_000.0)
        // across the antimeridian
        assertEquals(22_239.0, Geo.haversineM(0.0, 179.9, 0.0, -179.9), 100.0)
    }

    @Test fun validPositions() {
        assertTrue(Geo.validPosition(53.7, -1.5))
        assertFalse(Geo.validPosition(0.0, 0.0))
        assertTrue(Geo.validPosition(0.0, 5.0))
        assertFalse(Geo.validPosition(Double.NaN, 1.0))
        assertFalse(Geo.validPosition(1.0, Double.POSITIVE_INFINITY))
        assertFalse(Geo.validPosition(91.0, 0.0))
        assertFalse(Geo.validPosition(0.0, 181.0))
    }

    @Test fun firstSightingSetsStateWithoutAnAlert() {
        val e = eng()
        assertTrue(e.at(100.0, 0).isEmpty())
        assertTrue(e.at(5000.0, 120_000).isNotEmpty())     // proves it started inside
    }

    @Test fun exitAndEnter() {
        val e = eng()
        e.at(100.0, 0)
        val out = e.at(1500.0, 120_000)
        assertEquals(1, out.size); assertEquals(FenceEvent.EXIT, out[0].event); assertEquals("Node left Home", out[0].summary)
        val back = e.at(500.0, 240_000)
        assertEquals(1, back.size); assertEquals(FenceEvent.ENTER, back[0].event)
    }

    @Test fun startingOutsideThenEntering() {
        val e = eng()
        assertTrue(e.at(3000.0, 0).isEmpty())
        assertEquals(FenceEvent.ENTER, e.at(500.0, 100_000).single().event)
    }

    @Test fun hysteresisBand() {
        val e = eng()
        e.at(500.0, 0)
        assertTrue(e.at(1050.0, 100_000).isEmpty())         // outside the radius but within 10%: still inside
        assertTrue(e.at(1099.0, 200_000).isEmpty())
        assertEquals(FenceEvent.EXIT, e.at(1150.0, 300_000).single().event)
        assertTrue(e.at(950.0, 400_000).isEmpty())          // back in the radius but not 10% in: still outside
        assertEquals(FenceEvent.ENTER, e.at(850.0, 500_000).single().event)
    }

    @Test fun jitterAtTheBoundaryDoesNotFlap() {
        val e = eng()
        e.at(990.0, 0)
        var alerts = 0
        for (i in 1..200) alerts += e.at(if (i % 2 == 0) 970.0 else 1030.0, i * 10_000L).size
        assertEquals(0, alerts)
    }

    @Test fun minimumIntervalHoldsBackThenReports() {
        val e = eng()
        e.at(100.0, 0)
        assertEquals(1, e.at(2000.0, 100_000).size)          // exit
        assertTrue(e.at(100.0, 110_000).isEmpty())            // enter only 10 s later: held back
        assertEquals(FenceEvent.ENTER, e.at(100.0, 170_000).single().event)   // still true a minute on
    }

    @Test fun heldBackCrossingIsDroppedIfItNoLongerHolds() {
        val e = eng()
        e.at(100.0, 0)
        e.at(2000.0, 100_000)
        assertTrue(e.at(100.0, 110_000).isEmpty())
        assertTrue(e.at(2000.0, 120_000).isEmpty())           // went out again: nothing to say
    }

    @Test fun invalidAndZeroPositionsAreIgnoredAndKeepState() {
        val e = eng()
        e.at(100.0, 0)
        assertTrue(e.update("n1", "Node", 0.0, 0.0, 100_000, listOf(fence)).isEmpty())
        assertTrue(e.update("n1", "Node", Double.NaN, -1.5, 100_000, listOf(fence)).isEmpty())
        assertTrue(e.update("n1", "Node", 95.0, -1.5, 100_000, listOf(fence)).isEmpty())
        assertEquals(FenceEvent.EXIT, e.at(2000.0, 200_000).single().event)   // state survived
    }

    @Test fun nodesAreIndependent() {
        val e = eng()
        e.at(100.0, 0, "a"); e.at(2000.0, 0, "b")
        assertEquals("a", e.at(2000.0, 100_000, "a").single().node)
        assertEquals("b", e.at(100.0, 100_000, "b").single().node)
    }

    @Test fun invalidFenceIsSkippedAndDeletedFenceForgotten() {
        val e = eng()
        val bad = Geofence("bad", "", 53.7, -1.5, 100.0)
        assertTrue(e.update("n", "N", 53.7, -1.5, 0, listOf(bad)).isEmpty())
        e.at(100.0, 0)
        e.update("n1", "Node", north(100.0), -1.5, 10, emptyList())     // fence deleted
        assertTrue(e.at(2000.0, 200_000).isEmpty())                      // re-added: first sighting again, no alert
    }

    @Test fun validation() {
        assertNull(Fences.validate(fence))
        assertNotNull(Fences.validate(fence.copy(name = " ")))
        assertNotNull(Fences.validate(fence.copy(name = "x".repeat(41))))
        assertNotNull(Fences.validate(fence.copy(lat = 0.0, lon = 0.0)))
        assertNotNull(Fences.validate(fence.copy(radiusM = 5.0)))
        assertNotNull(Fences.validate(fence.copy(radiusM = 600_000.0)))
        assertNotNull(Fences.validate(fence.copy(radiusM = Double.NaN)))
    }

    private fun hit(i: Int) = FenceHit("f1", "Home", "k$i", "Node \"$i\"", if (i % 2 == 0) FenceEvent.ENTER else FenceEvent.EXIT, i.toLong(), 53.7, -1.5, 12.5)

    @Test fun historyIsBoundedAndKeepsNewest() {
        val all = GeoStore.appendEvents((1..450).map { hit(it) }, (451..600).map { hit(it) })
        assertEquals(GeoStore.MAX_EVENTS, all.size)
        assertEquals(101L, all.first().atMs); assertEquals(600L, all.last().atMs)
        assertTrue(GeoStore.appendEvents(all, emptyList()).isNotEmpty())
    }

    @Test fun storeRoundTrip() {
        val fences = listOf(fence, Geofence("f2", "Quote \" and, comma", -33.9, 151.2, 250.5))
        val events = (1..5).map { hit(it) }
        val (f, ev) = GeoStore.decode(GeoStore.encode(fences, events))
        assertEquals(fences, f); assertEquals(events, ev)
    }

    @Test fun decodeSurvivesDamage() {
        assertEquals(Pair(emptyList<Geofence>(), emptyList<FenceHit>()), GeoStore.decode("not json"))
        assertEquals(Pair(emptyList<Geofence>(), emptyList<FenceHit>()), GeoStore.decode("{}"))
        val (f, _) = GeoStore.decode("{\"fences\":[{\"id\":\"a\"},{\"id\":\"b\",\"n\":\"ok\",\"lat\":51.0,\"lon\":-1.0,\"r\":100.0},{\"id\":\"c\",\"n\":\"far\",\"lat\":51.0,\"lon\":-1.0,\"r\":1.0e9}]}")
        assertEquals(listOf("b"), f.map { it.id })
    }

    @Test fun decodeCapsFencesAndDropsDuplicates() {
        val many = (1..80).map { Geofence("id$it", "n$it", 51.0, -1.0, 100.0) } + Geofence("id1", "dup", 51.0, -1.0, 100.0)
        assertEquals(Fences.MAX_FENCES, GeoStore.decode(GeoStore.encode(many, emptyList())).first.size)
    }

    @Test fun mergeReplacesByIdAndDedupes() {
        val a = Geofence("a", "A", 51.0, -1.0, 100.0); val b = Geofence("b", "B", 52.0, -1.0, 100.0)
        val merged = GeoStore.mergeFences(listOf(a, b), listOf(a.copy(name = "A2"), Geofence("c", "C", 53.0, -1.0, 100.0)))
        assertEquals(listOf("B", "A2", "C"), merged.map { it.name })
        val ev = GeoStore.mergeEvents((1..3).map { hit(it) }, (2..5).map { hit(it) })
        assertEquals(listOf(1L, 2L, 3L, 4L, 5L), ev.map { it.atMs })
    }

    // ---- review fixes

    private fun evJson(at: String = "1700000000000", lat: String = "53.7", lon: String = "-1.5", d: String = "12.5", f: String = "f1", k: String = "k1", kn: String = "N") =
        "{\"f\":\"$f\",\"fn\":\"Home\",\"k\":\"$k\",\"kn\":\"$kn\",\"e\":\"ENTER\",\"at\":$at,\"lat\":$lat,\"lon\":$lon,\"d\":$d}"
    private fun storeWith(vararg ev: String) = "{\"v\":1,\"fences\":[{\"id\":\"a\",\"n\":\"A\",\"lat\":51.0,\"lon\":-1.0,\"r\":100.0}],\"events\":[${ev.joinToString(",")}]}"

    @Test fun nonFiniteEventsAreDroppedNotFatal() {
        val text = storeWith(evJson(), evJson(lat = "1e999"), evJson(d = "1e999"), evJson(at = "1e999"), evJson(lon = "-1e999"), evJson(at = "-5"), evJson(lat = "91"), evJson(d = "-1"))
        val (f, ev) = GeoStore.decode(text)
        assertEquals(1, f.size); assertEquals(1, ev.size)
    }

    @Test fun bareInfinityTokensFromAnOlderBuildStillLoad() {
        val text = storeWith(evJson(), evJson(d = "Infinity"), evJson(lat = "NaN"), evJson(lon = "-Infinity"))
        val (f, ev) = GeoStore.decode(text)
        assertEquals(1, f.size); assertEquals(1, ev.size)
    }

    @Test fun nonFiniteNeverWrittenAsInvalidJson() {
        val bad = FenceHit("f1", "Home", "k1", "N", FenceEvent.ENTER, 5L, 53.7, -1.5, Double.POSITIVE_INFINITY)
        val text = GeoStore.encode(listOf(fence), listOf(bad, hit(2)))
        assertFalse(text.contains("Infinity") || text.contains("NaN"))
        assertNotNull(uk.umc.app.net.MiniJson.parseObject(text))
        val (f, ev) = GeoStore.decode(text)
        assertEquals(listOf(fence), f); assertEquals(1, ev.size)       // the bad event is dropped, the fences survive
    }

    @Test fun eventTextIsCapped() {
        val ev = GeoStore.decode(storeWith(evJson(kn = "n".repeat(500)), evJson(k = "k".repeat(500)), evJson(f = "")))
        assertEquals(1, ev.second.size)
        assertEquals(64, ev.second[0].nodeName.length)
    }

    @Test fun damagedMainFileFallsBackToLastGoodCopy() {
        val good = GeoStore.encode(listOf(fence), listOf(hit(1)))
        val l1 = GeoStore.load("{\"v\":1,\"fences\":[{\"id\":", good)
        assertEquals(GeoStore.Source.BACKUP, l1.source); assertEquals(listOf(fence), l1.fences)
        assertEquals(GeoStore.Source.MAIN, GeoStore.load(good, "junk").source)
        assertEquals(GeoStore.Source.NONE, GeoStore.load("junk", "junk2").source)
        assertEquals(GeoStore.Source.NONE, GeoStore.load(null, null).source)
        // a readable file with a bad entry keeps its good fences
        val l2 = GeoStore.load("{\"fences\":[{\"id\":\"a\",\"n\":\"A\",\"lat\":51.0,\"lon\":-1.0,\"r\":100.0},{\"id\":5}]}", good)
        assertEquals(GeoStore.Source.MAIN, l2.source); assertEquals(1, l2.fences.size)
    }

    @Test fun mergeReportsKeptAndSkipped() {
        val old = (1..45).map { Geofence("o$it", "O$it", 51.0, -1.0, 100.0) }
        val inc = (1..10).map { Geofence("n$it", "N$it", 52.0, -1.0, 100.0) } + old[0].copy(name = "changed")
        val m = GeoStore.mergeFencesReport(old, inc)
        assertEquals(5, m.added); assertEquals(1, m.replaced); assertEquals(5, m.skipped)
        assertEquals(Fences.MAX_FENCES, m.fences.size)
        assertEquals("changed", m.fences.first { it.id == "o1" }.name)
        assertEquals("n5", m.fences.last().id)
    }

    @Test fun mergeSkipsInvalidAndDuplicateIncoming() {
        val m = GeoStore.mergeFencesReport(emptyList(), listOf(fence, fence, fence.copy(id = "x", radiusM = Double.NaN), fence.copy(id = "i".repeat(200))))
        assertEquals(1, m.added); assertEquals(2, m.skipped); assertEquals(0, m.replaced)
    }

    @Test fun clockGoingBackwardsDoesNotSilenceAFence() {
        val e = eng()
        e.at(100.0, 1_000_000)
        assertEquals(FenceEvent.EXIT, e.at(1500.0, 1_100_000).single().event)
        // the phone's clock jumps back an hour: the next crossing must still alert
        assertEquals(FenceEvent.ENTER, e.at(500.0, 100_000).single().event)
        // within the interval going forward is still held back
        assertTrue(e.at(1500.0, 110_000).isEmpty())
    }

    @Test fun commaDecimalsAreAccepted() {
        assertEquals(53.7, Fences.parseNumber("53,7")!!, 0.0)
        assertEquals(-1.5, Fences.parseNumber(" -1.5 ")!!, 0.0)
        assertEquals(500.0, Fences.parseNumber("500")!!, 0.0)
        assertNull(Fences.parseNumber("1,234.5"))
        assertNull(Fences.parseNumber("1,2,3"))
        assertNull(Fences.parseNumber("abc")); assertNull(Fences.parseNumber("")); assertNull(Fences.parseNumber("1e999")); assertNull(Fences.parseNumber("NaN"))
    }

    @Test fun invalidReplacementKeepsTheExistingFence() {
        val m = GeoStore.mergeFencesReport(listOf(fence), listOf(fence.copy(name = "", radiusM = 1.0)))
        assertEquals(listOf(fence), m.fences); assertEquals(1, m.skipped)
    }
}
