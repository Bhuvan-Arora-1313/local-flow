"""Opt-in vocabulary learning.

When enabled, examines the words you type (fed from the existing hotkey key
listener — no second listener). A "word" that is NOT an ordinary English word,
is not already in your dictionary, and shows up 2+ times gets added to
learned.txt, which feeds the same glossary as dictionary.txt.

Only individual word tokens are ever examined or stored — never phrases,
sentences, or context. macOS blocks keystroke taps while you type in password
fields, so those are never seen. Nothing leaves the machine.
"""
import os
import re
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
    def __init__(self, terms_getter, min_count: int = 2):
        self.enabled = False
        self.min_count = min_count
        self._terms_getter = terms_getter
        self._buf = ""
        self._counts: dict[str, int] = {}
        self._english: set[str] = set()
        self._learned: set[str] = set(w.lower() for w in load_learned())
        self._new = False
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

    # fed from flow._on_press for every key while enabled
    def feed(self, key):
        if not self.enabled:
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
        if lw in self._english or lw in self._learned:
            return
        try:
            if lw in {t.lower() for t in self._terms_getter()}:
                return
        except Exception:
            pass
        self._counts[lw] = self._counts.get(lw, 0) + 1
        if self._counts[lw] >= self.min_count:
            self._add(w)

    def _add(self, w: str):
        self._learned.add(w.lower())
        try:
            with open(LEARNED, "a", encoding="utf-8") as f:
                f.write(w + "\n")
            self._new = True
            print(f"[learn] added {w!r}")
        except OSError:
            pass

    def count(self) -> int:
        return len(self._learned)

    def take_dirty(self) -> bool:
        d, self._new = self._new, False
        return d

    def clear(self):
        self._learned.clear()
        self._counts.clear()
        try:
            os.remove(LEARNED)
        except OSError:
            pass
        self._new = True
