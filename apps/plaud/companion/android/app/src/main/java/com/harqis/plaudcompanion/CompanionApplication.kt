package com.harqis.plaudcompanion

import android.app.Application
import com.harqis.plaudcompanion.service.PlaudCompanionService

class CompanionApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        PlaudCompanionService.createNotificationChannel(this)
    }
}
