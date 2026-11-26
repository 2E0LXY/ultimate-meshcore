package uk.umc.app

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

/** A flashing accent button, shown only while a newer build is published. Tap to download and install it. */
@Composable
fun UpdateChip() {
    val release by Updater.latest.collectAsState()
    if (release == null) return
    val state by Updater.state.collectAsState()
    val context = LocalContext.current
    val transition = rememberInfiniteTransition(label = "update-flash")
    val pulse by transition.animateFloat(
        initialValue = 1f, targetValue = 0.35f,
        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "alpha",
    )
    val working = state is Updater.State.Downloading || state is Updater.State.Ready
    val label = when (val s = state) {
        is Updater.State.Downloading -> "Updating ${s.percent}%"
        is Updater.State.Ready -> "Installing…"
        else -> "Update available"
    }
    Button(
        onClick = { if (!working) Updater.downloadAndInstall(context) },
        modifier = Modifier.height(32.dp).alpha(if (working) 1f else pulse),
        contentPadding = PaddingValues(horizontal = 12.dp),
    ) {
        Text(label, style = MaterialTheme.typography.labelMedium)
    }
}
