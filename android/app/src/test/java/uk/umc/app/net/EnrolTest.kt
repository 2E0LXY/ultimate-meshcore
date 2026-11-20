package uk.umc.app.net

import org.junit.Assert.*
import org.junit.Test

/*
 * Vectors from the Python reference, server/umcnet/dash/umcnet_enrol.py:
 *   prv, pub = ed_keypair(bytes(range(32)));  msg = hello_message(ID, 1700000000, "0123456789abcdef");  sig = ed_sign(prv, pub, msg)
 *   grant = make_grant(ID, SETUP_CODE, eph_scalar=bytes(range(50, 82)), nonce=bytes(range(12)))   and open_grant(prv, ID, grant) == SETUP_CODE
 * Ed25519 signatures are deterministic, so the Kotlin signature must equal the Python one; the hello then passes
 * verify_hello because it signs the identical message bytes.
 */
class EnrolTest {
    private val seed = ByteArray(32) { it.toByte() }
    private val ID = "03A107BFF3CE10BE1D70DD18E74BC09967E4D6309BA50D5F1DDC8664125531B8"
    private val SIG = "454a7c1058922e75411f4b37ac82f2eecc09b7bf4d5be2f94ba720a8dbc95e9aea762d2b12322ecc29f5b0dcb499a2895d7279924ea5ff5701e839984566c70a"
    private val CODE = "umcclient1:eyJoIjoibmV0LmV4YW1wbGUudWsiLCJ1IjoiZGFyZW4tYXBwIiwicCI6InMzY3JldC1wdyIsImkiOiIwM0ExMDdCRkYzQ0UxMEJFMUQ3MEREMThFNzRCQzA5OTY3RTRENjMwOUJBNTBENUYxRERDODY2NDEyNTUzMUI4IiwiYSI6IkxCQSJ9"
    private val GRANT = "AdWicsWT3A_OTQODN8azU09AOYymDUpxBvyspTDhYIM2AAECAwQFBgcICQoLrpuWnsgpq8seOrXQb1acyN-o3j8IXQjd5lvNW8u0X5Zo1pUSNWzfbRapfUi2BKY5Tnk6k1qq9DSy-SfU5b8HZn591cuYb3Bfpnz4xuuNpQf7EMf6Falc-q1bDKaripOexRjFyCP2MqJJWxdT7Wx72N3iCJ3wYpmj8MR5pcE_sdyzK2a_CyF3RIfPIWnlGD_6m_eQRqECQCrlx1jCjdEGSx7qvjj_HxhFPwXowDcUBkkW141plGiOp1ovHm8AbM1bfoiiGsoQt5fXfRcTgm4t"
    private val GRANT_FOR_SOMEONE_ELSE = "AdWicsWT3A_OTQODN8azU09AOYymDUpxBvyspTDhYIM2AAECAwQFBgcICQoLzzs8PwMd_8b01FGh57Y6r0psIOIuR92sUhfVrNTHPQHTm3hBFw-qz2ee0XOGGySWjVR2vCSDbmy2AAa68U1ZZByWmToVLZeZ0aAFzzSfzSxol5b1dQzIWXAi7YGKe7Vo3dmvQc-JwplsUatA1GDjFuIpDiitVv-BqnrN6Z0piiqSQFzYLFoJpeKrSTsChtSKbsYcquGHD_hQs6JX_nktVDMb3I8dcro2L9D1ycSfX-XkU14JjzHAdW-5Eysw0YTSwGI9uAGQHhbHevEx-G_x"

    private val me = Identity(seed)

    @Test fun theClientIdIsThePublicKeyInUppercaseHex() = assertEquals(ID, me.id)

    @Test fun helloMessageAndSignatureMatchPython() {
        assertEquals("UMC-ENROL1|$ID|1700000000|0123456789abcdef", String(Enrol.helloMessage(ID.lowercase(), 1700000000, "0123456789abcdef")))
        assertEquals(SIG, MsgCodec.toHex(me.sign(Enrol.helloMessage(ID, 1700000000, "0123456789abcdef"))).lowercase())
    }

    @Test fun helloJsonHasTheFieldsTheServerChecks() {
        val j = MiniJson.parseObject(Enrol.helloJson(me, "Daren \"phone\"", "0.1.15", "UMC Android app", 1700000000, "0123456789abcdef"))!!
        assertEquals(1L, j["v"]); assertEquals(ID, j["id"]); assertEquals(1700000000L, j["ts"]); assertEquals("0123456789abcdef", j["nc"]); assertEquals(SIG, j["sig"])
        assertEquals("Daren phone", j["name"]); assertEquals("UMC Android app", j["bd"])
        assertTrue((j["nc"] as String).matches(Regex("^[0-9a-f]{8,32}$"))); assertTrue((j["sig"] as String).matches(Regex("^[0-9a-fA-F]{128}$")))
    }

    @Test fun nonceLooksLikeTheFirmwares() = assertTrue(Enrol.newNonce().matches(Regex("^[0-9a-f]{16}$")))

    @Test fun opensAGrantMadeByPython() = assertEquals(CODE, Enrol.openGrant(me, GRANT))

    @Test fun theOpenedGrantIsAUsableAccountForThisClient() {
        val a = SetupCode.parse(Enrol.openGrant(me, GRANT)!!).getOrThrow()
        assertEquals(UmcAccount("net.example.uk", "daren-app", "s3cret-pw", ID, "LBA"), a)
    }

    @Test fun aGrantForAnotherDeviceOrADamagedOneIsRefused() {
        assertNull(Enrol.openGrant(me, GRANT_FOR_SOMEONE_ELSE))
        val chars = GRANT.toCharArray(); chars[100] = if (chars[100] == 'A') 'B' else 'A'
        assertNull(Enrol.openGrant(me, String(chars)))
        assertNull(Enrol.openGrant(me, "")); assertNull(Enrol.openGrant(me, "AAAA")); assertNull(Enrol.openGrant(me, "not base64 !!"))
        assertNull(Enrol.openGrant(Identity(ByteArray(32) { (it + 1).toByte() }), GRANT))
    }

    @Test fun aNewIdentityHasAFreshId() {
        val a = Identity.generate(); val b = Identity.generate()
        assertNotEquals(a.id, b.id); assertTrue(a.id.matches(Regex("^[0-9A-F]{64}$")))
    }

    @Test fun topicsAndDoorbell() {
        assertEquals("umcnet/v1/enrol/grant/$ID", Enrol.grantTopic(ID)); assertEquals("umc-enrol-03A107BFF3CE", Enrol.doorbellClientId(ID))
        assertEquals("enrol", Enrol.DOORBELL_USER); assertEquals("enrol-open-door-v1", Enrol.DOORBELL_PASSWORD)
    }
}
