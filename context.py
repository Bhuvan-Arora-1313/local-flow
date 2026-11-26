"""On-screen context: names and terms from where you're dictating.

At the start of each recording (while you speak, so it adds no wait),
LocalFlow reads the text around where you're typing:

  * the focused window, via Accessibility (Terminal's scrollback, WhatsApp,
    Messages, browsers ...). Apps that hide their text are left alone -- we
    never switch on Electron's accessibility mode, which changes how VS Code
    behaves.
  * in terminals / editors: the recent Claude Code conversation (Claude Code
    saves each session under ~/.claude/projects), preferring the project
    named in the window title.

Only distinctive words are kept -- names, CamelCase, acronyms, words with
digits (Qwen, GPT-4o, LoRA, Rahul) -- and handed to the cleanup step as
spelling hints. Nothing is stored or sent anywhere; it lives in memory for
one dictation.
"""
import glob
import json
import os
import re
import time

TERMINALS = {
    "com.apple.Terminal", "com.googlecode.iterm2", "com.termius-dmg.mac", "com.mitchellh.ghostty",
    "dev.warp.Warp-Stable", "io.alacritty", "net.kovidgoyal.kitty", "com.github.wez.wezterm",
    "com.microsoft.VSCode", "com.todesktop.230313mzl4w4u92", "com.exafunction.windsurf",
    "dev.zed.Zed", "com.jetbrains.pycharm", "com.anthropic.claudefordesktop",
}
AX_BUDGET_S = 0.4
AX_MAX_NODES = 2500
MAX_TEXT = 60_000
CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")

_common = None


def _common_words():
    """Lower-case English words (macOS ships a word list); a name or term
    is something NOT in it."""
    global _common
    if _common is None:
        words = set()
        try:
            with open("/usr/share/dict/words", encoding="utf-8", errors="ignore") as f:
                for w in f:
                    w = w.strip()
                    if w and w.islower():
                        words.add(w)
        except OSError:
            pass
        _common = words
    return _common


# ---------- reading the screen ----------
def _ax_get(el, attr):
    import HIServices as H
    err, v = H.AXUIElementCopyAttributeValue(el, attr, None)
    return v if err == 0 else None


def _ax_text(pid):
    import HIServices as H
    app = H.AXUIElementCreateApplication(pid)
    win = _ax_get(app, "AXFocusedWindow")
    if win is None:
        return ""
    parts, nodes, t0 = [], 0, time.time()
    stack = [(win, 0)]
    while stack and nodes < AX_MAX_NODES and time.time() - t0 < AX_BUDGET_S:
        el, depth = stack.pop()
        nodes += 1
        role = _ax_get(el, "AXRole")
        for attr in ("AXValue", "AXTitle", "AXDescription"):
            v = _ax_get(el, attr)
            if isinstance(v, str) and v.strip():
                # a terminal's whole scrollback: the recent end matters
                parts.append(v[-12_000:] if role == "AXTextArea" else v)
        if depth < 40:
            kids = _ax_get(el, "AXChildren") or []
            stack.extend((k, depth + 1) for k in kids)
    return "\n".join(parts)


def _claude_code_text(title):
    """Recent messages of the Claude Code session(s) you're most likely in."""
    try:
        files = [f for f in glob.glob(os.path.join(CLAUDE_PROJECTS, "*", "*.jsonl"))
                 if time.time() - os.path.getmtime(f) < 3 * 3600]
    except OSError:
        return ""
    if not files:
        return ""
    t = (title or "").lower()

    def score(f):
        proj = os.path.basename(os.path.dirname(f)).lower()
        tail = proj.rsplit("-", 1)[-1]
        named = bool(t) and (tail in t or any(w in proj for w in re.findall(r"[a-z0-9]{4,}", t)))
        return (named, os.path.getmtime(f))

    texts = []
    for f in sorted(files, key=score, reverse=True)[:2]:
        try:
            size = os.path.getsize(f)
            with open(f, "rb") as fh:
                fh.seek(max(0, size - 400_000))
                lines = fh.read().decode("utf-8", "ignore").splitlines()[1:]
        except OSError:
            continue
        msgs = []
        for line in lines:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") not in ("user", "assistant"):
                continue
            content = d.get("message", {}).get("content")
            if isinstance(content, str):
                msgs.append(content)
            elif isinstance(content, list):
                msgs.extend(c.get("text", "") for c in content
                            if isinstance(c, dict) and c.get("type") == "text")
        texts.append("\n".join(msgs[-40:]))
    return "\n".join(texts)


def capture():
    """{'bid', 'title', 'text'} for the app you're dictating into."""
    try:
        import AppKit
        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        bid = str(app.bundleIdentifier() or "")
        pid = app.processIdentifier()
    except Exception:
        return {"bid": "", "title": "", "text": ""}
    title, text = "", ""
    try:
        import HIServices as H
        win = _ax_get(H.AXUIElementCreateApplication(pid), "AXFocusedWindow")
        title = str(_ax_get(win, "AXTitle") or "") if win is not None else ""
        text = _ax_text(pid)
    except Exception as e:
        print(f"[context] couldn't read the window ({e.__class__.__name__})")
    if bid in TERMINALS:
        text = text + "\n" + _claude_code_text(title)
    return {"bid": bid, "title": title, "text": text[-MAX_TEXT:]}


def _is_common(w, common):
    """In the word list, directly or as a regular inflection of a listed
    word (checking, committing, closing, deleted, settings, quickly)."""
    if w in common:
        return True
    for suf, adds in (("s", ("",)), ("es", ("",)), ("ies", ("y",)), ("ed", ("", "e")),
                      ("ing", ("", "e")), ("ly", ("",)), ("er", ("", "e")), ("est", ("", "e"))):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            stem = w[: -len(suf)]
            for a in adds:
                if stem + a in common:
                    return True
            if suf in ("ed", "ing", "er", "est") and len(stem) > 3 and stem[-1] == stem[-2] \
                    and stem[:-1] in common:        # committing, stopped
                return True
    return False


# ---------- picking the words worth hinting ----------
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_:+][A-Za-z0-9]+)*")


def _distinctive(tok, common):
    if len(tok) < 3 or len(tok) > 40:
        return False
    if re.search(r"\d", tok):                       # GPT-4o, qwen3:8b, v3
        return bool(re.search(r"[A-Za-z]{2}", tok))
    if re.search(r"[a-z][A-Z]", tok):               # LoRA, GitHub, iPhone
        return True
    if tok.isupper():                               # API, GPU, CORS
        return len(tok) <= 8
    parts = re.split(r"[-_:+]", tok)
    if len(parts) > 1:                              # local-flow, parakeet_tdt
        return any(not _is_common(p.lower(), common) for p in parts if p)
    return tok[0].isupper() and not _is_common(tok.lower(), common)   # Rahul, Qwen, Substack


def terms(text, limit=60):
    """Distinctive words in `text`, most frequent / most recent first."""
    if not text:
        return []
    common = _common_words()
    score = {}
    toks = _TOKEN.findall(text)
    n = len(toks) or 1
    for i, tok in enumerate(toks):
        if _distinctive(tok, common):
            score[tok] = score.get(tok, 0.0) + 1.0 + i / n     # later = more recent
    return [t for t, _ in sorted(score.items(), key=lambda kv: -kv[1])[:limit]]


def focus_point():
    """Centre of the focused window of the app you're typing into, in Cocoa
    screen coordinates (origin bottom-left of the primary display), or the
    mouse position if that can't be read. Short AX timeout: never stalls."""
    try:
        import AppKit
        import HIServices as H
        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        ax = H.AXUIElementCreateApplication(app.processIdentifier())
        H.AXUIElementSetMessagingTimeout(ax, 0.25)
        win = _ax_get(ax, "AXFocusedWindow")
        pos = _ax_get(win, "AXPosition") if win is not None else None
        size = _ax_get(win, "AXSize") if win is not None else None
        if pos is not None and size is not None:
            ok1, p = H.AXValueGetValue(pos, H.kAXValueCGPointType, None)
            ok2, s = H.AXValueGetValue(size, H.kAXValueCGSizeType, None)
            if ok1 and ok2:
                primary = AppKit.NSScreen.screens()[0].frame().size.height
                # AX: top-left origin, y down from the primary display's top
                return (p.x + s.width / 2.0, primary - (p.y + s.height / 2.0))
    except Exception:
        pass
    try:
        import AppKit
        m = AppKit.NSEvent.mouseLocation()
        return (m.x, m.y)
    except Exception:
        return None
