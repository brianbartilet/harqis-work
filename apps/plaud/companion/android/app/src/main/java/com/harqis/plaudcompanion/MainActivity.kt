package com.harqis.plaudcompanion

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.Switch
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.harqis.plaudcompanion.location.GeofenceRegistrar
import com.harqis.plaudcompanion.service.PlaudCompanionService
import com.harqis.plaudcompanion.storage.CompanionPreferences

class MainActivity : AppCompatActivity() {
    private lateinit var preferences: CompanionPreferences
    private val handler = Handler(Looper.getMainLooper())
    private val refresh = object : Runnable {
        override fun run() {
            renderStatus()
            handler.postDelayed(this, 1_000)
        }
    }
    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { renderStatus() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        preferences = CompanionPreferences(this)
        bindStoredValues()
        bindActions()
        requestRuntimePermissions()
        PlaudCompanionService.start(this)
    }

    override fun onStart() {
        super.onStart()
        handler.post(refresh)
    }

    override fun onStop() {
        handler.removeCallbacks(refresh)
        super.onStop()
    }

    private fun bindStoredValues() {
        field(R.id.controlToken).setText(preferences.controlToken)
        field(R.id.userAccessToken).apply {
            setText(preferences.sdkToken)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        field(R.id.appKey).setText(preferences.appKey)
        field(R.id.appSecret).apply {
            setText(preferences.appSecret)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        field(R.id.customDomain).setText(preferences.customDomain)
        field(R.id.deviceSerial).setText(preferences.deviceSerial)
        field(R.id.deviceToken).setText(preferences.deviceToken)
        field(R.id.scanMatch).setText(preferences.scanMatch)
        findViewById<Switch>(R.id.geofenceEnabled).isChecked = preferences.geofenceEnabled
        field(R.id.geofenceLatitude).setText(preferences.geofenceLatitude.toString())
        field(R.id.geofenceLongitude).setText(preferences.geofenceLongitude.toString())
        field(R.id.geofenceRadius).setText(preferences.geofenceRadiusMeters.toInt().toString())
    }

    private fun bindActions() {
        findViewById<Button>(R.id.saveButton).setOnClickListener {
            preferences.controlToken = field(R.id.controlToken).text.toString()
            preferences.sdkToken = field(R.id.userAccessToken).text.toString()
            preferences.appKey = field(R.id.appKey).text.toString()
            preferences.appSecret = field(R.id.appSecret).text.toString()
            preferences.customDomain = field(R.id.customDomain).text.toString()
            preferences.deviceSerial = field(R.id.deviceSerial).text.toString()
            preferences.deviceToken = field(R.id.deviceToken).text.toString()
            preferences.scanMatch = field(R.id.scanMatch).text.toString()
            preferences.geofenceEnabled = findViewById<Switch>(R.id.geofenceEnabled).isChecked
            preferences.geofenceLatitude =
                field(R.id.geofenceLatitude).text.toString().toDoubleOrNull() ?: 0.0
            preferences.geofenceLongitude =
                field(R.id.geofenceLongitude).text.toString().toDoubleOrNull() ?: 0.0
            preferences.geofenceRadiusMeters =
                field(R.id.geofenceRadius).text.toString().toFloatOrNull() ?: 150f
            GeofenceRegistrar(this).apply(preferences) {
                findViewById<TextView>(R.id.operationDetail).text = it
            }
            PlaudCompanionService.start(this, PlaudCompanionService.ACTION_CONNECT)
        }
        findViewById<Button>(R.id.connectButton).setOnClickListener {
            PlaudCompanionService.start(this, PlaudCompanionService.ACTION_CONNECT)
        }
        findViewById<Button>(R.id.startButton).setOnClickListener {
            PlaudCompanionService.start(this, PlaudCompanionService.ACTION_START)
        }
        findViewById<Button>(R.id.stopButton).setOnClickListener {
            PlaudCompanionService.start(this, PlaudCompanionService.ACTION_STOP)
        }
    }

    private fun requestRuntimePermissions() {
        val wanted = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            wanted += Manifest.permission.BLUETOOTH_SCAN
            wanted += Manifest.permission.BLUETOOTH_CONNECT
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            wanted += Manifest.permission.POST_NOTIFICATIONS
        }
        val missing = wanted.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isNotEmpty()) permissionLauncher.launch(missing.toTypedArray())
    }

    private fun renderStatus() {
        val snapshot = PlaudCompanionService.snapshot.get()
        findViewById<TextView>(R.id.stateValue).text = snapshot.state.wireName.uppercase()
        findViewById<TextView>(R.id.connectionValue).text =
            if (snapshot.connected) "BLE LINKED" else "NO LINK"
        findViewById<TextView>(R.id.batteryValue).text =
            snapshot.batteryPercent?.let { "$it%" } ?: "—"
        findViewById<TextView>(R.id.operationDetail).text = snapshot.detail
    }

    private fun field(id: Int): EditText = findViewById(id)
}
