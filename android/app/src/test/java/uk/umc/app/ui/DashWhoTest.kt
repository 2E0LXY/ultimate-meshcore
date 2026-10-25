package uk.umc.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test
import uk.umc.app.proto.Contact
import uk.umc.app.proto.HeardPacket
import uk.umc.app.proto.PacketInfo

class DashWhoTest {
    private fun contact(keyHead: String, name: String) =
        Contact(keyHead.padEnd(64, '0'), 2, 0, 1, ByteArray(64), name, 0, 0.0, 0.0, 0, ByteArray(0))

    private val contacts = listOf(contact("ec2436d4", "Hoyland Repeater"), contact("4caa3b8f", "Fulwood S10"), contact("4c11", "Other 4C"))

    private fun packet(info: PacketInfo?) = HeardPacket(0, 5.0, -90, "X", 10, true, info)
    private fun info(key: String? = null, name: String = "", src: Int? = null, dst: Int? = null, chan: Int? = null, via: Int? = null, hops: Int = 1) =
        PacketInfo("ADV", true, hops, via, src, dst, chan, key, name)

    @Test fun anAdvertKeyIsMatchedToTheFullName() =
        assertEquals("Hoyland Repeater", DashWho.who(packet(info(key = "EC2436D4", name = "Hoyland Rep")), contacts))

    @Test fun anUnknownAdvertKeepsItsOwnName() =
        assertEquals("MRLM-HA", DashWho.who(packet(info(key = "A917BC92", name = "MRLM-HA")), contacts))

    @Test fun aHashThatFitsOneContactIsNamed() =
        assertEquals("Hoyland Repeater → Fulwood S10", DashWho.who(packet(info(src = 0xEC, dst = 0x4C.let { 0x4C })), listOf(contact("ec24", "Hoyland Repeater"), contact("4caa", "Fulwood S10"))))

    @Test fun aHashThatFitsSeveralSaysSo() =
        assertEquals("4C (2 nodes)", DashWho.resolve("4C", contacts).name)

    @Test fun aHashThatFitsNoneIsShownAsHex() =
        assertEquals("B0", DashWho.resolve("b0", contacts).name)

    @Test fun channelPacketsNameTheirChannel() =
        assertEquals("channel 8A", DashWho.who(packet(info(chan = 0x8A)), contacts))

    @Test fun viaIsNamedOrDirect() {
        assertEquals("Hoyland Repeater", DashWho.via(packet(info(via = 0xEC)), contacts))
        assertEquals("direct", DashWho.via(packet(info(hops = 0)), contacts))
    }

    @Test fun aPacketWeCouldNotReadHasNoSender() =
        assertEquals("—", DashWho.who(packet(null), contacts))
}
