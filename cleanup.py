"""LLM post-processing pass (local, via Ollama): fix jargon, punctuation, filler words.

This mirrors what Wispr Flow does after raw transcription. All local.
"""
import re
import json
import requests

SYSTEM_PROMPT = """You clean up raw speech-to-text transcripts. You are given a RAW_TRANSCRIPT that a \
speech recogniser produced from a person dictating, plus a GLOSSARY of terms that person uses.

Do all of the following, but conservatively:
- Fix words the recogniser clearly misheard. Use the GLOSSARY as the source of truth for the spelling \
and capitalisation of any term in it (people's names, product names, acronyms, jargon).
- ALSO fix misheard words that are NOT in the glossary, using your own knowledge. Speech recognisers \
routinely garble uncommon but real words - restore the word the person obviously meant. Examples of \
the kind of error to fix: "sick of fancy"/"psychofancy" -> "sycophancy"; "pharmaco kinetics" -> \
"pharmacokinetics"; "eebitda" -> "EBITDA"; "starry decisis" -> "stare decisis"; "cash mear" -> \
"cache"; "grock"/"crock" as an AI model -> "Grok" (or "Groq" for the inference chips/cloud). Prefer \
the rarer correct technical/academic word, or the glossary brand name, when the phonetics match and \
the context fits.
- Keep real domain terminology exactly as spoken - do not "simplify" a correct technical word into a \
common one.
- Acronyms: a spelled-out or spaced/dotted letter run is an acronym - write "l l m" as "LLM", \
"g p u" as "GPU", "r a g" as "RAG", "A. P. I." as "API". Plurals keep a lowercase s: "l l ms" / \
"LLM's" / "LLMS" -> "LLMs"; "APIs", "SDKs", "IDEs", "KPIs", "UUIDs". Possessive stays apostrophe-s \
("the LLM's output"). Use the glossary's capitalisation for mixed-case ones ("gRPC", "OAuth", "PyTorch"). If a number is \
glued to a word ("3l llms", "5 hundred") write it naturally ("three LLMs", "500").
- Fix punctuation, capitalisation, sentence boundaries, and obvious homophones ("their/there", "to/two/too").
- Remove filler words and false starts: "um", "uh", "you know", "sort of", "like" (as filler), stutters, \
repeated words, and immediate self-corrections ("send it to Bob, no wait, to Alice" -> "send it to Alice").
- Expand spoken formatting commands: "new line" / "new paragraph" -> actual line breaks; "period", \
"comma", "question mark", "open quote", "bullet point" -> the punctuation/markup.
- Keep the person's own wording, tone, register and meaning. Do NOT summarise, paraphrase, answer a \
question in the text, translate, censor, or add any content or commentary.
- If the transcript is already clean, return it unchanged.

Return ONLY the cleaned text - no preamble, no quotes, no notes."""


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


class Cleaner:
    def __init__(self, url: str, model: str, timeout: int = 30, max_glossary_terms: int = 240):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_glossary_terms = max_glossary_terms

    def available(self) -> bool:
        try:
            requests.get(f"{self.url}/api/tags", timeout=2).raise_for_status()
            return True
        except Exception:
            return False

    def warm(self, glossary: list[str] | None = None):
        """Preload the model (and prime the glossary prefix cache) at startup."""
        try:
            self.clean("warm up.", glossary or [], _timeout=self.timeout)
        except Exception:
            pass

    def clean(self, raw: str, glossary: list[str], _timeout: int | None = None) -> str:
        raw = raw.strip()
        if not raw:
            return raw
        gl = select_glossary(glossary, self.max_glossary_terms)
        gloss = ", ".join(gl) if gl else "(none provided)"
        # Stable prefix (glossary) first, variable part (transcript) last -> Ollama
        # reuses the KV cache across dictations.
        user = f"GLOSSARY:\n{gloss}\n\nRAW_TRANSCRIPT:\n{raw}\n\n/no_think"
        payload = {
            "model": self.model,
            "prompt": user,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "think": False,
            "keep_alive": "30m",
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
        if not out or len(out) > max(400, len(raw) * 4):
            return raw
        return out
