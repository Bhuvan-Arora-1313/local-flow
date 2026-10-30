package com.localflow.remote

import android.content.Context
import android.graphics.Color
import android.inputmethodservice.InputMethodService
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.InputMethodManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

/**
 * LocalFlow as a selectable keyboard (the "keyboard" build flavour): the
 * same island UI inside the keyboard panel, committing text through the
 * keyboard's own InputConnection. Used where an accessibility service can't
 * be installed -- Play Protect blocks sideloading apps that declare one in
 * some regions -- at the cost of switching keyboards to dictate.
 */
class LocalFlowInputMethodService : InputMethodService() {

    private val recorder = AudioRecorder()
    private val mainHandler = Handler(Looper.getMainLooper())
    private var island: IslandView? = null
    private var hint: TextView? = null
    private var jobId = 0

    override fun onCreateInputView(): View {
        val d = resources.displayMetrics.density
        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.rgb(18, 18, 22))
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, (150 * d).toInt())
        }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
        }
        val v = IslandView(this).apply {
            scale = 1.3f
            bandsProvider = { recorder.bands }
            onStart = { start() }
            onCancel = { cancel() }
            onConfirm = { finish(pressEnter = false) }
            onSend = { finish(pressEnter = true) }
        }
        island = v
        column.addView(v)
        hint = TextView(this).apply {
            text = "Tap to dictate"
            setTextColor(Color.argb(140, 255, 255, 255))
            textSize = 12f
            setPadding(0, (10 * d).toInt(), 0, 0)
        }
        column.addView(hint)
        root.addView(column, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER))

        // back to the user's normal keyboard
        root.addView(TextView(this).apply {
            text = "⌨"
            setTextColor(Color.argb(170, 255, 255, 255))
            textSize = 22f
            setPadding((20 * d).toInt(), (16 * d).toInt(), (20 * d).toInt(), (16 * d).toInt())
            setOnClickListener {
                (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager)
                    .showInputMethodPicker()
            }
        }, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM or Gravity.END))
        return root
    }

    override fun onFinishInputView(finishingInput: Boolean) {
        super.onFinishInputView(finishingInput)
        if (recorder.isRecording() || island?.state == IslandState.SENDING) cancel()
    }

    private fun setState(s: IslandState) {
        island?.state = s
        hint?.text = when (s) {
            IslandState.IDLE -> "Tap to dictate"
            IslandState.RECORDING -> "Listening…"
            IslandState.SENDING -> "Transcribing…"
        }
    }

    private fun start() {
        if (recorder.start(this)) {
            setState(IslandState.RECORDING)
        } else {
            toast("Microphone permission needed — open LocalFlow Remote and grant it")
        }
    }

    private fun cancel() {
        jobId++
        if (recorder.isRecording()) recorder.stop()
        setState(IslandState.IDLE)
    }

    private fun finish(pressEnter: Boolean) {
        if (!recorder.isRecording()) return
        val pcm = recorder.stop()
        setState(IslandState.SENDING)
        val job = ++jobId
        Thread { sendAndCommit(pcm, job, pressEnter) }.start()
    }

    private fun sendAndCommit(pcm: ByteArray, job: Int, pressEnter: Boolean) {
        val host = Prefs.host(this)
        val port = Prefs.port(this)
        val token = Prefs.token(this)
        if (host.isBlank() || token.isBlank()) {
            mainHandler.post {
                toast("Set up the Mac's address in LocalFlow Remote first")
                setState(IslandState.IDLE)
            }
            return
        }
        val result = ApiClient.transcribe(host, port, token, pcm)
        mainHandler.post {
            if (job != jobId) return@post   // cancelled while transcribing
            result.onSuccess { text ->
                if (text.isNotBlank()) {
                    currentInputConnection?.commitText(text, 1)
                    // like the Enter key: the field's own action, else a real Enter press
                    if (pressEnter && !sendDefaultEditorAction(true)) {
                        sendDownUpKeyEvents(KeyEvent.KEYCODE_ENTER)
                    }
                } else toast("Heard nothing")
            }.onFailure { e -> toast("Dictation failed: ${e.message}") }
            setState(IslandState.IDLE)
        }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
