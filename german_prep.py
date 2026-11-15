"""Text preparation for the German Kokoro voices, which run on phonemes.

* years are spoken the German way (1913 -> "neunzehnhundertdreizehn", 2024 -> "zweitausendvierundzwanzig")
* abbreviations are spelled out ("Dr." -> "Doktor", "Mr." -> "Mister", "z. B." -> "zum Beispiel")
* names the phonemizer would read as English words are respelled ("May" -> "Mai", as in Karl May)
* English terms inside German text (e.g. "postcolonial turn") are phonemized with English rules instead of
  being read with German pronunciation rules
* the one German phoneme the model's vocabulary lacks (short "ü", as in müssen, würde, zurück) is mapped to the
  nearest symbol it has; without that the vowel was silently deleted ("fünf" -> "fnf")

English detection is deliberately conservative: runs of English words, and quoted terms judged as a whole.
Single ambiguous words ("These", "Said") are never switched on their own.

Four optional text files add exceptions (one entry per line, `#` starts a comment). They are looked up next to
the input and in the install folder, and entries there override the built-in tables:

    english_terms.txt    words or phrases that must be read with English pronunciation
    german_words.txt     words that must never be treated as English
    abbreviations.txt    "Prof. = Professor"  (German text);  "en: e.g. = for example"  (English quotes)
    pronunciations.txt   "May = Mai" (respelling) or "Said = /sɑːˈiːd/" (raw phonemes between slashes);
                         applied to German text only, whole words, case-sensitive
"""
from __future__ import annotations

import re
import threading
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


# ------------------------------------------------------------------ abbreviations and names
# written form -> spoken form. A key matches with or without spaces after inner dots ("z. B." / "z.B.").
DEFAULT_ABBREVIATIONS_DE = {
    # titles and forms of address
    "Dr.": "Doktor", "Prof.": "Professor", "Mr.": "Mister", "Mrs.": "Missis", "Ms.": "Miss", "Hr.": "Herr",
    "Frl.": "Fräulein", "Fa.": "Firma", "Jr.": "Junior", "Sr.": "Senior", "Dipl.": "Diplom",
    "St. Louis": "Saint Louis", "St.": "Sankt",
    # common phrases
    "z. B.": "zum Beispiel", "d. h.": "das heißt", "u. a.": "unter anderem", "u. ä.": "und ähnliches",
    "o. Ä.": "oder Ähnliches", "o. ä.": "oder ähnliches", "s. o.": "siehe oben", "s. u.": "siehe unten",
    "u. U.": "unter Umständen", "i. d. R.": "in der Regel", "z. T.": "zum Teil", "v. a.": "vor allem",
    "m. E.": "meines Erachtens", "a. a. O.": "am angegebenen Ort", "i. e.": "das heißt",
    "e. g.": "zum Beispiel", "et al.": "und andere", "usw.": "und so weiter", "usf.": "und so fort",
    "etc.": "et cetera", "bzw.": "beziehungsweise", "bspw.": "beispielsweise", "ggf.": "gegebenenfalls",
    "evtl.": "eventuell", "ca.": "zirka", "vgl.": "vergleiche", "ebd.": "ebenda", "ibid.": "ebenda",
    "cf.": "vergleiche", "sog.": "sogenannte", "inkl.": "inklusive", "exkl.": "exklusive", "zzgl.": "zuzüglich",
    "vs.": "versus",
    # references (only before a number, so that "die Art." / "der Abs." stay ordinary words)
    "Nr.": "Nummer", "Nrn.": "Nummern", "Abb.": "Abbildung", "Tab.": "Tabelle", "Kap.": "Kapitel",
    "Abs.": "Absatz", "Art.": "Artikel", "Anm.": "Anmerkung", "Bd.": "Band", "Bde.": "Bände", "Pkt.": "Punkt",
    "S.": "Seite", "Ss.": "Seiten", "pp.": "Seiten", "p.": "Seite", "Fig.": "Figur",
    # publications and counts (after a number: "2. Aufl.", "19. Jh.")
    "Aufl.": "Auflage", "Jh.": "Jahrhundert", "Jhd.": "Jahrhundert", "Jg.": "Jahrgang", "Std.": "Stunden",
    "Mio.": "Millionen", "Mrd.": "Milliarden", "Tsd.": "Tausend",
    # people and bibliography
    "Hrsg.": "Herausgeber", "hrsg.": "herausgegeben", "Hg.": "Herausgeber", "Übers.": "Übersetzung",
    "Verf.": "Verfasser", "Diss.": "Dissertation", "geb.": "geboren", "gest.": "gestorben",
    "Tel.": "Telefon", "Str.": "Straße", "Hbf.": "Hauptbahnhof",
}
# English abbreviations inside English quotes (everything else is left to the English phonemizer)
DEFAULT_ABBREVIATIONS_EN = {
    "e.g.": "for example", "i.e.": "that is", "cf.": "compare", "et al.": "and others", "vs.": "versus",
    "etc.": "et cetera", "ibid.": "ibidem", "pp.": "pages", "p.": "page", "Fig.": "Figure", "vol.": "volume",
}
# Names the phonemizer reads as English words. Applied to German text only (never inside English quotes).
DEFAULT_PRONUNCIATIONS = {"May": "Mai"}   # Karl May, not the English month

# only before a number: "Nr. 5", "Abb. 3", "S. 45" ...
_NEXT_DIGIT = {"Nr.", "Nrn.", "Abb.", "Tab.", "Kap.", "Abs.", "Art.", "Anm.", "Bd.", "Bde.", "Pkt.", "S.", "Ss.",
               "pp.", "p.", "Fig.", "vol."}
# only after a number: "2. Aufl.", "19. Jh.", "5 Mio."
_AFTER_DIGIT = {"Aufl.", "Jh.", "Jhd.", "Jg.", "Std.", "Mio.", "Mrd.", "Tsd."}
# only before a capitalized word ("St. Gallen" but not "5 St.")
_NEXT_CAPITAL = {"St."}
# these may end a sentence: keep the full stop that the abbreviation's dot stood for
_MAY_END_SENTENCE = {"usw.", "usf.", "etc.", "u. a.", "u. ä.", "o. Ä.", "o. ä.", "ebd.", "ibid.", "et al.",
                     "a. a. O.", "ff.", "f.", "vs.", "etc."}


def _abbr_core(key: str) -> str:
    """Regex for an abbreviation: spaces after inner dots are optional."""
    out = []
    for tok in re.findall(r"\.|\s+|[^.\s]+", key.strip()):
        if tok == ".":
            out.append(r"\.")
        elif tok.isspace():
            out.append(r"\s*" if out and out[-1] == r"\." else r"\s+")
        else:
            out.append(re.escape(tok))
    return "".join(out)


def _compile_abbreviations(table: dict[str, str]):
    """List of (regex, replacement function) pairs, longest keys first."""
    rules = []
    for key, spoken in sorted(table.items(), key=lambda kv: -len(kv[0])):
        variants = [(key, spoken)]
        if key[0].islower() and spoken[:1].islower():
            variants.append((key[0].upper() + key[1:], spoken[0].upper() + spoken[1:]))
        for k, sp in variants:
            core = _abbr_core(k)
            if k in _AFTER_DIGIT:
                pat = re.compile(r"(?P<pre>\d\.?\s*)" + core + r"(?!\w)")
            elif k in _NEXT_DIGIT:
                pat = re.compile(r"(?<![\w.])" + core + r"(?=\s*\d)")
            elif k in _NEXT_CAPITAL:
                pat = re.compile(r"(?<![\w.])" + core + r"(?=\s*[A-ZÄÖÜ])")
            else:
                pat = re.compile(r"(?<![\w.])" + core + r"(?!\w)")
            end_ok = key in _MAY_END_SENTENCE

            def repl(m, sp=sp, end_ok=end_ok):
                spoken_ = sp
                if end_ok and re.match(r"\s*$|\s+[A-ZÄÖÜ„“\"]", m.string[m.end():]):
                    spoken_ += "."
                return (m.group("pre") if "pre" in m.groupdict() else "") + spoken_

            rules.append((pat, repl))
    return rules


# page references after a number: "S. 45 f." / "S. 45 ff."
_PAGE_FF = re.compile(r"(?<=\d)\s*ff\.")
_PAGE_F = re.compile(r"(?<=\d)\s*f\.(?=\s|$|[,;)])")
# note: a trailing full stop after "f."/"ff." is restored when the abbreviation ends the sentence


def _read_map(name: str, dirs, lang_prefix: bool = False) -> dict[str, str]:
    """`key = value` lines; later entries and earlier directories win. With lang_prefix, "en:" lines are
    returned under a key prefixed with "en:"."""
    out: dict[str, str] = {}
    for d in reversed(list(dirs)):                      # first directory has the highest priority
        p = Path(d) / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" not in line:
                continue
            k, v = (s.strip() for s in line.split("=", 1))
            if k and v:
                out[k] = v
    return out


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
        dirs = list(dirs)
        self.english = _read_list("english_terms.txt", dirs)
        self.german = _read_list("german_words.txt", dirs)
        self._cache: dict[str, tuple[bool, bool]] = {}
        user = _read_map("abbreviations.txt", dirs)
        self._abbr_de = _compile_abbreviations(
            {**DEFAULT_ABBREVIATIONS_DE, **{k: v for k, v in user.items() if not k.lower().startswith("en:")}})
        self._abbr_en = _compile_abbreviations(
            {**DEFAULT_ABBREVIATIONS_EN,
             **{k[3:].strip(): v for k, v in user.items() if k.lower().startswith("en:")}})
        self.pron = {**DEFAULT_PRONUNCIATIONS, **_read_map("pronunciations.txt", dirs)}
        # a name you gave a pronunciation must never be swallowed by an English run ("Edward Said")
        self._pron_words = {k.lower() for k in self.pron if " " not in k}
        self._pron_re = (re.compile(r"(?<!\w)(" + "|".join(re.escape(k) for k in sorted(self.pron, key=len, reverse=True))
                                    + r")(?!\w)") if self.pron else None)

    def expand_abbreviations(self, text: str, lang: str = "de") -> str:
        """Spell out abbreviations ("Dr." -> "Doktor"). lang is "de" (German text) or "en" (English quotes)."""
        for pat, repl in (self._abbr_de if lang == "de" else self._abbr_en):
            text = pat.sub(repl, text)
        if lang == "de":
            def page(word):
                def repl(m):
                    end = bool(re.match(r"\s*$|\s+[A-ZÄÖÜ„“\"]", m.string[m.end():]))
                    return " " + word + ("." if end else "")
                return repl

            text = _PAGE_FF.sub(page("fortfolgende"), text)
            text = _PAGE_F.sub(page("folgende"), text)
        return text

    def apply_pronunciations(self, text: str):
        """Respell names; entries written as /phonemes/ are returned as placeholders plus a list of phoneme
        strings. Returns (text, raw_phonemes)."""
        raw: list[str] = []
        if self._pron_re is None:
            return text, raw

        def repl(m: re.Match) -> str:
            val = self.pron[m.group(1)]
            if len(val) > 2 and val.startswith("/") and val.endswith("/"):
                raw.append(val[1:-1])
                return f"{len(raw) - 1}"
            return val

        return self._pron_re.sub(repl, text), raw

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
        if len(w) >= 2 and not re.search(r"[äöüß]", w) and w not in self.german and w not in self._pron_words:
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
# The model's vocabulary has no short "ü" (ʏ, as in müssen, würde, zurück, Stück). kokoro-onnx silently deletes
# unknown symbols, which turned "fünf" into "fnf". "y" is the same vowel without the length mark.
PHONEME_MAP = {"ʏ": "y"}


def _espeak_lock():
    try:
        from kokoro_onnx.tokenizer import _espeak_lock as lock
        return lock
    except Exception:  # noqa: BLE001
        return threading.Lock()


_LOCK = _espeak_lock()


def _phon_de(tokenizer, text: str) -> str:
    """German phonemes like tokenizer.phonemize(text, "de"), but with the unknown short ü mapped, not dropped."""
    import phonemizer

    text = text.strip()
    if not text:
        return ""
    with _LOCK:
        raw = phonemizer.phonemize(text, "de", preserve_punctuation=True, with_stress=True)
    raw = "".join(PHONEME_MAP.get(c, c) for c in _MARK.sub("", raw))
    return "".join(c for c in raw if c in tokenizer.vocab).strip()


def _phon_en(tokenizer, text: str, lang: str) -> str:
    return _MARK.sub("", tokenizer.phonemize(text, lang)).strip()


_PLACEHOLDER = re.compile("(\\d+)")


def _german_segment(tokenizer, seg: str, lex: Lexicon) -> str:
    seg = lex.expand_abbreviations(seg, "de")
    seg = years_to_words(seg)
    seg, raw = lex.apply_pronunciations(seg)
    if not raw:
        return _phon_de(tokenizer, seg)
    out, pos = [], 0
    for m in _PLACEHOLDER.finditer(seg):            # entries given as /phonemes/ bypass the phonemizer
        out.append(_phon_de(tokenizer, seg[pos:m.start()]))
        out.append("".join(c for c in raw[int(m.group(1))] if c in tokenizer.vocab))
        pos = m.end()
    out.append(_phon_de(tokenizer, seg[pos:]))
    return " ".join(p for p in out if p)


def to_phonemes(text: str, tokenizer, lex: Lexicon, en_lang: str = "en-us") -> str:
    """Phoneme string for Kokoro-style models. German text: abbreviations spelled out, years as words, names
    respelled, German rules. English terms and quotes: English rules (digits and abbreviations left to English)."""
    parts, pos = [], 0
    for s, e in english_spans(text, lex):
        if s > pos:
            parts.append(_german_segment(tokenizer, text[pos:s], lex))
        parts.append(_phon_en(tokenizer, lex.expand_abbreviations(text[s:e], "en"), en_lang))
        pos = e
    if pos < len(text):
        parts.append(_german_segment(tokenizer, text[pos:], lex))
    return " ".join(p for p in parts if p)
