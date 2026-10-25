package uk.umc.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import com.composables.icons.lucide.Activity
import com.composables.icons.lucide.Hash
import com.composables.icons.lucide.House
import com.composables.icons.lucide.LocateFixed
import com.composables.icons.lucide.Lucide
import com.composables.icons.lucide.Map
import com.composables.icons.lucide.MessageSquare
import com.composables.icons.lucide.Settings
import com.composables.icons.lucide.Users
import com.composables.icons.lucide.Wifi
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import uk.umc.app.link.LinkState
import uk.umc.app.ui.*

private enum class Tab(val label: String, val icon: ImageVector) {
    DASHBOARD("Home", Lucide.House),
    CHATS("Messages", Lucide.MessageSquare),
    CONTACTS("Contacts", Lucide.Users),
    CHANNELS("Channels", Lucide.Hash),
    MAP("Map", Lucide.Map),
    SPECTRUM("Spectrum", Lucide.Activity),
    GPS("GPS", Lucide.LocateFixed),
    RADIO("Radio", Lucide.Settings),
    DEVICE("Device", Lucide.Wifi),
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        AppState.init(this)
        createNotificationChannel()
        setContent { UmcApp() }
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
        var tab by remember { mutableStateOf(Tab.DASHBOARD) }
        var openChat by remember { mutableStateOf<String?>(null) }
        var showConnect by remember { mutableStateOf(false) }
        var showLook by remember { mutableStateOf(false) }
        val snackbar = remember { SnackbarHostState() }
        val toast by AppState.toast.collectAsState()
        val state by AppState.linkState.collectAsState()
        val session by AppState.session.collectAsState()
        val self by (session?.self ?: remember { kotlinx.coroutines.flow.MutableStateFlow(null) }).collectAsState()

        LaunchedEffect(toast) {
            toast?.let {
                snackbar.showSnackbar(it)
                AppState.toast.value = null
            }
        }

        Backdrop {
        Scaffold(
            containerColor = androidx.compose.ui.graphics.Color.Transparent,
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
                    actions = { ShButton(variant = ShVariant.Outline, onClick = { showConnect = true }) { Text("Radios") } },
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                )
            },
            bottomBar = {
                Column {
                ShSeparator()
                NavigationBar(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.94f), tonalElevation = 0.dp) {
                    Tab.entries.forEach { t ->
                        NavigationBarItem(
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = MaterialTheme.colorScheme.primary, selectedTextColor = MaterialTheme.colorScheme.primary,
                                indicatorColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.14f),
                                unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant, unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                            ),
                            selected = tab == t && openChat == null && !showConnect && !showLook,
                            onClick = { tab = t; openChat = null; showConnect = false; showLook = false },
                            icon = { Icon(t.icon, contentDescription = t.label) },
                            label = { Text(t.label, style = MaterialTheme.typography.labelSmall) },
                        )
                    }
                }
                }
            },
        ) { padding ->
            Box(Modifier.fillMaxSize().padding(padding)) {
                when {
                    showConnect -> ConnectScreen()
                    openChat != null -> ChatScreen(openChat!!) { openChat = null }
                    showLook -> LookScreen()
                    else -> when (tab) {
                        Tab.DASHBOARD -> DashboardScreen { where ->
                            when (where) {
                                "chats" -> tab = Tab.CHATS
                                "contacts" -> tab = Tab.CONTACTS
                                "map" -> tab = Tab.MAP
                                "radio" -> tab = Tab.RADIO
                                "look" -> showLook = true
                            }
                        }
                        Tab.CHATS -> ChatsScreen { openChat = it }
                        Tab.CONTACTS -> ContactsScreen(onMessage = { openChat = it }, onMap = { tab = Tab.MAP })
                        Tab.CHANNELS -> ChannelsScreen()
                        Tab.MAP -> MapScreen()
                        Tab.SPECTRUM -> SpectrumScreen()
                        Tab.GPS -> GpsScreen()
                        Tab.RADIO -> RadioScreen()
                        Tab.DEVICE -> UmcDeviceScreen()
                    }
                }
            }
        }
        }
    }
}
