package com.harqis.plaudcompanion.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.harqis.plaudcompanion.MainActivity
import com.harqis.plaudcompanion.R
import com.harqis.plaudcompanion.model.CompanionSnapshot
import com.harqis.plaudcompanion.plaud.PlaudSdkBridge
import com.harqis.plaudcompanion.storage.CompanionPreferences
import java.util.concurrent.atomic.AtomicReference

class PlaudCompanionService : Service() {
    private lateinit var bridge: PlaudSdkBridge
    private lateinit var preferences: CompanionPreferences

    override fun onCreate() {
        super.onCreate()
        startForeground(NOTIFICATION_ID, notification(snapshot.get()))
        preferences = CompanionPreferences(applicationContext)
        bridge = PlaudSdkBridge(
            applicationContext,
            preferences,
        ) { state ->
            val enriched = state.copy(activeTriggers = preferences.activeTriggers)
            snapshot.set(enriched)
            Log.i(LOG_TAG, enriched.toJson())
            getSystemService(NotificationManager::class.java)
                .notify(NOTIFICATION_ID, notification(enriched))
            if (
                enriched.connected &&
                enriched.state == com.harqis.plaudcompanion.model.RecordingState.IDLE &&
                enriched.activeTriggers.isNotEmpty()
            ) {
                bridge.startRecording()
            }
        }
        bridge.initializeAndConnect()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CONNECT -> bridge.initializeAndConnect()
            ACTION_START -> bridge.startRecording()
            ACTION_STOP -> bridge.stopRecording()
            ACTION_PAUSE -> bridge.pauseRecording()
            ACTION_RESUME -> bridge.resumeRecording()
            ACTION_STATUS -> bridge.refreshState()
            ACTION_SET_TRIGGER -> reconcileTrigger(
                source = intent.getStringExtra(EXTRA_SOURCE).orEmpty(),
                active = intent.getBooleanExtra(EXTRA_ACTIVE, false),
            )
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun reconcileTrigger(source: String, active: Boolean) {
        if (source !in setOf("calendar", "location")) {
            Log.w(LOG_TAG, "Ignored unsupported trigger source=$source")
            return
        }
        val hadActiveTrigger = preferences.activeTriggers.isNotEmpty()
        preferences.setTriggerActive(source, active)
        val activeTriggers = preferences.activeTriggers
        snapshot.set(snapshot.get().copy(activeTriggers = activeTriggers))
        when {
            activeTriggers.isNotEmpty() &&
                snapshot.get().state !in setOf(
                    com.harqis.plaudcompanion.model.RecordingState.RECORDING,
                    com.harqis.plaudcompanion.model.RecordingState.PAUSED,
                ) -> bridge.startRecording()
            activeTriggers.isEmpty() && hadActiveTrigger &&
                snapshot.get().state in setOf(
                    com.harqis.plaudcompanion.model.RecordingState.RECORDING,
                    com.harqis.plaudcompanion.model.RecordingState.PAUSED,
                ) -> bridge.stopRecording()
        }
    }

    private fun notification(state: CompanionSnapshot) =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_recorder)
            .setContentTitle("PLAUD · ${state.state.wireName}")
            .setContentText(state.detail)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(
                PendingIntent.getActivity(
                    this,
                    0,
                    Intent(this, MainActivity::class.java),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                ),
            )
            .build()

    companion object {
        const val ACTION_CONNECT = "com.harqis.plaudcompanion.CONNECT"
        const val ACTION_START = "com.harqis.plaudcompanion.START"
        const val ACTION_STOP = "com.harqis.plaudcompanion.STOP"
        const val ACTION_PAUSE = "com.harqis.plaudcompanion.PAUSE"
        const val ACTION_RESUME = "com.harqis.plaudcompanion.RESUME"
        const val ACTION_STATUS = "com.harqis.plaudcompanion.STATUS"
        const val ACTION_SET_TRIGGER = "com.harqis.plaudcompanion.SET_TRIGGER"
        const val EXTRA_SOURCE = "source"
        const val EXTRA_ACTIVE = "active"
        const val LOG_TAG = "HARQIS_PLAUD"
        private const val CHANNEL_ID = "plaud_control"
        private const val NOTIFICATION_ID = 4701

        val snapshot = AtomicReference(CompanionSnapshot())

        fun start(context: Context, action: String = ACTION_CONNECT) {
            val intent = Intent(context, PlaudCompanionService::class.java).setAction(action)
            androidx.core.content.ContextCompat.startForegroundService(context, intent)
        }

        fun setTrigger(context: Context, source: String, active: Boolean) {
            val intent = Intent(context, PlaudCompanionService::class.java)
                .setAction(ACTION_SET_TRIGGER)
                .putExtra(EXTRA_SOURCE, source)
                .putExtra(EXTRA_ACTIVE, active)
            androidx.core.content.ContextCompat.startForegroundService(context, intent)
        }

        fun createNotificationChannel(context: Context) {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "PLAUD device control",
                    NotificationManager.IMPORTANCE_LOW,
                ).apply {
                    description = "Keeps the BLE controller available in the background."
                },
            )
        }
    }
}
