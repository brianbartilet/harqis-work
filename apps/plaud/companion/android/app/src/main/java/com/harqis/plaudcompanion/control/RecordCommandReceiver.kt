package com.harqis.plaudcompanion.control

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.harqis.plaudcompanion.service.PlaudCompanionService
import com.harqis.plaudcompanion.storage.CompanionPreferences
import org.json.JSONObject

class RecordCommandReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val preferences = CompanionPreferences(context)
        val supplied = intent.getStringExtra("token").orEmpty()
        if (preferences.controlToken.isBlank() || supplied != preferences.controlToken) {
            resultCode = 2
            resultData = JSONObject()
                .put("success", false)
                .put("error", "unauthorized")
                .toString()
            return
        }

        val action = intent.getStringExtra("action")?.lowercase().orEmpty()
        val serviceAction = when (action) {
            "connect" -> PlaudCompanionService.ACTION_CONNECT
            "start", "stop" -> null
            "pause" -> PlaudCompanionService.ACTION_PAUSE
            "resume" -> PlaudCompanionService.ACTION_RESUME
            "status" -> null
            else -> {
                resultCode = 3
                resultData = JSONObject()
                    .put("success", false)
                    .put("error", "unsupported action")
                    .toString()
                return
            }
        }
        if (action == "start" || action == "stop") {
            PlaudCompanionService.setTrigger(
                context,
                source = "calendar",
                active = action == "start",
            )
        } else if (serviceAction != null) {
            PlaudCompanionService.start(context, serviceAction)
        }
        resultCode = 0
        resultData = PlaudCompanionService.snapshot.get().toJson(
            success = true,
            commandAccepted = serviceAction != null || action == "start" || action == "stop",
        )
    }
}
