package uk.umc.app.ui

import android.app.Activity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import uk.umc.app.AppState

/** Choose what the app is drawn over, and how much a sent message reports. */
@Composable
fun LookScreen() {
    val kind by AppState.background.collectAsState()
    val chosen by AppState.backgroundColour.collectAsState()
    val show by AppState.ackDisplay.collectAsState()

    val pick = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        if (res.resultCode == Activity.RESULT_OK) {
            res.data?.data?.let { AppState.setBackgroundPhoto(it.toString()) }
        }
    }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Text("Background", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Pages are cards floating over this. A photo is dimmed and blurred so text stays readable.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                    Spacer(Modifier.height(8.dp))
                    Background.entries.forEach { b ->
                        Row(
                            Modifier.fillMaxWidth().clickable {
                                if (b == Background.PHOTO) {
                                    pick.launch(
                                        android.content.Intent(android.content.Intent.ACTION_OPEN_DOCUMENT)
                                            .addCategory(android.content.Intent.CATEGORY_OPENABLE)
                                            .setType("image/*")
                                    )
                                } else {
                                    AppState.setBackground(b)
                                }
                            }.padding(vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(selected = kind == b, onClick = {
                                if (b == Background.PHOTO) {
                                    pick.launch(
                                        android.content.Intent(android.content.Intent.ACTION_OPEN_DOCUMENT)
                                            .addCategory(android.content.Intent.CATEGORY_OPENABLE)
                                            .setType("image/*")
                                    )
                                } else {
                                    AppState.setBackground(b)
                                }
                            })
                            Column {
                                Text(b.label)
                                Text(b.blurb, style = MaterialTheme.typography.bodySmall,
                                     color = MaterialTheme.colorScheme.outline)
                            }
                        }
                    }
                }
            }
        }

        if (kind == Background.COLOUR || kind == Background.GRADIENT) {
            item {
                GlassCard(Modifier.fillMaxWidth()) {
                    Column {
                        Text("Colours", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.height(10.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            backgroundPalette.forEachIndexed { i, (name, pair) ->
                                Box(
                                    Modifier
                                        .size(44.dp)
                                        .clip(CircleShape)
                                        .background(
                                            Brush.linearGradient(
                                                listOf(pair.first, pair.second),
                                                start = Offset.Zero, end = Offset.Infinite,
                                            )
                                        )
                                        .border(
                                            if (chosen == i) 3.dp else 0.dp,
                                            MaterialTheme.colorScheme.primary, CircleShape,
                                        )
                                        .clickable { AppState.setBackgroundColour(i) },
                                )
                            }
                        }
                        Spacer(Modifier.height(6.dp))
                        Text(
                            backgroundPalette.getOrNull(chosen)?.first ?: "",
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                        )
                    }
                }
            }
        }

        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Text("Delivery marks", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Green once the other radio acknowledged it, amber while that is still outstanding, " +
                            "red when no answer came.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline,
                    )
                    Spacer(Modifier.height(8.dp))
                    listOf(
                        "off" to "Nothing",
                        "mark" to "A coloured mark",
                        "count" to "The mark and what happened",
                    ).forEach { (mode, label) ->
                        Row(
                            Modifier.fillMaxWidth().clickable { AppState.setAckDisplay(mode) }.padding(vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(selected = show == mode, onClick = { AppState.setAckDisplay(mode) })
                            Text(label)
                        }
                    }
                }
            }
        }

        item {
            GlassCard(Modifier.fillMaxWidth()) {
                Column {
                    Text("Preview", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(8.dp))
                    Box(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                            .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.18f)).padding(12.dp)
                    ) {
                        Column {
                            Text("Net at 8?", fontWeight = FontWeight.Medium)
                            Text("delivered ✓", style = MaterialTheme.typography.labelSmall,
                                 color = Color(0xFF2E7D32))
                        }
                    }
                }
            }
        }
    }
}
