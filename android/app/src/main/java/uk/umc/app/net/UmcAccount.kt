package uk.umc.app.net

/** The login for UMC Net: where the broker is, who we are on it and which area's topics we use. */
data class UmcAccount(val host: String, val user: String, val password: String, val clientId: String, val area: String) {
    fun toSetupCode(): String = SetupCode.encode(this)
}

/** `umcclient1:` + base64url (no padding) of compact JSON {"h":host,"u":user,"p":password,"i":client id,"a":area}. */
object SetupCode {
    const val PREFIX = "umcclient1:"
    private val ID = Regex("^[0-9A-F]{64}$")
    private val HOST = Regex("^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
    private val AREA = Regex("^[A-Za-z0-9_-]{1,32}$")

    fun validHost(h: String) = HOST.matches(h)

    /** Checks the five values. Returns an error in plain words, or null if they are usable. */
    fun validate(a: UmcAccount): String? = when {
        !HOST.matches(a.host) -> "the host must be a name such as net.example.uk, with no https:// or path"
        a.user.isBlank() -> "the username is missing"
        a.password.isEmpty() -> "the password is missing"
        !ID.matches(a.clientId) -> "the client id must be 64 uppercase hex digits"
        !AREA.matches(a.area) -> "the area is letters, digits, dashes or underscores"
        else -> null
    }

    fun encode(a: UmcAccount): String =
        PREFIX + MsgCodec.b64urlEncode(MiniJson.obj("h" to a.host, "u" to a.user, "p" to a.password, "i" to a.clientId, "a" to a.area).toByteArray(Charsets.UTF_8))

    /** Parses a pasted code (whitespace around it is ignored). The account, or an error message. */
    fun parse(code: String): Result<UmcAccount> {
        val t = code.trim()
        if (!t.startsWith(PREFIX)) return Result.failure(IllegalArgumentException("that is not a UMC Net setup code (it starts umcclient1:)"))
        val bytes = MsgCodec.b64urlDecode(t.removePrefix(PREFIX)) ?: return Result.failure(IllegalArgumentException("the setup code is damaged (not base64)"))
        val j = MiniJson.parseObject(String(bytes, Charsets.UTF_8)) ?: return Result.failure(IllegalArgumentException("the setup code is damaged (not JSON)"))
        fun s(k: String) = (j[k] as? String)?.trim().orEmpty()
        val a = UmcAccount(s("h"), s("u"), (j["p"] as? String).orEmpty(), s("i").uppercase(), s("a"))
        return validate(a)?.let { Result.failure(IllegalArgumentException(it)) } ?: Result.success(a)
    }
}
