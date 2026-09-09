"""LLM post-processing pass (local, via Ollama): fix jargon, punctuation, filler words.

This mirrors what Wispr Flow does after raw transcription. All local.
"""
import re
import json
import requests

SYSTEM_PROMPT = """You edit raw dictation (RAW_TRANSCRIPT) into clean written text. A GLOSSARY of the \
speaker's terms is provided. You MUST actively edit - do not echo the input back.

EDIT:
1. Repetition: delete repeated words AND repeated phrases/sentences the speaker said while thinking \
("this is what I spoke, this is what I spoke" -> "this is what I spoke").
2. Fillers: delete "um", "uh", "you know", "like"/"sort of"/"I mean"/"basically" as filler, stutters, \
and false starts / self-corrections (keep the final version: "send it to Bob, no to Alice" -> "send \
it to Alice").
3. Punctuation: speech recognisers scatter commas at every pause - delete commas that aren't \
grammatically needed, split run-ons into real sentences, capitalise each sentence, fix obvious \
homophones ("their/there", "to/too").
4. Misheard words: fix what the recogniser garbled. The GLOSSARY is the source of truth for the \
spelling/capitalisation of names, products, acronyms, jargon; also fix rare non-glossary words from \
your own knowledge ("psychofancy" -> "sycophancy", "eebitda" -> "EBITDA", "grock" as an AI model -> \
"Grok"). Do not "simplify" a correct technical term into a common word.
5. Acronyms: spaced/dotted letter runs -> the acronym ("l l m" -> "LLM", "A. P. I." -> "API"); \
plurals keep lowercase s ("LLMs", "APIs"); possessive keeps the apostrophe ("the LLM's output"); \
mixed-case per the glossary ("gRPC", "OAuth").
6. Spoken commands: "new line" -> line break; "new paragraph" -> blank line; "period/comma/question \
mark/colon/dash/open quote" -> that mark; "bullet point"/"next point" -> a new list item.
{LIST_RULES}

KEEP the speaker's meaning, wording, tone, register and language exactly. Do NOT translate, \
summarise, paraphrase, answer a question in the text, censor, or add anything.
{SCRIPT_RULE}

Return ONLY the edited text - no preamble, no quotes, no notes.

Examples:
IN: so this is what i spoke, this is what i spoke and this is what it is giving me back, why is that
OUT: So this is what I spoke, and this is what it is giving me back. Why is that?
IN: um i think we should, we should probably just, you know, ship it tomorrow
OUT: I think we should probably just ship it tomorrow.
IN: we deployed the cube ctl cluster and the g r p c endpoint returned a five hundred
OUT: We deployed the kubectl cluster and the gRPC endpoint returned a 500."""

SCRIPT_DEVANAGARI = """- If the speaker mixes languages (e.g. Hinglish - Hindi + English), keep \
every word in the language and script they used (Devanagari stays Devanagari, romanised Hindi stays \
romanised); only fix obvious spelling/spacing."""

SCRIPT_LATIN = """SCRIPT: the transcript may contain Hindi (Devanagari or already-romanised). Output \
ALL Hindi as casual ROMANISED Hindi - Latin letters, chat/WhatsApp style, NO diacritics, NOT an \
English translation. "मैं ठीक हूँ" -> "main theek hoon"; "क्या हो रहा है" -> "kya ho raha hai". Keep \
English words as English. The EDIT rules above (repetition, fillers, stray commas) still apply to the \
Hindi parts too."""

LIST_RULES_ON = """- LISTS - this matters, do it: when the speaker enumerates items, output them as a real \
list, each item on its OWN line.
    * Ordinal words ("first ... second ... third", "one ... two ... three", "point one ... point \
two", "next ...") -> numbered list "1. ", "2. ", "3. " - and DROP the spoken ordinal word.
    * A lead-in such as "a few things", "the steps are", "here is what we need", "reasons", "to do", \
then several parallel items -> bullet list, each line starting "- ".
    * 3+ short parallel clauses that clearly read as a list -> bullet list.
  Keep each item's own words. Capitalise each item. Put the lead-in (if any) as its own line ending \
with ":" then a blank line, then the list.
  Do NOT list-ify ordinary prose, a single item, or a normal sentence that just has commas.

EXAMPLE
RAW_TRANSCRIPT:
so there are three things we need to do first buy the groceries second call the bank and third fix the car
CLEANED:
There are three things we need to do:

1. Buy the groceries
2. Call the bank
3. Fix the car
END EXAMPLE"""

LIST_RULES_OFF = """- Do not convert anything into a bulleted or numbered list; keep the text as flowing prose \
(still honour an explicit spoken "new line" / "bullet point")."""


def _strip_think(s: str) -> str:
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<\|.*?\|>", "", s)
    return s.strip()


def _unwrap_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'“" and s[-1] in "\"'”":
        s = s[1:-1].strip()
    return s


def _proper_noun_ish(term: str) -> bool:
    """Terms the LLM can't just guess: names, acronyms, product names, code."""
    return (
        " " in term
        or any(c.isupper() for c in term[1:])
        or any(c.isdigit() for c in term)
        or "." in term or "-" in term or "/" in term
    )


def select_glossary(terms: list[str], cap: int) -> list[str]:
    """Send the LLM a focused subset: proper-noun-ish terms first (it needs those),
    then plain words up to the cap. Keeps the prompt small and cache-friendly, and
    the strengthened system prompt covers ordinary rare vocabulary from the model's
    own knowledge."""
    if cap <= 0 or len(terms) <= cap:
        return terms
    priority = [t for t in terms if _proper_noun_ish(t)]
    plain = [t for t in terms if not _proper_noun_ish(t)]
    return (priority + plain)[:cap]


_DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Small models translate Hindi if the prompt mentions anything but transliteration,
# so the Hindi pass is pure transliteration. Cleanup was already done deterministically
# (collapse_repeats / tidy_commas) before this.
HINDI_PROMPT = (
    "Convert every Devanagari word in the line to casual romanised Hindi (Latin letters, "
    "WhatsApp/chat style, no diacritics). Keep English words exactly as English. Do NOT "
    "translate any word to English, do NOT paraphrase, do NOT explain or add anything. "
    "Output ONLY the converted line."
)


class Cleaner:
    def __init__(self, url: str, model: str, timeout: int = 30, max_glossary_terms: int = 240,
                 keep_loaded: bool = True, hindi_model: str = "", hindi_active: bool = False):
        self.url = url.rstrip("/")
        self.model = model
        self.hindi_model = hindi_model or ""
        self.hindi_active = hindi_active     # config says Hindi->Roman is on
        self._hindi_used = False             # a Hindi transcript has actually come through
        self.timeout = timeout
        self.max_glossary_terms = max_glossary_terms
        self.keep_loaded = keep_loaded

    @property
    def keep_alive(self):
        return -1 if self.keep_loaded else "30m"

    def available(self) -> bool:
        try:
            requests.get(f"{self.url}/api/tags", timeout=2).raise_for_status()
            return True
        except Exception:
            return False

    def warm(self, glossary: list[str] | None = None,
             smart_format: bool = True, romanize_hindi: bool = False):
        """Run the real cleanup prompt on a tiny input so Ollama loads the model
        and primes its prompt cache (system + glossary). Use the SAME flags the
        live pipeline uses, or the cached prefix won't match."""
        try:
            self.clean("warm up.", glossary or [], _timeout=self.timeout,
                       smart_format=smart_format, romanize_hindi=romanize_hindi)
        except Exception:
            pass

    def ping(self):
        """Keep the model(s) resident in RAM (called on a timer when keep_loaded).
        The Hindi model is only kept warm once Hindi is actually in use, so an
        English-only user never loads it."""
        models = [self.model]
        if self.hindi_model and (self.hindi_active or self._hindi_used):
            models.append(self.hindi_model)
        for m in models:
            try:
                requests.post(f"{self.url}/api/generate",
                              json={"model": m, "prompt": "", "keep_alive": self.keep_alive},
                              timeout=90)
            except Exception:
                pass

    def _generate(self, model, system, prompt, timeout, num_ctx=8192):
        payload = {
            "model": model, "system": system, "prompt": prompt,
            "stream": False, "think": False, "keep_alive": self.keep_alive,
            "options": {"temperature": 0.1, "num_ctx": num_ctx},
        }
        r = requests.post(f"{self.url}/api/generate", json=payload, timeout=timeout)
        r.raise_for_status()
        return _unwrap_quotes(_strip_think(r.json().get("response", "")))

    def clean(self, raw: str, glossary: list[str], _timeout: int | None = None,
              smart_format: bool = True, romanize_hindi: bool = False) -> str:
        raw = raw.strip()
        if not raw:
            return raw
        to = _timeout or self.timeout

        # Hindi -> Roman: dedicated small-model transliteration pass (small models
        # translate instead of transliterate if asked to do anything else).
        if romanize_hindi and self.hindi_model and _DEVANAGARI.search(raw):
            try:
                out = self._generate(self.hindi_model, HINDI_PROMPT, raw, to)
                out = re.sub(r"\s*/?no_?think\s*$", "", out, flags=re.I).strip()
                if out and len(out) <= max(600, len(raw) * 5) and not _DEVANAGARI.search(out):
                    self._hindi_used = True
                    return out
            except Exception as e:
                print(f"[cleanup] hindi pass failed ({e.__class__.__name__}); trying main model")

        gl = select_glossary(glossary, self.max_glossary_terms)
        gloss = ", ".join(gl) if gl else "(none provided)"
        system = SYSTEM_PROMPT.replace(
            "{LIST_RULES}", LIST_RULES_ON if smart_format else LIST_RULES_OFF
        ).replace(
            "{SCRIPT_RULE}", SCRIPT_LATIN if romanize_hindi else SCRIPT_DEVANAGARI)
        # Stable prefix (glossary) first, variable part (transcript) last -> Ollama
        # reuses the KV cache across dictations.
        user = f"GLOSSARY:\n{gloss}\n\nRAW_TRANSCRIPT:\n{raw}\n\n/no_think"
        payload = {
            "model": self.model,
            "prompt": user,
            "system": system,
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0.1, "num_ctx": 8192},
        }
        try:
            r = requests.post(
                f"{self.url}/api/generate", json=payload, timeout=_timeout or self.timeout
            )
            r.raise_for_status()
            out = r.json().get("response", "")
        except Exception as e:
            print(f"[cleanup] skipped ({e.__class__.__name__}: {e}); using raw text")
            return raw
        out = _unwrap_quotes(_strip_think(out))
        # Guard against a model that ignored instructions and ballooned the text.
        if not out or len(out) > max(600, len(raw) * 5):
            return raw
        return out
