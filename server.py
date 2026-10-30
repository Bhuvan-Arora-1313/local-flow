"""Remote dictation server.

Lets another device on the Tailscale tailnet (e.g. an Android phone) send
recorded audio and get back the same cleaned-up text the local hotkey path
produces -- by calling straight into the already-loaded Transcriber/Cleaner
that flow.py's App owns, not a second copy of either model.

Runs inside the main LocalFlow process (see App.set_remote_server in
flow.py), bound to the Mac's Tailscale IP rather than 0.0.0.0, so it's only
reachable over the tailnet, not on whatever other Wi-Fi the Mac is on.
Tailscale already encrypts/authenticates the transport (WireGuard); the
pairing token below is a second factor on top of that, not a replacement
for it -- plain HTTP over the tailnet is the normal, documented pattern for
this kind of internal-only service.
"""
import asyncio
import secrets
import subprocess
import threading
import time

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

import dictionary as dictmod
import inserter
try:
    import usage
except Exception:
    usage = None

# audio longer than this per request is almost certainly a mistake, not a
# real utterance -- reject it instead of tying up the pipeline for minutes
MAX_AUDIO_BYTES = 20 * 1024 * 1024   # ~10 minutes of 16kHz mono PCM16
MIN_AUDIO_BYTES = 1600               # ~50ms, matches Transcriber's own floor
# re-decoding the whole recording every second gets slower the longer you
# talk; a recent window keeps each live preview equally fast (same as the
# Mac's GHOST_WINDOW_SECONDS)
PREVIEW_SECONDS = 10


_TAILSCALE_CANDIDATES = (
    "/usr/local/bin/tailscale",
    "/opt/homebrew/bin/tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    "tailscale",  # last resort: whatever PATH the process happens to have
)


def tailscale_ip() -> str | None:
    """The Mac's own Tailscale IPv4 address, or None if tailscale isn't
    running / isn't installed -- callers must treat that as 'don't start'.

    Launched as a double-clicked app bundle (not from a shell), this process
    gets a minimal PATH that usually doesn't include /usr/local/bin, so a
    bare "tailscale" lookup silently fails here even though it works fine
    from a terminal -- try known install locations first."""
    for exe in _TAILSCALE_CANDIDATES:
        try:
            out = subprocess.run([exe, "ip", "-4"], capture_output=True,
                                  text=True, timeout=3, check=True)
            ip = out.stdout.strip().splitlines()[0].strip() if out.stdout.strip() else ""
            if ip:
                return ip
        except Exception:
            continue
    return None


def new_token() -> str:
    return secrets.token_urlsafe(24)


class RemoteServer:
    """Owns at most one running uvicorn instance. Cheap to start/stop --
    Settings flips this live via App.set_remote_server, no app restart
    needed (only a port change needs a restart, to rebind the socket)."""

    def __init__(self, app, cfg_getter):
        self.app = app             # the flow.App instance: shares asr/cleaner/terms
        self.cfg = cfg_getter       # callable -> current CFG dict, so edits are live
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.bound_host = None
        self.bound_port = None

    @property
    def running(self) -> bool:
        return self._thread is not None

    # ---------- request handling ----------
    def _check_token(self, request: Request):
        want = self.cfg().get("remote_token", "")
        got = request.headers.get("authorization", "")
        expected = f"Bearer {want}"
        if not want or len(got) != len(expected) or not secrets.compare_digest(got, expected):
            raise HTTPException(status_code=401, detail="missing or wrong pairing token")

    def _run_pipeline(self, audio: np.ndarray) -> str:
        """Same sequence as App._worker (flow.py), minus the local paste --
        that's opt-in here via remote_also_paste_locally."""
        a = self.app
        cfg = self.cfg()
        raw = a.asr.transcribe(audio, prompt=", ".join(a.terms))
        text = dictmod.collapse_repeats(raw)
        text = dictmod.tidy_commas(text)
        text = dictmod.apply_literal_corrections(text, a.corrections)
        text = dictmod.normalize_acronyms(text, a.acronyms)
        if a.cleanup_on and a.cleaner.available():
            text = a.cleaner.clean(
                text, a.terms,
                smart_format=cfg.get("smart_formatting", True),
                romanize_hindi=(cfg.get("hindi_script", "devanagari") == "latin"))
        elif text:
            text = text[0].upper() + text[1:]
        text = text.strip()
        if cfg.get("trailing_space", True) and text:
            text += " "
        if text:
            a.last_text = text
            if cfg.get("remote_also_paste_locally", False):
                try:
                    inserter.paste_text(text)
                except Exception:
                    pass
            if a.learner is not None:
                a.learner.arm_correction_window()
        return text

    def _build_app(self) -> FastAPI:
        api = FastAPI(title="LocalFlow remote dictation", docs_url=None, redoc_url=None)

        @api.get("/v1/health")
        def health(request: Request):
            self._check_token(request)
            return {"ok": True, "model": self.cfg().get("asr_model", ""),
                     "ready": self.app.asr is not None}

        @api.post("/v1/preview")
        async def preview(request: Request):
            """Rough live transcript of the audio so far, for the faded preview
            above the island -- speech model only (no dictionary/LLM cleanup),
            on the last PREVIEW_SECONDS, like the Mac's own ghost text.
            Nothing here touches usage stats, the learner or last_text."""
            self._check_token(request)
            if self.app.asr is None:
                raise HTTPException(status_code=503, detail="model still loading")
            body = await request.body()
            if len(body) < MIN_AUDIO_BYTES or len(body) > MAX_AUDIO_BYTES:
                return JSONResponse({"text": ""})
            audio = np.frombuffer(body, dtype="<i2").astype(np.float32) / 32768.0
            audio = audio[-PREVIEW_SECONDS * self.app.asr.sample_rate:]
            prompt = ", ".join(self.app.terms)
            loop = asyncio.get_running_loop()
            try:
                text = await loop.run_in_executor(
                    None, lambda: self.app.asr.transcribe(audio, prompt=prompt))
            except Exception as e:
                print(f"[server] preview error: {e}")
                text = ""
            return JSONResponse({"text": text.strip()})

        @api.post("/v1/transcribe")
        async def transcribe(request: Request):
            self._check_token(request)
            if self.app.asr is None:
                raise HTTPException(status_code=503, detail="model still loading")
            cl = request.headers.get("content-length")
            if cl is not None and int(cl) > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail="audio too long")
            body = await request.body()
            if len(body) < MIN_AUDIO_BYTES:
                raise HTTPException(status_code=400, detail="audio too short")
            if len(body) > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail="audio too long")
            # little-endian int16 mono PCM -> float32 in [-1, 1], exactly what
            # Transcriber.transcribe() expects -- no resampling needed since
            # the client records at the model's own sample rate (16kHz)
            audio = np.frombuffer(body, dtype="<i2").astype(np.float32) / 32768.0

            t0 = time.time()
            loop = asyncio.get_running_loop()
            try:
                text = await loop.run_in_executor(None, self._run_pipeline, audio)
            except Exception as e:
                print(f"[server] pipeline error: {e}")
                raise HTTPException(status_code=500, detail="pipeline error") from e
            if usage is not None and text:
                try:
                    usage.record(text, latency_ms=(time.time() - t0) * 1000.0)
                except Exception:
                    pass
            if not text:
                raise HTTPException(status_code=422, detail="empty transcription")
            return JSONResponse({"text": text})

        return api

    # ---------- lifecycle ----------
    def start(self, port: int) -> bool:
        if self.running:
            return True
        host = tailscale_ip()
        if not host:
            print("[server] couldn't resolve a Tailscale IP -- is Tailscale running? "
                  "remote dictation NOT started")
            return False
        config = uvicorn.Config(self._build_app(), host=host, port=port,
                                 log_level="warning")
        server = uvicorn.Server(config)
        self._server = server
        self.bound_host, self.bound_port = host, port

        def run():
            print(f"[server] remote dictation listening on http://{host}:{port}")
            try:
                server.run()
            finally:
                print("[server] remote dictation stopped")

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        if self._server is not None:
            self._server.should_exit = True
        self._thread = None
        self._server = None
        self.bound_host = self.bound_port = None
