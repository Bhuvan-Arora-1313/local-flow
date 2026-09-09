#!/usr/bin/env python3
"""LocalFlow - a local, on-device dictation tool (a free Wispr Flow).

Hold the hotkey, talk, release. Audio -> Parakeet (MLX, on-GPU) -> local LLM
cleanup (Ollama) -> text is pasted at your cursor. Nothing leaves the machine.
"""
import os
import sys
import json
import time
import queue
import threading
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))


def load_config():
    with open(os.path.join(BASE, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()

import numpy as np  # noqa: E402
import rumps  # noqa: E402
from pynput import keyboard  # noqa: E402

from recorder import Recorder  # noqa: E402
from asr import Transcriber  # noqa: E402
try:
    from island import Island  # noqa: E402
except Exception as _e:  # AppKit missing / headless
    Island = None
    print(f"[flow] island unavailable: {_e}")
from cleanup import Cleaner  # noqa: E402
import dictionary as dictmod  # noqa: E402
import inserter  # noqa: E402

DICT_PATH = os.path.join(BASE, "dictionary.txt")

SOUNDS = {
    "start": "/System/Library/Sounds/Tink.aiff",
    "done": "/System/Library/Sounds/Pop.aiff",
    "error": "/System/Library/Sounds/Basso.aiff",
}


def notify(title: str, subtitle: str, msg: str):
    if not CFG.get("notify", True):
        return
    try:
        rumps.notification(title, subtitle, msg)
    except Exception:
        pass


def play(kind: str):
    if not CFG.get("sounds", True):
        return
    path = SOUNDS.get(kind)
    if path and os.path.exists(path):
        try:
            subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def resolve_key(name: str):
    name = name.strip().lower()
    if hasattr(keyboard.Key, name):
        return getattr(keyboard.Key, name)
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise ValueError(f"Unknown hotkey in config: {name!r}")


class LocalFlow(rumps.App):
    def __init__(self):
        super().__init__("LocalFlow", title="LF·", quit_button=None)
        self.state = "loading"          # loading | idle | rec | work | error
        self.asr = None
        self.last_text = ""
        self._jobs: queue.Queue = queue.Queue()
        self._hotkey = resolve_key(CFG["hotkey"])
        self._hotkey_down = False
        self._toggle_on = False
        self.mode = CFG.get("mode", "push_to_talk")

        self.rec = Recorder(CFG.get("sample_rate", 16000))
        self.cleaner = Cleaner(
            CFG.get("ollama_url", "http://localhost:11434"),
            CFG.get("ollama_model", "qwen3:8b"),
            CFG.get("cleanup_timeout_seconds", 30),
            CFG.get("max_glossary_terms", 240),
        )
        self.terms, self.corrections = dictmod.load(DICT_PATH)
        self.acronyms = dictmod.acronym_set(self.terms)

        self.island = None
        if CFG.get("island", True) and Island is not None:
            try:
                self.island = Island(lambda: (self.state, *self.rec.snapshot()))
            except Exception as e:
                print(f"[flow] island init failed: {e}")

        self.item_status = rumps.MenuItem("Loading model…")
        self.item_cleanup = rumps.MenuItem("AI cleanup", callback=self.toggle_cleanup)
        self.item_cleanup.state = CFG.get("cleanup_enabled", True)
        self.item_last = rumps.MenuItem("Last: —")
        self.menu = [
            self.item_status,
            None,
            self.item_cleanup,
            rumps.MenuItem("Reload dictionary", callback=self.reload_dict),
            rumps.MenuItem("Copy last transcript", callback=self.copy_last),
            self.item_last,
            None,
            rumps.MenuItem("Quit LocalFlow", callback=rumps.quit_application),
        ]

        threading.Thread(target=self._load_model, daemon=True).start()
        threading.Thread(target=self._worker, daemon=True).start()
        if self.item_cleanup.state:
            threading.Thread(
                target=lambda: self.cleaner.available() and self.cleaner.warm(self.terms),
                daemon=True,
            ).start()
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        self._status_timer = rumps.Timer(self._tick, 0.25)
        self._status_timer.start()
        if self.island is not None:
            self._island_timer = rumps.Timer(self._island_tick, 1.0 / 30.0)
            self._island_timer.start()

    # ---------- model ----------
    def _load_model(self):
        try:
            self.asr = Transcriber(CFG["asr_model"], CFG.get("sample_rate", 16000))
            self.rec.sample_rate = self.asr.sample_rate
            self.state = "idle"
        except Exception as e:
            print(f"[flow] model load failed: {e}")
            self.state = "error"

    # ---------- hotkey ----------
    def _on_press(self, key):
        if key != self._hotkey:
            return
        if self.mode == "push_to_talk":
            if self._hotkey_down:
                return
            self._hotkey_down = True
            self._begin()
        else:  # toggle
            self._toggle_on = not self._toggle_on
            self._begin() if self._toggle_on else self._end()

    def _on_release(self, key):
        if key != self._hotkey:
            return
        if self.mode == "push_to_talk":
            self._hotkey_down = False
            self._end()

    def _begin(self):
        if self.state != "idle":
            return
        self.state = "rec"
        try:
            self.rec.start()
            play("start")
        except Exception as e:
            print(f"[flow] mic start failed: {e}")
            self.state = "idle"

    def _end(self):
        if self.state != "rec":
            return
        audio = self.rec.stop()
        dur = len(audio) / max(1, self.rec.sample_rate)
        if dur < CFG.get("min_record_seconds", 0.35):
            self.state = "idle"
            return
        self.state = "work"
        self._jobs.put(audio)

    # ---------- pipeline worker ----------
    def _worker(self):
        while True:
            audio = self._jobs.get()
            try:
                if self.asr is None:
                    continue
                t0 = time.time()
                raw = self.asr.transcribe(audio, prompt=", ".join(self.terms))
                t1 = time.time()
                text = dictmod.apply_literal_corrections(raw, self.corrections)
                text = dictmod.normalize_acronyms(text, self.acronyms)
                if self.item_cleanup.state and self.cleaner.available():
                    text = self.cleaner.clean(text, self.terms)
                elif text:
                    text = text[0].upper() + text[1:]
                t2 = time.time()
                text = text.strip()
                if CFG.get("trailing_space", True) and text:
                    text += " "
                print(f"[flow] raw={raw!r}")
                print(f"[flow] out={text!r}  (asr {t1-t0:.2f}s, clean {t2-t1:.2f}s)")
                if text:
                    self.last_text = text
                    if CFG.get("auto_paste", True):
                        inserter.paste_text(text)
                    else:
                        subprocess.run(["pbcopy"], input=text.encode(), check=False)
                    play("done")
                else:
                    play("error")
            except Exception as e:
                print(f"[flow] pipeline error: {e}")
                play("error")
            finally:
                self.state = "idle"

    # ---------- menu callbacks ----------
    def toggle_cleanup(self, sender):
        sender.state = not sender.state

    def reload_dict(self, _):
        self.terms, self.corrections = dictmod.load(DICT_PATH)
        self.acronyms = dictmod.acronym_set(self.terms)
        notify("LocalFlow", "Dictionary reloaded", f"{len(self.terms)} terms")

    def copy_last(self, _):
        if self.last_text:
            subprocess.run(["pbcopy"], input=self.last_text.encode(), check=False)

    # ---------- island (bottom-screen HUD) ----------
    def _island_tick(self, _):
        try:
            self.island.set_state(self.state)
            self.island.tick()
        except Exception:
            pass

    # ---------- status tick ----------
    def _tick(self, _):
        # Plain-text glyphs: emoji status-bar titles can render zero-width on some
        # macOS builds, making the item look missing.
        icons = {"loading": "LF·", "idle": "LF", "rec": "● REC", "work": "LF…", "error": "LF !"}
        labels = {
            "loading": "Loading model…",
            "idle": "Ready — hold %s to talk" % CFG["hotkey"],
            "rec": "Recording…",
            "work": "Transcribing…",
            "error": "Model error — see logs",
        }
        self.title = icons.get(self.state, "LF")
        self.item_status.title = labels.get(self.state, "")
        if self.last_text:
            preview = self.last_text.strip()
            self.item_last.title = "Last: " + (preview[:40] + "…" if len(preview) > 40 else preview)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # Headless pipeline test on a wav file: python flow.py --selftest file.wav
        import soundfile as sf
        wav = sys.argv[sys.argv.index("--selftest") + 1]
        data, sr = sf.read(wav, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        asr = Transcriber(CFG["asr_model"])
        if sr != asr.sample_rate:
            import librosa
            data = librosa.resample(data, orig_sr=sr, target_sr=asr.sample_rate)
        terms, corr = dictmod.load(DICT_PATH)
        raw = asr.transcribe(data, prompt=", ".join(terms))
        fixed = dictmod.apply_literal_corrections(raw, corr)
        fixed = dictmod.normalize_acronyms(fixed, dictmod.acronym_set(terms))
        cl = Cleaner(CFG["ollama_url"], CFG["ollama_model"], CFG["cleanup_timeout_seconds"],
                     CFG.get("max_glossary_terms", 240))
        if cl.available():
            tw = time.time(); cl.warm(terms); print(f"(warm {time.time()-tw:.1f}s)")
            tc = time.time(); final = cl.clean(fixed, terms); print(f"(clean {time.time()-tc:.1f}s)")
        else:
            final = fixed
        print("RAW  :", raw)
        print("FINAL:", final)
        sys.exit(0)

    # Single-instance lock: a second launch just exits, so you can never end up
    # with two menu-bar icons / two hotkey listeners.
    import fcntl
    _lock = open(os.path.join(BASE, ".flow.lock"), "w")
    try:
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[flow] LocalFlow is already running — this instance is exiting.")
        sys.exit(0)
    _lock.write(str(os.getpid()))
    _lock.flush()

    LocalFlow().run()
