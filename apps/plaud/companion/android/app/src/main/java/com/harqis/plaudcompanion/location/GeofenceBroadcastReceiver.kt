package com.harqis.plaudcompanion.location

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.google.android.gms.location.Geofence
import com.google.android.gms.location.GeofencingEvent
import com.harqis.plaudcompanion.service.PlaudCompanionService

class GeofenceBroadcastReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val event = GeofencingEvent.fromIntent(intent) ?: return
        if (event.hasError()) return
        when (event.geofenceTransition) {
            Geofence.GEOFENCE_TRANSITION_ENTER ->
                PlaudCompanionService.setTrigger(context, "location", true)
            Geofence.GEOFENCE_TRANSITION_EXIT ->
                PlaudCompanionService.setTrigger(context, "location", false)
        }
    }
}
