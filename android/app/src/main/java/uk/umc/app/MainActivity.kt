package uk.umc.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import com.composables.icons.lucide.Lucide
import com.composables.icons.lucide.Menu
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import uk.umc.app.link.LinkState
import uk.umc.app.ui.*

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        AppState.init(this)
        uk.umc.app.net.UmcNet.init(this)
        uk.umc.app.tools.OfflineMaps.init(this)
        uk.umc.app.tools.GeoAlerts.init(this)
        createNotificationChannel()
        Updater.start(this)
        setContent { UmcApp() }
    }

    override fun onStop() {
        super.onStop()
        uk.umc.app.net.UmcNet.flush()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(
                NotificationChannel("messages", "Mesh messages", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "New messages from the mesh"
                },
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Suppress("DEPRECATION")
@Composable
fun UmcApp() {
    // Both UMC themes are dark and the choice is the app's own (Look > Appearance), not the phone's light/dark setting.
    // UmcThemeState is snapshot state, so changing it recomposes everything at once.
    ShadTheme(UmcThemeState.id) {
        val palette = LocalUmcPalette.current
        val view = LocalView.current
        // light icons on the dark bars, and bar colours that match the top and bottom of the app
        SideEffect {
            val window = (view.context as? android.app.Activity)?.window ?: return@SideEffect
            window.statusBarColor = palette.mainTop.toArgb()
            window.navigationBarColor = palette.mainBottom.toArgb()
            val bars = WindowCompat.getInsetsController(window, view)
            bars.isAppearanceLightStatusBars = false
            bars.isAppearanceLightNavigationBars = false
        }
        // kept across rotation: where we are, and the open conversation ("ch:<idx>", "c:<prefix>" or "net:<channel>")
        var destName by rememberSaveable { mutableStateOf(Dest.HOME.name) }
        var openChat by rememberSaveable { mutableStateOf<String?>(null) }
        var menuOpen by remember { mutableStateOf(false) }
        val appContext = androidx.compose.ui.platform.LocalContext.current.applicationContext
        val dest = Dest.entries.firstOrNull { it.name == destName } ?: Dest.HOME
        fun go(d: Dest) { destName = d.name; openChat = null }
        val snackbar = remember { SnackbarHostState() }
        val toast by AppState.toast.collectAsState()
        val state by AppState.linkState.collectAsState()
        val session by AppState.session.collectAsState()
        val self by (session?.self ?: remember { kotlinx.coroutines.flow.MutableStateFlow(null) }).collectAsState()
        // text colour for everything under the transparent Scaffold: white over a photo, colour or gradient, else the theme's own
        val ink = if (onGlass()) Color.White else MaterialTheme.colorScheme.onBackground

        // back: a conversation closes to its list, a page returns to Home, Home leaves the app
        BackHandler(enabled = dest != Dest.HOME && openChat == null) { destName = Dest.HOME.name }
        BackHandler(enabled = openChat != null) { openChat = null }

        LaunchedEffect(toast) {
            toast?.let {
                snackbar.showSnackbar(it)
                AppState.toast.value = null
            }
        }

        Backdrop {
        Scaffold(
            containerColor = Color.Transparent,
            contentColor = ink,
            snackbarHost = { SnackbarHost(snackbar) },
            topBar = {
                TopAppBar(
                    title = {
                        Column {
                            Text(self?.name ?: "Ultimate MeshCore App", style = MaterialTheme.typography.titleMedium)
                            Text(
                                when (val s = state) {
                                    is LinkState.Connected -> "connected · ${s.what}"
                                    is LinkState.Connecting -> "connecting…"
                                    is LinkState.Failed -> "not connected · ${s.reason}"
                                    else -> "not connected"
                                },
                                style = MaterialTheme.typography.labelSmall,
                                color = if (onGlass()) ink else palette.muted,
                            )
                        }
                    },
                    actions = {
                        UpdateChip()
                        Box {
                            IconButton(onClick = { menuOpen = true }) { Icon(Lucide.Menu, contentDescription = "Menu") }
                            DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                                Dest.entries.forEach { d ->
                                    // the current place: Overview fills it with the accent, Analytics with a quiet chip
                                    val active = d == dest && openChat == null
                                    DropdownMenuItem(
                                        text = { Text(d.label, color = if (active) palette.navActiveInk else Color.Unspecified) },
                                        leadingIcon = { Icon(d.icon, contentDescription = null, tint = if (active) palette.navActiveInk else LocalContentColor.current) },
                                        onClick = { menuOpen = false; go(d) },
                                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp)
                                            .clip(RoundedCornerShape(palette.radiusSm))
                                            .background(if (active) palette.navActive else Color.Transparent),
                                    )
                                }
                                DropdownMenuItem(
                                    text = { Text("Check for update") },
                                    onClick = { menuOpen = false; Updater.checkNow(appContext) },
                                )
                                DropdownMenuItem(
                                    text = { Text("Build ${BuildConfig.VERSION_NAME}+${BuildConfig.GIT_SHA}", style = MaterialTheme.typography.labelSmall) },
                                    onClick = {},
                                    enabled = false,
                                )
                            }
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = Color.Transparent, scrolledContainerColor = Color.Transparent,
                        titleContentColor = ink, actionIconContentColor = ink, navigationIconContentColor = ink,
                    ),
                )
            },
        ) { padding ->
            Box(Modifier.fillMaxSize().padding(padding)) {
                val chat = openChat
                when {
                    chat != null ->
                        if (chat.startsWith("net:")) NetChannelChat(chat.removePrefix("net:")) { openChat = null }
                        else ChatScreen(chat) { openChat = null }
                    else -> when (dest) {
                        Dest.HOME -> HomeScreen { go(it) }
                        Dest.DASHBOARD -> DashboardScreen { where ->
                            when (where) {
                                "chats" -> go(Dest.CHATS)
                                "contacts" -> go(Dest.CONTACTS)
                                "map" -> go(Dest.MAP)
                                "radio" -> go(Dest.RADIO)
                                "look" -> go(Dest.LOOK)
                            }
                        }
                        Dest.CHATS -> ChatsScreen { openChat = it }
                        Dest.CONTACTS -> ContactsScreen(onMessage = { openChat = it }, onMap = { go(Dest.MAP) })
                        Dest.CHANNELS -> ChannelsScreen()
                        Dest.MAP -> MapScreen()
                        Dest.SPECTRUM -> SpectrumScreen()
                        Dest.GPS -> GpsScreen()
                        Dest.RADIO -> RadioScreen()
                        Dest.DEVICE -> UmcDeviceScreen()
                        Dest.SENSORS -> SensorsScreen()
                        Dest.NET -> UmcNetScreen(onBack = { go(Dest.HOME) }, onMessages = { go(Dest.CHATS) })
                        Dest.RADIOS -> ConnectScreen(onUmcNet = { go(Dest.NET) })
                        Dest.LOOK -> LookScreen()
                        Dest.GEOFENCES -> GeofenceScreen()
                        Dest.BACKUP -> BackupScreen()
                    }
                }
            }
        }
        }
    }
}
