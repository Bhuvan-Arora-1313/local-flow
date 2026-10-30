package com.localflow.remote

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import android.widget.Toast

/**
 * Started exactly once, from MainActivity while it's visible -- the one and
 * only moment this app creates a microphone-type foreground service.
 *
 * Why: Android 14's while-in-use restrictions on microphone/camera
 * foreground services only exempt a handful of specific triggers (a system
 * component, an app widget, a notification, a PendingIntent from a
 * different visible app, a device-policy controller, a VoiceInteractionService,
 * or the START_ACTIVITIES_FROM_BACKGROUND permission) -- a tap on a floating
 * overlay drawn by this app, from within some OTHER app, is not on that
 * list. So we never create this service in response to a tap on the island.
 * Instead it's created once while MainActivity is on screen (trivially
 * compliant), and then just stays alive -- with a persistent notification,
 * same model as a VPN or call-recorder app -- until the user stops it. Once
 * it's running, later AudioRecord calls are unaffected by that restriction;
 * it only gates the service's *creation*.
 */
class DictationOverlayService : Service() {

    companion object {
        const val ACTION_STOP = "com.localflow.remote.action.STOP"
        const val CHANNEL_ID = "dictation_active"
        const val NOTIF_ID = 1001

        @Volatile
        var instance: DictationOverlayService? = null
    }

    private lateinit var windowManager: WindowManager
    private var island: IslandView? = null
    private var params: WindowManager.LayoutParams? = null
    private val recorder = AudioRecorder()
    private val mainHandler = Handler(Looper.getMainLooper())
    // bumped by cancel so a transcription that's still in flight is dropped
    private var jobId = 0

    // live preview ("ghost text") above the island -- optional, off by default
    private var ghost: TextView? = null
    private var ghostParams: WindowManager.LayoutParams? = null
    private var previewBusy = false
    private val previewTick = object : Runnable {
        override fun run() = tickPreview(this)
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        startForegroundWithNotification()
        addIsland()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelfCompletely()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        instance = null
        removeIsland()
        super.onDestroy()
    }

    // ---------- notification / foreground ----------
    private fun startForegroundWithNotification() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, "LocalFlow dictation", NotificationManager.IMPORTANCE_LOW)
            nm.createNotificationChannel(channel)
        }
        val stopIntent = Intent(this, DictationOverlayService::class.java).setAction(ACTION_STOP)
        val stopPending = PendingIntent.getService(
            this, 0, stopIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification: Notification = Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("LocalFlow dictation is active")
            .setContentText("Tap the floating island in any text field to dictate. Tap here to stop.")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .setContentIntent(stopPending)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(NOTIF_ID, notification)
        }
    }

    private fun stopSelfCompletely() {
        if (recorder.isRecording()) recorder.stop()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    // ---------- island window ----------
    private fun addIsland() {
        val v = IslandView(this)
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT)
        lp.gravity = Gravity.TOP or Gravity.START
        v.bandsProvider = { recorder.bands }
        v.onDrag = { dx, dy ->
            lp.x += dx.toInt()
            lp.y += dy.toInt()
            relayout()
            if (ghost?.visibility == View.VISIBLE) positionGhost()
        }
        v.onDragEnd = {
            clampToScreen()
            savePosition()
        }
        v.onStart = { startRecording() }
        v.onCancel = { cancel() }
        v.onConfirm = { finishRecording(pressEnter = false) }
        v.onSend = { finishRecording(pressEnter = true) }
        v.visibility = View.GONE
        try {
            windowManager.addView(v, lp)
        } catch (_: Exception) {
            // overlay permission missing or revoked -- keep running as a
            // plain foreground service; the island just won't show.
        }
        island = v
        params = lp
        restorePosition()
        addGhost()
        applyAppearance()
    }

    private fun addGhost() {
        val d = resources.displayMetrics.density
        val tv = TextView(this).apply {
            setTextColor(Color.argb(215, 255, 255, 255))
            textSize = 14f
            maxLines = 3
            setPadding((14 * d).toInt(), (9 * d).toInt(), (14 * d).toInt(), (9 * d).toInt())
            background = GradientDrawable().apply {
                cornerRadius = 14 * d
                setColor(Color.argb(225, 23, 23, 28))
            }
            visibility = View.GONE
        }
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT)
        lp.gravity = Gravity.TOP or Gravity.START
        try {
            windowManager.addView(tv, lp)
        } catch (_: Exception) {
        }
        ghost = tv
        ghostParams = lp
    }

    /** Centres the preview box just above the island, kept on screen. */
    private fun positionGhost() {
        val tv = ghost ?: return
        val glp = ghostParams ?: return
        val v = island ?: return
        val ilp = params ?: return
        val screenW = resources.displayMetrics.widthPixels
        val maxW = (screenW * 0.7f).toInt()
        tv.maxWidth = maxW
        tv.measure(
            View.MeasureSpec.makeMeasureSpec(maxW, View.MeasureSpec.AT_MOST),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED))
        val gap = (8 * resources.displayMetrics.density).toInt()
        val centreX = ilp.x + v.widthFor(v.state) / 2
        glp.x = (centreX - tv.measuredWidth / 2).coerceIn(0, (screenW - tv.measuredWidth).coerceAtLeast(0))
        glp.y = (ilp.y - tv.measuredHeight - gap).coerceAtLeast(0)
        try {
            windowManager.updateViewLayout(tv, glp)
        } catch (_: Exception) {
        }
    }

    private fun showGhost(text: String) {
        val tv = ghost ?: return
        if (text.isBlank()) return
        // keep the newest words in view rather than the start of the sentence
        tv.text = if (text.length > 160) "\u2026" + text.takeLast(160) else text
        tv.visibility = View.VISIBLE
        positionGhost()
    }

    private fun hideGhost() {
        mainHandler.removeCallbacks(previewTick)
        ghost?.visibility = View.GONE
        ghost?.text = ""
    }

    private fun tickPreview(self: Runnable) {
        if (island?.state != IslandState.RECORDING || !recorder.isRecording()) return
        if (!previewBusy) {
            val pcm = recorder.audioSoFar(10)
            if (pcm.size >= AudioRecorder.SAMPLE_RATE) {     // >= 0.5s of audio
                previewBusy = true
                val job = jobId
                Thread {
                    val r = ApiClient.preview(Prefs.host(this), Prefs.port(this), Prefs.token(this), pcm)
                    mainHandler.post {
                        previewBusy = false
                        if (job == jobId && island?.state == IslandState.RECORDING) {
                            r.onSuccess { showGhost(it) }
                        }
                    }
                }.start()
            }
        }
        mainHandler.postDelayed(self, 1000)
    }

    /** Re-reads size/opacity from Prefs; called on start and live from Settings. */
    fun applyAppearance() {
        mainHandler.post {
            val v = island ?: return@post
            v.scale = Prefs.islandScale(this)
            v.alpha = Prefs.islandOpacity(this)
            ghost?.alpha = Prefs.islandOpacity(this)
            relayout()
        }
    }

    private val hidePreview = Runnable {
        if (island?.state == IslandState.IDLE &&
            LocalFlowAccessibilityService.instance?.hasFocusedField() != true
        ) island?.visibility = View.GONE
    }

    /** Shows the island briefly so appearance changes are visible from Settings. */
    fun preview() {
        mainHandler.post {
            island?.visibility = View.VISIBLE
            mainHandler.removeCallbacks(hidePreview)
            mainHandler.postDelayed(hidePreview, 2500)
        }
    }

    private fun relayout() {
        val v = island ?: return
        val lp = params ?: return
        try {
            windowManager.updateViewLayout(v, lp)
        } catch (_: Exception) {
        }
    }

    /** Switches state and grows/shrinks the island around its centre, kept on screen. */
    private fun setState(s: IslandState) {
        val v = island ?: return
        val lp = params ?: return
        if (v.state == s) return
        if (s == IslandState.IDLE) {
            // back to the saved spot -- undoes any shift that was needed to
            // keep the wider recording island on screen near an edge
            v.state = s
            restorePosition()
        } else {
            val oldW = v.widthFor(v.state)
            val newW = v.widthFor(s)
            val (screenW, _) = screenSize()
            lp.x = (lp.x - (newW - oldW) / 2).coerceIn(0, (screenW - newW).coerceAtLeast(0))
            v.state = s
            relayout()
        }
        if (s != IslandState.RECORDING) hideGhost()
    }

    private fun removeIsland() {
        hideGhost()
        ghost?.let {
            try {
                windowManager.removeView(it)
            } catch (_: Exception) {
            }
        }
        ghost = null
        island?.let {
            try {
                windowManager.removeView(it)
            } catch (_: Exception) {
            }
        }
        island = null
    }

    fun showBubble() {
        mainHandler.post {
            clampToScreen()
            island?.visibility = View.VISIBLE
        }
    }

    /**
     * Keeps the island fully on screen. A position saved in one orientation
     * (landscape is wider) can be off the edge in the other, which made the
     * island silently invisible.
     */
    private fun clampToScreen() {
        val v = island ?: return
        val lp = params ?: return
        val (screenW, screenH) = screenSize()
        val w = v.widthFor(v.state)
        val h = (if (v.height > 0) v.height else w / 3)
        val x = lp.x.coerceIn(0, (screenW - w).coerceAtLeast(0))
        val y = lp.y.coerceIn(0, (screenH - h).coerceAtLeast(0))
        if (x != lp.x || y != lp.y) {
            lp.x = x
            lp.y = y
            relayout()
        }
    }

    private fun screenSize(): Pair<Int, Int> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            windowManager.currentWindowMetrics.bounds.let { it.width() to it.height() }
        } else {
            resources.displayMetrics.let { it.widthPixels to it.heightPixels }
        }

    private fun orientationKey(): String {
        val (w, h) = screenSize()
        return if (w > h) "land" else "port"
    }

    /**
     * Landscape and portrait each remember their own spot. Saved spots are
     * for the idle pill; while recording the wider island is re-centred on it.
     */
    private fun restorePosition() {
        val v = island ?: return
        val lp = params ?: return
        val (w, h) = screenSize()
        val idleW = v.widthFor(IslandState.IDLE)
        val key = orientationKey()
        lp.x = Prefs.islandX(this, key, (w - idleW) / 2) - (v.widthFor(v.state) - idleW) / 2
        lp.y = Prefs.islandY(this, key, (h * 0.42f).toInt())
        relayout()
        clampToScreen()
        if (ghost?.visibility == View.VISIBLE) positionGhost()
    }

    private fun savePosition() {
        val v = island ?: return
        val lp = params ?: return
        val idleX = lp.x + (v.widthFor(v.state) - v.widthFor(IslandState.IDLE)) / 2
        Prefs.saveIslandPosition(this, orientationKey(), idleX, lp.y)
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        mainHandler.post { restorePosition() }
    }

    fun hideBubble() {
        mainHandler.post {
            if (island?.state == IslandState.IDLE) island?.visibility = View.GONE
        }
    }

    // ---------- record / send / insert ----------
    private fun startRecording() {
        if (recorder.start(this)) {
            setState(IslandState.RECORDING)
            if (Prefs.ghostText(this)) {
                previewBusy = false
                mainHandler.postDelayed(previewTick, 700)
            }
        } else {
            toast("Microphone permission needed")
        }
    }

    private fun cancel() {
        jobId++
        if (recorder.isRecording()) recorder.stop()
        toIdle()
    }

    private fun finishRecording(pressEnter: Boolean) {
        if (!recorder.isRecording()) return
        val pcm = recorder.stop()
        setState(IslandState.SENDING)
        val job = ++jobId
        Thread { sendAndInsert(pcm, job, pressEnter) }.start()
    }

    private fun sendAndInsert(pcm: ByteArray, job: Int, pressEnter: Boolean) {
        val host = Prefs.host(this)
        val port = Prefs.port(this)
        val token = Prefs.token(this)
        if (host.isBlank() || token.isBlank()) {
            mainHandler.post {
                toast("Set up the Mac's address in LocalFlow Remote first")
                toIdle()
            }
            return
        }
        val result = ApiClient.transcribe(host, port, token, pcm)
        mainHandler.post {
            if (job != jobId) return@post   // cancelled while transcribing
            result.onSuccess { text ->
                if (text.isNotBlank()) {
                    val a11y = LocalFlowAccessibilityService.instance
                    val inserted = a11y?.insertText(text) ?: false
                    if (!inserted) toast("Couldn't insert text -- copied to clipboard instead")
                    else if (pressEnter) a11y?.pressEnter()
                } else {
                    toast("Heard nothing")
                }
            }.onFailure { e ->
                toast("Dictation failed: ${e.message}")
            }
            toIdle()
        }
    }

    private fun toIdle() {
        setState(IslandState.IDLE)
        if (LocalFlowAccessibilityService.instance?.hasFocusedField() != true) {
            hideBubble()
        }
    }

    private fun toast(msg: String) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }
}
