package uk.umc.app.ui

import android.preference.PreferenceManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import uk.umc.app.tools.OfflineMaps
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
    val pack by OfflineMaps.pack.collectAsState()
    var dialog by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            busy = true
            uk.umc.app.AppState.scope.launch(Dispatchers.IO) {
                val err = OfflineMaps.importPack(context.applicationContext, uri)
                busy = false
                uk.umc.app.AppState.say(err?.let { "Tile pack not used: $it" } ?: "Offline map ready")
            }
        }
    }

    Box(Modifier.fillMaxSize()) {
        key(pack) { AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                Configuration.getInstance().load(ctx, PreferenceManager.getDefaultSharedPreferences(ctx))
                Configuration.getInstance().userAgentValue = "UltimateMeshCoreApp"
                MapView(ctx).apply {
                    val file = OfflineMaps.file(ctx)
                    if (file == null || !OfflineMaps.useOn(this, file)) setTileSource(TileSourceFactory.MAPNIK)
                    setMultiTouchControls(true)
                    controller.setZoom(6.0)
                    controller.setCenter(GeoPoint(54.0, -2.0))   // until a node with a location is known
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
                        map.controller.setZoom(11.0)
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
                        map.controller.setZoom(11.0)
                        centred = true
                    }
                }
                map.invalidate()
            },
        ) }
        ShButton(
            onClick = { dialog = true }, variant = ShVariant.Secondary,
            modifier = Modifier.align(Alignment.TopEnd).padding(8.dp),
        ) { Text(if (pack != null) "Offline map" else "Map source") }
    }

    if (dialog) {
        AlertDialog(
            onDismissRequest = { dialog = false },
            title = { Text("Offline map") },
            text = {
                Column {
                    Text(
                        if (pack != null) "Using your tile pack: $pack. No tiles are fetched from the internet."
                        else "Online: OpenStreetMap tiles, kept in a small cache as you browse. To work fully offline, choose a tile pack " +
                            "(.zip, .sqlite, .mbtiles or .gemf, up to 2 GB) that you made or downloaded. The app does not bulk download tiles: " +
                            "openstreetmap.org's tile servers do not allow it.",
                    )
                    if (busy) Text("Copying the pack...")
                }
            },
            confirmButton = {
                ShButton(enabled = !busy, onClick = { pick.launch(arrayOf("*/*")); dialog = false }) { Text("Choose pack") }
            },
            dismissButton = {
                if (pack != null) ShButton(variant = ShVariant.Outline, onClick = { OfflineMaps.remove(context.applicationContext); dialog = false }) { Text("Use online map") }
                else ShButton(variant = ShVariant.Ghost, onClick = { dialog = false }) { Text("Close") }
            },
        )
    }
}
