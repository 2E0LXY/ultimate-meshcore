package uk.umc.app.link

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import java.net.InetAddress
import java.net.Inet4Address

class WifiFinderTest {
    private fun ip(s: String) = InetAddress.getByName(s) as Inet4Address

    @Test fun aHomeNetworkHas253OtherAddressesNearestFirst() {
        val h = WifiFinder.hostsOf(ip("192.168.1.201"), 24)
        assertEquals(253, h.size)
        assertFalse(h.contains("192.168.1.201")); assertFalse(h.contains("192.168.1.0")); assertFalse(h.contains("192.168.1.255"))
        assertEquals(listOf("192.168.1.200", "192.168.1.202"), h.take(2).sorted())
    }

    @Test fun aHugeNetworkIsLimitedToA22() {
        assertEquals(1021, WifiFinder.hostsOf(ip("10.4.7.9"), 8).size)
    }
}
