package uk.umc.app.link

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothProfile
import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.util.UUID

/**
 * Bluetooth link to a MeshCore radio: the Nordic UART service every MeshCore companion
 * advertises. Pairing uses the PIN the radio shows on its screen; Android handles that
 * itself once the radio asks for it.
 */
@SuppressLint("MissingPermission")
class BleLink(
    private val context: Context,
    private val address: String,
    private val scope: CoroutineScope,
) : Link {
    companion object {
        val SERVICE: UUID = UUID.fromString("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
        val RX: UUID = UUID.fromString("6e400002-b5a3-f393-e0a9-e50e24dcca9e")   // app -> radio
        val TX: UUID = UUID.fromString("6e400003-b5a3-f393-e0a9-e50e24dcca9e")   // radio -> app
        val CCCD: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        const val NAME_PREFIX = "MeshCore-"
    }

    // replay: the radio can answer before the session has finished subscribing, and a
    // dropped first frame would leave the connection half-started
    override val frames = MutableSharedFlow<ByteArray>(replay = 32, extraBufferCapacity = 64)
    override val state = MutableStateFlow<LinkState>(LinkState.Idle)

    private var gatt: BluetoothGatt? = null
    private var rx: BluetoothGattCharacteristic? = null
    private val writeDone = Channel<Boolean>(Channel.CONFLATED)

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                state.value = LinkState.Connecting("finding services")
                g.requestMtu(247)
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                state.value = LinkState.Failed(if (status == 0) "disconnected" else "Bluetooth error $status")
                close()
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, mtu: Int, status: Int) {
            g.discoverServices()
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            val svc = g.getService(SERVICE)
            if (svc == null) {
                state.value = LinkState.Failed("not a MeshCore radio (no UART service)")
                return
            }
            rx = svc.getCharacteristic(RX)
            val tx = svc.getCharacteristic(TX)
            if (rx == null || tx == null) {
                state.value = LinkState.Failed("radio is missing the expected characteristics")
                return
            }
            g.setCharacteristicNotification(tx, true)
            val cccd = tx.getDescriptor(CCCD)
            if (cccd != null) {
                @Suppress("DEPRECATION")
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
                    g.writeDescriptor(cccd, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
                } else {
                    cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                    g.writeDescriptor(cccd)
                }
            }
            state.value = LinkState.Connected(g.device.name ?: address)
        }

        @Deprecated("Deprecated in Java")
        @Suppress("DEPRECATION")
        override fun onCharacteristicChanged(g: BluetoothGatt, ch: BluetoothGattCharacteristic) {
            val v = ch.value ?: return
            scope.launch { frames.emit(v.copyOf()) }
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, ch: BluetoothGattCharacteristic, value: ByteArray) {
            scope.launch { frames.emit(value.copyOf()) }
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, ch: BluetoothGattCharacteristic, status: Int) {
            writeDone.trySend(status == BluetoothGatt.GATT_SUCCESS)
        }
    }

    override suspend fun connect() {
        val adapter = BluetoothAdapter.getDefaultAdapter()
        if (adapter == null || !adapter.isEnabled) {
            state.value = LinkState.Failed("Bluetooth is off")
            return
        }
        val device: BluetoothDevice = try {
            adapter.getRemoteDevice(address)
        } catch (e: Exception) {
            state.value = LinkState.Failed("bad Bluetooth address")
            return
        }
        state.value = LinkState.Connecting(device.name ?: address)
        gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
    }

    override suspend fun send(frame: ByteArray): Boolean {
        val g = gatt ?: return false
        val c = rx ?: return false
        @Suppress("DEPRECATION")
        val ok = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            g.writeCharacteristic(c, frame, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == BluetoothGatt.GATT_SUCCESS
        } else {
            c.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            c.value = frame
            g.writeCharacteristic(c)
        }
        if (!ok) return false
        return withTimeoutOrNull(4000) { writeDone.receive() } ?: false
    }

    override fun close() {
        try { gatt?.close() } catch (_: Exception) {}
        gatt = null
        rx = null
    }
}
