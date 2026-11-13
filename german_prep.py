"""Text preparation for German voices that run on phonemes (the Martin model).

* years are spoken the German way (1913 -> "neunzehnhundertdreizehn", 2024 -> "zweitausendvierundzwanzig")
* English terms inside German text (e.g. "postcolonial turn") are phonemized with English rules instead of
  being read with German pronunciation rules

English detection is deliberately conservative: runs of English words, and quoted terms judged as a whole.
Single ambiguous words ("These", "Said") are never switched on their own. Exceptions can be added with two
optional text files (one entry per line, `#` starts a comment), looked up next to the input and in the
install folder:

    english_terms.txt   words or phrases that must be read with English pronunciation
    german_words.txt    words that must never be treated as English
"""
from __future__ import annotations

import re
from pathlib import Path

try:  # optional: without it only quotes and english_terms.txt are used
    from wordfreq import zipf_frequency
except ImportError:  # pragma: no cover
    zipf_frequency = None

# ------------------------------------------------------------------ numbers and years
_ONES = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf",
         "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn"]
_TENS = {2: "zwanzig", 3: "dreißig", 4: "vierzig", 5: "fünfzig", 6: "sechzig", 7: "siebzig", 8: "achtzig",
         9: "neunzig"}


def _below_100(n: int) -> str:
    if n < 20:
        return _ONES[n]
    t, o = divmod(n, 10)
    return _TENS[t] if o == 0 else ("ein" if o == 1 else _ONES[o]) + "und" + _TENS[t]


def year_to_words(year: int) -> str:
    """Spoken German form of a year between 1000 and 2099."""
    if 2000 <= year <= 2099:
        rest = year - 2000
        return "zweitausend" + ("" if rest == 0 else _below_100(rest))
    if 1000 <= year <= 1099:
        rest = year - 1000
        return "tausend" + ("" if rest == 0 else _below_100(rest))
    hundreds, rest = divmod(year, 100)  # 1100..1999: "neunzehnhundert..."
    return _below_100(hundreds) + "hundert" + ("" if rest == 0 else _below_100(rest))


_YEAR_RE = re.compile(r"(?<![\w.,/])(1[0-9]{3}|20[0-9]{2})(er)?(?![\w]|[.,]\d|\s*(?:%|€|EUR\b|Euro\b|Prozent\b|kg\b|km\b))")


def years_to_words(text: str) -> str:
    def repl(m: re.Match) -> str:
        return year_to_words(int(m.group(1))) + ("er" if m.group(2) else "")

    return _YEAR_RE.sub(repl, text)


# ------------------------------------------------------------------ English detection
_DE_STOP = set("""der die das den dem des ein eine einer einem einen eines und oder aber nicht ist sind war waren wird
werden wurde wurden hat haben hatte hatten sich auch als wie bei nach von vom zum zur mit für auf aus an am im um
über unter durch gegen ohne bis seit zwischen dass da wenn weil denn noch nur schon sehr mehr kann können soll
sollen muss müssen wir ihr sie er es ich du man dies diese dieser dieses dieses jede jeder jedes alle allen
vor hier dort dann also so zu in""".split())
# German function words that are NOT also common English words: these block an English reading of a quote.
_DE_STRICT = _DE_STOP - set("in an so war man was hat da am um also es dies bis zu".split())
_EN_FUNC = set("the of and or to in on at by for with from as a an is are was were be been this that these those "
               "its their his her".split())
_TOKEN = re.compile(r"[^\W\d_]+")
_GAP = re.compile(r"^[ \t,;:'’\-–/]{1,3}$")
_QUOTES = [("„", "“"), ("“", "”"), ("‚", "‘"), ("»", "«"), ('"', '"')]
_MARK = re.compile(r"\((?:[a-z]{2,3}(?:-[a-z]{2,4})?)\)")


def _read_list(name: str, dirs) -> set[str]:
    out: set[str] = set()
    for d in dirs:
        p = Path(d) / name
        if p.is_file():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.split("#", 1)[0].strip().lower()
                if line:
                    out.add(line)
    return out


class Lexicon:
    """User exceptions plus the English-ness test for single tokens."""

    STRONG_EN = 2.5     # minimum English zipf frequency of a clearly English word
    STRONG_DIFF = 0.9   # ... and how much more frequent it must be in English than in German

    def __init__(self, dirs=()):
        self.english = _read_list("english_terms.txt", dirs)
        self.german = _read_list("german_words.txt", dirs)
        self._cache: dict[str, tuple[bool, bool]] = {}

    def _freq(self, w: str):
        if zipf_frequency is None:
            return 0.0, 0.0
        return zipf_frequency(w, "en"), zipf_frequency(w, "de")

    def classify(self, token: str) -> tuple[bool, bool]:
        """Return (strong, weak). strong = clearly English; weak = leans English, only counts in a run."""
        w = token.lower()
        if w in self._cache:
            return self._cache[w]
        res = (False, False)
        if len(w) >= 2 and not re.search(r"[äöüß]", w) and w not in self.german:
            if w in self.english:
                res = (True, True)
            elif w not in _DE_STOP:
                en, de = self._freq(w)
                strong = ((en >= self.STRONG_EN and en - de >= self.STRONG_DIFF and de <= 4.0)
                          or (en > 0 and de == 0 and len(w) >= 5))
                weak = (not strong) and en >= 3.5 and en - de >= 0.3
                res = (strong, weak)
        self._cache[w] = res
        return res


def _quoted_spans(text: str):
    for op, cl in _QUOTES:
        pat = re.escape(op) + r"([^" + re.escape(cl) + r"]{2,90})" + re.escape(cl)
        for m in re.finditer(pat, text):
            yield m.start(1), m.end(1)


def english_spans(text: str, lex: Lexicon) -> list[tuple[int, int]]:
    """Character spans of `text` that should be read with English pronunciation."""
    toks = [(m.start(), m.end(), m.group(0)) for m in _TOKEN.finditer(text)]
    spans: list[tuple[int, int]] = []

    # 1. explicit terms from english_terms.txt (phrases or words)
    for term in sorted(lex.english, key=len, reverse=True):
        for m in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, flags=re.IGNORECASE):
            spans.append((m.start(), m.end()))

    # 2. runs of English words
    flags = [lex.classify(t[2]) for t in toks]
    i = 0
    while i < len(toks):
        if not (flags[i][0] or flags[i][1]):
            i += 1
            continue
        j = i
        while (j + 1 < len(toks) and (flags[j + 1][0] or flags[j + 1][1])
               and _GAP.match(text[toks[j][1]:toks[j + 1][0]])):
            j += 1
        run = range(i, j + 1)
        content = [k for k in run if toks[k][2].lower() not in _EN_FUNC and flags[k][0]]
        # a lone unquoted word is never switched (it may be a German word: "These", "Planes", "Partisan")
        if content and len(run) >= 2:
            spans.append((toks[i][0], toks[j][1]))
        i = j + 1

    # 3. quoted terms, judged as a whole
    for s, e in _quoted_spans(text):
        inner = [(m.group(0)) for m in _TOKEN.finditer(text[s:e])]
        if not inner or any(w.lower() in _DE_STRICT or w.lower() in lex.german for w in inner):
            continue
        votes = 0
        for w in inner:
            strong, weak = lex.classify(w)
            en, de = lex._freq(w.lower())
            if strong or weak or (en > 0 and en - de >= 0.2 and de < 2.5):
                votes += 1
        if votes / len(inner) >= 0.6:
            spans.append((s, e))

    # merge overlaps
    spans.sort()
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


# ------------------------------------------------------------------ phonemes
def _phon(tokenizer, text: str, lang: str) -> str:
    return _MARK.sub("", tokenizer.phonemize(text, lang)).strip()


def to_phonemes(text: str, tokenizer, lex: Lexicon, en_lang: str = "en-us") -> str:
    """Phoneme string for Kokoro-style models: German rules, English terms with English rules, years as words."""
    text = years_to_words(text)
    parts, pos = [], 0
    for s, e in english_spans(text, lex):
        if s > pos:
            parts.append(_phon(tokenizer, text[pos:s], "de"))
        parts.append(_phon(tokenizer, text[s:e], en_lang))
        pos = e
    if pos < len(text):
        parts.append(_phon(tokenizer, text[pos:], "de"))
    return " ".join(p for p in parts if p)
