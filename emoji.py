"""Emojis in dictation.

1. Spoken: "... that's great smiley emoji" -> "... that's great 😊". Needs the
   word "emoji" (or "emojis"), so ordinary sentences are never touched.
2. Automatic (opt-in, chat apps only): the cleanup model suggests one or two
   fitting emojis. Its output is used only if removing the emojis gives back
   EXACTLY the original text -- it can't reword, translate or "fix" you.
"""
import re

import requests

# name -> emoji. Longer names win ("heart eyes" before "heart").
_NAMED = {
    "smiley": "😊", "smile": "😊", "smiling": "😊", "happy": "😊", "blush": "😊",
    "big smile": "😁", "grin": "😁", "grinning": "😁",
    "laughing": "😂", "laugh": "😂", "lol": "😂", "haha": "😂", "tears of joy": "😂",
    "rolling on the floor": "🤣", "rofl": "🤣",
    "sweat smile": "😅", "nervous laugh": "😅", "wink": "😉", "winking": "😉",
    "heart eyes": "😍", "love eyes": "😍", "kiss": "😘", "kissing": "😘",
    "heart": "❤️", "red heart": "❤️", "love": "❤️", "broken heart": "💔",
    "thumbs up": "👍", "thumb up": "👍", "like": "👍", "thumbs down": "👎",
    "ok": "👌", "okay": "👌", "ok hand": "👌", "clap": "👏", "clapping": "👏",
    "pray": "🙏", "praying": "🙏", "folded hands": "🙏", "thank you": "🙏", "thanks": "🙏",
    "namaste": "🙏", "wave": "👋", "waving": "👋", "bye": "👋", "hi": "👋", "hello": "👋",
    "muscle": "💪", "strong": "💪", "flex": "💪", "shrug": "🤷", "facepalm": "🤦",
    "sad": "😢", "crying": "😭", "cry": "😭", "sob": "😭", "angry": "😠", "mad": "😠",
    "rage": "😡", "cool": "😎", "sunglasses": "😎", "thinking": "🤔", "think": "🤔",
    "hmm": "🤔", "party": "🎉", "celebrate": "🎉", "celebration": "🎉", "tada": "🎉",
    "confetti": "🎉", "rocket": "🚀", "fire": "🔥", "lit": "🔥", "hundred": "💯",
    "100": "💯", "check": "✅", "tick": "✅", "check mark": "✅", "done": "✅",
    "cross": "❌", "x": "❌", "eyes": "👀", "looking": "👀", "star": "⭐",
    "sparkles": "✨", "sparkle": "✨", "skull": "💀", "dead": "💀", "poop": "💩",
    "sleeping": "😴", "sleepy": "😴", "mind blown": "🤯", "exploding head": "🤯",
    "nerd": "🤓", "hug": "🤗", "hugging": "🤗", "monkey": "🙈", "see no evil": "🙈",
    "upside down": "🙃", "rolling eyes": "🙄", "eye roll": "🙄", "neutral": "😐",
    "shocked": "😮", "surprised": "😮", "wow": "😮", "scared": "😱", "scream": "😱",
    "sick": "🤒", "money": "💰", "warning": "⚠️", "coffee": "☕", "tea": "🍵",
    "chai": "☕", "cake": "🎂", "birthday": "🎂", "gift": "🎁", "flower": "🌸",
    "rose": "🌹", "sun": "☀️", "moon": "🌙", "rain": "🌧️", "dog": "🐶", "cat": "🐱",
    "pizza": "🍕", "beer": "🍺", "cheers": "🥂", "trophy": "🏆", "medal": "🥇",
    "idea": "💡", "bulb": "💡", "bug": "🐛", "laptop": "💻", "phone": "📱",
    "salute": "🫡", "melting": "🫠", "pleading": "🥺", "puppy eyes": "🥺",
    "smirk": "😏", "zipper mouth": "🤐", "devil": "😈", "angel": "😇",
    "crossed fingers": "🤞", "fingers crossed": "🤞", "raised hands": "🙌",
    "high five": "🙌", "point up": "☝️", "point down": "👇", "point right": "👉",
    "snail": "🐌", "turtle": "🐢", "rabbit": "🐰", "monkey face": "🐵", "lion": "🦁",
    "tiger": "🐯", "panda": "🐼", "unicorn": "🦄", "horse": "🐴", "cow": "🐮", "pig": "🐷",
    "chicken": "🐔", "bird": "🐦", "fish": "🐟", "snake": "🐍", "butterfly": "🦋",
    "clown": "🤡", "robot": "🤖", "alien": "👽", "ghost": "👻", "zombie": "🧟",
    "cold": "🥶", "hot": "🥵", "hungry": "🤤", "drooling": "🤤", "yum": "😋", "yummy": "😋",
    "tongue": "😛", "silly": "🤪", "crazy": "🤪", "quiet": "🤫", "shush": "🤫",
    "lying": "🤥", "money face": "🤑", "cowboy": "🤠", "disguise": "🥸", "partying": "🥳",
    "confused": "😕", "worried": "😟", "tired": "😫", "weary": "😩", "relieved": "😌",
    "grimace": "😬", "awkward": "😬", "pensive": "😔", "disappointed": "😞",
    "flushed": "😳", "embarrassed": "😳", "joy": "😂", "zany": "🤪", "vomit": "🤮",
    "mask": "😷", "nauseated": "🤢", "sneeze": "🤧", "hourglass": "⏳", "clock": "⏰",
    "alarm": "⏰", "calendar": "📅", "pin": "📌", "link": "🔗", "lock": "🔒", "key": "🔑",
    "book": "📖", "pen": "🖊️", "memo": "📝", "note": "📝", "chart": "📈", "graph": "📈",
    "mail": "📧", "email": "📧", "bell": "🔔", "music": "🎵", "movie": "🎬", "camera": "📷",
    "game": "🎮", "car": "🚗", "plane": "✈️", "train": "🚆", "house": "🏠", "home": "🏠",
    "earth": "🌍", "world": "🌍", "rainbow": "🌈", "snow": "❄️", "lightning": "⚡",
    "zap": "⚡", "boom": "💥", "bomb": "💣", "gem": "💎", "diamond": "💎", "crown": "👑",
    "ring": "💍", "balloon": "🎈", "ice cream": "🍦", "burger": "🍔", "fries": "🍟",
    "popcorn": "🍿", "apple": "🍎", "banana": "🍌", "mango": "🥭", "watermelon": "🍉",
    "wine": "🍷", "soccer": "⚽", "football": "⚽", "cricket": "🏏", "basketball": "🏀",
    "running": "🏃", "dance": "💃", "dancing": "💃", "sweat": "💦", "drop": "💧",
    "plant": "🌱", "tree": "🌳", "leaf": "🍃", "mushroom": "🍄", "india": "🇮🇳",
    "indian flag": "🇮🇳", "white heart": "🤍", "black heart": "🖤", "blue heart": "💙",
    "green heart": "💚", "yellow heart": "💛", "purple heart": "💜", "orange heart": "🧡",
    "sparkling heart": "💖", "two hearts": "💕", "question": "❓", "exclamation": "❗",
    "sos": "🆘", "new": "🆕", "free": "🆓", "cool button": "🆒", "speech bubble": "💬",
    "zzz": "💤", "nail polish": "💅", "sassy": "💅", "eye": "👁️", "brain": "🧠",
    "heart hands": "🫶", "handshake": "🤝", "writing": "✍️", "call me": "🤙",
    "rock on": "🤘", "peace": "✌️", "victory": "✌️", "middle finger": "🖕",
}
_NAMES = sorted(_NAMED, key=len, reverse=True)
# "emoji" as Whisper may spell it, incl. romanised from Devanagari (इमोजी -> imoji)
_EMOJI_WORD = r"(?:emoji|emojis|emojee|imoji|imojee|emoticon)"
_SPOKEN = re.compile(
    r"(?:\b(?:an?|the)\s+)?\b(" + "|".join(re.escape(n) for n in _NAMES) + r")[\s-]+" + _EMOJI_WORD + r"\b"
    r"\.?",
    re.IGNORECASE)

# every emoji-ish code point we may insert or the model may produce
_EMOJI_CHARS = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿️‍⃣"
    "\U0001F1E6-\U0001F1FF]")


def spoken(text: str) -> str:
    """Replace "<name> emoji" with the emoji itself."""
    if not text or not re.search(_EMOJI_WORD, text, re.IGNORECASE):
        return text

    def rep(m):
        return " " + _NAMED[m.group(1).lower()] + " "

    s = _SPOKEN.sub(rep, text)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r" +([,.?!])", r"\1", s)
    return s.strip() + (" " if text.endswith(" ") else "")


def _strip(text: str) -> str:
    s = _EMOJI_CHARS.sub("", text)
    return re.sub(r"\s+", " ", s).strip()


AUTO_PROMPT = """Add one or two emojis to the MESSAGE that fit its mood, the way a \
person texting would. Put each emoji right after the phrase it belongs to or at the end.

STRICT: copy every word, letter, number and punctuation mark exactly as given -- same \
language, same spelling, same order. Do not translate, correct, add or remove any word. \
Only insert emojis. If no emoji fits, return the message unchanged.

Return ONLY the MESSAGE (with the emojis)."""


def auto(text: str, url: str, model: str, keep_alive="30m", timeout: float = 8.0,
         chat: str = "") -> str:
    """Suggest emojis via the local model; keep them only if nothing else changed.
    num_ctx and keep_alive MUST match the cleanup call's: Ollama reloads the
    model whenever num_ctx changes, and keep_alive resets its unload timer."""
    body = text.strip()
    if not body or _EMOJI_CHARS.search(body):    # already has emojis (spoken ones)
        return text
    prompt = f"MESSAGE:\n{body}\n\n/no_think"
    if chat.strip():
        prompt = ("RECENT CHAT, for the mood only -- do not copy any of it:\n" + chat.strip()
                  + "\n\n" + prompt)
    try:
        r = requests.post(f"{url}/api/generate", json={
            "model": model, "system": AUTO_PROMPT, "prompt": prompt,
            "stream": False, "think": False, "keep_alive": keep_alive,
            "options": {"temperature": 0.3, "num_ctx": 8192},
        }, timeout=timeout)
        r.raise_for_status()
        out = r.json().get("response", "")
    except Exception as e:
        print(f"[emoji] auto emoji skipped ({e.__class__.__name__})")
        return text
    out = re.sub(r"(?s)<think>.*?</think>", "", out).strip().strip('"').strip()
    if not _EMOJI_CHARS.search(out) or _strip(out) != _strip(body):
        return text          # no emoji, or it changed words -> keep the original
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out + (" " if text.endswith(" ") else "")


# ---------- where to add automatic emojis ----------
CHAT_APPS = {
    "net.whatsapp.WhatsApp", "desktop.WhatsApp", "com.apple.MobileSMS",
    "com.tinyspeck.slackmacgap", "ru.keepcoder.Telegram", "org.telegram.desktop",
    "com.hnc.Discord", "com.facebook.archon", "com.microsoft.teams2",
    "com.apple.iChat", "jp.naver.line.mac", "com.viber.osx", "org.whispersystems.signal-desktop",
}
BROWSERS = {
    "com.google.Chrome", "com.apple.Safari", "company.thebrowser.Browser", "org.mozilla.firefox",
    "com.brave.Browser", "com.microsoft.edgemac", "com.operasoftware.Opera",
}
CHAT_TITLES = re.compile(r"whatsapp|messenger|instagram|telegram|discord|slack|"
                         r"messages|direct|\bchat\b|linkedin.*messag", re.IGNORECASE)


def frontmost():
    """(bundle id, focused window title) of the app you're typing into."""
    try:
        import AppKit
        import HIServices
        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        bid = str(app.bundleIdentifier() or "")
        title = ""
        try:
            ax = HIServices.AXUIElementCreateApplication(app.processIdentifier())
            err, win = HIServices.AXUIElementCopyAttributeValue(ax, "AXFocusedWindow", None)
            if not err and win is not None:
                err, t = HIServices.AXUIElementCopyAttributeValue(win, "AXTitle", None)
                title = str(t or "") if not err else ""
        except Exception:
            pass
        return bid, title
    except Exception:
        return "", ""


def is_chat(target) -> bool:
    bid, title = target or ("", "")
    if bid in CHAT_APPS:
        return True
    return bid in BROWSERS and bool(CHAT_TITLES.search(title))
