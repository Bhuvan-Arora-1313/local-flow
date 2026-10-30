package com.localflow.remote

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.InputMethod
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.util.Log
import android.view.KeyEvent
import android.view.View
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.inputmethod.EditorInfo
import androidx.annotation.RequiresApi

/**
 * Focus-watcher + text-injector for the floating bubble.
 *
 * On Android 13+ the service declares flagInputMethodEditor, which gives it
 * its own InputConnection to whatever field currently has input focus --
 * alongside the user's real keyboard, no switching. commitText() through
 * that connection is the same path a keyboard uses, so it works in every
 * text-accepting view: terminal emulators, Samsung Notes' custom editor,
 * and fields whose placeholder text the node-based API misreports as real
 * content. The node-based ACTION_SET_TEXT path below is only a fallback for
 * older Android versions.
 */
class LocalFlowAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "LocalFlowA11y"

        @Volatile
        var instance: LocalFlowAccessibilityService? = null
    }

    private var focusedNode: AccessibilityNodeInfo? = null
    // a text field holds input focus: between onStartInput and onFinishInput
    @Volatile private var inputActive = false

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
    }

    override fun onDestroy() {
        instance = null
        super.onDestroy()
    }

    override fun onInterrupt() {}

    @RequiresApi(Build.VERSION_CODES.TIRAMISU)
    override fun onCreateInputMethod(): InputMethod = object : InputMethod(this) {
        override fun onStartInput(attribute: EditorInfo, restarting: Boolean) {
            super.onStartInput(attribute, restarting)
            // Screens with no text field still open a placeholder input
            // session (seen on the Samsung home screen): no text type and no
            // view behind it (fieldId -1), and it stays open the whole time
            // you're there. A terminal also has no text type but is a real
            // view, so it still counts.
            inputActive = attribute.inputType != InputType.TYPE_NULL ||
                (attribute.fieldId != View.NO_ID && attribute.fieldId != 0)
            updateBubble()
        }

        override fun onFinishInput() {
            super.onFinishInput()
            inputActive = false
            updateBubble()
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // TYPE_VIEW_FOCUSED's own source is ground truth that THIS node just
        // became focused -- some OEM text widgets (seen on Samsung Notes)
        // never report isFocused()==true when the tree is re-queried later.
        val eventNode = if (event?.eventType == AccessibilityEvent.TYPE_VIEW_FOCUSED) {
            event.source?.takeIf { it.isEditable }
        } else null
        focusedNode = eventNode ?: rootInActiveWindow?.let { findFocused(it) }
        updateBubble()
    }

    /**
     * The island shows while a text field is active -- whether or not the
     * keyboard is currently up. On Android 13+ that's exactly the window
     * between onStartInput and onFinishInput (verified on-device: leaving a
     * field or app always finishes input; lowering the keyboard doesn't).
     * The node-based check is only a fallback for older Android versions:
     * focus nodes can go stale and keep the island up with no field.
     */
    fun hasFocusedField(): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) inputActive
        else focusedNode != null

    private val handler = Handler(Looper.getMainLooper())
    private var showPending = false
    private val showIfStillActive = Runnable {
        showPending = false
        if (hasFocusedField()) DictationOverlayService.instance?.showBubble()
    }

    // Hide immediately, but only show once a field has stayed active for a
    // moment: some screens (the home launcher) report a momentary input
    // start that finishes again within milliseconds, which would otherwise
    // flash the island.
    // (the timer isn't restarted by further events, so a screen that updates
    // constantly, like a terminal printing output, still shows the island)
    private fun updateBubble() {
        if (hasFocusedField()) {
            if (!showPending) {
                showPending = true
                handler.postDelayed(showIfStillActive, 150)
            }
        } else {
            handler.removeCallbacks(showIfStillActive)
            showPending = false
            DictationOverlayService.instance?.hideBubble()
        }
    }

    private fun findFocused(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (node.isFocused && node.isEditable) return node
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            findFocused(child)?.let { return it }
        }
        return null
    }

    /** Returns true if the text landed in the focused field. */
    fun insertText(text: String): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val ic = inputMethod?.currentInputConnection
            Log.d(TAG, "insertText via InputConnection, available=${ic != null}")
            if (ic != null) {
                ic.commitText(text, 1, null)
                return true
            }
        }
        return insertViaNode(text)
    }

    /**
     * What a keyboard's Enter key does: trigger the field's own action if it
     * declares one (Search, Send, Go...), otherwise send a real Enter key
     * press -- which is what a terminal like Termux needs to run the line.
     */
    fun pressEnter(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return false
        val im = inputMethod ?: return false
        val ic = im.currentInputConnection ?: return false
        val info = im.currentInputEditorInfo
        val action = (info?.imeOptions ?: 0) and EditorInfo.IME_MASK_ACTION
        val noEnterAction = ((info?.imeOptions ?: 0) and EditorInfo.IME_FLAG_NO_ENTER_ACTION) != 0
        if (!noEnterAction && action != EditorInfo.IME_ACTION_NONE &&
            action != EditorInfo.IME_ACTION_UNSPECIFIED
        ) {
            ic.performEditorAction(action)
        } else {
            ic.sendKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_ENTER))
            ic.sendKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_ENTER))
        }
        return true
    }

    // ---------- pre-Android-13 fallback ----------

    private fun insertViaNode(text: String): Boolean {
        val node = focusedNode ?: return fallbackClipboard(text)
        // The node captured at focus time can go stale during the seconds
        // the recording + network round-trip take; refresh() re-syncs it.
        if (!node.refresh()) return fallbackClipboard(text)
        // Some apps put their placeholder straight into text without
        // flagging it, and/or report no usable selection (-1, -1) -- with
        // no trustworthy signal, replace the field rather than append onto
        // what may be placeholder text.
        val rawText = node.text?.toString()
        val hintText = node.hintText?.toString()
        val isHint = node.isShowingHintText || (hintText != null && rawText == hintText)
        val rawStart = node.textSelectionStart
        val rawEnd = node.textSelectionEnd
        val combined = if (isHint || rawStart < 0 || rawEnd < 0) {
            text
        } else {
            val existing = rawText.orEmpty()
            val lo = minOf(rawStart, rawEnd).coerceIn(0, existing.length)
            val hi = maxOf(rawStart, rawEnd).coerceIn(0, existing.length)
            existing.substring(0, lo) + text + existing.substring(hi)
        }
        val args = Bundle()
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, combined)
        if (node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) return true
        return fallbackClipboard(text)
    }

    private fun fallbackClipboard(text: String): Boolean {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("LocalFlow dictation", text))
        val node = focusedNode ?: return false
        return node.performAction(AccessibilityNodeInfo.ACTION_PASTE)
    }
}
