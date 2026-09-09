"""Microphone capture via sounddevice.

While recording it (a) accumulates the raw audio for the transcriber and
(b) computes a cheap live spectrum (log-spaced FFT bands + RMS level) that the
on-screen island reads for its waveform.
"""
import numpy as np
import sounddevice as sd

_NB = 13          # number of spectrum bars shown on the island
_FFT = 512        # FFT size (mic blocks at 16 kHz are ~512 frames anyway)
_FMIN, _FMAX = 90, 5500


class Recorder:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self.recording = False
        self._win = np.hanning(_FFT).astype(np.float32)
        self._bands = np.zeros(_NB, dtype=np.float32)
        self._level = 0.0
        self._agc = 1e-4  # running loudness estimate for auto-gain
        self._edges = self._band_edges()

    def _band_edges(self):
        freqs = np.fft.rfftfreq(_FFT, 1.0 / self.sample_rate)
        cuts = np.geomspace(_FMIN, min(_FMAX, self.sample_rate / 2 - 1), _NB + 1)
        return [np.searchsorted(freqs, c) for c in cuts]

    def _callback(self, indata, frames, time_info, status):
        mono = indata.reshape(-1).astype(np.float32)
        self._frames.append(mono.copy())

        rms = float(np.sqrt(np.mean(mono * mono)) + 1e-9)
        self._level = rms

        x = mono[:_FFT]
        if x.size < _FFT:
            x = np.pad(x, (0, _FFT - x.size))
        mag = np.abs(np.fft.rfft(x * self._win))
        raw = np.empty(_NB, dtype=np.float32)
        for i in range(_NB):
            a, b = self._edges[i], max(self._edges[i] + 1, self._edges[i + 1])
            raw[i] = np.sqrt(np.mean(mag[a:b] ** 2)) if b <= mag.size else 0.0
        raw = np.log1p(raw * 4.0)

        self._agc = max(raw.max(), self._agc * 0.995, 1e-4)
        self._bands = np.clip(raw / self._agc, 0.0, 1.0)

    def start(self):
        if self.recording:
            return
        self._frames = []
        self._bands = np.zeros(_NB, dtype=np.float32)
        self._level = 0.0
        self._agc = 1e-4
        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32",
            blocksize=0, callback=self._callback,
        )
        self._stream.start()
        self.recording = True

    def stop(self) -> np.ndarray:
        if not self.recording:
            return np.zeros(0, dtype=np.float32)
        self.recording = False
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None
        if not self._frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._frames).astype(np.float32)

    def snapshot(self):
        """(level 0..~0.3, bands list[float] 0..1) — safe to call from any thread."""
        return self._level, list(self._bands)

    @property
    def duration(self) -> float:
        return sum(len(f) for f in self._frames) / self.sample_rate
