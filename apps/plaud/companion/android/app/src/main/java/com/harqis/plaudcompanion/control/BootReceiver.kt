package com.harqis.plaudcompanion.control

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.harqis.plaudcompanion.location.GeofenceRegistrar
import com.harqis.plaudcompanion.service.PlaudCompanionService
import com.harqis.plaudcompanion.storage.CompanionPreferences

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val preferences = CompanionPreferences(context)
        if (!preferences.sdkReady) return
        PlaudCompanionService.start(context, PlaudCompanionService.ACTION_CONNECT)
        if (preferences.geofenceEnabled) {
            GeofenceRegistrar(context).apply(preferences) { }
        }
    }
}
