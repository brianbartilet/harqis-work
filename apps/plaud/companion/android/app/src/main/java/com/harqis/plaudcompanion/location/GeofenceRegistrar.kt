package com.harqis.plaudcompanion.location

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.ActivityCompat
import com.google.android.gms.location.Geofence
import com.google.android.gms.location.GeofencingRequest
import com.google.android.gms.location.LocationServices
import com.harqis.plaudcompanion.storage.CompanionPreferences

class GeofenceRegistrar(private val context: Context) {
    private val client = LocationServices.getGeofencingClient(context)
    private val pendingIntent by lazy {
        PendingIntent.getBroadcast(
            context,
            4702,
            Intent(context, GeofenceBroadcastReceiver::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
        )
    }

    fun apply(preferences: CompanionPreferences, callback: (String) -> Unit) {
        if (!preferences.geofenceEnabled) {
            client.removeGeofences(pendingIntent)
                .addOnCompleteListener { callback("Location trigger disabled.") }
            return
        }
        if (ActivityCompat.checkSelfPermission(
                context,
                Manifest.permission.ACCESS_FINE_LOCATION,
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            callback("Location permission is required.")
            return
        }
        val geofence = Geofence.Builder()
            .setRequestId("plaud-record-zone")
            .setCircularRegion(
                preferences.geofenceLatitude,
                preferences.geofenceLongitude,
                preferences.geofenceRadiusMeters.coerceAtLeast(100f),
            )
            .setTransitionTypes(
                Geofence.GEOFENCE_TRANSITION_ENTER or Geofence.GEOFENCE_TRANSITION_EXIT,
            )
            .setLoiteringDelay(60_000)
            .setExpirationDuration(Geofence.NEVER_EXPIRE)
            .build()
        val request = GeofencingRequest.Builder()
            .setInitialTrigger(GeofencingRequest.INITIAL_TRIGGER_ENTER)
            .addGeofence(geofence)
            .build()
        client.addGeofences(request, pendingIntent)
            .addOnSuccessListener { callback("Location trigger armed.") }
            .addOnFailureListener { callback("Location trigger failed: ${it.message}") }
    }
}
