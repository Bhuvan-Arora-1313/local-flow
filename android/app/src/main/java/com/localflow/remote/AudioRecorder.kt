package com.localflow.remote

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import java.io.ByteArrayOutputStream
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.ln
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Records mono 16-bit PCM at 16kHz -- the exact format the Mac's Transcriber
 * expects, so the server needs zero resampling.
 *
 * While recording it also computes a live spectrum for the island, ported
 * from the Mac's recorder.py: log-spaced bands, each with its own auto-gain
 * (so quiet high-frequency sounds still move the outer bars instead of the
 * whole thing pinning at max), gated against the room's noise floor so it rests flat
 * when you're not speaking.
 */
class AudioRecorder {
    companion object {
        const val SAMPLE_RATE = 16000
        const val BANDS = 12
        private const val FFT = 512
        private const val FMIN = 110.0
        private const val FMAX = 6500.0
    }

    private var record: AudioRecord? = null
    private var audioManager: AudioManager? = null
    private var focusRequest: AudioFocusRequest? = null
    private var thread: Thread? = null
    private val buffer = ByteArrayOutputStream()
    @Volatile private var recording = false

    /** Latest spectrum, low -> high frequency, each 0..1. */
    @Volatile
    var bands = FloatArray(BANDS)
        private set

    private val win = FloatArray(FFT) { (0.5 - 0.5 * cos(2 * PI * it / (FFT - 1))).toFloat() }
    private val edges = IntArray(BANDS + 1) { i ->
        val cut = FMIN * (FMAX / FMIN).pow(i.toDouble() / BANDS)
        kotlin.math.ceil(cut * FFT / SAMPLE_RATE).toInt()
    }
    private val agc = FloatArray(BANDS)
    // Room-noise floor = the quietest 32ms chunk in the last ~2s. Calibrates
    // from the very first chunk, and speech can't drag it upward because
    // the gaps between words keep showing it the real room level.
    private val recentDb = DoubleArray(62)
    private var recentCount = 0
    private var recentIdx = 0
    private val re = DoubleArray(FFT)
    private val im = DoubleArray(FFT)

    fun start(context: Context): Boolean {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            return false
        }
        val minBuf = AudioRecord.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (minBuf <= 0) return false
        val bufSize = max(minBuf * 2, FFT * 4)
        val r = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufSize)
        if (r.state != AudioRecord.STATE_INITIALIZED) {
            r.release()
            return false
        }
        buffer.reset()
        agc.fill(1e-3f)
        recentCount = 0
        recentIdx = 0
        bands = FloatArray(BANDS)
        record = r
        recording = true
        pauseOtherAudio(context)
        r.startRecording()
        thread = Thread {
            val chunk = ByteArray(FFT * 2)        // 512 samples = 32ms
            while (recording) {
                val n = r.read(chunk, 0, chunk.size)
                if (n > 0) {
                    synchronized(buffer) { buffer.write(chunk, 0, n) }
                    bands = spectrum(chunk, n)
                }
            }
        }.also { it.start() }
        return true
    }

    private fun spectrum(b: ByteArray, n: Int): FloatArray {
        val count = min(n / 2, FFT)
        var sumSq = 0.0
        for (i in 0 until FFT) {
            val s = if (i < count) {
                ((b[2 * i + 1].toInt() shl 8) or (b[2 * i].toInt() and 0xFF)).toShort() / 32768.0
            } else 0.0
            sumSq += s * s
            re[i] = s * win[i]
            im[i] = 0.0
        }
        val rms = sqrt(sumSq / max(count, 1))
        fft(re, im)

        val out = FloatArray(BANDS)
        val db = 20 * log10(max(rms, 1e-6))
        recentDb[recentIdx] = db
        recentIdx = (recentIdx + 1) % recentDb.size
        if (recentCount < recentDb.size) recentCount++
        var floorDb = db
        for (i in 0 until recentCount) if (recentDb[i] < floorDb) floorDb = recentDb[i]
        // bars only open for sound clearly above the room's noise floor
        val gate = ((db - floorDb - 7.0) / 12.0).coerceIn(0.0, 1.0)
        val nBins = FFT / 2 + 1
        for (i in 0 until BANDS) {
            val a = edges[i]
            val e = min(max(edges[i] + 1, edges[i + 1]), nBins)
            var acc = 0.0
            for (k in a until e) acc += re[k] * re[k] + im[k] * im[k]
            val mag = if (e > a) sqrt(acc / (e - a)) else 0.0
            val raw = ln(1.0 + mag * 6.0).toFloat()
            agc[i] = max(max(raw, agc[i] * 0.992f), 2e-3f)
            out[i] = ((raw / agc[i]).coerceIn(0f, 1f).toDouble().pow(0.7) * gate).toFloat()
        }
        return out
    }

    /** In-place iterative radix-2 FFT; FFT is a power of two. */
    private fun fft(x: DoubleArray, y: DoubleArray) {
        val n = x.size
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) {
                j = j xor bit
                bit = bit shr 1
            }
            j = j xor bit
            if (i < j) {
                var t = x[i]; x[i] = x[j]; x[j] = t
                t = y[i]; y[i] = y[j]; y[j] = t
            }
        }
        var len = 2
        while (len <= n) {
            val ang = -2 * PI / len
            val wr = cos(ang)
            val wi = sin(ang)
            var i = 0
            while (i < n) {
                var cr = 1.0
                var ci = 0.0
                for (k in 0 until len / 2) {
                    val ur = x[i + k]
                    val ui = y[i + k]
                    val vr = x[i + k + len / 2] * cr - y[i + k + len / 2] * ci
                    val vi = x[i + k + len / 2] * ci + y[i + k + len / 2] * cr
                    x[i + k] = ur + vr; y[i + k] = ui + vi
                    x[i + k + len / 2] = ur - vr; y[i + k + len / 2] = ui - vi
                    val nr = cr * wr - ci * wi
                    ci = cr * wi + ci * wr
                    cr = nr
                }
                i += len
            }
            len = len shl 1
        }
    }

    /**
     * Music or video playing on this same device is otherwise picked up by
     * the mic and transcribed. Taking transient audio focus makes media apps
     * (Spotify, YouTube Music, ...) pause while you dictate, and resume on
     * their own when it's released in stop().
     */
    private fun pauseOtherAudio(context: Context) {
        val am = context.getSystemService(AudioManager::class.java) ?: return
        val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE)
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build())
            .setOnAudioFocusChangeListener { }
            .build()
        am.requestAudioFocus(req)
        audioManager = am
        focusRequest = req
    }

    private fun resumeOtherAudio() {
        focusRequest?.let { audioManager?.abandonAudioFocusRequest(it) }
        focusRequest = null
    }

    /** Stops recording and returns everything captured, as raw PCM16 bytes. */
    fun stop(): ByteArray {
        recording = false
        thread?.join(500)
        thread = null
        record?.let {
            try {
                it.stop()
            } catch (_: Exception) {
            }
            it.release()
        }
        record = null
        resumeOtherAudio()
        bands = FloatArray(BANDS)
        return synchronized(buffer) { buffer.toByteArray() }
    }

    /** Copy of the last [seconds] of audio recorded so far, without stopping. */
    fun audioSoFar(seconds: Int): ByteArray = synchronized(buffer) {
        val all = buffer.toByteArray()
        val keep = seconds * SAMPLE_RATE * 2
        if (all.size <= keep) all else all.copyOfRange(all.size - keep, all.size)
    }

    fun isRecording(): Boolean = recording
}
