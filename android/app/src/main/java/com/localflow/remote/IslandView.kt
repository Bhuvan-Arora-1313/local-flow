package com.localflow.remote

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.sin

enum class IslandState { IDLE, RECORDING, SENDING }

/**
 * The floating island -- Android twin of the Mac's island.py: a dark pill
 * that sits small while idle, and while dictating expands to
 * [x]  live voice bars  [stop] [send]. Bars are the live frequency spectrum
 * mirrored around the centre, like the Mac version.
 */
class IslandView(context: Context) : View(context) {

    var state = IslandState.IDLE
        set(value) {
            if (field == value) return
            field = value
            if (value == IslandState.RECORDING) disp.fill(0f)
            requestLayout()
            invalidate()
        }

    var bandsProvider: (() -> FloatArray)? = null
    var onStart: (() -> Unit)? = null
    var onCancel: (() -> Unit)? = null
    var onConfirm: (() -> Unit)? = null      // ■ stop and insert
    var onSend: (() -> Unit)? = null         // ↑ insert, then Enter
    var onDrag: ((dx: Float, dy: Float) -> Unit)? = null
    var onDragEnd: (() -> Unit)? = null

    private val d = resources.displayMetrics.density
    private fun dp(v: Float) = v * d * scale

    /** User-set size multiplier (Settings -> Island size). */
    var scale = 1f
        set(value) {
            field = value
            requestLayout()
            invalidate()
        }

    private val bands = AudioRecorder.BANDS
    private val disp = FloatArray(bands * 2)
    private val t0 = SystemClock.uptimeMillis()

    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(240, 23, 23, 28) }
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(1f)
        color = Color.argb(28, 255, 255, 255)
    }
    private val bar = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE }
    private val cancelBg = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(36, 255, 255, 255) }
    private val confirmBg = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE }
    private val glyph = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        strokeWidth = dp(2f)
    }
    private val rect = RectF()

    fun widthFor(s: IslandState): Int = (if (s == IslandState.IDLE) dp(58f) else dp(244f)).toInt()
    private fun heightFor(s: IslandState): Int = (if (s == IslandState.IDLE) dp(34f) else dp(46f)).toInt()

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        setMeasuredDimension(widthFor(state), heightFor(state))
    }

    override fun onDraw(canvas: Canvas) {
        stroke.strokeWidth = dp(1f)
        glyph.strokeWidth = dp(2f)
        val w = width.toFloat()
        val h = height.toFloat()
        rect.set(dp(0.5f), dp(0.5f), w - dp(0.5f), h - dp(0.5f))
        canvas.drawRoundRect(rect, h / 2, h / 2, fill)
        canvas.drawRoundRect(rect, h / 2, h / 2, stroke)

        when (state) {
            IslandState.IDLE -> drawIdle(canvas, w, h)
            IslandState.RECORDING -> {
                drawButtons(canvas, w, h, confirm = true)
                drawBars(canvas, w, h)
                postInvalidateOnAnimation()
            }
            IslandState.SENDING -> {
                drawButtons(canvas, w, h, confirm = false)
                drawDots(canvas, w, h)
                postInvalidateOnAnimation()
            }
        }
    }

    private fun drawIdle(canvas: Canvas, w: Float, h: Float) {
        val heights = floatArrayOf(0.25f, 0.5f, 0.8f, 0.5f, 0.25f)
        val bw = dp(3f)
        val gap = dp(3.5f)
        val total = heights.size * bw + (heights.size - 1) * gap
        var x = (w - total) / 2
        val maxH = h - dp(16f)
        bar.alpha = 210
        for (f in heights) {
            val bh = max(bw, f * maxH)
            rect.set(x, (h - bh) / 2, x + bw, (h + bh) / 2)
            canvas.drawRoundRect(rect, bw / 2, bw / 2, bar)
            x += bw + gap
        }
    }

    private fun buttonRadius(h: Float) = h / 2 - dp(6f)

    private fun drawButtons(canvas: Canvas, w: Float, h: Float, confirm: Boolean) {
        val r = buttonRadius(h)
        val cy = h / 2
        // cancel (x), left
        val lx = h / 2
        canvas.drawCircle(lx, cy, r, cancelBg)
        val k = r * 0.38f
        glyph.color = Color.argb(220, 255, 255, 255)
        canvas.drawLine(lx - k, cy - k, lx + k, cy + k, glyph)
        canvas.drawLine(lx - k, cy + k, lx + k, cy - k, glyph)
        if (!confirm) return
        // stop and insert (square), second from right
        val sx = w - h * 1.5f
        canvas.drawCircle(sx, cy, r, cancelBg)
        val q = r * 0.34f
        rect.set(sx - q, cy - q, sx + q, cy + q)
        bar.alpha = 235
        canvas.drawRoundRect(rect, q * 0.3f, q * 0.3f, bar)
        // send (up arrow): insert, then Enter -- far right
        val rx = w - h / 2
        canvas.drawCircle(rx, cy, r, confirmBg)
        glyph.color = Color.rgb(23, 23, 28)
        val a = r * 0.45f
        canvas.drawLine(rx, cy + a, rx, cy - a, glyph)
        canvas.drawLine(rx - a * 0.75f, cy - a * 0.2f, rx, cy - a, glyph)
        canvas.drawLine(rx + a * 0.75f, cy - a * 0.2f, rx, cy - a, glyph)
    }

    private fun drawBars(canvas: Canvas, w: Float, h: Float) {
        // Same as the Mac island: the band spectrum mirrored around the
        // centre (lowest band in the middle, where the voice has the most
        // energy).
        val u = bandsProvider?.invoke() ?: FloatArray(bands)
        val n = bands * 2
        for (i in 0 until n) {
            val j = if (i < bands) bands - 1 - i else i - bands
            val target = if (j < u.size) u[j] else 0f
            // ease in rather than jump, and fall back gently
            disp[i] = if (target > disp[i]) disp[i] + (target - disp[i]) * 0.3f
            else disp[i] * 0.9f + target * 0.1f
        }

        val left = h + dp(4f)
        val right = w - h * 2 - dp(4f)
        val bw = dp(2.5f)
        val gap = (right - left - n * bw) / (n - 1)
        val maxH = h - dp(16f)
        for (i in 0 until n) {
            val v = disp[i].coerceIn(0f, 1f)
            val bh = max(dp(2.5f), v * maxH)
            val x = left + i * (bw + gap)
            rect.set(x, (h - bh) / 2, x + bw, (h + bh) / 2)
            bar.alpha = (130 + 125 * (v * 1.6f).coerceAtMost(1f)).toInt()
            canvas.drawRoundRect(rect, bw / 2, bw / 2, bar)
        }
    }

    private fun drawDots(canvas: Canvas, w: Float, h: Float) {
        val t = (SystemClock.uptimeMillis() - t0) / 1000f
        val cx = w / 2
        val cy = h / 2
        for (i in -1..1) {
            val ph = 0.5f + 0.5f * sin(t * 5f + i * 1.1f)
            bar.alpha = (90 + 140 * ph).toInt()
            canvas.drawCircle(cx + i * dp(11f), cy, dp(2.2f) + dp(1.6f) * ph, bar)
        }
    }

    // ---------- touch: tap buttons, drag anywhere ----------
    private var downX = 0f
    private var downY = 0f
    private var lastX = 0f
    private var lastY = 0f
    private var dragged = false

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = event.rawX; downY = event.rawY
                lastX = downX; lastY = downY
                dragged = false
            }
            MotionEvent.ACTION_MOVE -> {
                if (!dragged && (abs(event.rawX - downX) > dp(8f) || abs(event.rawY - downY) > dp(8f))) {
                    dragged = true
                }
                if (dragged) onDrag?.invoke(event.rawX - lastX, event.rawY - lastY)
                lastX = event.rawX; lastY = event.rawY
            }
            MotionEvent.ACTION_UP -> {
                if (dragged) onDragEnd?.invoke() else handleTap(event.x)
            }
            MotionEvent.ACTION_CANCEL -> if (dragged) onDragEnd?.invoke()
        }
        return true
    }

    private fun handleTap(x: Float) {
        val zone = height + dp(10f)
        when (state) {
            IslandState.IDLE -> onStart?.invoke()
            IslandState.RECORDING -> when {
                x <= zone -> onCancel?.invoke()
                x >= width - height -> onSend?.invoke()
                x >= width - height * 2 - dp(6f) -> onConfirm?.invoke()
            }
            IslandState.SENDING -> if (x <= zone) onCancel?.invoke()
        }
    }
}
