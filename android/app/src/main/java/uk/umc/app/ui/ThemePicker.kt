package uk.umc.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.composables.icons.lucide.Check
import com.composables.icons.lucide.Lucide
import uk.umc.app.AppState

/** Look > Appearance: the two UMC themes as selectable preview cards. Choosing one applies it to the whole app at once. */
@Composable
fun ThemePicker(modifier: Modifier = Modifier) {
    val current = UmcThemeState.id
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        UmcThemeId.entries.forEach { id ->
            ThemePreviewCard(id, id == current, Modifier.weight(1f)) { AppState.setTheme(id) }
        }
    }
}

/** One theme drawn in its own palette (not the active one): sample nav pill, button, delta pills, chart bars and series dots. */
@Composable
fun ThemePreviewCard(id: UmcThemeId, selected: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val p = UmcPalettes.of(id)
    val shape = RoundedCornerShape(p.radius)
    Column(
        modifier.clip(shape)
            .background(Brush.verticalGradient(listOf(p.mainTop, p.mainBottom)))
            .border(if (selected) 2.dp else 1.dp, if (selected) p.accent else p.border, shape)
            .selectable(selected = selected, role = Role.RadioButton, onClick = onClick)
            .padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(id.label, color = p.ink, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, modifier = Modifier.weight(1f))
            if (selected) Icon(Lucide.Check, "Selected", tint = p.accent, modifier = Modifier.size(16.dp))
        }
        Text(id.blurb, color = p.muted, fontSize = 11.sp, lineHeight = 14.sp)
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(p.radiusSm)).background(p.card)
                .border(1.dp, p.border, RoundedCornerShape(p.radiusSm)).padding(8.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(
                "Home", color = p.navActiveInk, fontSize = 11.sp,
                modifier = Modifier.clip(RoundedCornerShape(p.radiusSm)).background(p.navActive).padding(horizontal = 8.dp, vertical = 3.dp),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.Bottom, modifier = Modifier.height(30.dp)) {
                listOf(14, 22, 18, 30, 12, 26).forEachIndexed { i, h ->
                    Box(Modifier.width(10.dp).height(h.dp).clip(RoundedCornerShape(2.dp)).background(p.series(i)))
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("▲ 4%", color = p.ok, fontSize = 10.sp, modifier = Modifier.clip(RoundedCornerShape(p.radiusPill)).background(p.okBg).padding(horizontal = 6.dp, vertical = 1.dp))
                Text("▼ 2%", color = p.bad, fontSize = 10.sp, modifier = Modifier.clip(RoundedCornerShape(p.radiusPill)).background(p.badBg).padding(horizontal = 6.dp, vertical = 1.dp))
            }
            Box(Modifier.fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)).background(p.track)) {
                Box(Modifier.fillMaxWidth(0.6f).height(4.dp).background(p.series(0)))
            }
            Text(
                "Primary", color = p.accentInk, fontSize = 11.sp,
                modifier = Modifier.clip(RoundedCornerShape(p.radiusSm)).background(p.accent).padding(horizontal = 10.dp, vertical = 4.dp),
            )
        }
    }
}
