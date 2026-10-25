package uk.umc.app.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.text.DateFormat
import java.util.Date
import kotlin.math.abs
import kotlin.math.roundToInt

/** The dashboard's own dark-green palette, used on every dashboard panel whatever the app theme is. */
object Dc {
    val bg = Color(0xFF07100D)
    val bgGlow = Color(0xFF10301F)
    val card1 = Color(0xFF0E1F19)
    val card2 = Color(0xFF0B1814)
    val line = Color(0xFF1B3A30)
    val grid = Color(0xFF17342A)
    val track = Color(0xFF143027)
    val g = Color(0xFF2FE27A)
    val g2 = Color(0xFF8DFFB0)
    val tx = Color(0xFFE9F7EF)
    val mu = Color(0xFF7FA392)
    val am = Color(0xFFF2C14E)
    val bl = Color(0xFF4AA8FF)
    val pu = Color(0xFFA58BFF)
    val rd = Color(0xFFFF5D6C)
    val or = Color(0xFFFF8F5A)
    val iconBox = Color(0xFF0F3A28)
}

/** False in tests, so the screen can go idle and be captured; true on a phone. */
val LocalDashAnimate = androidx.compose.runtime.compositionLocalOf { true }

data class ChartSeries(val name: String, val color: Color, val data: List<Point>)
data class DonutPart(val label: String, val value: Double, val color: Color)
data class FlowNode(val title: String, val sub: String, val ok: Boolean)

private fun hm(t: Double): String = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date((t * 1000).toLong()))

@Composable
fun DashPanel(title: String, note: String = "", modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    Column(
        modifier.fillMaxWidth().clip(shape)
            .background(Brush.verticalGradient(listOf(Dc.card1, Dc.card2)))
            .border(1.dp, Dc.line, shape).padding(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(title, color = Dc.tx, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
            Spacer(Modifier.weight(1f))
            if (note.isNotEmpty()) Text(note, color = Dc.mu, fontSize = 11.sp)
        }
        Spacer(Modifier.height(8.dp))
        content()
    }
}

@Composable
fun EmptyNote(text: String) {
    Box(Modifier.fillMaxWidth().padding(vertical = 26.dp), contentAlignment = Alignment.Center) {
        Text(text, color = Dc.mu, fontSize = 12.sp)
    }
}

@Composable
fun Legend(items: List<Pair<String, Color>>) {
    Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        items.forEach { (name, c) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(9.dp).clip(RoundedCornerShape(3.dp)).background(c))
                Spacer(Modifier.width(5.dp))
                Text(name, color = Dc.mu, fontSize = 11.sp)
            }
        }
    }
}

@Composable
fun KpiCard(
    icon: ImageVector, label: String, value: String, note: String, noteColor: Color = Dc.mu,
    spark: List<Double> = emptyList(), sparkColor: Color = Dc.g, modifier: Modifier = Modifier, onClick: (() -> Unit)? = null,
) {
    val shape = RoundedCornerShape(14.dp)
    Box(
        modifier.clip(shape).background(Brush.verticalGradient(listOf(Dc.card1, Dc.card2))).border(1.dp, Dc.line, shape)
            .let { if (onClick != null) it.clickable { onClick() } else it }.padding(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(38.dp).clip(RoundedCornerShape(11.dp)).background(Dc.iconBox).border(1.dp, Color(0xFF1F6A45), RoundedCornerShape(11.dp)),
                contentAlignment = Alignment.Center,
            ) { Icon(icon, null, tint = Dc.g, modifier = Modifier.size(20.dp)) }
            Spacer(Modifier.width(10.dp))
            Column {
                Text(label, color = Dc.mu, fontSize = 11.sp, maxLines = 1)
                Text(value, color = Dc.tx, fontSize = 22.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                Text(note, color = noteColor, fontSize = 11.sp, maxLines = 2)
            }
        }
        if (spark.size >= 2) Sparkline(spark, sparkColor, Modifier.align(Alignment.BottomEnd).size(52.dp, 20.dp))
    }
}

@Composable
fun Sparkline(values: List<Double>, color: Color, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val mx = values.max()
        val mn = minOf(values.min(), 0.0)
        val span = if (mx - mn == 0.0) 1.0 else mx - mn
        val p = Path()
        values.forEachIndexed { i, v ->
            val x = i.toFloat() / (values.size - 1) * size.width
            val y = (size.height - 3.dp.toPx() - ((v - mn) / span).toFloat() * (size.height - 6.dp.toPx()))
            if (i == 0) p.moveTo(x, y) else p.lineTo(x, y)
        }
        drawPath(p, color.copy(alpha = 0.3f), style = Stroke(5.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
        drawPath(p, color, style = Stroke(1.8f.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
    }
}

/** A line-and-area chart. Touch and drag to read values. [offset] is subtracted from the axis labels. */
@Composable
fun AreaChart(series: List<ChartSeries>, modifier: Modifier = Modifier, height: Dp = 190.dp, unit: String = "", offset: Double = 0.0) {
    val pts = series.flatMap { it.data }
    if (pts.size < 2) {
        EmptyNote("Collecting data. The chart fills in as the app stays connected (one point a minute).")
        return
    }
    var sel by remember { mutableStateOf<Float?>(null) }
    var widthPx by remember { mutableStateOf(1) }
    val x0 = pts.minOf { it.first }
    val x1 = pts.maxOf { it.first }
    val ym = DashMath.niceMax(pts.maxOf { it.second } * 1.05)
    val axis = remember { android.graphics.Paint().apply { color = 0xFF6F9483.toInt(); isAntiAlias = true } }
    val density = androidx.compose.ui.platform.LocalDensity.current
    val lPad = with(density) { 34.dp.toPx() }
    val rPad = with(density) { 8.dp.toPx() }
    Column(modifier) {
        Box(
            Modifier.fillMaxWidth().height(height).onSizeChanged { widthPx = it.width.coerceAtLeast(1) }
                .pointerInput(Unit) {
                    awaitEachGesture {
                        val down = awaitFirstDown()
                        sel = down.position.x
                        do {
                            val ev = awaitPointerEvent()
                            ev.changes.firstOrNull()?.let { sel = it.position.x }
                        } while (ev.changes.any { it.pressed })
                        sel = null
                    }
                },
        ) {
            Canvas(Modifier.fillMaxSize()) {
                val t = 8.dp.toPx()
                val b = 20.dp.toPx()
                val plotW = size.width - lPad - rPad
                val plotH = size.height - t - b
                axis.textSize = 10.sp.toPx()
                fun px(time: Double) = lPad + ((time - x0) / ((x1 - x0).takeIf { it != 0.0 } ?: 1.0)).toFloat() * plotW
                fun py(v: Double) = t + (1f - (v / ym).toFloat()) * plotH
                drawIntoCanvas { c ->
                    for (i in 0..4) {
                        val v = ym * i / 4
                        val y = py(v)
                        drawLine(Dc.grid, Offset(lPad, y), Offset(size.width - rPad, y), 1.dp.toPx())
                        axis.textAlign = android.graphics.Paint.Align.RIGHT
                        c.nativeCanvas.drawText(DashMath.fmt(v - offset), lPad - 4.dp.toPx(), y + 3.dp.toPx(), axis)
                    }
                    for (i in 0..4) {
                        val time = x0 + (x1 - x0) * i / 4
                        axis.textAlign = when (i) { 0 -> android.graphics.Paint.Align.LEFT; 4 -> android.graphics.Paint.Align.RIGHT; else -> android.graphics.Paint.Align.CENTER }
                        c.nativeCanvas.drawText(hm(time), px(time), size.height - 5.dp.toPx(), axis)
                    }
                }
                series.forEach { s ->
                    if (s.data.size < 2) return@forEach
                    val line = Path()
                    s.data.forEachIndexed { i, p -> if (i == 0) line.moveTo(px(p.first), py(p.second)) else line.lineTo(px(p.first), py(p.second)) }
                    val area = Path().apply {
                        addPath(line)
                        lineTo(px(s.data.last().first), py(0.0))
                        lineTo(px(s.data.first().first), py(0.0))
                        close()
                    }
                    drawPath(area, Brush.verticalGradient(listOf(s.color.copy(alpha = 0.40f), Color.Transparent), startY = t, endY = t + plotH))
                    drawPath(line, s.color.copy(alpha = 0.25f), style = Stroke(6.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
                    drawPath(line, s.color, style = Stroke(2.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
                    val last = s.data.last()
                    drawCircle(s.color, 3.5f.dp.toPx(), Offset(px(last.first), py(last.second)))
                }
                sel?.let { x ->
                    val cx = x.coerceIn(lPad, size.width - rPad)
                    drawLine(Dc.g.copy(alpha = 0.6f), Offset(cx, t), Offset(cx, t + plotH), 1.dp.toPx())
                }
            }
            sel?.let { x ->
                val plotW = (widthPx - lPad - rPad).coerceAtLeast(1f)
                val time = x0 + ((x - lPad) / plotW).coerceIn(0f, 1f) * (x1 - x0)
                val lines = series.mapNotNull { s -> s.data.minByOrNull { abs(it.first - time) }?.let { s to it } }
                Column(
                    Modifier.offset { IntOffset((x.roundToInt() - 70).coerceIn(0, (widthPx - 150).coerceAtLeast(0)), 4) }
                        .clip(RoundedCornerShape(8.dp)).background(Color(0xE606130D)).border(1.dp, Dc.g, RoundedCornerShape(8.dp)).padding(horizontal = 8.dp, vertical = 5.dp),
                ) {
                    Text(hm(time), color = Dc.tx, fontSize = 11.sp)
                    lines.forEach { (s, p) -> Text("${s.name}: ${DashMath.fmt(p.second - offset)}$unit", color = s.color, fontSize = 11.sp) }
                }
            }
        }
        Legend(series.map { it.name to it.color })
    }
}

/** Receiving and transmitting airtime, stacked, one bar per bucket. */
@Composable
fun AirtimeBars(rx: List<Point>, tx: List<Point>, modifier: Modifier = Modifier, height: Dp = 150.dp) {
    val map = java.util.TreeMap<Long, DoubleArray>()
    rx.forEach { map[it.first.roundToInt().toLong()] = doubleArrayOf(it.second, 0.0) }
    tx.forEach { p -> val a = map.getOrPut(p.first.roundToInt().toLong()) { doubleArrayOf(0.0, 0.0) }; a[1] = p.second }
    val rows = map.entries.toList()
    if (rows.size < 2) { EmptyNote("Collecting data."); return }
    val ym = DashMath.niceMax(rows.maxOf { it.value[0] + it.value[1] } * 1.1)
    val axis = remember { android.graphics.Paint().apply { color = 0xFF6F9483.toInt(); isAntiAlias = true } }
    val density = androidx.compose.ui.platform.LocalDensity.current
    val lPad = with(density) { 34.dp.toPx() }
    Column(modifier) {
        Canvas(Modifier.fillMaxWidth().height(height)) {
            val t = 8.dp.toPx(); val b = 20.dp.toPx(); val rPad = 8.dp.toPx()
            val plotW = size.width - lPad - rPad; val plotH = size.height - t - b
            axis.textSize = 10.sp.toPx()
            fun py(v: Double) = t + (1f - (v / ym).toFloat()) * plotH
            drawIntoCanvas { c ->
                for (i in 0..4) {
                    val v = ym * i / 4
                    drawLine(Dc.grid, Offset(lPad, py(v)), Offset(size.width - rPad, py(v)), 1.dp.toPx())
                    axis.textAlign = android.graphics.Paint.Align.RIGHT
                    c.nativeCanvas.drawText(DashMath.fmt(v) + "%", lPad - 4.dp.toPx(), py(v) + 3.dp.toPx(), axis)
                }
                for (i in 0..4) {
                    val r = rows[((rows.size - 1) * i / 4.0).roundToInt().coerceIn(0, rows.size - 1)]
                    axis.textAlign = when (i) { 0 -> android.graphics.Paint.Align.LEFT; 4 -> android.graphics.Paint.Align.RIGHT; else -> android.graphics.Paint.Align.CENTER }
                    c.nativeCanvas.drawText(hm(r.key.toDouble()), lPad + plotW * i / 4f, size.height - 5.dp.toPx(), axis)
                }
            }
            val slot = plotW / rows.size
            val bw = (slot - 2.dp.toPx()).coerceAtLeast(2f)
            rows.forEachIndexed { i, r ->
                val x = lPad + i * slot + 1.dp.toPx()
                val both = r.value[0] + r.value[1]
                drawRect(Brush.verticalGradient(listOf(Dc.g2, Color(0xFF1FB85C)), startY = py(both), endY = py(0.0)), Offset(x, py(both)), Size(bw, py(0.0) - py(both)))
                if (r.value[1] > 0) drawRect(Brush.verticalGradient(listOf(Dc.am, Color(0xFFB8861C)), startY = py(r.value[1]), endY = py(0.0)), Offset(x, py(r.value[1])), Size(bw, py(0.0) - py(r.value[1])))
            }
        }
        Legend(listOf("Receiving" to Dc.g, "Transmitting" to Dc.am))
    }
}

/** A glowing dial: a 270 degree arc filled to [value]'s place between [min] and [max]. */
@Composable
fun DialGauge(value: Double?, min: Double, max: Double, label: String, text: String, sub: String, color: Color, modifier: Modifier = Modifier) {
    val target = if (value == null) 0f else ((value - min) / (max - min)).toFloat().coerceIn(0f, 1f)
    val shown by animateFloatAsState(target, tween(700), label = "dial")
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.size(104.dp), contentAlignment = Alignment.Center) {
            Canvas(Modifier.fillMaxSize()) {
                val stroke = 9.dp.toPx()
                val inset = stroke + 3.dp.toPx()
                val box = Size(size.width - inset * 2, size.height - inset * 2)
                drawArc(Dc.track, 135f, 270f, false, Offset(inset, inset), box, style = Stroke(stroke, cap = StrokeCap.Round))
                if (shown > 0.004f) {
                    drawArc(color.copy(alpha = 0.22f), 135f, 270f * shown, false, Offset(inset, inset), box, style = Stroke(stroke * 2f, cap = StrokeCap.Round))
                    drawArc(color, 135f, 270f * shown, false, Offset(inset, inset), box, style = Stroke(stroke, cap = StrokeCap.Round))
                }
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(text, color = Dc.tx, fontSize = 19.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                Text(sub, color = Dc.mu, fontSize = 10.sp, maxLines = 1)
            }
        }
        Text(label, color = Dc.mu, fontSize = 11.sp)
    }
}

/** A ring split into [parts], with the legend beside it. */
@Composable
fun DonutChart(parts: List<DonutPart>, centre: String, sub: String, modifier: Modifier = Modifier) {
    val total = parts.sumOf { it.value }
    if (total <= 0.0) { EmptyNote("Nothing yet."); return }
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(112.dp), contentAlignment = Alignment.Center) {
            Canvas(Modifier.fillMaxSize()) {
                val stroke = 13.dp.toPx()
                val inset = stroke / 2 + 2.dp.toPx()
                val box = Size(size.width - inset * 2, size.height - inset * 2)
                drawArc(Color(0xFF12291F), 0f, 360f, false, Offset(inset, inset), box, style = Stroke(stroke))
                var start = -90f
                parts.filter { it.value > 0 }.forEach { p ->
                    val sweep = (p.value / total * 360.0).toFloat()
                    drawArc(p.color, start, (sweep - 1.5f).coerceAtLeast(0.5f), false, Offset(inset, inset), box, style = Stroke(stroke))
                    start += sweep
                }
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(centre, color = Dc.tx, fontSize = 19.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                Text(sub, color = Dc.mu, fontSize = 10.sp)
            }
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            parts.forEach { p ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(9.dp).clip(RoundedCornerShape(5.dp)).background(p.color))
                    Spacer(Modifier.width(7.dp))
                    Text(p.label, color = Dc.tx, fontSize = 12.sp, modifier = Modifier.weight(1f), maxLines = 1)
                    Text("${p.value.toLong()}", color = Dc.tx, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.width(6.dp))
                    Text("${(p.value / total * 100).roundToInt()}%", color = Dc.mu, fontSize = 11.sp)
                }
            }
        }
    }
}

/**
 * What moves where: the radio on the left, this node in the middle, the links on the right. The
 * lines move only while their link is up, faster the more packets a minute pass.
 */
@Composable
fun FlowDiagram(
    freq: String, name: String, role: String, rxPerMin: Double, txPerMin: Double, links: List<FlowNode>,
    modifier: Modifier = Modifier,
) {
    val paint = remember { android.graphics.Paint().apply { isAntiAlias = true; textAlign = android.graphics.Paint.Align.CENTER } }
    val rate = remember { Pair(rxPerMin, txPerMin) }
    val phase = if (LocalDashAnimate.current) {
        val infinite = rememberInfiniteTransition(label = "flow")
        val moving by infinite.animateFloat(0f, 32f, infiniteRepeatable(tween(900, easing = LinearEasing), RepeatMode.Restart), label = "phase")
        moving
    } else 8f
    val rows = links.size.coerceAtLeast(1)
    val h = (96 + rows * 52).dp
    Canvas(modifier.fillMaxWidth().height(h)) {
        val w = size.width
        val hubX = w * 0.45f; val hubY = size.height / 2
        val leftX = w * 0.11f
        val rightX = w * 0.84f
        fun edge(x1: Float, y1: Float, x2: Float, y2: Float, color: Color, on: Boolean, perMin: Double) {
            val path = Path().apply { moveTo(x1, y1); cubicTo((x1 + x2) / 2, y1, (x1 + x2) / 2, y2, x2, y2) }
            drawPath(path, Color(0xFF1D3D31), style = Stroke(2.2f.dp.toPx(), cap = StrokeCap.Round))
            if (on) {
                val speed = (0.6f + (kotlin.math.log10(1.0 + perMin).toFloat() * 0.7f)).coerceIn(0.6f, 2.6f)
                drawPath(path, color.copy(alpha = 0.25f), style = Stroke(5.dp.toPx(), cap = StrokeCap.Round))
                drawPath(path, color, style = Stroke(2.2f.dp.toPx(), cap = StrokeCap.Round, pathEffect = PathEffect.dashPathEffect(floatArrayOf(7.dp.toPx(), 9.dp.toPx()), -phase * speed * density)))
            }
        }
        fun node(cx: Float, cy: Float, nw: Float, nh: Float, title: String, sub: String, ok: Boolean, hub: Boolean) {
            val tl = Offset(cx - nw / 2, cy - nh / 2)
            if (hub) drawRoundRect(Dc.g.copy(alpha = 0.16f), tl - Offset(4.dp.toPx(), 4.dp.toPx()), Size(nw + 8.dp.toPx(), nh + 8.dp.toPx()), androidx.compose.ui.geometry.CornerRadius(16.dp.toPx()))
            drawRoundRect(if (ok) Color(0xFF0C2018) else Color(0xFF0A1511), tl, Size(nw, nh), androidx.compose.ui.geometry.CornerRadius(12.dp.toPx()))
            drawRoundRect(if (hub) Dc.g else if (ok) Color(0xFF1F6A45) else Color(0xFF2A3A34), tl, Size(nw, nh), androidx.compose.ui.geometry.CornerRadius(12.dp.toPx()), style = Stroke((if (hub) 2f else 1.2f).dp.toPx()))
            drawIntoCanvas { c ->
                paint.color = 0xFFE9F7EF.toInt(); paint.isFakeBoldText = true; paint.textSize = 12.sp.toPx()
                c.nativeCanvas.drawText(if (title.length > 13) title.take(12) + "…" else title, cx, cy - 1.dp.toPx(), paint)
                paint.color = 0xFF7FA392.toInt(); paint.isFakeBoldText = false; paint.textSize = 10.sp.toPx()
                c.nativeCanvas.drawText(if (sub.length > 17) sub.take(16) + "…" else sub, cx, cy + 13.dp.toPx(), paint)
            }
        }
        edge(leftX + 32.dp.toPx(), hubY - 14.dp.toPx(), hubX - 44.dp.toPx(), hubY - 14.dp.toPx(), Dc.g, rate.first > 0 || rxPerMin > 0, rxPerMin)
        edge(hubX - 44.dp.toPx(), hubY + 14.dp.toPx(), leftX + 32.dp.toPx(), hubY + 14.dp.toPx(), Dc.am, txPerMin > 0, txPerMin)
        links.forEachIndexed { i, l ->
            val y = if (links.size == 1) hubY else 34.dp.toPx() + i * ((size.height - 68.dp.toPx()) / (links.size - 1))
            edge(hubX + 44.dp.toPx(), hubY, rightX - 52.dp.toPx(), y, Dc.bl, l.ok, 1.0)
            node(rightX, y, 100.dp.toPx(), 40.dp.toPx(), l.title, l.sub, l.ok, false)
        }
        node(leftX, hubY, 64.dp.toPx(), 52.dp.toPx(), "LoRa", freq, true, false)
        node(hubX, hubY, 88.dp.toPx(), 60.dp.toPx(), name, role, true, true)
        drawIntoCanvas { c ->
            paint.color = 0xFF7FA392.toInt(); paint.isFakeBoldText = false; paint.textSize = 10.sp.toPx()
            c.nativeCanvas.drawText("in ${DashMath.fmt(rxPerMin)}/min", (leftX + hubX) / 2 - 2.dp.toPx(), hubY - 22.dp.toPx(), paint)
            c.nativeCanvas.drawText("out ${DashMath.fmt(txPerMin)}/min", (leftX + hubX) / 2 - 2.dp.toPx(), hubY + 34.dp.toPx(), paint)
        }
    }
}
