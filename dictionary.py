"""Parse dictionary.txt into a term list + sounds-like correction map."""
import os
import re


def load(path: str):
    terms: list[str] = []
    corrections: list[tuple[str, str]] = []
    if not os.path.exists(path):
        return terms, corrections
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=>" in line:
                left, right = line.split("=>", 1)
                left, right = left.strip(), right.strip()
                if left and right:
                    corrections.append((left, right))
                    terms.append(right)
            else:
                terms.append(line)
    # de-dup, keep order
    seen = set()
    uniq = []
    for t in terms:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq, corrections


# 2-letter acronyms are only collapsed if known; 3+ letters always collapse.
_BUILTIN_2 = {
    "AI", "ML", "UI", "UX", "PR", "QA", "OS", "DB", "IP", "VM", "CI", "CD", "OK",
    "IO", "ID", "PC", "IT", "HR", "QA", "GA", "GP", "VC", "PE", "TV", "AC", "DC",
}
_LETTER_RUN = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z](?:\.)?(?:\s+[A-Za-z](?:\.)?){1,7})(?![A-Za-z])"
)


def acronym_set(terms: list[str]) -> set[str]:
    """All-caps alphabetic terms from the dictionary, as an upper-case set."""
    out = set(_BUILTIN_2)
    for t in terms:
        core = re.sub(r"[^A-Za-z]", "", t)
        if 2 <= len(core) <= 7 and core.isupper():
            out.add(core)
        # also register the singular of an all-caps plural like "LLMs"
        if 3 <= len(t) <= 8 and t[-1] == "s" and t[:-1].isupper() and t[:-1].isalpha():
            out.add(t[:-1])
    return out


def normalize_acronyms(text: str, known: set[str]) -> str:
    """Collapse spelled-out letter runs into acronyms: "l l m" -> "LLM",
    "g p u s" -> "GPUs", "R. A. G." -> "RAG". Conservative: 2-letter runs only
    fire for known acronyms, so ordinary prose is left alone."""
    def repl(m):
        letters = re.sub(r"[^A-Za-z]", "", m.group(1)).upper()
        plural = False
        if len(letters) >= 3 and letters.endswith("S") and (
            letters[:-1] in known or len(letters) - 1 >= 3
        ):
            letters, plural = letters[:-1], True
        if len(letters) >= 3 or letters in known:
            return letters + ("s" if plural else "")
        return m.group(0)

    return _LETTER_RUN.sub(repl, text)


def apply_literal_corrections(text: str, corrections: list[tuple[str, str]]) -> str:
    """Case-insensitive whole-word replacement, done before the LLM pass.

    Word boundaries stop "json" -> "JSON" from also hitting "jsonify".
    Longer phrases are applied first so "post grey sql" wins over "sql".
    """
    for wrong, right in sorted(corrections, key=lambda c: len(c[0]), reverse=True):
        left = r"\b" if wrong[:1].isalnum() else ""
        right_b = r"\b" if wrong[-1:].isalnum() else ""
        pattern = re.compile(left + re.escape(wrong) + right_b, re.IGNORECASE)
        text = pattern.sub(lambda _m, r=right: r, text)
    return text
