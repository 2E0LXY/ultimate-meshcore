package uk.umc.app.net

import org.bouncycastle.crypto.agreement.X25519Agreement
import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters
import org.bouncycastle.crypto.params.X25519PrivateKeyParameters
import org.bouncycastle.crypto.params.X25519PublicKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import java.math.BigInteger
import java.security.MessageDigest
import java.security.SecureRandom

/*
 * UMC Net zero-touch enrolment, the client's half. The same protocol a repeater uses (docs/umc/ENROL.md; server half
 * server/umcnet/dash/umcnet_enrol.py; repeater half src/helpers/mqtt/Enrol.h). The curve arithmetic is BouncyCastle's
 * lightweight API (Ed25519Signer, X25519Agreement); only the Edwards-to-Montgomery coordinate change and the
 * HMAC key derivation are written here. Pure JVM, no Android imports.
 */

/** The app's own Ed25519 identity. The public key, as 64 uppercase hex digits, is the client id. */
class Identity(val seed: ByteArray) {
    init { require(seed.size == 32) { "an identity seed is 32 bytes" } }
    private val priv = Ed25519PrivateKeyParameters(seed, 0)
    val publicKey: ByteArray = priv.generatePublicKey().encoded
    val id: String = MsgCodec.toHex(publicKey)

    fun sign(msg: ByteArray): ByteArray {
        val s = Ed25519Signer(); s.init(true, priv); s.update(msg, 0, msg.size); return s.generateSignature()
    }

    /** The X25519 scalar for this identity: the clamped first half of SHA-512(seed), as the firmware's key layout has it. */
    fun scalar(): ByteArray {
        val h = MessageDigest.getInstance("SHA-512").digest(seed).copyOf(32)
        h[0] = (h[0].toInt() and 248).toByte(); h[31] = ((h[31].toInt() and 127) or 64).toByte()
        return h
    }

    companion object {
        fun generate(random: SecureRandom = SecureRandom()): Identity = Identity(ByteArray(32).also { random.nextBytes(it) })
    }
}

object Enrol {
    const val DOORBELL_USER = "enrol"
    const val DOORBELL_PASSWORD = "enrol-open-door-v1"          // deliberately public: it opens nothing but the doorbell
    const val TOPIC_HELLO = "umcnet/v1/enrol/hello"
    const val DEFAULT_HOST = "net.2e0lxy.uk"
    fun grantTopic(id: String) = "umcnet/v1/enrol/grant/$id"
    /** The MQTT client id the doorbell connection uses (as the firmware does). */
    fun doorbellClientId(id: String) = "umc-enrol-" + id.take(12)

    /** What is signed: "UMC-ENROL1|<ID>|<ts>|<nonce>". */
    fun helloMessage(id: String, ts: Long, nonce: String): ByteArray =
        "UMC-ENROL1|${id.uppercase()}|$ts|$nonce".toByteArray(Charsets.UTF_8)

    /** A fresh lowercase-hex nonce of 16 characters. */
    fun newNonce(random: SecureRandom = SecureRandom()): String = MsgCodec.toHex(ByteArray(8).also { random.nextBytes(it) }).lowercase()

    private fun clean(s: String, max: Int) = s.filter { it.code in 0x20..0x7e && it != '"' && it != '\\' }.take(max)

    /** The request to publish on [TOPIC_HELLO], signed with the identity. */
    fun helloJson(who: Identity, name: String, fw: String, board: String, ts: Long, nonce: String): String {
        val sig = MsgCodec.toHex(who.sign(helloMessage(who.id, ts, nonce))).lowercase()
        return MiniJson.obj("v" to 1, "id" to who.id, "name" to clean(name, 31), "fw" to clean(fw, 16), "bd" to clean(board, 32), "ts" to ts, "nc" to nonce, "sig" to sig)
    }

    private val P = BigInteger.ONE.shiftLeft(255).subtract(BigInteger.valueOf(19))
    private val MASK = BigInteger.ONE.shiftLeft(255).subtract(BigInteger.ONE)

    private fun le(b: ByteArray) = BigInteger(1, b.reversedArray())
    private fun le32(v: BigInteger): ByteArray {
        val be = v.toByteArray().let { if (it.size > 1 && it[0] == 0.toByte()) it.copyOfRange(1, it.size) else it }
        val out = ByteArray(32); for (k in be.indices) out[k] = be[be.size - 1 - k]; return out
    }

    /** Montgomery u of an Ed25519 public key: (1 + y) / (1 - y). Null for the one key it is undefined for. */
    fun edToMontU(pub: ByteArray): ByteArray? {
        val y = le(pub).and(MASK)
        val den = BigInteger.ONE.subtract(y).mod(P)
        if (den.signum() == 0) return null
        return le32(BigInteger.ONE.add(y).multiply(den.modInverse(P)).mod(P))
    }

    private fun kdf(shared: ByteArray, devPub: ByteArray, eph: ByteArray) =
        MsgCodec.hmac(shared, "UMC-ENROL1 key".toByteArray() + devPub + eph)

    private fun stream(key: ByteArray, nonce: ByteArray, n: Int): ByteArray {
        val out = java.io.ByteArrayOutputStream(); var ctr = 0
        while (out.size() < n) {
            out.write(MsgCodec.hmac(key, "ks".toByteArray() + nonce + byteArrayOf((ctr ushr 24).toByte(), (ctr ushr 16).toByte(), (ctr ushr 8).toByte(), ctr.toByte())))
            ctr++
        }
        return out.toByteArray().copyOf(n)
    }

    /** Opens a grant (base64url text of 0x01 | eph(32) | nonce(12) | ciphertext | tag(16)). The join code, or null if it is not for us or is damaged. */
    fun openGrant(who: Identity, text: String): String? {
        try {
            val raw = MsgCodec.b64urlDecode(text) ?: return null
            if (raw.size < 1 + 32 + 12 + 16 || raw[0] != 1.toByte()) return null
            val eph = raw.copyOfRange(1, 33); val nonce = raw.copyOfRange(33, 45)
            val ct = raw.copyOfRange(45, raw.size - 16); val tag = raw.copyOfRange(raw.size - 16, raw.size)
            val u = edToMontU(eph) ?: return null
            val agreement = X25519Agreement(); agreement.init(X25519PrivateKeyParameters(who.scalar(), 0))
            val shared = ByteArray(32); agreement.calculateAgreement(X25519PublicKeyParameters(u, 0), shared, 0)
            val key = kdf(shared, who.publicKey, eph)
            val mac = MsgCodec.hmac(key, "mac".toByteArray() + nonce + ct).copyOf(16)
            if (!MessageDigest.isEqual(mac, tag)) return null
            val ks = stream(key, nonce, ct.size)
            return String(ByteArray(ct.size) { (ct[it].toInt() xor ks[it].toInt()).toByte() }, Charsets.UTF_8)
        } catch (e: Exception) { return null }
    }
}
