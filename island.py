"""The 'island' - a tiny floating pill near the bottom of the screen that appears
only while you're dictating and shows a live spectrum of your voice.

Pure AppKit via PyObjC. All UI calls must happen on the main thread; flow.py drives
tick()/set_state() from a main-thread rumps.Timer.
"""
import time
import math
import numpy as np
import AppKit
from Foundation import NSMakeRect, NSMakePoint

_W, _H = 96.0, 24.0
_PAD_X, _PAD_Y = 10.0, 5.0
_BAR_W = 2.0

_CB = (
    (1 << 0)   # CanJoinAllSpaces
    | (1 << 4)  # Stationary
    | (1 << 6)  # IgnoresCycle
    | (1 << 8)  # FullScreenAuxiliary
)


def _rgba(r, g, b, a):
    return AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)


class WaveView(AppKit.NSView):
    def initWithFrame_(self, frame):
        self = AppKit.NSView.initWithFrame_(self, frame)
        if self is None:
            return None
        self.provider = None
        self.state = "idle"
        self.disp = None
        self._t0 = time.time()
        return self

    # ---- driven from the main-thread timer ----
    def tick(self):
        st = "idle"
        level, bands = 0.0, []
        if self.provider is not None:
            try:
                st, level, bands = self.provider()
            except Exception:
                pass
        self.state = st
        u = np.asarray(bands, dtype=float) if bands else np.zeros(8)
        # mirror low->high around the centre: symmetric, centre-weighted
        target = np.concatenate([u[::-1], u])
        if self.disp is None or len(self.disp) != len(target):
            self.disp = np.zeros(len(target), dtype=float)
        if st == "rec":
            self.disp = np.maximum(target, self.disp * 0.72)
        else:
            self.disp *= 0.80
        self.setNeedsDisplay_(True)

    # ---- drawing ----
    def drawRect_(self, _rect):
        b = self.bounds()
        pill = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            b, b.size.height / 2.0, b.size.height / 2.0
        )
        _rgba(0.09, 0.09, 0.11, 0.92).setFill()
        pill.fill()
        _rgba(1, 1, 1, 0.10).setStroke()
        pill.setLineWidth_(1.0)
        pill.stroke()

        if self.state == "work":
            self._draw_working(b)
        else:
            self._draw_bars(b)

    def _draw_bars(self, b):
        d = self.disp if self.disp is not None else np.zeros(16)
        n = len(d)
        area_w = b.size.width - 2 * _PAD_X
        gap = max(1.5, (area_w - _BAR_W * n) / (n - 1)) if n > 1 else 0.0
        max_h = b.size.height - 2 * _PAD_Y
        mid_y = b.size.height / 2.0
        for i, v in enumerate(d):
            h = 1.5 + float(np.clip(v, 0, 1)) * max_h
            x = _PAD_X + i * (_BAR_W + gap)
            r = NSMakeRect(x, mid_y - h / 2.0, _BAR_W, h)
            path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                r, _BAR_W / 2.0, _BAR_W / 2.0
            )
            a = 0.50 + 0.45 * float(np.clip(v * 1.6, 0, 1))
            _rgba(0.96, 0.98, 1.0, a).setFill()
            path.fill()

    def _draw_working(self, b):
        t = time.time() - self._t0
        cx, cy = b.size.width / 2.0, b.size.height / 2.0
        for i in (-1, 0, 1):
            ph = 0.5 + 0.5 * math.sin(t * 5.0 + i * 1.1)
            r = 1.6 + 1.6 * ph
            _rgba(0.96, 0.98, 1.0, 0.35 + 0.55 * ph).setFill()
            dot = AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(cx + i * 9.0 - r, cy - r, 2 * r, 2 * r)
            )
            dot.fill()


class Island:
    def __init__(self, provider):
        self.provider = provider
        self.panel = None
        self.view = None
        self._visible = False
        self._state = "idle"

    def _ensure(self):
        if self.panel is not None:
            return
        style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        rect = NSMakeRect(0, 0, _W, _H)
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False
        )
        panel.setFloatingPanel_(True)
        panel.setLevel_(AppKit.NSScreenSaverWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setReleasedWhenClosed_(False)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setCollectionBehavior_(_CB)
        view = WaveView.alloc().initWithFrame_(rect)
        view.provider = self.provider
        panel.setContentView_(view)
        self.panel, self.view = panel, view

    def _reposition(self):
        screen = AppKit.NSScreen.mainScreen()
        if screen is None:
            return
        vf = screen.visibleFrame()
        x = vf.origin.x + (vf.size.width - _W) / 2.0
        y = vf.origin.y + 16.0
        self.panel.setFrameOrigin_(NSMakePoint(x, y))

    def set_state(self, state):
        if state == self._state:
            return
        self._state = state
        if state in ("rec", "work"):
            self.show()
        else:
            self.hide()

    def show(self):
        self._ensure()
        self._reposition()
        self.panel.orderFrontRegardless()
        self.panel.invalidateShadow()
        self._visible = True

    def hide(self):
        if self.panel is not None:
            self.panel.orderOut_(None)
        self._visible = False

    def tick(self):
        if self._visible and self.view is not None:
            self.view.tick()


import objc  # noqa: E402
from Foundation import NSTimer  # noqa: E402


class _ToastTarget(AppKit.NSObject):
    def initWithToast_(self, toast):
        self = objc.super(_ToastTarget, self).init()
        if self is None:
            return None
        self._toast = toast
        return self

    def undo_(self, sender):
        self._toast._do_undo()

    def dismiss_(self, sender):
        self._toast.hide()


class Toast:
    """A small transient panel above the island: 'Added "word"'  [Undo]."""

    def __init__(self):
        self.panel = None
        self._label = None
        self._on_undo = None
        self._word = None
        self._timer = None
        self._tgt = _ToastTarget.alloc().initWithToast_(self)

    def _ensure(self):
        if self.panel is not None:
            return
        W, H = 300.0, 40.0
        style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        p = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), style, AppKit.NSBackingStoreBuffered, False)
        p.setFloatingPanel_(True)
        p.setLevel_(AppKit.NSScreenSaverWindowLevel)
        p.setOpaque_(False)
        p.setBackgroundColor_(AppKit.NSColor.clearColor())
        p.setHasShadow_(True)
        p.setReleasedWhenClosed_(False)
        p.setBecomesKeyOnlyIfNeeded_(True)
        p.setCollectionBehavior_(_CB)

        bg = AppKit.NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        bg.setWantsLayer_(True)
        bg.layer().setCornerRadius_(H / 2.0)
        bg.layer().setBackgroundColor_(
            _rgba(0.09, 0.09, 0.11, 0.95).CGColor())
        p.setContentView_(bg)

        lbl = AppKit.NSTextField.labelWithString_("")
        lbl.setFrame_(NSMakeRect(16, 10, W - 90, 20))
        lbl.setFont_(AppKit.NSFont.systemFontOfSize_(12))
        lbl.setTextColor_(AppKit.NSColor.whiteColor())
        bg.addSubview_(lbl)
        self._label = lbl

        btn = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(W - 72, 7, 60, 26))
        btn.setTitle_("Undo")
        btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        btn.setTarget_(self._tgt)
        btn.setAction_(b"undo:")
        bg.addSubview_(btn)

        self.panel = p

    def _position(self):
        screen = AppKit.NSScreen.mainScreen()
        if screen is None:
            return
        vf = screen.visibleFrame()
        fr = self.panel.frame()
        x = vf.origin.x + (vf.size.width - fr.size.width) / 2.0
        y = vf.origin.y + 16.0 + _H + 10.0     # just above the island's spot
        self.panel.setFrameOrigin_(NSMakePoint(x, y))

    def show(self, word, on_undo):
        self._ensure()
        self._word, self._on_undo = word, on_undo
        w = word if len(word) <= 24 else word[:23] + "…"
        self._label.setStringValue_(f'Added  “{w}”  to dictionary')
        self._position()
        self.panel.orderFrontRegardless()
        self.panel.invalidateShadow()
        if self._timer is not None:
            self._timer.invalidate()
        self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            6.0, False, lambda t: self.hide())

    def _do_undo(self):
        if self._on_undo and self._word:
            try:
                self._on_undo(self._word)
            except Exception:
                pass
        self.hide()

    def hide(self):
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
        if self.panel is not None:
            self.panel.orderOut_(None)


# --- standalone visual demo: python island.py ---
if __name__ == "__main__":
    app = AppKit.NSApplication.sharedApplication()
    st = {"mode": "rec"}
    rng = np.random.default_rng()
    bands = np.zeros(8)
    _profile = np.linspace(1.0, 0.35, 8)   # low freq louder, like a real voice

    def provider():
        return st["mode"], 0.1, list(bands)

    isl = Island(provider)
    isl.set_state("rec")

    t0 = time.time()

    def step(_timer):
        global bands
        el = time.time() - t0
        if el > 8:
            AppKit.NSApp().terminate_(None)
        st["mode"] = "work" if 4 < el < 6 else "rec"
        env = 0.45 + 0.55 * math.sin(el * 3)
        bands = np.clip(_profile * env * (0.55 + 0.45 * rng.random(8)), 0, 1)
        isl.set_state(st["mode"])
        isl.tick()

    from Foundation import NSTimer
    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(1 / 30.0, True, step)
    print("Showing island demo for ~8s near the bottom of your screen…")
    app.run()
