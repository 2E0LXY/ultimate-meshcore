package uk.umc.app.net

import com.hivemq.client.mqtt.MqttGlobalPublishFilter
import com.hivemq.client.mqtt.datatypes.MqttQos
import com.hivemq.client.mqtt.mqtt3.Mqtt3AsyncClient
import com.hivemq.client.mqtt.mqtt3.Mqtt3Client
import com.hivemq.client.mqtt.mqtt3.exceptions.Mqtt3ConnAckException
import com.hivemq.client.mqtt.MqttWebSocketConfig
import java.util.concurrent.TimeUnit

/**
 * One MQTT 3.1.1 connection to the UMC Net broker over WebSocket (wss://host:443/mqtt), with the HiveMQ client.
 * It reconnects by itself with a growing delay (1 s up to 60 s) and subscribes again after every reconnect.
 * [onState] gets short plain-words states; [refused] is true when the broker rejected the login (no point retrying).
 */
class MqttSession(
    private val host: String, private val user: String, private val password: String, private val clientId: String,
    private val subscriptions: List<String>,
    private val onMessage: (topic: String, payload: ByteArray, retained: Boolean) -> Unit,
    private val onState: (state: String, connected: Boolean, refused: Boolean) -> Unit,
    private val onConnected: () -> Unit = {},
) {
    @Volatile private var closed = false
    @Volatile private var retryDelayS = 1L
    private val client: Mqtt3AsyncClient = Mqtt3Client.builder()
        .identifier(clientId)
        .serverHost(host)
        .serverPort(443)
        .sslWithDefaultConfig()
        .webSocketConfig(MqttWebSocketConfig.builder().serverPath("mqtt").build())
        .automaticReconnect().initialDelay(1, TimeUnit.SECONDS).maxDelay(60, TimeUnit.SECONDS).applyAutomaticReconnect()
        .addConnectedListener {
            retryDelayS = 1
            onState("connected", true, false)
            subscribe()
            onConnected()
        }
        .addDisconnectedListener { ctx ->
            if (!closed) onState("disconnected: " + (ctx.cause.message ?: "connection lost") + " (reconnecting)", false, false)
        }
        .buildAsync()

    fun start() {
        client.publishes(MqttGlobalPublishFilter.ALL) { p ->
            onMessage(p.topic.toString(), p.payloadAsBytes, p.isRetain)
        }
        onState("connecting…", false, false)
        connect()
    }

    private fun connect() {
        if (closed) return
        client.connectWith().simpleAuth().username(user).password(password.toByteArray(Charsets.UTF_8)).applySimpleAuth()
            .keepAlive(30).send()
            .whenComplete { _, err ->
                if (err == null || closed) return@whenComplete
                val cause = generateSequence(err) { it.cause }.firstOrNull { it is Mqtt3ConnAckException }
                if (cause != null) { onState("the broker refused this login (${(cause as Mqtt3ConnAckException).mqttMessage.returnCode})", false, true); return@whenComplete }
                // the client only reconnects by itself after it has been connected once, so the first attempts are retried here
                val wait = retryDelayS; retryDelayS = minOf(60, retryDelayS * 2)
                onState("cannot reach $host: ${err.cause?.message ?: err.message} (retrying in ${wait}s)", false, false)
                Thread { try { Thread.sleep(wait * 1000) } catch (e: InterruptedException) { return@Thread }; connect() }.also { it.isDaemon = true }.start()
            }
    }

    private fun subscribe() {
        for (t in subscriptions) client.subscribeWith().topicFilter(t).qos(MqttQos.AT_MOST_ONCE).send()
    }

    /** QoS 0. Reports a failure (not connected, for one) through [onFail]. */
    fun publish(topic: String, payload: ByteArray, onFail: (String) -> Unit = {}) {
        client.publishWith().topic(topic).payload(payload).qos(MqttQos.AT_MOST_ONCE).send()
            .whenComplete { _, err -> if (err != null) onFail(err.message ?: "publish failed") }
    }

    fun close() {
        closed = true
        runCatching { client.disconnect() }
    }
}
