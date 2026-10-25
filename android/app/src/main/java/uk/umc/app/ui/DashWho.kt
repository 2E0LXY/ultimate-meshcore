package uk.umc.app.ui

import uk.umc.app.proto.Contact
import uk.umc.app.proto.HeardPacket

/** A name for a one-byte hash or key prefix, and whether it was the only match. */
data class Resolved(val name: String, val sure: Boolean)

/** Turns who-and-via codes into names using the contacts this radio knows. */
object DashWho {
    fun resolve(hex: String, contacts: List<Contact>): Resolved {
        val h = hex.lowercase()
        val hits = contacts.filter { it.publicKey.lowercase().startsWith(h) }
        return when {
            hits.size == 1 -> Resolved(hits[0].name.ifEmpty { hex.uppercase() }, true)
            hits.size > 1 -> Resolved("${hex.uppercase()} (${hits.size} nodes)", false)
            else -> Resolved(hex.uppercase(), false)
        }
    }

    private fun hex2(v: Int) = "%02X".format(v)

    /** Who a packet is from: an advert's name, or sender and destination matched to contacts. */
    fun who(p: HeardPacket, contacts: List<Contact>): String {
        val i = p.info ?: return "—"
        if (i.key != null) { val r = resolve(i.key, contacts); if (r.sure) return r.name }
        if (i.name.isNotEmpty()) return i.name
        if (i.key != null) return i.key
        if (i.src != null) {
            val a = resolve(hex2(i.src), contacts)
            val b = i.dst?.let { resolve(hex2(it), contacts) }
            return a.name + (if (b != null) " → " + b.name else "")
        }
        if (i.chan != null) return "channel " + hex2(i.chan)
        return "—"
    }

    /** The repeater that handed the packet to us, or "direct". */
    fun via(p: HeardPacket, contacts: List<Contact>): String {
        val i = p.info ?: return "—"
        return when {
            i.via != null -> resolve(hex2(i.via), contacts).name
            i.hops == 0 -> "direct"
            else -> "—"
        }
    }
}
