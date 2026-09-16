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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.Map
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Tag
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.core.view.WindowCompat
import uk.umc.app.link.LinkState
import uk.umc.app.ui.*

private enum class Tab(val label: String, val icon: ImageVector) {
    CHATS("Messages", Icons.Filled.Chat),
    CONTACTS("Contacts", Icons.Filled.Group),
    CHANNELS("Channels", Icons.Filled.Tag),
    MAP("Map", Icons.Filled.Map),
    RADIO("Radio", Icons.Filled.Settings),
    DEVICE("Device", Icons.Filled.Wifi),
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
    MaterialTheme(colorScheme = if (dark) darkColorScheme() else lightColorScheme()) {
        var tab by remember { mutableStateOf(Tab.CHATS) }
        var openChat by remember { mutableStateOf<String?>(null) }
        var showConnect by remember { mutableStateOf(false) }
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

        Scaffold(
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
                    actions = { TextButton(onClick = { showConnect = true }) { Text("Radios") } },
                )
            },
            bottomBar = {
                NavigationBar {
                    Tab.entries.forEach { t ->
                        NavigationBarItem(
                            selected = tab == t && openChat == null && !showConnect,
                            onClick = { tab = t; openChat = null; showConnect = false },
                            icon = { Icon(t.icon, contentDescription = t.label) },
                            label = { Text(t.label, style = MaterialTheme.typography.labelSmall) },
                        )
                    }
                }
            },
        ) { padding ->
            Box(Modifier.fillMaxSize().padding(padding)) {
                when {
                    showConnect -> ConnectScreen()
                    openChat != null -> ChatScreen(openChat!!) { openChat = null }
                    else -> when (tab) {
                        Tab.CHATS -> ChatsScreen { openChat = it }
                        Tab.CONTACTS -> ContactsScreen(onMessage = { openChat = it }, onMap = { tab = Tab.MAP })
                        Tab.CHANNELS -> ChannelsScreen()
                        Tab.MAP -> MapScreen()
                        Tab.RADIO -> RadioScreen()
                        Tab.DEVICE -> UmcDeviceScreen()
                    }
                }
            }
        }
    }
}
