package uk.umc.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import uk.umc.app.AppState
import uk.umc.app.proto.HeardPacket

private val good = Color(0xFF2E7D32)
private val warn = Color(0xFFEF6C00)
private val bad = Color(0xFFC62828)

/** A colour per kind of packet, so the chart and the log agree with each other. */
private fun kindColour(kind: String): Color = when (kind) {
    "ADV" -> Color(0xFF8E24AA)
    "MSG" -> Color(0xFF1E88E5)
    "GRP", "GDAT" -> Color(0xFF00897B)
    "ACK" -> Color(0xFF43A047)
    "TRACE" -> Color(0xFFD81B60)
    "PATH" -> Color(0xFF6D4C41)
    "REQ", "RSP", "ANON" -> Color(0xFFF9A825)
    else -> Color(0xFF757575)
}

/**
 * What the channel sounds like: how quiet it is, how busy, and every packet the radio has
 * heard lately whether or not it was meant for us.
 */
@Composable
fun SpectrumScreen() {
    val s by AppState.session.collectAsState()
    val session = s ?: return NotConnected()
    val heard by session.heard.collectAsState()
    val stats by session.radioStats.collectAsState()
    val me by session.self.collectAsState()
    var window by remember { mutableStateOf(5) }        // minutes of history to draw

    // the counters only change slowly, so asking every ten seconds is plenty
    LaunchedEffect(session) {
        while (true) {
            runCatching { session.refreshRadioStats() }
            delay(10_000)
        }
    }

    val cutoff = System.currentTimeMillis() - window * 60_000L
    val recent = heard.filter { it.at >= cutoff }
    val perMinute = if (recent.isEmpty()) 0.0 else recent.size.toDouble() / window
    val airShare = stats?.let { st ->
        if (st.upSecs > 0) (st.txAirSecs + st.rxAirSecs) * 100.0 / st.upSecs else 0.0
    }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Text(
                        me?.let { "%.3f MHz".format(it.freqKhz / 1000.0) } ?: "Channel",
                        style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold,
                    )
                    Text(
                        me?.let { "SF${it.sf} · ${it.bwKhz / 1000} kHz · CR ${it.cr}" } ?: "",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                val floor = stats?.noiseFloor
                Stat(Modifier.weight(1f), "FLOOR", floor?.let { "$it" } ?: "—", "dBm",
                     when { floor == null -> MaterialTheme.colorScheme.outline
                            floor > -95 -> bad
                            floor > -110 -> warn
                            else -> good })
                val last = stats?.lastRssi
                Stat(Modifier.weight(1f), "LAST", last?.let { "$it" } ?: "—", "dBm",
                     MaterialTheme.colorScheme.primary)
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Stat(Modifier.weight(1f), "AIR", airShare?.let { "%.1f%%".format(it) } ?: "—", "of the time",
                     when { airShare == null -> MaterialTheme.colorScheme.outline
                            airShare > 10 -> bad
                            airShare > 3 -> warn
                            else -> good })
                Stat(Modifier.weight(1f), "PACKETS", "%.1f".format(perMinute), "a minute",
                     MaterialTheme.colorScheme.primary)
            }
        }

        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Channel", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                        listOf(1, 5, 30).forEach { m ->
                            Text(
                                "${m}m",
                                Modifier
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(
                                        if (window == m) MaterialTheme.colorScheme.primary.copy(alpha = 0.25f)
                                        else Color.Transparent
                                    )
                                    .clickable { window = m }
                                    .padding(horizontal = 10.dp, vertical = 4.dp),
                                style = MaterialTheme.typography.labelMedium,
                            )
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    ChannelChart(recent, stats?.noiseFloor, window)
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        recent.map { it.kind }.distinct().take(7).forEach { k ->
                            Text(
                                k,
                                Modifier.clip(RoundedCornerShape(6.dp))
                                    .background(kindColour(k).copy(alpha = 0.3f))
                                    .padding(horizontal = 6.dp, vertical = 2.dp),
                                style = MaterialTheme.typography.labelSmall,
                            )
                        }
                    }
                }
            }
        }

        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Text("Traffic", style = MaterialTheme.typography.titleSmall)
                    Spacer(Modifier.height(6.dp))
                    if (recent.isEmpty()) {
                        Text(
                            "Nothing heard in the last $window minutes.",
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                        )
                    } else {
                        recent.reversed().take(40).forEach { p ->
                            Row(Modifier.fillMaxWidth().padding(vertical = 3.dp),
                                verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    p.kind,
                                    Modifier.clip(RoundedCornerShape(6.dp))
                                        .background(kindColour(p.kind).copy(alpha = 0.3f))
                                        .padding(horizontal = 6.dp, vertical = 2.dp),
                                    style = MaterialTheme.typography.labelSmall,
                                )
                                Spacer(Modifier.width(8.dp))
                                Text(if (p.flood) "flood" else "direct", Modifier.weight(1f),
                                     style = MaterialTheme.typography.bodySmall,
                                     color = MaterialTheme.colorScheme.outline)
                                Text("${p.rssi} dBm", style = MaterialTheme.typography.bodySmall)
                                Spacer(Modifier.width(8.dp))
                                Text("%.1f".format(p.snr), style = MaterialTheme.typography.bodySmall,
                                     color = if (p.snr > 5) good else if (p.snr > -5) warn else bad)
                                Spacer(Modifier.width(8.dp))
                                Text(agoMillis(p.at), style = MaterialTheme.typography.labelSmall,
                                     color = MaterialTheme.colorScheme.outline)
                            }
                        }
                    }
                }
            }
        }
    }
}

/** Every packet as a dot: time across, how strongly it was heard up the side. */
@Composable
private fun ChannelChart(packets: List<HeardPacket>, noiseFloor: Int?, windowMinutes: Int) {
    val outline = MaterialTheme.colorScheme.outline
    val primary = MaterialTheme.colorScheme.primary
    Canvas(Modifier.fillMaxWidth().height(140.dp)) {
        val top = -40f                       // the strongest signal worth showing
        val bottom = -130f                   // and the weakest
        fun y(dbm: Float) = size.height * (top - dbm.coerceIn(bottom, top)) / (top - bottom)

        // the grid, every 30 dB
        listOf(-50f, -80f, -110f).forEach { line ->
            drawLine(outline.copy(alpha = 0.25f), Offset(0f, y(line)), Offset(size.width, y(line)), 1f)
        }
        // where the noise sits: anything below this line is lost in it
        noiseFloor?.let { nf ->
            drawLine(
                primary.copy(alpha = 0.6f), Offset(0f, y(nf.toFloat())), Offset(size.width, y(nf.toFloat())),
                2f,
            )
        }
        if (packets.isEmpty()) return@Canvas
        val now = System.currentTimeMillis()
        val span = windowMinutes * 60_000f
        packets.forEach { p ->
            val x = size.width * (1f - (now - p.at) / span).coerceIn(0f, 1f)
            drawCircle(kindColour(p.kind), radius = 4f, center = Offset(x, y(p.rssi.toFloat())))
        }
    }
}

@Composable
private fun Stat(modifier: Modifier, label: String, value: String, unit: String, colour: Color) {
    GlassCard(modifier) {
        Column {
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
            Text(value, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = colour)
            Text(unit, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
        }
    }
}
