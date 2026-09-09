#!/usr/bin/env python3
"""LocalFlow - a local, on-device dictation tool (a free Wispr Flow).

Hold the hotkey, talk, release. Audio -> Parakeet (MLX, on-GPU) -> local LLM
cleanup (Ollama) -> text is pasted at your cursor. Nothing leaves the machine.

The menu-bar item is built directly with AppKit (no rumps) so it registers
reliably however the app is launched.
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
from pynput import keyboard  # noqa: E402

from recorder import Recorder  # noqa: E402
from asr import Transcriber  # noqa: E402
try:
    from island import Island  # noqa: E402
except Exception as _e:
    Island = None
    print(f"[flow] island unavailable: {_e}")
from cleanup import Cleaner  # noqa: E402
import dictionary as dictmod  # noqa: E402
import inserter  # noqa: E402
try:
    import usage  # noqa: E402
except Exception:
    usage = None
try:
    import learn  # noqa: E402
except Exception:
    learn = None

DICT_PATH = os.path.join(BASE, "dictionary.txt")

SOUNDS = {
    "start": "/System/Library/Sounds/Tink.aiff",
    "done": "/System/Library/Sounds/Pop.aiff",
    "error": "/System/Library/Sounds/Basso.aiff",
}


def notify(title: str, msg: str):
    if not CFG.get("notify", True):
        return
    try:
        subprocess.Popen(
            ["osascript", "-e", f'display notification "{msg}" with title "{title}"'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
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


class App:
    """All the dictation logic; UI-framework-agnostic."""

    def __init__(self):
        self.state = "loading"          # loading | idle | rec | work | error
        self.asr = None
        self.last_text = ""
        self.cleanup_on = CFG.get("cleanup_enabled", True)
        self._jobs: queue.Queue = queue.Queue()
        self._hotkey = resolve_key(CFG["hotkey"])
        self._hotkey_down = False
        self._toggle_on = False
        self._locked = False
        self._press_t = 0.0
        self._release_timer = None
        self.mode = CFG.get("mode", "hold_or_lock")

        self.rec = Recorder(CFG.get("sample_rate", 16000))
        self.cleaner = Cleaner(
            CFG.get("ollama_url", "http://localhost:11434"),
            CFG.get("ollama_model", "qwen3:8b"),
            CFG.get("cleanup_timeout_seconds", 30),
            CFG.get("max_glossary_terms", 240),
        )
        self._reload_terms()
        self.learner = None
        if learn is not None:
            try:
                self.learner = learn.Learner(lambda: self.terms)
            except Exception as e:
                print(f"[flow] learner init failed: {e}")

        self.island = None
        if CFG.get("island", True) and Island is not None:
            try:
                self.island = Island(lambda: (self.state, *self.rec.snapshot()))
            except Exception as e:
                print(f"[flow] island init failed: {e}")

    def _reload_terms(self):
        terms, self.corrections = dictmod.load(DICT_PATH)
        if learn is not None:
            terms = terms + learn.load_learned()
        seen, uniq = set(), []
        for t in terms:
            if t.lower() not in seen:
                seen.add(t.lower())
                uniq.append(t)
        self.terms = uniq
        self.acronyms = dictmod.acronym_set(self.terms)

    def start_background(self):
        threading.Thread(target=self._load_model, daemon=True).start()
        threading.Thread(target=self._worker, daemon=True).start()
        if self.cleanup_on:
            threading.Thread(
                target=lambda: self.cleaner.available() and self.cleaner.warm(self.terms),
                daemon=True,
            ).start()
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        if self.learner is not None and CFG.get("learn_words", False):
            self.learner.set_enabled(True)

    # ---------- model ----------
    def _load_model(self):
        for attempt in (1, 2):
            try:
                self.asr = Transcriber(CFG["asr_model"], CFG.get("sample_rate", 16000),
                                       CFG.get("asr_language", "auto"))
                self.rec.sample_rate = self.asr.sample_rate
                self.state = "idle"
                return
            except Exception as e:
                # offline env is set once Parakeet is cached; if the user switched
                # to a model that isn't downloaded yet, retry with network on.
                if attempt == 1 and os.environ.pop("HF_HUB_OFFLINE", None):
                    os.environ.pop("TRANSFORMERS_OFFLINE", None)
                    print("[flow] model not cached — retrying download with network…")
                    continue
                print(f"[flow] model load failed: {e}")
                self.state = "error"

    # ---------- hotkey ----------
    def _on_press(self, key):
        if key != self._hotkey:
            return
        m = self.mode
        if m == "push_to_talk":
            if self._hotkey_down:
                return
            self._hotkey_down = True
            self._begin()
        elif m == "toggle":
            self._toggle_on = not self._toggle_on
            self._begin() if self._toggle_on else self._end()
        else:  # hold_or_lock
            self._hotkey_down = True
            if self._locked:
                self._locked = False
                self._end()
                return
            if self._cancel_release_timer():
                # pending stop from a quick first tap -> this press is the 2nd
                # tap of a double-tap: lock hands-free
                self._locked = True
                return
            self._press_t = time.time()
            self._begin()

    def _on_release(self, key):
        if key != self._hotkey:
            return
        m = self.mode
        if m == "push_to_talk":
            self._hotkey_down = False
            self._end()
        elif m == "toggle":
            pass
        else:  # hold_or_lock
            self._hotkey_down = False
            if self._locked or self.state != "rec":
                return
            if time.time() - self._press_t < 0.35:
                t = threading.Timer(0.4, self._release_finalize)
                t.daemon = True
                self._release_timer = t
                t.start()
            else:
                self._end()

    def _cancel_release_timer(self) -> bool:
        t = self._release_timer
        self._release_timer = None
        if t is not None:
            t.cancel()
            return True
        return False

    def _release_finalize(self):
        self._release_timer = None
        if self._locked or self._hotkey_down:
            return
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
                if self.cleanup_on and self.cleaner.available():
                    text = self.cleaner.clean(
                        text, self.terms,
                        smart_format=CFG.get("smart_formatting", True))
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
                    if usage is not None:
                        try:
                            usage.record(text)
                        except Exception:
                            pass
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

    # ---------- menu actions ----------
    def reload_dict(self):
        self._reload_terms()
        notify("LocalFlow", f"Dictionary reloaded — {len(self.terms)} terms")

    def set_learn(self, on: bool):
        if self.learner is not None:
            self.learner.set_enabled(on)

    def copy_last(self):
        if self.last_text:
            subprocess.run(["pbcopy"], input=self.last_text.encode(), check=False)

    # ---------- text for the UI ----------
    def status_glyph(self):
        return {"loading": "LF·", "idle": "LF", "rec": "● REC",
                "work": "LF…", "error": "LF!"}.get(self.state, "LF")

    def status_label(self):
        return {
            "loading": "Loading model…",
            "idle": "Ready — hold %s to talk" % CFG["hotkey"],
            "rec": "Recording…",
            "work": "Transcribing…",
            "error": "Model error — see localflow.log",
        }.get(self.state, "")


# ======================================================================
#  AppKit menu-bar shell
# ======================================================================
def run_app(app: App):
    import AppKit
    from Foundation import NSTimer

    NSApp = AppKit.NSApplication.sharedApplication()
    # accessory = menu-bar app, no Dock icon
    ok = NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    NSApp.finishLaunching()
    print(f"[flow] setActivationPolicy ok={ok} policy={NSApp.activationPolicy()}")

    # Ask for Accessibility (pynput's hotkey + paste need it). The prompting
    # variant puts LocalFlow into System Settings' Accessibility list and shows
    # the standard "Open System Settings" dialog on first run.
    try:
        import HIServices
        opts = {"AXTrustedCheckOptionPrompt": True}
        trusted = HIServices.AXIsProcessTrustedWithOptions(opts)
        print(f"[flow] AXIsProcessTrusted = {trusted}")
    except Exception as e:
        print(f"[flow] AX prompt failed: {e}")

    class Target(AppKit.NSObject):
        def toggleCleanup_(self, sender):
            app.cleanup_on = not app.cleanup_on
            sender.setState_(1 if app.cleanup_on else 0)

        def reloadDict_(self, sender):
            app.reload_dict()

        def copyLast_(self, sender):
            app.copy_last()

        def openSettings_(self, sender):
            try:
                import settings
                if getattr(app, "_settings_win", None) is None:
                    app._settings_win = settings.SettingsWindow(app)
                app._settings_win.show()
            except Exception as e:
                print(f"[flow] settings failed: {e}")

        def openUsage_(self, sender):
            try:
                import usage as _u
                if getattr(app, "_usage_win", None) is None:
                    app._usage_win = _u.UsageWindow()
                app._usage_win.show()
            except Exception as e:
                print(f"[flow] usage failed: {e}")

        def quitApp_(self, sender):
            AppKit.NSApp().terminate_(None)

    tgt = Target.alloc().init()

    menu = AppKit.NSMenu.alloc().init()

    def add(title, sel=None, key=""):
        it = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key)
        if sel is not None:
            it.setTarget_(tgt)
        else:
            it.setEnabled_(False)
        menu.addItem_(it)
        return it

    mi_status = add("Loading model…")
    mi_last = add("Last: —")
    menu.addItem_(AppKit.NSMenuItem.separatorItem())
    mi_cleanup = add("AI cleanup", b"toggleCleanup:")
    mi_cleanup.setState_(1 if app.cleanup_on else 0)
    add("Copy last transcript", b"copyLast:")
    menu.addItem_(AppKit.NSMenuItem.separatorItem())
    add("Settings…", b"openSettings:", ",")
    add("Usage & History…", b"openUsage:")
    add("Reload dictionary", b"reloadDict:")
    menu.addItem_(AppKit.NSMenuItem.separatorItem())
    add("Quit LocalFlow", b"quitApp:", "q")

    bar = AppKit.NSStatusBar.systemStatusBar()
    status_item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
    btn = status_item.button()
    if btn is not None:
        btn.setTitle_("LF·")
        btn.setImagePosition_(AppKit.NSImageLeft)
    else:
        try:
            status_item.setTitle_("LF·")
        except Exception:
            pass
    try:
        status_item.setVisible_(True)
    except Exception:
        pass
    status_item.setMenu_(menu)
    # keep strong refs so nothing is GC'd out of the menu bar
    app._ui = (NSApp, tgt, menu, status_item, mi_status, mi_last, mi_cleanup)
    print(f"[flow] statusBar={bar!r} item={status_item!r} button={btn!r} "
          f"visible={getattr(status_item, 'isVisible', lambda: '?')()}")

    app.start_background()

    def status_tick():
        try:
            status_item.button().setTitle_(app.status_glyph())
            mi_status.setTitle_(app.status_label())
            if app.last_text:
                p = app.last_text.strip()
                mi_last.setTitle_("Last: " + (p[:40] + "…" if len(p) > 40 else p))
            if app.learner is not None and app.learner.take_dirty():
                app._reload_terms()
        except Exception as e:
            print(f"[flow] status_tick: {e}")

    def island_tick():
        if app.island is None:
            return
        try:
            app.island.set_state(app.state)
            app.island.tick()
        except Exception:
            pass

    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.25, True, lambda t: status_tick())
    if app.island is not None:
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(1 / 30.0, True, lambda t: island_tick())

    print("[flow] menu-bar item created; entering run loop")
    NSApp.run()


def _selftest():
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
    final = cl.clean(fixed, terms) if cl.available() else fixed
    print("RAW  :", raw)
    print("FINAL:", final)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(0)

    # Single-instance lock: a second launch just exits.
    import fcntl
    _lock = open(os.path.join(BASE, ".flow.lock"), "w")
    try:
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[flow] LocalFlow is already running — this instance is exiting.")
        sys.exit(0)
    _lock.write(str(os.getpid()))
    _lock.flush()

    run_app(App())
