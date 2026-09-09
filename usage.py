"""Usage tracking + a small History/Stats window."""
import os
import json
import time
import threading
import datetime as _dt

import objc
import AppKit
from Foundation import NSObject, NSMakeRect

BASE = os.path.dirname(os.path.abspath(__file__))
HISTORY = os.path.join(BASE, "history.jsonl")
STATS = os.path.join(BASE, "stats.json")
_MAX_LINES = 3000
_lock = threading.Lock()


# ---------------- data ----------------
def record(text: str):
    text = (text or "").strip()
    if not text:
        return
    words = len(text.split())
    now = time.time()
    with _lock:
        try:
            with open(HISTORY, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": now, "w": words, "c": len(text),
                                    "text": text[:2000]}, ensure_ascii=False) + "\n")
        except OSError:
            pass
        _bump_stats(words, len(text), now)
        _maybe_trim()


def _bump_stats(words, chars, now):
    s = _read_stats()
    s["total_words"] = s.get("total_words", 0) + words
    s["total_chars"] = s.get("total_chars", 0) + chars
    s["total_dictations"] = s.get("total_dictations", 0) + 1
    s.setdefault("first_use", now)
    try:
        with open(STATS, "w", encoding="utf-8") as f:
            json.dump(s, f)
    except OSError:
        pass


def _read_stats() -> dict:
    try:
        with open(STATS, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _maybe_trim():
    try:
        if os.path.getsize(HISTORY) < 800_000:
            return
        with open(HISTORY, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > _MAX_LINES:
            with open(HISTORY, "w", encoding="utf-8") as f:
                f.writelines(lines[-_MAX_LINES:])
    except OSError:
        pass


def _iter_history():
    try:
        with open(HISTORY, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        pass
    except OSError:
        return


def summary() -> dict:
    s = _read_stats()
    entries = list(_iter_history())
    days = {}
    for e in entries:
        d = _dt.date.fromtimestamp(e.get("t", 0)).isoformat()
        days[d] = days.get(d, 0) + e.get("w", 0)

    # streak: consecutive days up to today (or yesterday) with any usage
    streak = 0
    day = _dt.date.today()
    if day.isoformat() not in days:
        day = day - _dt.timedelta(days=1)
    while day.isoformat() in days:
        streak += 1
        day = day - _dt.timedelta(days=1)

    today = _dt.date.today().isoformat()
    wk_start = _dt.date.today() - _dt.timedelta(days=6)
    week_words = sum(w for d, w in days.items() if d >= wk_start.isoformat())

    total_words = s.get("total_words") or sum(e.get("w", 0) for e in entries)
    total_dict = s.get("total_dictations") or len(entries)
    first = s.get("first_use")
    return {
        "total_words": total_words,
        "total_dictations": total_dict,
        "days_used": len(days),
        "streak": streak,
        "today_words": days.get(today, 0),
        "week_words": week_words,
        "first_use": first,
        "recent": list(reversed(entries))[:80],
    }


def clear():
    with _lock:
        for p in (HISTORY, STATS):
            try:
                os.remove(p)
            except OSError:
                pass


# ---------------- window ----------------
class _UActions(NSObject):
    def initWithOwner_(self, owner):
        self = objc.super(_UActions, self).init()
        if self is None:
            return None
        self._owner = owner
        return self

    def refresh_(self, sender):
        self._owner.refresh()

    def copyAll_(self, sender):
        self._owner.copy_all()

    def clearAll_(self, sender):
        self._owner.clear_all()

    def close_(self, sender):
        self._owner.window.orderOut_(None)


class UsageWindow:
    def __init__(self):
        self.window = None
        self.act = _UActions.alloc().initWithOwner_(self)
        self._tv = None
        self._stat = None

    def _build(self):
        W, H = 560, 620
        style = AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
        win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), style, AppKit.NSBackingStoreBuffered, False)
        win.setTitle_("LocalFlow — Usage & History")
        win.setReleasedWhenClosed_(False)
        win.center()
        c = win.contentView()

        self._stat = AppKit.NSTextField.labelWithString_("")
        self._stat.setFont_(AppKit.NSFont.systemFontOfSize_(13))
        self._stat.setFrame_(NSMakeRect(20, H - 90, W - 40, 62))
        self._stat.setLineBreakMode_(0)  # word wrap
        try:
            self._stat.setMaximumNumberOfLines_(3)
        except Exception:
            pass
        c.addSubview_(self._stat)

        hdr = AppKit.NSTextField.labelWithString_("Recent transcripts")
        hdr.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
        hdr.setFrame_(NSMakeRect(20, H - 116, 300, 20))
        c.addSubview_(hdr)

        sv = AppKit.NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 56, W - 40, H - 180))
        sv.setHasVerticalScroller_(True)
        sv.setBorderType_(AppKit.NSBezelBorder)
        tv = AppKit.NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, W - 60, H - 180))
        tv.setEditable_(False)
        tv.setFont_(AppKit.NSFont.systemFontOfSize_(12))
        sv.setDocumentView_(tv)
        c.addSubview_(sv)
        self._tv = tv

        def btn(x, w, title, sel):
            b = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(x, 16, w, 28))
            b.setTitle_(title)
            b.setBezelStyle_(AppKit.NSBezelStyleRounded)
            b.setTarget_(self.act)
            b.setAction_(sel)
            c.addSubview_(b)
            return b

        btn(20, 90, "Refresh", b"refresh:")
        btn(114, 110, "Copy all", b"copyAll:")
        btn(228, 130, "Clear history…", b"clearAll:")
        btn(W - 100, 80, "Close", b"close:")

        self.window = win

    def refresh(self):
        s = summary()
        first = ""
        if s.get("first_use"):
            first = "  ·  since " + _dt.date.fromtimestamp(s["first_use"]).strftime("%b %-d, %Y")
        self._stat.setStringValue_(
            f"{s['total_words']:,} words   ·   {s['total_dictations']:,} dictations   ·   "
            f"{s['streak']}-day streak\n"
            f"{s['today_words']:,} words today   ·   {s['week_words']:,} this week   ·   "
            f"used on {s['days_used']} day(s){first}")
        lines = []
        for e in s["recent"]:
            ts = _dt.datetime.fromtimestamp(e.get("t", 0)).strftime("%b %-d  %H:%M")
            lines.append(f"[{ts}]  {e.get('text','')}")
        self._tv.setString_("\n\n".join(lines) if lines else "No transcripts yet.")

    def copy_all(self):
        pb = AppKit.NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(self._tv.string(), AppKit.NSPasteboardTypeString)

    def clear_all(self):
        a = AppKit.NSAlert.alloc().init()
        a.setMessageText_("Clear all history and stats?")
        a.setInformativeText_("This can't be undone.")
        a.addButtonWithTitle_("Clear")
        a.addButtonWithTitle_("Cancel")
        if a.runModal() == AppKit.NSAlertFirstButtonReturn:
            clear()
            self.refresh()

    def show(self):
        if self.window is None:
            self._build()
        self.refresh()
        AppKit.NSApp().activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)
