"""Native Settings window for LocalFlow (AppKit / PyObjC)."""
import os
import json
import plistlib
import subprocess

import objc
import AppKit
from Foundation import NSObject, NSMakeRect

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "config.json")
DICT = os.path.join(BASE, "dictionary.txt")
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.localflow.dictation.plist")
LABEL = "com.localflow.dictation"

HOTKEYS = [
    ("Right Option  ⌥", "alt_r"),
    ("Left Option  ⌥", "alt_l"),
    ("Right Command  ⌘", "cmd_r"),
    ("Right Control  ⌃", "ctrl_r"),
    ("Right Shift  ⇧", "shift_r"),
    ("F5", "f5"), ("F6", "f6"), ("F13", "f13"), ("F14", "f14"),
    ("F15", "f15"), ("F16", "f16"), ("F17", "f17"), ("F18", "f18"), ("F19", "f19"),
]
MODES = [
    ("Hold to talk — double-tap to lock hands-free", "hold_or_lock"),
    ("Hold to talk (release to send)", "push_to_talk"),
    ("Press once to start, again to stop", "toggle"),
]
ASR_MODELS = [
    ("Parakeet — fastest, English / European", "mlx-community/parakeet-tdt-0.6b-v3"),
    ("Whisper large-v3-turbo — multilingual, Hinglish", "mlx-community/whisper-large-v3-turbo"),
    ("Whisper large-v3 — most accurate, slower", "mlx-community/whisper-large-v3-mlx"),
]
HINDI_SCRIPT = [
    ("हिंदी (Devanagari)", "devanagari"),
    ("Roman / Hinglish (kya haal hai)", "latin"),
]
LANGS = [
    ("Auto-detect", "auto"), ("English", "en"), ("Hindi / Hinglish", "hi"),
    ("Spanish", "es"), ("French", "fr"), ("German", "de"), ("Portuguese", "pt"),
    ("Italian", "it"), ("Dutch", "nl"), ("Japanese", "ja"), ("Chinese", "zh"),
    ("Korean", "ko"), ("Arabic", "ar"), ("Russian", "ru"),
]


# ---------- open-at-login (LaunchAgent) ----------
def login_enabled() -> bool:
    return os.path.exists(PLIST)


def set_login(on: bool):
    exe = AppKit.NSBundle.mainBundle().executablePath()
    dom = f"gui/{os.getuid()}"
    if on:
        data = {
            "Label": LABEL,
            "ProgramArguments": [exe],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 10,
            "LimitLoadToSessionType": "Aqua",
            "ProcessType": "Interactive",
            "StandardOutPath": os.path.join(BASE, "localflow.log"),
            "StandardErrorPath": os.path.join(BASE, "localflow.log"),
        }
        os.makedirs(os.path.dirname(PLIST), exist_ok=True)
        with open(PLIST, "wb") as f:
            plistlib.dump(data, f)
        subprocess.run(["launchctl", "bootout", f"{dom}/{LABEL}"],
                       capture_output=True)
        subprocess.run(["launchctl", "bootstrap", dom, PLIST], capture_output=True)
    else:
        subprocess.run(["launchctl", "bootout", f"{dom}/{LABEL}"], capture_output=True)
        try:
            os.remove(PLIST)
        except OSError:
            pass


# ---------- config i/o ----------
_DEFAULT = os.path.join(BASE, "config.default.json")


def load_cfg() -> dict:
    for path in (CONFIG, _DEFAULT):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
        except (OSError, ValueError):
            continue
    return {}


def save_cfg(cfg: dict):
    # atomic: write to a temp file then rename, so a crash never truncates config
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CONFIG)


class _Actions(NSObject):
    def initWithOwner_(self, owner):
        self = objc.super(_Actions, self).init()
        if self is None:
            return None
        self._owner = owner
        return self

    def checkbox_(self, sender):
        self._owner._on_checkbox(sender)

    def save_(self, sender):
        self._owner._save()

    def saveDict_(self, sender):
        self._owner._save_dict()

    def close_(self, sender):
        self._owner.window.orderOut_(None)

    def openDictFile_(self, sender):
        subprocess.Popen(["open", "-t", DICT])

    def openUsage_(self, sender):
        self._owner._open_usage()


class SettingsWindow:
    """Owns one NSWindow. Call .show()."""

    def __init__(self, app):
        self.app = app
        self.window = None
        self.controls = {}
        self.act = _Actions.alloc().initWithOwner_(self)

    # ---------- build ----------
    def _build(self):
        W, H = 520, 928
        style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable)
        win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), style, AppKit.NSBackingStoreBuffered, False)
        win.setTitle_("LocalFlow Settings")
        win.setReleasedWhenClosed_(False)
        win.center()
        content = win.contentView()

        y = H - 40
        cfg = load_cfg()

        def label(text, size=13, bold=False, dy=22):
            nonlocal y
            lb = AppKit.NSTextField.labelWithString_(text)
            f = (AppKit.NSFont.boldSystemFontOfSize_(size) if bold
                 else AppKit.NSFont.systemFontOfSize_(size))
            lb.setFont_(f)
            lb.setFrame_(NSMakeRect(20, y, W - 40, dy))
            content.addSubview_(lb)
            y -= dy + 6

        def check(key, text, default=True):
            nonlocal y
            b = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(22, y, W - 44, 20))
            b.setButtonType_(AppKit.NSButtonTypeSwitch)
            b.setTitle_(" " + text)
            b.setState_(1 if cfg.get(key, default) else 0)
            b.setTarget_(self.act)
            b.setAction_(b"checkbox:")
            b.setIdentifier_(key)
            content.addSubview_(b)
            self.controls[key] = b
            y -= 26

        def textrow(key, text, value, width=180):
            nonlocal y
            lb = AppKit.NSTextField.labelWithString_(text)
            lb.setFrame_(NSMakeRect(22, y, 150, 20))
            content.addSubview_(lb)
            tf = AppKit.NSTextField.alloc().initWithFrame_(
                NSMakeRect(180, y - 2, width, 24))
            tf.setStringValue_(str(value))
            content.addSubview_(tf)
            self.controls[key] = tf
            y -= 30

        def popup(key, text, items, cur, width=300):
            nonlocal y
            lb = AppKit.NSTextField.labelWithString_(text)
            lb.setFrame_(NSMakeRect(22, y, 150, 20))
            content.addSubview_(lb)
            pu = AppKit.NSPopUpButton.alloc().initWithFrame_(
                NSMakeRect(178, y - 3, width, 26))
            for lbl, _v in items:
                pu.addItemWithTitle_(lbl)
            for lbl, v in items:
                if v == cur:
                    pu.selectItemWithTitle_(lbl)
                    break
            content.addSubview_(pu)
            self.controls[key] = pu
            y -= 34

        label("General", bold=True)
        # login checkbox (not stored in config.json; reflects the LaunchAgent)
        b = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(22, y, W - 44, 20))
        b.setButtonType_(AppKit.NSButtonTypeSwitch)
        b.setTitle_(" Start LocalFlow at login")
        b.setState_(1 if login_enabled() else 0)
        b.setTarget_(self.act)
        b.setAction_(b"checkbox:")
        b.setIdentifier_("_login")
        content.addSubview_(b)
        self.controls["_login"] = b
        y -= 26

        check("cleanup_enabled", "AI cleanup — fix jargon, drop “um / uh”")
        check("smart_formatting", "Smart formatting — spoken lists become bullets / numbers")
        check("keep_model_loaded", "Keep the AI model always loaded — no wake-up lag (more RAM)")
        check("island", "Show the waveform island while dictating")
        check("sounds", "Play start / done sounds")
        check("auto_paste", "Paste automatically (off = just copy)")
        check("trailing_space", "Add a space after each dictation")
        check("notify", "Show notifications")
        check("learn_words", "Learn new words as I type", default=False)
        hint = AppKit.NSTextField.labelWithString_(
            "   Unusual words you type 2+ times get added to the glossary. "
            "Only single words, all local.")
        hint.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        hint.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        hint.setFrame_(NSMakeRect(22, y, W - 44, 16))
        content.addSubview_(hint)
        y -= 24

        y -= 6
        label("Keys & models  (restart LocalFlow to apply these)", bold=True)
        popup("hotkey", "Hotkey", HOTKEYS, cfg.get("hotkey", "alt_l"), 240)
        popup("mode", "Recording style", MODES, cfg.get("mode", "hold_or_lock"))
        popup("asr_model", "Speech model", ASR_MODELS,
              cfg.get("asr_model", ASR_MODELS[0][1]))
        popup("asr_language", "Language", LANGS, cfg.get("asr_language", "auto"), 200)
        popup("hindi_script", "Hindi text as", HINDI_SCRIPT,
              cfg.get("hindi_script", "devanagari"), 260)
        textrow("ollama_model", "Ollama model", cfg.get("ollama_model", "qwen3:8b"), 180)

        # usage button
        bu = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(178, y, 220, 28))
        bu.setTitle_("Usage & History…")
        bu.setBezelStyle_(AppKit.NSBezelStyleRounded)
        bu.setTarget_(self.act)
        bu.setAction_(b"openUsage:")
        content.addSubview_(bu)
        y -= 36

        y -= 4
        label("Dictionary — your names, product names, jargon", bold=True)
        hint = AppKit.NSTextField.labelWithString_(
            "One per line.  “wrong => right” lines are auto-replaced.")
        hint.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        hint.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        hint.setFrame_(NSMakeRect(22, y, W - 44, 18))
        content.addSubview_(hint)
        y -= 24

        sv = AppKit.NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 70, W - 40, y - 70))
        sv.setHasVerticalScroller_(True)
        sv.setBorderType_(AppKit.NSBezelBorder)
        tv = AppKit.NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, W - 60, y - 70))
        tv.setFont_(AppKit.NSFont.monospacedSystemFontOfSize_weight_(11, 0))
        tv.setAutomaticQuoteSubstitutionEnabled_(False)
        tv.setAutomaticDashSubstitutionEnabled_(False)
        tv.setRichText_(False)
        try:
            with open(DICT, "r", encoding="utf-8") as f:
                tv.setString_(f.read())
        except OSError:
            pass
        sv.setDocumentView_(tv)
        content.addSubview_(sv)
        self.controls["_dict"] = tv

        # buttons
        bd = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(20, 34, 150, 28))
        bd.setTitle_("Save Dictionary")
        bd.setBezelStyle_(AppKit.NSBezelStyleRounded)
        bd.setTarget_(self.act)
        bd.setAction_(b"saveDict:")
        content.addSubview_(bd)

        be = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(176, 34, 130, 28))
        be.setTitle_("Open in editor")
        be.setBezelStyle_(AppKit.NSBezelStyleRounded)
        be.setTarget_(self.act)
        be.setAction_(b"openDictFile:")
        content.addSubview_(be)

        bs = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(W - 210, 34, 90, 28))
        bs.setTitle_("Close")
        bs.setBezelStyle_(AppKit.NSBezelStyleRounded)
        bs.setTarget_(self.act)
        bs.setAction_(b"close:")
        content.addSubview_(bs)

        bsave = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(W - 115, 34, 95, 28))
        bsave.setTitle_("Save")
        bsave.setBezelStyle_(AppKit.NSBezelStyleRounded)
        bsave.setKeyEquivalent_("\r")
        bsave.setTarget_(self.act)
        bsave.setAction_(b"save:")
        content.addSubview_(bsave)

        self.window = win

    # ---------- actions ----------
    def _on_checkbox(self, sender):
        key = sender.identifier()
        on = bool(sender.state())
        if key == "_login":
            try:
                set_login(on)
            except Exception as e:
                self._alert("Couldn't change login item", str(e))
                sender.setState_(1 if login_enabled() else 0)
            return
        # live-apply the simple toggles
        if key == "cleanup_enabled":
            self.app.cleanup_on = on
        elif key == "island" and not on and self.app.island is not None:
            try:
                self.app.island.hide()
            except Exception:
                pass
        elif key == "learn_words":
            try:
                self.app.set_learn(on)
            except Exception:
                pass
        elif key == "keep_model_loaded":
            try:
                self.app.cleaner.keep_loaded = on
                if on:
                    import threading
                    threading.Thread(target=self.app.cleaner.ping, daemon=True).start()
            except Exception:
                pass
        cfg = load_cfg()
        cfg[key] = on
        save_cfg(cfg)

    def _save(self):
        cfg = load_cfg()
        for key in ("cleanup_enabled", "smart_formatting", "keep_model_loaded", "island",
                    "sounds", "auto_paste", "trailing_space", "notify", "learn_words"):
            cfg[key] = bool(self.controls[key].state())
        cfg["hotkey"] = dict(HOTKEYS).get(self.controls["hotkey"].titleOfSelectedItem(), "alt_l")
        cfg["mode"] = dict(MODES).get(self.controls["mode"].titleOfSelectedItem(), "hold_or_lock")
        cfg["asr_model"] = dict(ASR_MODELS).get(
            self.controls["asr_model"].titleOfSelectedItem(), ASR_MODELS[0][1])
        cfg["asr_language"] = dict(LANGS).get(
            self.controls["asr_language"].titleOfSelectedItem(), "auto")
        cfg["hindi_script"] = dict(HINDI_SCRIPT).get(
            self.controls["hindi_script"].titleOfSelectedItem(), "devanagari")
        cfg["ollama_model"] = self.controls["ollama_model"].stringValue().strip() or "qwen3:8b"
        save_cfg(cfg)
        # live where possible
        self.app.cleanup_on = cfg["cleanup_enabled"]
        try:
            self.app.cleaner.model = cfg["ollama_model"]
        except Exception:
            pass
        globals_apply(cfg)
        self._save_dict(silent=True)
        self._alert("Saved",
                    "Settings saved. Hotkey / mode / model changes take effect "
                    "after you quit and reopen LocalFlow.")

    def _save_dict(self, silent=False):
        tv = self.controls["_dict"]
        text = tv.string()
        try:
            with open(DICT, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            self._alert("Couldn't save dictionary", str(e))
            return
        try:
            self.app.reload_dict()
        except Exception:
            pass
        if not silent:
            self._alert("Dictionary saved", "Reloaded — new terms are active now.")

    def _alert(self, title, msg):
        a = AppKit.NSAlert.alloc().init()
        a.setMessageText_(title)
        a.setInformativeText_(msg)
        a.runModal()

    def _open_usage(self):
        import usage
        if getattr(self, "_usage_win", None) is None:
            self._usage_win = usage.UsageWindow()
        self._usage_win.show()

    # ---------- show ----------
    def show(self):
        if self.window is None:
            self._build()
        AppKit.NSApp().activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)


def globals_apply(cfg: dict):
    """Push edited values into the running flow module's CFG dict."""
    import sys
    for name in ("__main__", "flow"):
        m = sys.modules.get(name)
        if m is not None and hasattr(m, "CFG"):
            try:
                m.CFG.update(cfg)
            except Exception:
                pass
