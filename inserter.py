"""Insert text wherever the cursor is, by borrowing the clipboard and sending Cmd-V."""
import time
import subprocess
from pynput.keyboard import Controller, Key

_kbd = Controller()


def _pbcopy(text: str):
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)


def _pbpaste() -> str:
    try:
        return subprocess.run(["pbpaste"], capture_output=True, check=False).stdout.decode("utf-8")
    except Exception:
        return ""


def paste_text(text: str, restore_clipboard: bool = True):
    if not text:
        return
    prev = _pbpaste() if restore_clipboard else None
    _pbcopy(text)
    time.sleep(0.05)
    with _kbd.pressed(Key.cmd):
        _kbd.press("v")
        _kbd.release("v")
    if restore_clipboard:
        time.sleep(0.25)
        _pbcopy(prev or "")


def type_text(text: str):
    """Fallback: literally type the characters (slower, but no clipboard use)."""
    _kbd.type(text)
