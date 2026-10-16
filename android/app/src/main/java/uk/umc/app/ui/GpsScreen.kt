package uk.umc.app.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.launch
import uk.umc.app.AppState

/**
 * Where the radio thinks it is, where this phone is, and how to tell one from the other.
 *
 * The radio's position is whatever it has been given or found; the phone's is only read
 * when you ask for it, so the app never requests a location you did not want to share.
 */
@Composable
fun GpsScreen() {
    val s by AppState.session.collectAsState()
    val session = s ?: return NotConnected()
    val me by session.self.collectAsState()
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()

    var phone by remember { mutableStateOf<Location?>(null) }
    var asked by remember { mutableStateOf(false) }

    fun readPhonePosition() {
        val granted = ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        if (!granted) return
        val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val best = runCatching {
            lm.getProviders(true).mapNotNull { p ->
                @Suppress("MissingPermission")
                lm.getLastKnownLocation(p)
            }.maxByOrNull { it.time }
        }.getOrNull()
        phone = best
        if (best == null) AppState.say("No position from this phone yet - try again outdoors")
    }

    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        asked = true
        if (ok) readPhonePosition() else AppState.say("Location permission refused")
    }

    val radioSet = me?.let { it.lat != 0.0 || it.lon != 0.0 } ?: false
    val apart = remember(phone, me) {
        val m = me
        val p = phone
        if (m == null || p == null || !radioSet) null
        else distanceBetween(m.lat, m.lon, p.latitude, p.longitude)
    }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Text("RADIO", style = MaterialTheme.typography.labelSmall,
                         color = MaterialTheme.colorScheme.outline)
                    Text(
                        if (radioSet) "%.5f, %.5f".format(me!!.lat, me!!.lon) else "No position",
                        style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold,
                    )
                    Text(
                        if (radioSet) "What it tells the mesh when it adverts"
                        else "Nothing to advertise, and the map has nowhere to centre",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        }

        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Text("THIS PHONE", style = MaterialTheme.typography.labelSmall,
                         color = MaterialTheme.colorScheme.outline)
                    val p = phone
                    Text(
                        if (p != null) "%.5f, %.5f".format(p.latitude, p.longitude) else "Not read",
                        style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold,
                    )
                    if (p != null) {
                        Text(
                            "± %.0f m · %s".format(p.accuracy, agoMillis(p.time)),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                        )
                    } else {
                        Text(
                            "The app only asks for this when you tap below.",
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = {
                            val granted = ContextCompat.checkSelfPermission(
                                ctx, Manifest.permission.ACCESS_FINE_LOCATION,
                            ) == PackageManager.PERMISSION_GRANTED
                            if (granted) readPhonePosition() else ask.launch(Manifest.permission.ACCESS_FINE_LOCATION)
                        }) { Text(if (phone == null) "Read my position" else "Read again") }

                        phone?.let { p2 ->
                            Button(onClick = {
                                scope.launch {
                                    runCatching { session.setLocation(p2.latitude, p2.longitude) }
                                        .onSuccess { AppState.say("Sent to the radio") }
                                        .onFailure { AppState.say(it.message ?: "failed") }
                                }
                            }) { Text("Give it to the radio") }
                        }
                    }
                }
            }
        }

        if (apart != null) {
            item {
                GlassCard(Modifier.fillMaxWidth()) {
                    Column {
                        Text("APART", style = MaterialTheme.typography.labelSmall,
                             color = MaterialTheme.colorScheme.outline)
                        Text(
                            if (apart < 1000) "%.0f m".format(apart) else "%.1f km".format(apart / 1000),
                            style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold,
                        )
                        Text(
                            if (apart < 50) "The radio is with you"
                            else "The radio's saved position is not where this phone is",
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                        )
                    }
                }
            }
        }

        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Text("Sharing", style = MaterialTheme.typography.titleSmall)
                    Text(
                        when (me?.advertLocPolicy) {
                            0 -> "Position is not included in adverts."
                            else -> "Position goes out with adverts, so others can map this node."
                        },
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        }
    }
}

/** Great-circle distance in metres. */
private fun distanceBetween(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val r = 6371000.0
    val p = Math.PI / 180
    val a = 0.5 - Math.cos((lat2 - lat1) * p) / 2 +
        Math.cos(lat1 * p) * Math.cos(lat2 * p) * (1 - Math.cos((lon2 - lon1) * p)) / 2
    return 2 * r * Math.asin(Math.sqrt(a))
}
