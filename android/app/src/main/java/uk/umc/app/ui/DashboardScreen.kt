package uk.umc.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import uk.umc.app.AppState
import uk.umc.app.link.LinkKind
import uk.umc.app.link.LinkState

private fun upText(secs: Long): String {
    val d = secs / 86400
    val h = secs % 86400 / 3600
    val m = secs % 3600 / 60
    val s = secs % 60
    return if (d > 0) "${d}d ${h}h ${m}m" else "%d:%02d:%02d".format(h, m, s)
}

private fun levelColour(v: Double?, good: Double, warn: Double, higherIsBetter: Boolean = true): Color = when {
    v == null -> Dc.mu
    higherIsBetter -> if (v >= good) Dc.g else if (v >= warn) Dc.am else Dc.rd
    else -> if (v <= good) Dc.g else if (v <= warn) Dc.am else Dc.rd
}

private fun dashAgo(secs: Long): String = when {
    secs < 120 -> "${secs}s ago"
    secs < 7200 -> "${secs / 60} min ago"
    secs < 172800 -> "${secs / 3600} h ago"
    else -> "${secs / 86400} days ago"
}

/**
 * The radio at a glance, drawn from what the radio reports: a card for each number that matters
 * with its trend, charts of the last hour, six dials, a picture of what moves where, the links
 * that are up, and what has just been heard. The history is kept on the phone, one reading a
 * minute, because the radio keeps counters rather than a time series.
 */
/** Everything the dashboard draws, as plain values, so it can be drawn (and tested) without a radio. */
data class DashInput(
    val me: uk.umc.app.proto.SelfInfo?,
    val device: uk.umc.app.proto.DeviceInfo?,
    val contacts: List<uk.umc.app.proto.Contact>,
    val channels: List<uk.umc.app.proto.Channel>,
    val messages: List<uk.umc.app.proto.ChatMessage>,
    val stats: uk.umc.app.proto.RadioStats?,
    val heard: List<uk.umc.app.proto.HeardPacket>,
    val rows: List<DashSample>,
    val storage: Pair<Long, Long>?,
    val target: uk.umc.app.link.LinkTarget?,
    val linkState: LinkState,
    val nowMs: Long,
)

@Composable
fun DashboardScreen(onOpen: (String) -> Unit) {
    val s by AppState.session.collectAsState()
    val session = s ?: return NotConnected()
    val device by session.device.collectAsState()
    val me by session.self.collectAsState()
    val contacts by session.contacts.collectAsState()
    val channels by session.channels.collectAsState()
    val messages by session.messages.collectAsState()
    val stats by session.radioStats.collectAsState()
    val heard by session.heard.collectAsState()
    val rows by DashHistory.samples.collectAsState()
    val storage by DashHistory.storage.collectAsState()
    val target by AppState.target.collectAsState()
    val linkState by AppState.linkState.collectAsState()
    val scope = rememberCoroutineScope()
    var range by remember { mutableStateOf(3600L) }
    var tick by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(session) { runCatching { DashHistory.sample(session) } }
    LaunchedEffect(session) { while (true) { delay(1000); tick = System.currentTimeMillis() } }
    DashboardContent(
        DashInput(me, device, contacts, channels, messages, stats, heard, rows, storage, target, linkState, tick),
        range, { range = it }, onOpen,
    ) { flood ->
        scope.launch {
            runCatching { session.advert(flood) }
                .onSuccess { AppState.say(if (flood) "Flood advert sent" else "Advert sent") }
                .onFailure { AppState.say(it.message ?: "failed") }
        }
    }
}

@Composable
fun DashboardContent(d: DashInput, range: Long, setRange: (Long) -> Unit, onOpen: (String) -> Unit, onAdvert: (Boolean) -> Unit) {
    val me = d.me
    val device = d.device
    val contacts = d.contacts
    val channels = d.channels
    val messages = d.messages
    val stats = d.stats
    val heard = d.heard
    val rows = d.rows
    val storage = d.storage
    val target = d.target
    val linkState = d.linkState
    val tick = d.nowMs
    val now = tick / 1000
    val (win, bucket) = when (range) { 86400L -> 86400L to 900L; 21600L -> 21600L to 300L; else -> 3600L to 60L }
    val rxS = DashMath.series(rows, now, win, bucket, SeriesMode.RATE) { it.rx.toDouble() }
    val txS = DashMath.series(rows, now, win, bucket, SeriesMode.RATE) { it.tx.toDouble() }
    val rxNow = rxS.lastOrNull()?.second ?: 0.0
    val txNow = txS.lastOrNull()?.second ?: 0.0
    val tRx = DashMath.trend(rows, now) { it.rx.toDouble() }
    val tTx = DashMath.trend(rows, now) { it.tx.toDouble() }
    val airTxH = DashMath.total(rows, now - 3600, now) { it.txAir.toDouble() }
    val airRxH = DashMath.total(rows, now - 3600, now) { it.rxAir.toDouble() }
    val airPct = if (airTxH != null && airRxH != null) (airTxH + airRxH) / 36.0 else null
    val batt = rows.lastOrNull { it.battMv > 0 }?.battMv
    val battPct = batt?.let { DashMath.batteryPercent(it) }
    val upSecs = stats?.let { it.upSecs + (now - (rows.lastOrNull()?.t ?: now)).coerceAtLeast(0) }
    val snr = stats?.lastSnr
    val trendText = { t: Trend ->
        val p = t.pct
        when {
            t.cur == null -> "collecting history…" to Dc.mu
            p == null -> "this hour: ${t.cur.toLong()}" to Dc.mu
            else -> "${if (p >= 0) "▲" else "▼"} ${Math.abs(p).toLong()}% vs previous hour" to (if (p >= 0) Dc.g else Dc.am)
        }
    }

    Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Dc.bgGlow, Dc.bg, Dc.bg)))) {
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Row {
                                Text(me?.name ?: "Radio", color = Dc.g, fontSize = 24.sp, fontWeight = FontWeight.Bold)
                                Text(" Dashboard", color = Dc.tx, fontSize = 24.sp, fontWeight = FontWeight.Bold)
                            }
                            Text(
                                listOfNotNull(device?.model, device?.version).joinToString(" · "),
                                color = Dc.mu, fontSize = 12.sp,
                            )
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                        listOf(3600L to "1 h", 21600L to "6 h", 86400L to "24 h").forEach { (v, label) ->
                            val on = range == v
                            Text(
                                label, color = if (on) Color(0xFF06140C) else Dc.mu, fontSize = 12.sp,
                                modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(if (on) Dc.g else Color(0xFF0D2219))
                                    .clickable { setRange(v) }.padding(horizontal = 12.dp, vertical = 5.dp),
                            )
                        }
                        Spacer(Modifier.weight(1f))
                        Text(
                            "● live", color = if (linkState is LinkState.Connected) Dc.g else Dc.am, fontSize = 12.sp,
                            modifier = Modifier.clip(RoundedCornerShape(99.dp)).background(Color(0xFF0D2219)).padding(horizontal = 10.dp, vertical = 4.dp),
                        )
                    }
                }
            }

            item {
                val (rxNote, rxCol) = trendText(tRx)
                val (txNote, txCol) = trendText(tTx)
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        KpiCard(Icons.Filled.South, "Received this hour", tRx.cur?.toLong()?.toString() ?: "${stats?.let { it.recvFlood + it.recvDirect } ?: "—"}",
                            if (tRx.cur == null) "since connecting" else rxNote, rxCol, rxS.takeLast(30).map { it.second }, Dc.g, Modifier.weight(1f).fillMaxHeight())
                        KpiCard(Icons.Filled.North, "Sent this hour", tTx.cur?.toLong()?.toString() ?: "${stats?.let { it.sentFlood + it.sentDirect } ?: "—"}",
                            if (tTx.cur == null) "since connecting" else txNote, txCol, txS.takeLast(30).map { it.second }, Dc.am, Modifier.weight(1f).fillMaxHeight())
                    }
                    Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        KpiCard(Icons.Filled.DonutLarge, "Airtime this hour", airPct?.let { DashMath.fmt(it) + "%" } ?: "—",
                            if (airTxH != null && airRxH != null) "receiving ${DashMath.fmt(airRxH / 36.0)}% · sending ${DashMath.fmt(airTxH / 36.0)}%" else "collecting history…", Dc.mu, modifier = Modifier.weight(1f).fillMaxHeight())
                        KpiCard(Icons.Filled.Group, "Nodes known", contacts.size.toString(),
                            "${contacts.count { it.hops == 0 }} direct · ${contacts.count { it.type == 2 }} repeaters", Dc.mu, modifier = Modifier.weight(1f).fillMaxHeight())
                    }
                    Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        KpiCard(Icons.Filled.Timer, "Uptime", upSecs?.let { upText(it) } ?: "—", "radio running time", Dc.mu, modifier = Modifier.weight(1f).fillMaxHeight())
                        KpiCard(Icons.Filled.BatteryFull, "Battery", batt?.let { "%.2f V".format(it / 1000.0) } ?: "—",
                            battPct?.let { "about $it% full" } ?: "no reading", if ((battPct ?: 100) < 25) Dc.rd else Dc.mu, modifier = Modifier.weight(1f).fillMaxHeight())
                    }
                }
            }

            item {
                DashPanel("Traffic", "packets per minute") {
                    AreaChart(listOf(ChartSeries("Received", Dc.g, rxS), ChartSeries("Sent", Dc.am, txS)))
                }
            }
            item {
                DashPanel("Airtime", "share of the last hour") {
                    AirtimeBars(
                        DashMath.series(rows, now, 3600, 120, SeriesMode.PCT) { it.rxAir.toDouble() },
                        DashMath.series(rows, now, 3600, 120, SeriesMode.PCT) { it.txAir.toDouble() },
                    )
                }
            }

            item {
                DashPanel("Dials", "live") {
                    val contactsUsed = device?.maxContacts?.takeIf { it > 0 }?.let { contacts.size * 100.0 / it }
                    val storagePct = storage?.takeIf { it.second > 0 }?.let { it.first * 100.0 / it.second }
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                            DialGauge(battPct?.toDouble(), 0.0, 100.0, "Battery", battPct?.let { "$it%" } ?: "—", batt?.let { "%.2f V".format(it / 1000.0) } ?: "", levelColour(battPct?.toDouble(), 50.0, 25.0))
                            DialGauge(snr, -20.0, 15.0, "Last signal", snr?.let { DashMath.fmt(it) } ?: "—", "SNR dB", levelColour(snr, 5.0, -5.0))
                            DialGauge(airPct, 0.0, 30.0, "Channel busy", airPct?.let { DashMath.fmt(it) + "%" } ?: "—", "airtime", levelColour(airPct, 10.0, 20.0, false))
                        }
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                            DialGauge(stats?.noiseFloor?.toDouble(), -130.0, -70.0, "Noise floor", stats?.noiseFloor?.toString() ?: "—", "dBm", levelColour(stats?.noiseFloor?.toDouble(), -105.0, -95.0, false))
                            DialGauge(contactsUsed, 0.0, 100.0, "Contact list", "${contacts.size}", "of ${device?.maxContacts ?: "?"}", levelColour(contactsUsed, 70.0, 90.0, false))
                            DialGauge(storagePct, 0.0, 100.0, "Storage", storagePct?.let { "${it.toInt()}%" } ?: "—", "radio flash", levelColour(storagePct, 70.0, 90.0, false))
                        }
                    }
                }
            }

            item {
                DashPanel("Data flow", "what moves where, right now") {
                    val up = linkState is LinkState.Connected
                    val repeaters = contacts.count { it.type == 2 }
                    val links = listOf(
                        FlowNode(if (target?.kind == LinkKind.WIFI) "WiFi app" else "Bluetooth app", target?.address?.take(20) ?: "—", up),
                        FlowNode("Mesh nodes", "${contacts.size} known · $repeaters rptr", contacts.isNotEmpty()),
                        FlowNode("Repeating", if (device?.repeatEnabled == true) "this radio relays" else "off", device?.repeatEnabled == true),
                    )
                    FlowDiagram(
                        freq = me?.let { "%.3f".format(it.freqKhz / 1000.0) } ?: "—", name = me?.name ?: "Radio",
                        role = "client", rxPerMin = rxNow, txPerMin = txNow, links = links,
                    )
                }
            }

            item {
                DashPanel("Connections") {
                    val dot = { ok: Boolean, warnIt: Boolean -> if (ok) Dc.g else if (warnIt) Dc.am else Dc.rd }
                    val list = buildList {
                        add(Triple("LoRa radio", me?.let { "%.3f MHz · SF%d · %d kHz".format(it.freqKhz / 1000.0, it.sf, it.bwKhz / 1000) } ?: "—", Dc.g))
                        add(Triple(
                            if (target?.kind == LinkKind.WIFI) "WiFi app link" else "Bluetooth link",
                            when (val st = linkState) { is LinkState.Connected -> "connected"; is LinkState.Connecting -> "connecting"; is LinkState.Failed -> st.reason; else -> "idle" },
                            dot(linkState is LinkState.Connected, linkState is LinkState.Connecting),
                        ))
                        add(Triple("Relaying", if (device?.repeatEnabled == true) "this radio repeats packets" else "client only", dot(device?.repeatEnabled == true, true)))
                        add(Triple("Position", me?.let { if (it.lat != 0.0 || it.lon != 0.0) "%.3f, %.3f".format(it.lat, it.lon) else "not shared" } ?: "—", dot(me?.let { it.lat != 0.0 || it.lon != 0.0 } ?: false, true)))
                        add(Triple("Channels", "${channels.size} of ${device?.maxChannels ?: "?"}", Dc.g))
                        add(Triple("Messages", "${messages.count { !it.outgoing }} received · ${messages.size} kept", Dc.g))
                    }
                    list.forEach { (name, detail, col) ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(9.dp).clip(RoundedCornerShape(5.dp)).background(col))
                            Spacer(Modifier.width(10.dp))
                            Text(name, color = Dc.tx, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                            Spacer(Modifier.weight(1f))
                            Text(detail, color = Dc.mu, fontSize = 12.sp)
                        }
                    }
                }
            }

            item {
                DashPanel("Traffic mix", "last ${heard.size} packets") {
                    val colours = mapOf("ADV" to Dc.g, "GRP" to Dc.bl, "MSG" to Dc.pu, "ACK" to Dc.am, "PATH" to Dc.or, "TRACE" to Color(0xFF5BE3D8), "REQ" to Color(0xFFE977C5), "RSP" to Color(0xFFE977C5))
                    DonutChart(
                        heard.groupingBy { it.kind }.eachCount().entries.sortedByDescending { it.value }.take(6)
                            .map { DonutPart(it.key, it.value.toDouble(), colours[it.key] ?: Dc.mu) },
                        heard.size.toString(), "packets",
                    )
                }
            }
            item {
                DashPanel("Flood and direct", "since the radio started") {
                    val st = stats
                    DonutChart(
                        listOf(
                            DonutPart("Flood received", (st?.recvFlood ?: 0L).toDouble(), Dc.g), DonutPart("Direct received", (st?.recvDirect ?: 0L).toDouble(), Dc.bl),
                            DonutPart("Flood sent", (st?.sentFlood ?: 0L).toDouble(), Dc.am), DonutPart("Direct sent", (st?.sentDirect ?: 0L).toDouble(), Dc.pu),
                        ),
                        ((st?.recvFlood ?: 0L) + (st?.recvDirect ?: 0L) + (st?.sentFlood ?: 0L) + (st?.sentDirect ?: 0L)).toString(), "packets",
                    )
                }
            }
            item {
                DashPanel("Signal", "noise floor and last RSSI, dBm") {
                    AreaChart(
                        listOf(
                            ChartSeries("Noise floor", Dc.or, DashMath.series(rows, now, win, bucket, SeriesMode.AVG) { it.noise.toDouble() }.map { it.first to it.second + 130 }),
                            ChartSeries("Last RSSI", Dc.g, DashMath.series(rows, now, win, bucket, SeriesMode.AVG) { it.rssi.toDouble() }.map { it.first to it.second + 130 }),
                        ),
                        offset = 130.0, unit = " dBm",
                    )
                }
            }

            item {
                DashPanel("Repeaters heard", "most recent adverts first") {
                    val reps = contacts.filter { it.type == 2 }.sortedByDescending { it.lastAdvert }.take(6)
                    if (reps.isEmpty()) EmptyNote("No repeaters heard yet.") else reps.forEach { c ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(c.name.ifEmpty { c.prefix }, color = Dc.tx, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, modifier = Modifier.weight(1f), maxLines = 1)
                            Text(if (c.hops < 0) "route unknown" else if (c.hops == 0) "direct" else "${c.hops} hop${if (c.hops == 1) "" else "s"}", color = Dc.g, fontSize = 12.sp)
                            Spacer(Modifier.width(10.dp))
                            Text(if (c.lastAdvert > 0) dashAgo((now - c.lastAdvert).coerceAtLeast(0)) else "—", color = Dc.mu, fontSize = 12.sp)
                        }
                    }
                }
            }
            item {
                DashPanel("Recent activity", "newest first") {
                    val recent = heard.takeLast(10).reversed()
                    if (recent.isEmpty()) EmptyNote("No packets yet.") else recent.forEach { p ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("RX", color = Dc.g, fontSize = 11.sp, modifier = Modifier.clip(RoundedCornerShape(99.dp)).background(Color(0xFF10301F)).padding(horizontal = 8.dp, vertical = 1.dp))
                            Spacer(Modifier.width(8.dp))
                            Text(p.kind, color = Dc.tx, fontSize = 12.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.width(52.dp))
                            Text(if (p.flood) "flood" else "direct", color = Dc.mu, fontSize = 12.sp, modifier = Modifier.weight(1f).fillMaxHeight())
                            Text("${p.rssi} / ${DashMath.fmt(p.snr)}", color = Dc.mu, fontSize = 12.sp)
                            Spacer(Modifier.width(10.dp))
                            Text("${((tick - p.at) / 1000).coerceAtLeast(0)}s", color = Dc.mu, fontSize = 12.sp)
                        }
                    }
                }
            }

            item { Text("Shortcuts", color = Dc.mu, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp)) }
            item {
                Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    KpiCard(Icons.Filled.Podcasts, "Radio", me?.let { "%.3f".format(it.freqKhz / 1000.0) } ?: "—",
                        me?.let { "SF${it.sf} · ${it.bwKhz / 1000} kHz · CR ${it.cr}" } ?: "", Dc.mu, modifier = Modifier.weight(1f).fillMaxHeight()) { onOpen("radio") }
                    val fix = me?.let { it.lat != 0.0 || it.lon != 0.0 } ?: false
                    KpiCard(Icons.Filled.LocationOn, "Position", if (fix) "Set" else "None",
                        me?.let { if (fix) "%.3f, %.3f".format(it.lat, it.lon) else "not shared" } ?: "", Dc.mu, modifier = Modifier.weight(1f).fillMaxHeight()) { onOpen("map") }
                }
            }
            item {
                Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    KpiCard(Icons.Filled.Group, "Nodes", contacts.size.toString(), "${contacts.count { it.hops == 0 }} direct", Dc.mu, modifier = Modifier.weight(1f).fillMaxHeight()) { onOpen("contacts") }
                    val incoming = messages.count { !it.outgoing }
                    KpiCard(Icons.Filled.Chat, "Messages", incoming.toString(), "${messages.size} kept", Dc.mu, modifier = Modifier.weight(1f).fillMaxHeight()) { onOpen("chats") }
                }
            }
            item { DashAction(Icons.Filled.Campaign, "Send advert", "Let other nodes find this radio") { onAdvert(false) } }
            item { DashAction(Icons.Filled.Sensors, "Flood advert", "Repeaters pass it on across the mesh") { onAdvert(true) } }
            item { DashAction(Icons.Filled.Tune, "Appearance", "Background, cards and delivery marks") { onOpen("look") } }
        }
    }
}

@Composable
private fun DashAction(icon: ImageVector, title: String, blurb: String, onClick: () -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    Row(
        Modifier.fillMaxWidth().clip(shape).background(Brush.verticalGradient(listOf(Dc.card1, Dc.card2))).border(1.dp, Dc.line, shape)
            .clickable { onClick() }.padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, null, tint = Dc.g)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, color = Dc.tx, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
            Text(blurb, color = Dc.mu, fontSize = 12.sp)
        }
        Icon(Icons.Filled.ChevronRight, null, tint = Dc.mu)
    }
}
