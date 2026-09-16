package uk.umc.app.ui

import android.preference.PreferenceManager
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import org.osmdroid.config.Configuration
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import uk.umc.app.AppState

/**
 * Everyone on the mesh who shares a location, on an OpenStreetMap map. Tiles are cached by
 * osmdroid, so an area you have looked at before still works without a data connection.
 */
@Composable
fun MapScreen() {
    val context = LocalContext.current
    val session by AppState.session.collectAsState()
    val s = session ?: return NotConnected()
    val contacts by s.contacts.collectAsState()
    val self by s.self.collectAsState()

    Box(Modifier.fillMaxSize()) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                Configuration.getInstance().load(ctx, PreferenceManager.getDefaultSharedPreferences(ctx))
                Configuration.getInstance().userAgentValue = "UltimateMeshCoreApp"
                MapView(ctx).apply {
                    setTileSource(TileSourceFactory.MAPNIK)
                    setMultiTouchControls(true)
                    controller.setZoom(11.0)
                }
            },
            update = { map ->
                map.overlays.clear()
                var centred = false
                self?.let { me ->
                    if (me.lat != 0.0 || me.lon != 0.0) {
                        val p = GeoPoint(me.lat, me.lon)
                        map.overlays.add(Marker(map).apply {
                            position = p
                            title = "${me.name} (this radio)"
                            setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
                        })
                        map.controller.setCenter(p)
                        centred = true
                    }
                }
                contacts.filter { it.lat != 0.0 || it.lon != 0.0 }.forEach { c ->
                    val p = GeoPoint(c.lat, c.lon)
                    map.overlays.add(Marker(map).apply {
                        position = p
                        title = c.name
                        snippet = "${c.typeName} · ${pathLabel(c)}"
                        setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
                    })
                    if (!centred) {
                        map.controller.setCenter(p)
                        centred = true
                    }
                }
                map.invalidate()
            },
        )
    }
}
