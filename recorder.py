"""Microphone capture (the audio itself runs in mic_helper.py).

While recording it (a) accumulates the raw audio for the transcriber and
(b) computes a cheap live spectrum that the on-screen island mirrors into a
symmetric, centre-weighted waveform.

`_NB` = number of *unique* frequency bands (low -> high). The island shows them
mirrored: lowest band in the centre (where the voice has most energy), higher
bands toward the edges, so it stays symmetric and reacts to what you say.
Each band has its own auto-gain, so quiet high-frequency sounds (s, sh, t) still
move the outer bars instead of sitting flat.
"""
import os
import struct
import subprocess
import sys
import threading
import time
import numpy as np

_HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mic_helper.py")

_NB = 8
_FFT = 512        # FFT size (mic blocks at 16 kHz are ~512 frames anyway)
_FMIN, _FMAX = 110, 6500


def _read_exact(f, n):
    buf = b""
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class _Helper:
    def __init__(self, proc):
        self.proc = proc
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.dead = threading.Event()
        self.used = False
        self.error = None


class Recorder:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._frames: list[np.ndarray] = []
        self._frames_lock = threading.Lock()
        self._helper: _Helper | None = None      # warmed-up, not yet used
        self._helper_lock = threading.Lock()
        self._active: _Helper | None = None      # the one recording right now
        self.recording = False
        self._win = np.hanning(_FFT).astype(np.float32)
        self._bands = np.zeros(_NB, dtype=np.float32)
        self._level = 0.0
        self._agc = np.full(_NB, 1e-3, dtype=np.float32)  # per-band running max
        self._edges = self._band_edges()
        # liveness: when the mic last delivered audio
        self._got_audio = threading.Event()
        self._last_audio = 0.0
        self._spawn_bg()            # warm up the first recording's helper

    def _band_edges(self):
        freqs = np.fft.rfftfreq(_FFT, 1.0 / self.sample_rate)
        cuts = np.geomspace(_FMIN, min(_FMAX, self.sample_rate / 2 - 1), _NB + 1)
        return [int(np.searchsorted(freqs, c)) for c in cuts]

    def _on_audio(self, mono):
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

    # The mic itself lives in a helper process (mic_helper.py). On macOS,
    # PortAudio's stop can deadlock inside CoreAudio and never return; in-
    # process that froze LocalFlow's mic control for good (seen 13 & 16 Nov:
    # "recording started" with no "recording stopped", every later dictation
    # dead). A hung helper is just killed -- the OS frees the mic, and every
    # audio block it already sent is kept, so the dictation still goes through.
    #
    # Also seen: a stream that starts but delivers NOTHING (CoreAudio "IO
    # overload"). So never trust a started stream: wait for real audio, and
    # if none arrives, throw the helper away and try a fresh one.
    START_WAIT_S = 0.8
    START_ATTEMPTS = 3
    STALL_S = 1.0
    READY_WAIT_S = 8.0
    STOP_WAIT_S = 1.5

    # ---------- helper process ----------
    @staticmethod
    def _python():
        cand = os.path.join(sys.prefix, "bin", "python3")
        # inside LocalFlow.app sys.executable is the app's launcher, not python
        return cand if os.path.exists(cand) else sys.executable

    def _spawn(self):
        p = subprocess.Popen([self._python(), _HELPER], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, bufsize=0)
        h = _Helper(p)
        with self._helper_lock:
            self._helper = h
        threading.Thread(target=self._reader, args=(h,), daemon=True).start()
        return h

    def _spawn_bg(self):
        threading.Thread(target=self._safe_spawn, daemon=True).start()

    def _safe_spawn(self):
        try:
            self._spawn()
        except Exception as e:
            print(f"[rec] couldn't start the microphone helper: {e}")

    def _take_helper(self):
        """A fresh, ready helper (warmed up in the background after the last
        recording, so normally this returns immediately)."""
        with self._helper_lock:
            h = self._helper
        if h is None or h.used or h.dead.is_set():
            h = self._spawn()
        if not h.ready.wait(self.READY_WAIT_S):
            self._kill(h)
            raise RuntimeError("microphone helper didn't start")
        if h.dead.is_set():
            raise RuntimeError(h.error or "microphone helper exited")
        return h

    def _kill(self, h):
        if h is None:
            return
        with self._helper_lock:
            if self._helper is h:
                self._helper = None
        try:
            h.proc.kill()
        except Exception:
            pass
        threading.Thread(target=h.proc.wait, daemon=True).start()   # reap

    def _reader(self, h):
        f = h.proc.stdout
        while True:
            hdr = _read_exact(f, 5)
            if hdr is None:
                break
            kind, n = struct.unpack("<cI", hdr)
            data = _read_exact(f, n) if n else b""
            if data is None:
                break
            if kind == b"A":
                if h is self._active:
                    self._on_audio(np.frombuffer(data, dtype=np.float32))
            elif kind == b"R":
                h.ready.set()
            elif kind == b"E":
                h.error = data.decode("utf-8", "replace")
                print(f"[rec] microphone: {h.error}")
            elif kind == b"X":
                h.stopped.set()
        h.dead.set()
        h.ready.set()       # wake anyone waiting on a helper that died early
        h.stopped.set()

    def _send(self, h, line):
        h.proc.stdin.write((line + "\n").encode())
        h.proc.stdin.flush()

    def _halt(self, h):
        """Stops h's stream. Returns once every audio block it captured has
        arrived -- or kills it if the audio driver hangs on stop."""
        if h is None:
            return
        try:
            self._send(h, "stop")
        except Exception:
            pass
        if not h.stopped.wait(self.STOP_WAIT_S):
            print("[rec] audio driver hung while stopping the mic — "
                  "killed the mic helper (your dictation is kept)")
            self._kill(h)

    # ---------- recording ----------
    def _open(self):
        h = self._take_helper()
        h.used = True
        self._got_audio.clear()
        self._active = h
        self._send(h, f"start {int(self.sample_rate)}")
        return h

    def _close(self):
        h = self._active
        if h is None:
            return
        # stop first, THEN stop accepting its audio, so the trailing blocks
        # captured right before the key-up still make it in
        self._halt(h)
        self._active = None
        self._kill(h)           # normally already exiting by itself
        self._spawn_bg()        # warm up the next recording's helper

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
            h = None
            try:
                h = self._open()
                if self._got_audio.wait(self.START_WAIT_S):
                    self.recording = True
                    if attempt > 1:
                        print(f"[rec] microphone recovered on attempt {attempt}")
                    return
                last_err = h.error
                print(f"[rec] microphone opened but delivered no audio (attempt {attempt}) "
                      "— retrying with a fresh audio process")
            except Exception as e:
                last_err = e
                print(f"[rec] microphone failed to open (attempt {attempt}): {e}")
            self._active = None
            self._kill(h)
        self._spawn_bg()
        raise RuntimeError(f"microphone isn't delivering audio ({last_err or 'no data'})")

    def stalled(self) -> bool:
        """True if we're recording but the mic has gone silent at the driver
        level (no callbacks at all -- not just a quiet room)."""
        return self.recording and time.monotonic() - self._last_audio > self.STALL_S

    def reopen(self) -> bool:
        """Mid-recording recovery: a fresh mic helper, keeping everything
        captured so far. Returns True once audio is flowing again."""
        old, self._active = self._active, None
        self._kill(old)
        try:
            self._open()
        except Exception as e:
            print(f"[rec] reopening the microphone failed: {e}")
            return False
        return self._got_audio.wait(self.START_WAIT_S)

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
