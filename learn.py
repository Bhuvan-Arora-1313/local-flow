"""Opt-in vocabulary learning, triggered by correcting a dictation.

Typing is watched only for a short window right after LocalFlow pastes a
transcript -- not continuously. The idea: if you just dictated something and
go back to fix a misheard word by typing the correct one, that's a strong,
deliberate signal of a real term worth learning (unlike any random word
you happen to type twice during ordinary keyboard use, which was the old
behaviour and the reason this used to feel intrusive). A "word" that is NOT
an ordinary English word, is not already in your dictionary, and is typed
during that window gets added to learned.txt, which feeds the same glossary
as dictionary.txt.

Only individual word tokens are ever examined or stored — never phrases,
sentences, or context, and only during the correction window, not all the
time. macOS blocks keystroke taps while you type in password fields, so
those are never seen. Nothing leaves the machine.
"""
import os
import re
import time
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
LEARNED = os.path.join(BASE, "learned.txt")
_SYS_WORDS = "/usr/share/dict/words"
_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9][A-Za-z0-9._+\-]*$")


def load_learned() -> list[str]:
    out = []
    try:
        with open(LEARNED, "r", encoding="utf-8") as f:
            for line in f:
                w = line.strip()
                if w and not w.startswith("#"):
                    out.append(w)
    except OSError:
        pass
    return out


class Learner:
    def __init__(self, terms_getter, window_seconds: float = 60.0):
        self.enabled = False
        self.window_seconds = window_seconds
        self._terms_getter = terms_getter
        self._buf = ""
        self._window_until = 0.0
        self._english: set[str] = set()
        self._learned: set[str] = set(w.lower() for w in load_learned())
        self._blocked: set[str] = set()        # explicitly undone -- never re-learn
        self._new = False
        self._pending: list[str] = []          # words added but not yet shown to the user
        self._lock = threading.Lock()
        threading.Thread(target=self._load_english, daemon=True).start()

    def _load_english(self):
        try:
            with open(_SYS_WORDS, "r", encoding="utf-8", errors="ignore") as f:
                self._english = {w.strip().lower() for w in f if w.strip()}
        except OSError:
            self._english = set()

    def set_enabled(self, on: bool):
        self.enabled = bool(on)
        if not self.enabled:
            self._buf = ""
            self._window_until = 0.0

    def arm_correction_window(self):
        """Call this right after a dictation's text is pasted/copied. Typing
        done in the next window_seconds is treated as likely corrections to
        that dictation (go fix a misheard word -> we're watching for exactly
        that). Typing outside this window is never examined."""
        if self.enabled:
            self._window_until = time.time() + self.window_seconds

    def _watching(self) -> bool:
        return time.time() < self._window_until

    # fed from flow._on_press for every key while enabled
    def feed(self, key):
        if not self.enabled or not self._watching():
            return
        try:
            ch = getattr(key, "char", None)
            if ch and (ch.isalnum() or ch in "._+-"):
                self._buf += ch
                if len(self._buf) > 40:
                    self._buf = ""
            else:
                w, self._buf = self._buf, ""
                if w:
                    self._consider(w)
        except Exception:
            self._buf = ""

    def _consider(self, w: str):
        w = w.strip("._+-")
        if len(w) < 3 or len(w) > 40 or w.isdigit() or not _TOKEN.match(w):
            return
        lw = w.lower()
        if lw in self._english or lw in self._learned or lw in self._blocked:
            return
        try:
            if lw in {t.lower() for t in self._terms_getter()}:
                return
        except Exception:
            pass
        # a single occurrence is enough: typing it during the correction
        # window right after a dictation is already a deliberate, specific
        # signal, unlike spotting the same word typed twice anywhere.
        self._add(w)

    def _add(self, w: str):
        self._learned.add(w.lower())
        try:
            with open(LEARNED, "a", encoding="utf-8") as f:
                f.write(w + "\n")
            self._new = True
            with self._lock:
                self._pending.append(w)
            print(f"[learn] added {w!r}")
        except OSError:
            pass

    def forget(self, w: str):
        """Undo: remove a word from learned.txt and never re-learn it."""
        lw = w.lower()
        self._learned.discard(lw)
        self._blocked.add(lw)
        try:
            lines = load_learned()
            with open(LEARNED, "w", encoding="utf-8") as f:
                for x in lines:
                    if x.lower() != lw:
                        f.write(x + "\n")
        except OSError:
            pass
        self._new = True

    def pop_pending(self) -> list[str]:
        with self._lock:
            p, self._pending = self._pending, []
        return p

    def count(self) -> int:
        return len(self._learned)

    def take_dirty(self) -> bool:
        d, self._new = self._new, False
        return d

    def clear(self):
        self._learned.clear()
        self._blocked.clear()
        try:
            os.remove(LEARNED)
        except OSError:
            pass
        self._new = True
