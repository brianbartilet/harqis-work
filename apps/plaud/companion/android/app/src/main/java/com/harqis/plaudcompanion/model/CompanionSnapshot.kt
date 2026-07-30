package com.harqis.plaudcompanion.model

import org.json.JSONObject

enum class RecordingState(val wireName: String) {
    UNCONFIGURED("unconfigured"),
    DISCONNECTED("disconnected"),
    CONNECTING("connecting"),
    IDLE("idle"),
    RECORDING("recording"),
    PAUSED("paused"),
    ERROR("error"),
}

data class CompanionSnapshot(
    val state: RecordingState = RecordingState.UNCONFIGURED,
    val connected: Boolean = false,
    val sessionId: Long? = null,
    val batteryPercent: Int? = null,
    val activeTriggers: Set<String> = emptySet(),
    val detail: String = "Configure the PLAUD SDK and controller phone.",
    val updatedAt: Long = System.currentTimeMillis(),
) {
    fun toJson(success: Boolean = true, commandAccepted: Boolean? = null): String =
        JSONObject()
            .put("success", success)
            .put("state", state.wireName)
            .put("connected", connected)
            .put("session_id", sessionId)
            .put("battery_percent", batteryPercent)
            .put("active_triggers", activeTriggers.sorted())
            .put("detail", detail)
            .put("updated_at", updatedAt)
            .apply {
                if (commandAccepted != null) put("command_accepted", commandAccepted)
            }
            .toString()
}
