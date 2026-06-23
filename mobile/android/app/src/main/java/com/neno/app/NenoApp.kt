package com.neno.app

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import com.neno.app.data.NenoApi
import com.neno.app.data.NenoRepository
import com.neno.app.data.SettingsStore
import com.neno.app.ui.AppNav
import kotlinx.coroutines.delay

@Composable
fun NenoApp() {
    val context = LocalContext.current.applicationContext
    val settingsStore = remember { SettingsStore(context) }
    val repository = remember { NenoRepository(NenoApi(settingsStore), settingsStore) }

    LaunchedEffect(repository) {
        repository.startRealtime()
        try {
            repository.refreshConnection()
            while (true) {
                delay(30_000)
                repository.refreshConnection()
            }
        } finally {
            repository.stopRealtime()
        }
    }

    AppNav(repository = repository)
}
