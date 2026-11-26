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
import androidx.compose.ui.graphics.Color
import androidx.core.view.WindowCompat
import uk.umc.app.link.LinkState
import uk.umc.app.ui.*

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        AppState.init(this)
        uk.umc.app.net.UmcNet.init(this)
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
@Composable
fun UmcApp() {
    val dark = androidx.compose.foundation.isSystemInDarkTheme()
    ShadTheme(dark) {
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
                            )
                        }
                    },
                    actions = {
                        UpdateChip()
                        Box {
                            IconButton(onClick = { menuOpen = true }) { Icon(Lucide.Menu, contentDescription = "Menu") }
                            DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                                Dest.entries.forEach { d ->
                                    DropdownMenuItem(
                                        text = { Text(d.label, color = if (d == dest && openChat == null) MaterialTheme.colorScheme.primary else Color.Unspecified) },
                                        leadingIcon = { Icon(d.icon, contentDescription = null) },
                                        onClick = { menuOpen = false; go(d) },
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
                        Dest.NET -> UmcNetScreen(onBack = { go(Dest.HOME) }, onMessages = { go(Dest.CHATS) })
                        Dest.RADIOS -> ConnectScreen(onUmcNet = { go(Dest.NET) })
                        Dest.LOOK -> LookScreen()
                    }
                }
            }
        }
        }
    }
}
