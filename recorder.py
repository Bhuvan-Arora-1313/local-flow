"""Microphone capture via sounddevice.

While recording it (a) accumulates the raw audio for the transcriber and
(b) computes a cheap live spectrum that the on-screen island mirrors into a
symmetric, centre-weighted waveform.

`_NB` = number of *unique* frequency bands (low -> high). The island shows them
mirrored: lowest band in the centre (where the voice has most energy), higher
bands toward the edges, so it stays symmetric and reacts to what you say.
Each band has its own auto-gain, so quiet high-frequency sounds (s, sh, t) still
move the outer bars instead of sitting flat.
"""
import threading
import time
import numpy as np
import sounddevice as sd

_NB = 8
_FFT = 512        # FFT size (mic blocks at 16 kHz are ~512 frames anyway)
_FMIN, _FMAX = 110, 6500


class Recorder:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._frames: list[np.ndarray] = []
        self._frames_lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self.recording = False
        self._win = np.hanning(_FFT).astype(np.float32)
        self._bands = np.zeros(_NB, dtype=np.float32)
        self._level = 0.0
        self._agc = np.full(_NB, 1e-3, dtype=np.float32)  # per-band running max
        self._edges = self._band_edges()
        # liveness: when the mic last delivered audio
        self._got_audio = threading.Event()
        self._last_audio = 0.0

    def _band_edges(self):
        freqs = np.fft.rfftfreq(_FFT, 1.0 / self.sample_rate)
        cuts = np.geomspace(_FMIN, min(_FMAX, self.sample_rate / 2 - 1), _NB + 1)
        return [int(np.searchsorted(freqs, c)) for c in cuts]

    def _callback(self, indata, frames, time_info, status):
        mono = indata.reshape(-1).astype(np.float32)
        with self._frames_lock:
            self._frames.append(mono.copy())
        self._last_audio = time.monotonic()
        self._got_audio.set()

        rms = float(np.sqrt(np.mean(mono * mono)) + 1e-9)
        self._level = rms

        x = mono[:_FFT]
        if x.size < _FFT:
            x = np.pad(x, (0, _FFT - x.size))
        mag = np.abs(np.fft.rfft(x * self._win))

        raw = np.empty(_NB, dtype=np.float32)
        for i in range(_NB):
            a, b = self._edges[i], max(self._edges[i] + 1, self._edges[i + 1])
            b = min(b, mag.size)
            raw[i] = np.sqrt(np.mean(mag[a:b] ** 2)) if b > a else 0.0
        raw = np.log1p(raw * 6.0)

        # per-band auto-gain: track a decaying max so every band uses its full range
        self._agc = np.maximum(np.maximum(raw, self._agc * 0.992), 2e-3)
        norm = np.clip(raw / self._agc, 0.0, 1.0) ** 0.7
        # gate: below speaking level, collapse toward zero so it rests flat
        norm *= float(np.clip(rms * 40.0, 0.0, 1.0))
        self._bands = norm.astype(np.float32)

    # Seen in the wild: CoreAudio logs an "IO overload" right as the stream
    # starts and the stream then delivers NOTHING -- LocalFlow shows it's
    # recording while every word is lost, and only a full restart (which
    # re-initialises PortAudio) fixes it. So never trust a started stream:
    # wait for real audio, and if none arrives, re-initialise PortAudio and
    # reopen -- the same thing the restart did.
    START_WAIT_S = 0.5
    START_ATTEMPTS = 3
    STALL_S = 1.0

    def _open(self):
        self._got_audio.clear()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32",
            blocksize=0, callback=self._callback,
        )
        self._stream.start()

    def _close(self):
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    @staticmethod
    def _reinit_portaudio():
        try:
            sd._terminate()
        except Exception:
            pass
        sd._initialize()

    def start(self):
        """Opens the mic and returns once it is actually delivering audio.
        Raises RuntimeError if it can't get live audio after retrying."""
        if self.recording:
            return
        with self._frames_lock:
            self._frames = []
        self._bands = np.zeros(_NB, dtype=np.float32)
        self._level = 0.0
        self._agc = np.full(_NB, 1e-3, dtype=np.float32)
        last_err = None
        for attempt in range(1, self.START_ATTEMPTS + 1):
            try:
                self._open()
                if self._got_audio.wait(self.START_WAIT_S):
                    self.recording = True
                    if attempt > 1:
                        print(f"[rec] microphone recovered on attempt {attempt}")
                    return
                print(f"[rec] microphone opened but delivered no audio (attempt {attempt}) "
                      "— re-initialising audio")
            except Exception as e:
                last_err = e
                print(f"[rec] microphone failed to open (attempt {attempt}): {e}")
            self._close()
            self._reinit_portaudio()
        raise RuntimeError(f"microphone isn't delivering audio ({last_err or 'no data'})")

    def stalled(self) -> bool:
        """True if we're recording but the mic has gone silent at the driver
        level (no callbacks at all -- not just a quiet room)."""
        return self.recording and time.monotonic() - self._last_audio > self.STALL_S

    def reopen(self) -> bool:
        """Mid-recording recovery: reopen the stream, keeping everything
        captured so far. Returns True once audio is flowing again."""
        self._close()
        self._reinit_portaudio()
        try:
            self._open()
        except Exception as e:
            print(f"[rec] reopening the microphone failed: {e}")
            return False
        return self._got_audio.wait(0.8)

    def stop(self) -> np.ndarray:
        if not self.recording:
            self._close()
            return np.zeros(0, dtype=np.float32)
        self.recording = False
        self._close()
        with self._frames_lock:
            frames = list(self._frames)
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames).astype(np.float32)

    def audio_so_far(self) -> np.ndarray:
        """A copy of everything captured since start(), without stopping the
        recording -- for a live/ghost preview while still talking. Safe to
        call from any thread, concurrently with the recording continuing."""
        with self._frames_lock:
            frames = list(self._frames)
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames).astype(np.float32)

    def snapshot(self):
        """(level, bands) — bands = _NB unique low->high values in 0..1.
        Safe to call from any thread."""
        return self._level, list(self._bands)

    @property
    def duration(self) -> float:
        return sum(len(f) for f in self._frames) / self.sample_rate
