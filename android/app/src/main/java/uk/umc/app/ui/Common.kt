package uk.umc.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import uk.umc.app.proto.Contact
import java.util.concurrent.TimeUnit

@Composable
fun SectionCard(title: String, subtitle: String? = null, content: @Composable () -> Unit) {
    Card(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp)) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
            content()
        }
    }
}

@Composable
fun KeyValue(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}

fun ago(seconds: Long): String = when {
    seconds < 90 -> "${seconds}s"
    seconds < 5400 -> "${seconds / 60} min"
    seconds < 172800 -> "${seconds / 3600} h"
    else -> "${seconds / 86400} days"
}

fun agoMillis(ms: Long): String = ago(TimeUnit.MILLISECONDS.toSeconds(System.currentTimeMillis() - ms))

fun pathLabel(c: Contact): String = when {
    c.hops < 0 -> "flood (no path)"
    c.hops == 0 -> "direct"
    else -> "${c.hops} hop" + if (c.hops > 1) "s" else ""
}

fun clock(seconds: Long): String {
    val d = java.util.Date(seconds * 1000)
    return java.text.SimpleDateFormat("d MMM HH:mm", java.util.Locale.getDefault()).format(d)
}
