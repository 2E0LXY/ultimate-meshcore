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
}
