package com.harqis.plaudcompanion.plaud

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
import com.harqis.plaudcompanion.model.CompanionSnapshot
import com.harqis.plaudcompanion.model.RecordingState
import com.harqis.plaudcompanion.storage.CompanionPreferences
import sdk.NiceBuildSdk
import sdk.bluetooth.BluetoothManager
import sdk.penblesdk.Constants
import sdk.penblesdk.core.IBleAgent
import sdk.penblesdk.entity.AgentCallback
import sdk.penblesdk.entity.BleDevice
import sdk.penblesdk.entity.BleErrorCode
import sdk.penblesdk.entity.BluetoothStatus
import sdk.penblesdk.entity.bean.ble.response.GetStateRsp
import sdk.penblesdk.entity.bean.ble.response.RecordStartRsp
import sdk.penblesdk.entity.bean.ble.response.RecordStopRsp
import sdk.penblesdk.impl.ble.BleAgentListener

class PlaudSdkBridge(
    private val context: Context,
    private val preferences: CompanionPreferences,
    private val onSnapshot: (CompanionSnapshot) -> Unit,
) : BleAgentListener {
    private val sdk = NiceBuildSdk
    private var manager: BluetoothManager? = null
    private var bleAgent: IBleAgent? = null
    private var snapshot = CompanionSnapshot()

    @SuppressLint("MissingPermission")
    fun initializeAndConnect() {
        if (!hasBluetoothPermissions()) {
            fail("Nearby devices and location permissions are required.")
            return
        }
        if (!preferences.sdkReady) {
            update(
                state = RecordingState.UNCONFIGURED,
                connected = false,
                detail = "Save PLAUD credentials, device serial, and device token.",
            )
            return
        }
        try {
            update(state = RecordingState.CONNECTING, detail = "Initializing PLAUD SDK…")
            sdk.initSdk(
                context.applicationContext,
                preferences.appKey,
                preferences.appSecret,
                this,
                "",
                emptyMap(),
                preferences.customDomain.removePrefix("https://").substringBefore("/"),
                preferences.sdkToken,
            )
            manager = sdk.javaClass
                .getMethod("getBluetoothManager\$libs_release")
                .invoke(sdk) as BluetoothManager
            bleAgent = manager?.let {
                it.javaClass.getDeclaredField("set_buffer_capacity").apply {
                    isAccessible = true
                }.get(it) as IBleAgent
            }
            manager?.onConnectionStateChange = { connected, message ->
                update(
                    state = if (connected) RecordingState.IDLE else RecordingState.DISCONNECTED,
                    connected = connected,
                    detail = message.orEmpty().ifBlank {
                        if (connected) "PLAUD connected." else "PLAUD disconnected."
                    },
                )
                if (connected) refreshState()
            }
            manager?.onRecordingStateChange = { recording, sessionId ->
                update(
                    state = if (recording) RecordingState.RECORDING else RecordingState.IDLE,
                    connected = true,
                    sessionId = if (recording) sessionId else null,
                    detail = if (recording) "Recording on device." else "Recorder is idle.",
                )
            }
            manager?.onBatteryUpdate = { level ->
                update(batteryPercent = level)
            }
            manager?.onScanResult = { device -> handleScanResult(device) }
            manager?.startScan(15_000)
            update(state = RecordingState.CONNECTING, detail = "Scanning for PLAUD…")
        } catch (error: Throwable) {
            fail("SDK initialization failed", error)
        }
    }

    fun startRecording() {
        val agent = requireAgent() ?: return
        agent.startRecord(
            0,
            AgentCallback.OnRequest { accepted ->
                if (!accepted) update(detail = "PLAUD rejected the start request.")
            },
            AgentCallback.OnResponse<RecordStartRsp> { response ->
                update(
                    state = RecordingState.RECORDING,
                    connected = true,
                    sessionId = response?.sessionId,
                    detail = "Recording started.",
                )
            },
            AgentCallback.OnError { error -> fail("Start recording failed: $error") },
        )
    }

    fun stopRecording() {
        val agent = requireAgent() ?: return
        agent.stopRecord(
            0,
            AgentCallback.OnRequest { accepted ->
                if (!accepted) update(detail = "PLAUD rejected the stop request.")
            },
            AgentCallback.OnResponse<RecordStopRsp> {
                update(
                    state = RecordingState.IDLE,
                    connected = true,
                    sessionId = null,
                    detail = "Recording stopped; file remains on the recorder.",
                )
            },
            AgentCallback.OnError { error -> fail("Stop recording failed: $error") },
        )
    }

    fun pauseRecording() {
        val agent = requireAgent() ?: return
        val sessionId = snapshot.sessionId ?: run {
            fail("Cannot pause without an active session.")
            return
        }
        agent.recordPause(
            sessionId,
            0,
            AgentCallback.OnRequest { },
            AgentCallback.OnResponse { update(state = RecordingState.PAUSED, detail = "Recording paused.") },
            AgentCallback.OnError { error -> fail("Pause failed: $error") },
        )
    }

    fun resumeRecording() {
        val agent = requireAgent() ?: return
        val sessionId = snapshot.sessionId ?: run {
            fail("Cannot resume without an active session.")
            return
        }
        agent.recordResume(
            sessionId,
            0,
            AgentCallback.OnRequest { },
            AgentCallback.OnResponse { update(state = RecordingState.RECORDING, detail = "Recording resumed.") },
            AgentCallback.OnError { error -> fail("Resume failed: $error") },
        )
    }

    fun refreshState() {
        manager?.getDeviceState { nullableResponse ->
            val response = nullableResponse ?: return@getDeviceState
            val stateName = response.state.toString().uppercase()
            update(
                state = when {
                    "PAUSE" in stateName -> RecordingState.PAUSED
                    "RECORD" in stateName -> RecordingState.RECORDING
                    else -> RecordingState.IDLE
                },
                connected = true,
                sessionId = response.sessionId.takeIf { it > 0 },
                detail = "Device state refreshed.",
            )
        }
    }

    @SuppressLint("MissingPermission")
    private fun handleScanResult(device: BluetoothDevice) {
        if (!hasBluetoothPermissions()) {
            fail("Bluetooth permission was revoked during scanning.")
            return
        }
        val expected = preferences.scanMatch
        val matches = expected.isBlank() ||
            device.address.equals(expected, ignoreCase = true) ||
            (device.name ?: "").contains(expected, ignoreCase = true)
        if (!matches) return
        manager?.stopScan()
        manager?.connectDevice(
            preferences.deviceSerial,
            preferences.deviceToken,
        ) { connected, message ->
            update(
                state = if (connected) RecordingState.IDLE else RecordingState.ERROR,
                connected = connected,
                detail = message.orEmpty(),
            )
        }
    }

    private fun requireAgent(): IBleAgent? {
        val agent = bleAgent
        if (agent == null || !agent.isConnected) {
            update(
                state = RecordingState.DISCONNECTED,
                connected = false,
                detail = "PLAUD is not connected; run connect first.",
            )
            return null
        }
        return agent
    }

    private fun hasBluetoothPermissions(): Boolean {
        val permissions = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            listOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        } else {
            listOf(Manifest.permission.ACCESS_FINE_LOCATION)
        }
        return permissions.all {
            ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
        }
    }

    private fun update(
        state: RecordingState = snapshot.state,
        connected: Boolean = snapshot.connected,
        sessionId: Long? = snapshot.sessionId,
        batteryPercent: Int? = snapshot.batteryPercent,
        detail: String = snapshot.detail,
    ) {
        snapshot = CompanionSnapshot(
            state = state,
            connected = connected,
            sessionId = sessionId,
            batteryPercent = batteryPercent,
            detail = detail,
        )
        onSnapshot(snapshot)
    }

    private fun fail(message: String, error: Throwable? = null) {
        update(
            state = RecordingState.ERROR,
            detail = if (error == null) message else "$message: ${error.message ?: error.javaClass.simpleName}",
        )
    }

    override fun btStatusChange(serialNumber: String, status: BluetoothStatus) = Unit
    override fun bleConnectFail(serialNumber: String, reason: Constants.ConnectBleFailed) {
        fail("BLE connection failed: $reason")
    }
    override fun scanBleDeviceReceiver(device: BleDevice) = Unit
    override fun scanFail(reason: Constants.ScanFailed) {
        fail("BLE scan failed: $reason")
    }
    override fun handshakeWaitSure(serialNumber: String, timeout: Long) = Unit
    override fun rssiChange(serialNumber: String, rssi: Int) = Unit
    override fun mtuChange(serialNumber: String, mtu: Int, success: Boolean) = Unit
    override fun batteryLevelUpdate(serialNumber: String, level: Int) {
        update(batteryPercent = level)
    }
    override fun chargingStatusChange(serialNumber: String, charging: Boolean) = Unit
    override fun deviceOpRecordStart(serialNumber: String, response: RecordStartRsp) {
        update(
            state = RecordingState.RECORDING,
            connected = true,
            sessionId = response.sessionId,
            detail = "Recording started on PLAUD.",
        )
    }
    override fun deviceOpRecordStop(serialNumber: String, response: RecordStopRsp) {
        update(
            state = RecordingState.IDLE,
            connected = true,
            sessionId = null,
            detail = "Recording stopped on PLAUD.",
        )
    }
    override fun deviceStatusRsp(serialNumber: String, response: GetStateRsp) = Unit
}
