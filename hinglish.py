"""Devanagari -> casual romanised Hindi ("Hinglish", WhatsApp style).

Rule-based on purpose. An LLM asked to transliterate also rewrites: it
reordered words, changed "सकता" to "saka", translated clauses to English,
or left the line in Devanagari. A fixed mapping can only ever spell what
the speech model heard.

Handles Hindi's silent inherent "a" (schwa deletion: समझ -> samajh,
सकता -> sakta, मतलब -> matlab), conjuncts (अच्छा -> accha) and nasals, plus
a small table of very common words whose casual spelling isn't phonetic
(है -> hai, मैं -> main, नहीं -> nahi, यह -> yeh).
"""
import re

_WORDS = {
    "है": "hai", "हैं": "hain", "मैं": "main", "में": "mein", "हूँ": "hoon", "हूं": "hoon",
    "नहीं": "nahi", "नही": "nahi", "यह": "yeh", "वह": "woh", "ये": "ye", "वो": "wo",
    "तो": "toh", "क्यों": "kyun", "क्यूं": "kyun", "क्यूँ": "kyun", "कहाँ": "kahan",
    "कहां": "kahan", "यहाँ": "yahan", "यहां": "yahan", "वहाँ": "wahan", "वहां": "wahan",
    "हाँ": "haan", "हां": "haan", "अच्छा": "accha", "अच्छी": "acchi", "अच्छे": "acche",
    "ठीक": "theek", "बहुत": "bahut", "और": "aur", "कि": "ki", "काफी": "kaafi",
    "काफ़ी": "kaafi", "मुझे": "mujhe", "तुम्हें": "tumhe", "उन्हें": "unhe", "इन्हें": "inhe",
    "वाला": "wala", "वाली": "wali", "वाले": "wale", "वापस": "wapas", "वैसे": "waise",
    "ऐसे": "aise", "ऐसा": "aisa", "कैसे": "kaise", "कैसा": "kaisa", "जैसे": "jaise",
    "भाई": "bhai", "यार": "yaar", "आप": "aap", "आज": "aaj", "बात": "baat", "काम": "kaam",
    "एक": "ek", "दो": "do", "क्या": "kya", "कुछ": "kuch", "सच": "sach", "फिर": "phir",
    "मैंने": "maine", "हम": "hum", "हमने": "humne", "हमें": "humein", "हमारा": "humara",
    "हमारी": "humari", "हमारे": "humare", "लिए": "liye", "लिये": "liye", "दिए": "diye",
    "किए": "kiye", "गए": "gaye", "गई": "gayi", "हुआ": "hua", "हुए": "hue", "कोई": "koi",
    "सही": "sahi", "अभी": "abhi", "सभी": "sabhi", "तुम्हारा": "tumhara", "तुम्हारी": "tumhari",
}

_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "ch", "ज": "j",
    "झ": "jh", "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t",
    "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh",
    "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s",
    "ह": "h", "ळ": "l",
    # nukta forms (also composed below from base + ़)
    "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f", "य़": "y",
}
_NUKTA = {"क": "क़", "ख": "ख़", "ग": "ग़", "ज": "ज़", "ड": "ड़", "ढ": "ढ़", "फ": "फ़", "य": "य़"}
_INDEP = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e",
    "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e",
}
_MATRA = {
    "ा": "A", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e", "ै": "ai",
    "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
}
_VIRAMA, _ANUSVARA, _CHANDRA, _VISARGA, _NUKTA_SIGN = "्", "ं", "ँ", "ः", "़"
_LABIAL = ("p", "b", "m")

_DEVA_WORD = re.compile(r"[ऀ-ॿ]+")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _units(word):
    """Split a word into [consonant|None, vowel|'a'(inherent)|''(virama), nasal]."""
    u, i, n = [], 0, len(word)
    while i < n:
        ch = word[i]
        if ch in _NUKTA and i + 1 < n and word[i + 1] == _NUKTA_SIGN:
            ch = _NUKTA[ch]
            i += 1
        if ch in _CONS:
            unit = [_CONS[ch], "a", ""]
            if i + 1 < n and word[i + 1] in _MATRA:
                unit[1] = _MATRA[word[i + 1]]
                i += 1
            elif i + 1 < n and word[i + 1] == _VIRAMA:
                unit[1] = ""
                i += 1
            u.append(unit)
        elif ch in _INDEP:
            u.append([None, _INDEP[ch], ""])
        elif ch in (_ANUSVARA, _CHANDRA) and u:
            u[-1][2] = "n"
        elif ch == _VISARGA and u:
            u[-1][2] = "h"
        elif ch in ("।", "॥"):
            u.append([None, ".", ""])
        i += 1
    return u


def _has_vowel(unit):
    return unit[1] not in ("", "-")


def _word(word):
    if word in _WORDS:
        return _WORDS[word]
    u = _units(word)
    if not u:
        return word
    # schwa deletion, right to left: the last consonant's inherent "a" is
    # silent; a medial one is too when a vowel precedes and a consonant WITH a
    # vowel follows (sa-ka-taa -> sak-taa, ma-ta-la-ba -> mat-lab)
    if len(u) > 1 and u[-1][0] and u[-1][1] == "a" and not u[-1][2]:
        u[-1][1] = "-"
    for i in range(len(u) - 2, 0, -1):
        cur, prev, nxt = u[i], u[i - 1], u[i + 1]
        if (cur[0] and cur[1] == "a" and not cur[2] and _has_vowel(prev)
                and nxt[0] and _has_vowel(nxt)):
            cur[1] = "-"
    out = []
    for i, (c, v, nas) in enumerate(u):
        if c:
            out.append(c)
        if v == "A":
            # long aa written "aa" only in a closed syllable (kaam, baat, aaj);
            # open syllables read naturally with one a (jana, paya, raha)
            closed = i + 1 < len(u) and u[i + 1][0] and u[i + 1][1] in ("-", "")
            out.append("aa" if closed else "a")
        elif v not in ("-", ""):
            out.append(v)
        if nas:
            nxt_c = u[i + 1][0] if i + 1 < len(u) else None
            out.append("m" if nas == "n" and nxt_c and nxt_c.startswith(_LABIAL) else nas)
    s = "".join(out)
    s = s.replace("chch", "cch")
    return s


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI.search(text))


def romanize(text: str) -> str:
    """Romanise every Devanagari word; leave everything else untouched."""
    text = text.replace("।", ".").replace("॥", ".")
    s = _DEVA_WORD.sub(lambda m: _word(m.group(0)), text)
    s = s.replace(" .", ".")
    return s


# common romanised-Hindi words that aren't also everyday English words
_HINGLISH_MARKERS = set("""hai hain kya nahi nahin mujhe mein ka ki ke ko aur bhi toh yeh ye woh wo
kar raha rahi rahe tha thi hum tum aap kuch isse usse isko usko sakta sakti sakte matlab yaar abhi
bahut accha acha kaise kaisa kyun kyon gaya gayi hoon hu hoga hogi karna karo karke maine humne
bolo bola dekho dekh chahiye""".split())


def looks_hinglish(text: str) -> bool:
    """Latin-script text that is clearly romanised Hindi (2+ marker words)."""
    words = re.findall(r"[a-z]+", text.lower())
    return sum(w in _HINGLISH_MARKERS for w in words) >= 2


def tidy(text: str) -> str:
    """Whitespace + sentence capitalisation, nothing else."""
    s = re.sub(r"\s+", " ", text).strip()
    s = re.sub(r"\s+([,.?!])", r"\1", s)
    return re.sub(r"(^|[.?!]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)
