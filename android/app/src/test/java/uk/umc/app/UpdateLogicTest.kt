package uk.umc.app

import org.junit.Assert.*
import org.junit.Test

class UpdateLogicTest {
    private fun release(body: String, assets: String) =
        """{"tag_name":"app-latest","body":${uk.umc.app.net.MiniJson.quote(body)},"assets":[$assets]}"""
    private val apk = """{"name":"ultimate-meshcore-app-latest.apk","size":12345,"browser_download_url":"https://github.com/x/y/releases/download/app-latest/ultimate-meshcore-app-latest.apk"}"""
    private val other = """{"name":"ultimate-meshcore-app-abc1234.apk","size":1,"browser_download_url":"https://example.invalid/other.apk"}"""
    private val notes = "Ultimate MeshCore App, built from c587a58 on 2026-11-26.\n\nInstall the APK."

    @Test fun parsesShaAndAsset() {
        val r = UpdateLogic.parseRelease(release(notes, "$other,$apk"))!!
        assertEquals("c587a58", r.sha)
        assertEquals(12345L, r.size)
        assertTrue(r.url.endsWith("/ultimate-meshcore-app-latest.apk"))
    }

    @Test fun longShaIsCutToSeven() {
        assertEquals("c587a58", UpdateLogic.shaFromBody("built from c587a58b1d2e3f4a5b6c7d8e9f00112233445566"))
        assertNull(UpdateLogic.shaFromBody("no commit here"))
        assertNull(UpdateLogic.shaFromBody(null))
    }

    @Test fun missingAssetOrShaGivesNull() {
        assertNull(UpdateLogic.parseRelease(release(notes, other)))
        assertNull(UpdateLogic.parseRelease(release(notes, "")))
        assertNull(UpdateLogic.parseRelease(release("nothing useful", apk)))
        assertNull(UpdateLogic.parseRelease("""{"body":"built from c587a58 on x"}"""))
    }

    @Test fun malformedGivesNull() {
        assertNull(UpdateLogic.parseRelease(""))
        assertNull(UpdateLogic.parseRelease("not json"))
        assertNull(UpdateLogic.parseRelease("[1,2]"))
        assertNull(UpdateLogic.parseRelease("""{"body":"built from c587a58","assets":[1,"x",{"name":5}]}"""))
        assertNull(UpdateLogic.parseRelease("""{"body":"built from c587a58","assets":"""))
    }

    @Test fun updateRule() {
        assertTrue(UpdateLogic.isUpdateAvailable("c587a58", "d111111"))
        assertFalse(UpdateLogic.isUpdateAvailable("c587a58", "c587a58"))
        assertFalse(UpdateLogic.isUpdateAvailable("C587A58", "c587a58"))
        assertFalse(UpdateLogic.isUpdateAvailable("dev", "d111111"))
        assertFalse(UpdateLogic.isUpdateAvailable("c587a58", null))
        assertFalse(UpdateLogic.isUpdateAvailable("c587a58", ""))
    }

    @Test fun failureMessages() {
        assertEquals(UpdateLogic.SIGNATURE_MESSAGE, UpdateLogic.failureMessage(5, null))
        assertEquals(UpdateLogic.SIGNATURE_MESSAGE, UpdateLogic.failureMessage(7, "x"))
        assertEquals(UpdateLogic.SIGNATURE_MESSAGE, UpdateLogic.failureMessage(1, "INSTALL_FAILED_UPDATE_INCOMPATIBLE: signatures"))
        assertEquals("Install cancelled", UpdateLogic.failureMessage(3, null))
        assertEquals("Install failed: no space", UpdateLogic.failureMessage(6, "no space"))
        assertEquals("Install failed (code 4)", UpdateLogic.failureMessage(4, null))
    }
}
