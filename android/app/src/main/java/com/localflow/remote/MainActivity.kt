package com.localflow.remote

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.button.MaterialButton
import com.google.android.material.materialswitch.MaterialSwitch
import com.google.android.material.slider.Slider
import com.google.android.material.textfield.TextInputEditText

class MainActivity : AppCompatActivity() {

    private lateinit var hostInput: TextInputEditText
    private lateinit var portInput: TextInputEditText
    private lateinit var tokenInput: TextInputEditText
    private lateinit var testResult: TextView
    private lateinit var statusText: TextView
    private lateinit var enableButton: MaterialButton

    private val micPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()) { granted ->
        toast(if (granted) "Microphone permission granted" else "Microphone permission denied")
    }
    private val notifPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        hostInput = findViewById(R.id.hostInput)
        portInput = findViewById(R.id.portInput)
        tokenInput = findViewById(R.id.tokenInput)
        testResult = findViewById(R.id.testResult)
        statusText = findViewById(R.id.statusText)
        enableButton = findViewById(R.id.enableButton)

        hostInput.setText(Prefs.host(this))
        portInput.setText(Prefs.port(this).toString())
        tokenInput.setText(Prefs.token(this))

        findViewById<MaterialButton>(R.id.testButton).setOnClickListener { testConnection() }
        findViewById<MaterialButton>(R.id.micPermButton).setOnClickListener { requestMic() }
        findViewById<MaterialButton>(R.id.overlayPermButton).setOnClickListener { requestOverlay() }
        findViewById<MaterialButton>(R.id.notifPermButton).setOnClickListener { requestNotifications() }
        findViewById<MaterialButton>(R.id.accessibilityButton).setOnClickListener { openAccessibilitySettings() }
        findViewById<MaterialButton>(R.id.batteryButton).setOnClickListener { requestIgnoreBattery() }
        enableButton.setOnClickListener { toggleDictation() }
        setupIslandSliders()

        if (BuildConfig.FLAVOR == "keyboard") {
            findViewById<View>(R.id.islandOnly).visibility = View.GONE
            findViewById<View>(R.id.keyboardHint).visibility = View.VISIBLE
            findViewById<MaterialButton>(R.id.enableKeyboardButton).apply {
                visibility = View.VISIBLE
                setOnClickListener { startActivity(Intent(Settings.ACTION_INPUT_METHOD_SETTINGS)) }
            }
        }
    }

    private fun setupIslandSliders() {
        val size = findViewById<Slider>(R.id.islandSize)
        val opacity = findViewById<Slider>(R.id.islandOpacity)
        size.value = snap(Prefs.islandScale(this), size)
        opacity.value = snap(Prefs.islandOpacity(this), opacity)
        val listener = Slider.OnChangeListener { _, _, fromUser ->
            if (!fromUser) return@OnChangeListener
            Prefs.saveIslandAppearance(this, size.value, opacity.value)
            DictationOverlayService.instance?.let {
                it.applyAppearance()
                it.preview()
            }
        }
        size.addOnChangeListener(listener)
        opacity.addOnChangeListener(listener)

        val ghost = findViewById<MaterialSwitch>(R.id.ghostSwitch)
        ghost.isChecked = Prefs.ghostText(this)
        ghost.setOnCheckedChangeListener { _, on -> Prefs.saveGhostText(this, on) }
    }

    /** Slider throws if value isn't on its step grid, so round saved values onto it. */
    private fun snap(v: Float, s: Slider): Float {
        val steps = Math.round((v - s.valueFrom) / s.stepSize)
        return (s.valueFrom + steps * s.stepSize).coerceIn(s.valueFrom, s.valueTo)
    }

    override fun onResume() {
        super.onResume()
        updateStatus()
    }

    private fun savePrefs() {
        val host = hostInput.text?.toString()?.trim().orEmpty()
        val port = portInput.text?.toString()?.trim()?.toIntOrNull() ?: 8765
        val token = tokenInput.text?.toString()?.trim().orEmpty()
        Prefs.save(this, host, port, token)
    }

    private fun testConnection() {
        savePrefs()
        val host = Prefs.host(this)
        val port = Prefs.port(this)
        val token = Prefs.token(this)
        testResult.text = "Checking…"
        Thread {
            val result = ApiClient.health(host, port, token)
            runOnUiThread {
                testResult.text = result.fold(
                    onSuccess = { "Connected to $host:$port" },
                    onFailure = { "Couldn't reach $host:$port — ${it.message}" })
            }
        }.start()
    }

    private fun requestMic() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            == PackageManager.PERMISSION_GRANTED
        ) {
            toast("Already granted")
        } else {
            micPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    private fun requestOverlay() {
        if (Settings.canDrawOverlays(this)) {
            toast("Already granted")
            return
        }
        startActivity(Intent(
            Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
    }

    private fun requestNotifications() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED
            ) {
                toast("Already granted")
            } else {
                notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        } else {
            toast("Not needed on this Android version")
        }
    }

    private fun openAccessibilitySettings() {
        startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        toast("Find \"LocalFlow Remote\" in the list and turn it on")
    }

    private fun requestIgnoreBattery() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        if (pm.isIgnoringBatteryOptimizations(packageName)) {
            toast("Already ignoring battery optimizations")
            return
        }
        startActivity(Intent(
            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
    }

    private fun toggleDictation() {
        if (DictationOverlayService.instance != null) {
            startService(Intent(this, DictationOverlayService::class.java)
                .setAction(DictationOverlayService.ACTION_STOP))
            updateStatus()
            return
        }
        savePrefs()
        if (!Settings.canDrawOverlays(this)) {
            toast("Grant the overlay permission first")
            return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            toast("Grant microphone permission first")
            return
        }
        ContextCompat.startForegroundService(this, Intent(this, DictationOverlayService::class.java))
        statusText.postDelayed({ updateStatus() }, 300)
    }

    private fun updateStatus() {
        val running = DictationOverlayService.instance != null
        val accessibilityOn = isAccessibilityServiceEnabled()
        enableButton.text = if (running) getString(R.string.action_disable_dictation)
        else getString(R.string.action_enable_dictation)
        statusText.text = buildString {
            append(if (running) "Dictation service: running\n" else "Dictation service: stopped\n")
            append(if (accessibilityOn) "Accessibility: on" else "Accessibility: off — tap above to enable")
        }
    }

    private fun isAccessibilityServiceEnabled(): Boolean {
        val expected = "$packageName/${LocalFlowAccessibilityService::class.java.canonicalName}"
        val enabled = Settings.Secure.getString(
            contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: return false
        return enabled.split(":").any { it.equals(expected, ignoreCase = true) }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
