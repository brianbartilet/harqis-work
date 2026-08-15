package com.harqis.plaudcompanion.storage

import android.content.Context

class CompanionPreferences(context: Context) {
    private val store = context.getSharedPreferences("plaud_companion", Context.MODE_PRIVATE)

    var controlToken: String
        get() = store.getString("control_token", "") ?: ""
        set(value) = store.edit().putString("control_token", value.trim()).apply()
    var sdkToken: String
        get() = store.getString("sdk_token", "") ?: ""
        set(value) = store.edit().putString("sdk_token", value.trim()).apply()
    var appKey: String
        get() = store.getString("app_key", "") ?: ""
        set(value) = store.edit().putString("app_key", value.trim()).apply()
    var appSecret: String
        get() = store.getString("app_secret", "") ?: ""
        set(value) = store.edit().putString("app_secret", value.trim()).apply()
    var customDomain: String
        get() = store.getString("custom_domain", "platform-us.plaud.ai") ?: "platform-us.plaud.ai"
        set(value) = store.edit().putString("custom_domain", value.trim()).apply()
    var deviceSerial: String
        get() = store.getString("device_serial", "") ?: ""
        set(value) = store.edit().putString("device_serial", value.trim()).apply()
    var deviceToken: String
        get() = store.getString("device_token", "") ?: ""
        set(value) = store.edit().putString("device_token", value.trim()).apply()
    var scanMatch: String
        get() = store.getString("scan_match", "") ?: ""
        set(value) = store.edit().putString("scan_match", value.trim()).apply()

    var geofenceEnabled: Boolean
        get() = store.getBoolean("geofence_enabled", false)
        set(value) = store.edit().putBoolean("geofence_enabled", value).apply()
    var geofenceLatitude: Double
        get() = store.getString("geofence_latitude", "")?.toDoubleOrNull() ?: 0.0
        set(value) = store.edit().putString("geofence_latitude", value.toString()).apply()
    var geofenceLongitude: Double
        get() = store.getString("geofence_longitude", "")?.toDoubleOrNull() ?: 0.0
        set(value) = store.edit().putString("geofence_longitude", value.toString()).apply()
    var geofenceRadiusMeters: Float
        get() = store.getFloat("geofence_radius", 150f)
        set(value) = store.edit().putFloat("geofence_radius", value).apply()

    val activeTriggers: Set<String>
        get() = store.getStringSet("active_triggers", emptySet())?.toSet() ?: emptySet()

    fun setTriggerActive(source: String, active: Boolean) {
        val updated = activeTriggers.toMutableSet()
        if (active) updated += source else updated -= source
        store.edit().putStringSet("active_triggers", updated).apply()
    }

    val sdkReady: Boolean
        get() = sdkToken.isNotBlank() &&
            appKey.isNotBlank() &&
            appSecret.isNotBlank() &&
            customDomain.isNotBlank() &&
            deviceSerial.isNotBlank() &&
            deviceToken.isNotBlank()
}
