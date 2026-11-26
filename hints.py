"""Which dictionary / on-screen terms did the speaker probably mean?

The cleanup prompt's fixed glossary holds only a few hundred of the
dictionary's thousands of terms, and a bare list of hints is easy for a
small model to ignore. So for every dictation we find the exact spans that
look or SOUND like a known term ("Lama" ~ Llama, "low RA" ~ LoRA,
"Jayanth" ~ Jayant) and hand the model explicit "span -> term" pairs.

Sound matching uses a rough phonetic key tuned for English + Indian names:
Hindi aspirates fold into plain consonants (dh -> d, th -> t), v/w merge,
doubled letters and long vowels collapse (Rahool -> rahul).
"""
import difflib
import re

_STRONG, _SPELLED = 2, 1


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


_PHON_RULES = [
    (r"qu", "kw"), (r"q", "k"), (r"(?<![a-z])ku(?=[aeiou])", "kw"), (r"ck", "k"), (r"ph", "f"), (r"c(?=[eiy])", "s"), (r"c", "k"),
    (r"x", "ks"), (r"z", "s"), (r"([bdgjkt])h", r"\1"), (r"w(?=[^aeiou]|$)", ""), (r"w", "v"),
    (r"ee", "i"), (r"oo", "u"), (r"y$", "i"), (r"(.)\1+", r"\1"),
]


def phon(s: str) -> str:
    k = norm(s)
    for pat, rep in _PHON_RULES:
        k = re.sub(pat, rep, k)
    return k


_index_cache = {}


def _index(terms):
    key = (id(terms), len(terms))
    idx = _index_cache.get(key)
    if idx is None:
        idx = {}
        for t in terms:
            n, p = norm(t), phon(t)
            if len(n) >= 3 and p:
                idx.setdefault(p[0], []).append((n, p, t))
        if len(_index_cache) > 4:
            _index_cache.clear()
        _index_cache[key] = idx
    return idx


def _common():
    try:
        import context
        return context._common_words(), context._is_common
    except Exception:
        return set(), (lambda w, c: False)


def matches(raw: str, terms: list[str], limit: int = 10):
    """[(span_in_raw, term, strong)] -- best first, non-overlapping.
    strong = sounds identical (phonetic keys equal)."""
    spans = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[A-Za-z0-9]+", raw)]
    if not spans or not terms:
        return []
    common, is_common = _common()
    idx = _index(terms)
    # an ALL-CAPS fragment ("low RA") is a typical mishearing, never an everyday word
    words_common = [not (w.isupper() and len(w) >= 2)
                    and (is_common(w.lower(), common) or (len(w) <= 2 and w.lower() in common))
                    for w, _, _ in spans]
    # words already spelled exactly like a term ("Opus", "Gemini Flash") are
    # right -- never re-match them as part of something else
    exact = set()
    for n in (3, 2, 1):
        for i in range(len(spans) - n + 1):
            text = raw[spans[i][1]:spans[i + n - 1][2]]
            g = norm(text)
            if any(t == text for tn, _, t in idx.get(phon(text)[:1], ()) if tn == g):
                exact |= set(range(i, i + n))
    cands = []
    for n in (3, 2, 1):
        for i in range(len(spans) - n + 1):
            if exact & set(range(i, i + n)):
                continue
            if n > 1 and all(words_common[i:i + n]):
                continue                        # "I am" is not a misheard "IAM"
            text = raw[spans[i][1]:spans[i + n - 1][2]]
            g, gp = norm(text), phon(text)
            if len(g) < 3 or not gp:
                continue
            g_common = n == 1 and words_common[i]
            for tn, tp, t in idx.get(gp[0], ()):
                if text == t:
                    continue                                   # already right
                if abs(len(tn) - len(g)) > max(2, len(tn) // 3):
                    continue
                if text.lower() == t.lower() and text[:1].isupper() and t[:1].islower():
                    continue                           # just a capital at a sentence start
                if gp == tp and len(tp) >= 3:          # sounds the same
                    cands.append((_STRONG, 1.0, n, i, text, t))
                    continue
                if g_common:
                    continue                    # "table" is not a misheard "Tableau"
                sm = difflib.SequenceMatcher(None, g, tn)
                if sm.real_quick_ratio() < 0.8 or sm.quick_ratio() < 0.8:
                    continue
                r = sm.ratio()
                if r >= 0.8:
                    cands.append((_SPELLED, r, n, i, text, t))
    cands.sort(key=lambda c: (-c[0], -c[1], -c[2]))
    used, out, seen = set(), [], set()
    for kind, r, n, i, text, t in cands:
        cover = set(range(i, i + n))
        if cover & used or (text.lower(), t.lower()) in seen:
            continue
        used |= cover
        seen.add((text.lower(), t.lower()))
        out.append((text, t, kind == _STRONG))
        if len(out) >= limit:
            break
    return out


def fix_names(text: str, terms: list[str]) -> str:
    """Deterministic, for text that skips the cleanup model (Hinglish):
    replace a span that SOUNDS identical to a name in the dictionary or on
    screen (jayant -> Jayant, prakriti -> Prakriti). Names only -- capitalised,
    4+ letters, not an everyday word."""
    try:
        from hinglish import _HINGLISH_MARKERS as everyday
    except Exception:
        everyday = set()
    clash = {phon(w) for w in everyday}
    names = [t for t in terms if t[:1].isupper() and len(norm(t)) >= 4
             and phon(t) not in clash]
    out = text
    for span, term, strong in matches(text, names, limit=20):
        if strong and " " not in span:
            out = re.sub(r"\b" + re.escape(span) + r"\b", term, out)
    return out
