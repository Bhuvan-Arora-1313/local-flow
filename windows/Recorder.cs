using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using NAudio.Wave;

namespace LocalFlowRemote
{
    /// <summary>
    /// Records 16 kHz mono 16-bit PCM -- exactly what the Mac's speech model
    /// takes, so the server does no resampling (Windows' own mixer converts
    /// from the mic's native format).
    ///
    /// Also computes the island's live spectrum, ported from the Mac's
    /// recorder.py (via the Android AudioRecorder): log-spaced bands, each with
    /// its own auto-gain, gated against the room's noise floor so the bars
    /// rest flat when you're not speaking.
    /// </summary>
    internal sealed class Recorder
    {
        public const int SampleRate = 16000;
        public const int Bands = 8;
        private const int Fft = 512;
        private const double FMin = 110, FMax = 6500;

        private WaveInEvent? _wave;
        private readonly MemoryStream _buffer = new();
        private ManualResetEventSlim? _stopped;
        private volatile float[] _bands = new float[Bands];

        private readonly double[] _win = new double[Fft];
        private readonly int[] _edges = new int[Bands + 1];
        private readonly float[] _agc = new float[Bands];
        private readonly double[] _recentDb = new double[62];   // ~2 s of 32 ms chunks
        private int _recentCount, _recentIdx;
        private readonly double[] _re = new double[Fft], _im = new double[Fft];

        public Recorder()
        {
            for (int i = 0; i < Fft; i++) _win[i] = 0.5 - 0.5 * Math.Cos(2 * Math.PI * i / (Fft - 1));
            for (int i = 0; i <= Bands; i++)
            {
                double cut = FMin * Math.Pow(FMax / FMin, (double)i / Bands);
                _edges[i] = (int)Math.Ceiling(cut * Fft / SampleRate);
            }
        }

        /// <summary>Latest spectrum, low -> high frequency, each 0..1.</summary>
        public float[] CurrentBands => _bands;
        public bool IsRecording => _wave != null;

        public bool Start(out string error)
        {
            error = "";
            lock (_buffer) _buffer.SetLength(0);
            Array.Fill(_agc, 1e-3f);
            _recentCount = _recentIdx = 0;
            _bands = new float[Bands];
            var ctx = SynchronizationContext.Current;
            try
            {
                // NAudio reports "stopped" through the creating thread's
                // SynchronizationContext -- the UI thread, which is blocked in
                // Stop() waiting for exactly that. Create it context-free.
                SynchronizationContext.SetSynchronizationContext(null);
                var w = new WaveInEvent
                {
                    DeviceNumber = -1,                       // the Windows default mic
                    WaveFormat = new WaveFormat(SampleRate, 16, 1),
                    BufferMilliseconds = 32,                 // 512 samples = one FFT
                    NumberOfBuffers = 4,
                };
                var stopped = new ManualResetEventSlim();
                w.DataAvailable += OnData;
                w.RecordingStopped += (_, e) =>
                {
                    if (e.Exception != null) Log.Write("mic stopped with error: " + e.Exception.Message);
                    stopped.Set();
                };
                w.StartRecording();
                _wave = w;
                _stopped = stopped;
                return true;
            }
            catch (Exception e)
            {
                error = e.Message;
                Log.Write("mic open failed: " + e.Message);
                _wave = null;
                return false;
            }
            finally
            {
                SynchronizationContext.SetSynchronizationContext(ctx);
            }
        }

        private void OnData(object? sender, WaveInEventArgs e)
        {
            if (e.BytesRecorded <= 0) return;
            lock (_buffer) _buffer.Write(e.Buffer, 0, e.BytesRecorded);
            _bands = Spectrum(e.Buffer, e.BytesRecorded);
        }

        /// <summary>Stops and returns everything captured as PCM16 bytes.</summary>
        public byte[] Stop()
        {
            var w = _wave;
            _wave = null;
            if (w != null)
            {
                try { w.StopRecording(); } catch (Exception e) { Log.Write("mic stop: " + e.Message); }
                // the last buffer arrives with RecordingStopped; never hang on a
                // stuck driver (the Mac's mic once deadlocked exactly here)
                _stopped?.Wait(400);
                var dispose = w;
                Task.Run(() => { try { dispose.Dispose(); } catch { } });
            }
            _bands = new float[Bands];
            lock (_buffer) return _buffer.ToArray();
        }

        /// <summary>The last <paramref name="seconds"/> of audio so far, without stopping.</summary>
        public byte[] AudioSoFar(int seconds)
        {
            lock (_buffer)
            {
                var all = _buffer.GetBuffer();
                int len = (int)_buffer.Length;
                int keep = Math.Min(len, seconds * SampleRate * 2);
                var outBuf = new byte[keep];
                Buffer.BlockCopy(all, len - keep, outBuf, 0, keep);
                return outBuf;
            }
        }

        private float[] Spectrum(byte[] b, int n)
        {
            int count = Math.Min(n / 2, Fft);
            double sumSq = 0;
            for (int i = 0; i < Fft; i++)
            {
                double s = i < count ? BitConverter.ToInt16(b, 2 * i) / 32768.0 : 0.0;
                sumSq += s * s;
                _re[i] = s * _win[i];
                _im[i] = 0;
            }
            double rms = Math.Sqrt(sumSq / Math.Max(count, 1));
            FftInPlace(_re, _im);

            var outBands = new float[Bands];
            double db = 20 * Math.Log10(Math.Max(rms, 1e-6));
            _recentDb[_recentIdx] = db;
            _recentIdx = (_recentIdx + 1) % _recentDb.Length;
            if (_recentCount < _recentDb.Length) _recentCount++;
            double floorDb = db;
            for (int i = 0; i < _recentCount; i++) if (_recentDb[i] < floorDb) floorDb = _recentDb[i];
            // bars only open for sound clearly above the room's noise floor
            double gate = Math.Clamp((db - floorDb - 7.0) / 12.0, 0.0, 1.0);
            int nBins = Fft / 2 + 1;
            for (int i = 0; i < Bands; i++)
            {
                int a = _edges[i];
                int e = Math.Min(Math.Max(_edges[i] + 1, _edges[i + 1]), nBins);
                double acc = 0;
                for (int k = a; k < e; k++) acc += _re[k] * _re[k] + _im[k] * _im[k];
                double mag = e > a ? Math.Sqrt(acc / (e - a)) : 0;
                float raw = (float)Math.Log(1.0 + mag * 6.0);
                _agc[i] = Math.Max(Math.Max(raw, _agc[i] * 0.992f), 2e-3f);
                outBands[i] = (float)(Math.Pow(Math.Clamp(raw / _agc[i], 0f, 1f), 0.7) * gate);
            }
            return outBands;
        }

        private static void FftInPlace(double[] x, double[] y)
        {
            int n = x.Length;
            for (int i = 1, j = 0; i < n; i++)
            {
                int bit = n >> 1;
                for (; (j & bit) != 0; bit >>= 1) j ^= bit;
                j ^= bit;
                if (i < j)
                {
                    (x[i], x[j]) = (x[j], x[i]);
                    (y[i], y[j]) = (y[j], y[i]);
                }
            }
            for (int len = 2; len <= n; len <<= 1)
            {
                double ang = -2 * Math.PI / len, wr = Math.Cos(ang), wi = Math.Sin(ang);
                for (int i = 0; i < n; i += len)
                {
                    double cr = 1, ci = 0;
                    for (int k = 0; k < len / 2; k++)
                    {
                        int p = i + k, q = i + k + len / 2;
                        double vr = x[q] * cr - y[q] * ci, vi = x[q] * ci + y[q] * cr;
                        x[q] = x[p] - vr; y[q] = y[p] - vi;
                        x[p] += vr; y[p] += vi;
                        double nr = cr * wr - ci * wi;
                        ci = cr * wi + ci * wr;
                        cr = nr;
                    }
                }
            }
        }
    }
}
