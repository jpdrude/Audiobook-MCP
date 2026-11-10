"""Render HTML/Markdown chapters to MP3 with local neural TTS.

Engines: Kokoro (kokoro-onnx, GPU if possible) for English and other Kokoro languages;
Piper (CPU) for German, default voice de_DE-thorsten-medium.

Usage:
  render_book.py INPUT_DIR OUTPUT_DIR [--artist A] [--album B] [--voice V]
                 [--lang auto|en|de|<kokoro code>] [--speed S] [--provider auto|cuda|dml|cpu]
  render_book.py --test [--lang de] [--out-file OUTPUT_FILE.mp3]

--lang auto (default) guesses English vs German per file. Without --voice the defaults are
af_sky (English) and de_DE-thorsten-medium (German).
"""
import argparse
import html
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODEL = HERE / "models" / "kokoro-v1.0.onnx"
VOICES = HERE / "models" / "voices-v1.0.bin"
SR = 24000
PAUSE_HEADING = 1.2
PAUSE_PARA = 0.45
EN_DEFAULT_VOICE = "af_sky"
DE_DEFAULT_VOICE = "de_DE-thorsten-medium"
PIPER_DIR = HERE / "models" / "piper"


def make_kokoro(provider_pref):
    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    # Load CUDA/cuDNN DLLs shipped as pip wheels in this venv.
    if hasattr(ort, "preload_dlls"):
        try:
            ort.preload_dlls()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] preload_dlls failed: {e}")

    avail = ort.get_available_providers()
    order = {
        "cuda": ["CUDAExecutionProvider"],
        "dml": ["DmlExecutionProvider"],
        "cpu": [],
        "auto": ["CUDAExecutionProvider", "DmlExecutionProvider"],
    }[provider_pref]
    providers = [p for p in order if p in avail] + ["CPUExecutionProvider"]
    so = ort.SessionOptions()
    so.log_severity_level = 3  # silence harmless warnings
    sess = ort.InferenceSession(str(MODEL), sess_options=so, providers=providers)
    used = sess.get_providers()[0]
    print(f"[provider] requested={providers} active={sess.get_providers()} -> using {used}")
    return Kokoro.from_session(sess, str(VOICES)), used


_DE_WORDS = set("""der die das und ist nicht ein eine einer mit für auf den dem von sich auch wir ich
sind wird werden dass daß als aber wie oder bei nach über zum zur dem des im ihre ihr sein seine
noch nur kann wenn auch durch gegen diese dieser dieses können wurde hat haben war""".split())
_EN_WORDS = set("""the and of to is that it for with as on was are this be by not or have from
but they his her which you were their has had would there what about when who will more""".split())


def detect_language(text):
    """Very small heuristic: 'de' or 'en' from stopword counts (+ umlauts)."""
    sample = text[:6000].lower()
    words = re.findall(r"[a-zäöüß]+", sample)
    de = sum(w in _DE_WORDS for w in words) + 2 * len(re.findall(r"[äöüß]", sample)) // 3
    en = sum(w in _EN_WORDS for w in words)
    return "de" if de > en else "en"


def resolve(lang_arg, voice_arg, sample_text=""):
    """Decide engine/voice/lang code. Returns (kind, voice, lang_code)."""
    lang = (lang_arg or "auto").lower()
    voice = voice_arg or ""
    if lang == "auto":
        lang = "de" if (voice.startswith("de_") or detect_language(sample_text) == "de") else "en"
    if voice.startswith("de_") or (lang.startswith("de") and not voice):
        return "piper", voice or DE_DEFAULT_VOICE, "de"
    if lang.startswith("de"):                 # explicit non-German voice reading German
        return "kokoro", voice, "de"
    voice = voice or EN_DEFAULT_VOICE
    if lang in ("en", "english"):
        lang = "en-gb" if voice.startswith("b") else "en-us"
    return "kokoro", voice, lang


class KokoroEngine:
    kind = "kokoro"

    def __init__(self, provider_pref):
        self.k, self.provider = make_kokoro(provider_pref)
        self.sr = SR

    def synth(self, text, voice, lang, speed=1.0):
        s, sr = self.k.create(text, voice=voice, speed=speed, lang=lang)
        assert sr == SR, sr
        return s, sr


class PiperEngine:
    kind = "piper"
    provider = "CPUExecutionProvider"

    def __init__(self, voice):
        from piper import PiperVoice

        model = PIPER_DIR / f"{voice}.onnx"
        if not model.exists():
            raise FileNotFoundError(f"Piper voice model not found: {model}")
        self.voice_name = voice
        self.v = PiperVoice.load(str(model))
        self.sr = self.v.config.sample_rate

    def synth(self, text, voice=None, lang=None, speed=1.0):
        from piper import SynthesisConfig

        cfg = SynthesisConfig(length_scale=1.0 / speed) if speed != 1.0 else None
        chunks = list(self.v.synthesize(text, cfg))
        if not chunks:
            return np.zeros(0, dtype=np.float32), self.sr
        return np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32), self.sr


_engines = {}


def get_engine(kind, voice, provider_pref="auto"):
    """Engines are cached; one Kokoro session, one Piper model per voice."""
    key = ("kokoro",) if kind == "kokoro" else ("piper", voice)
    if key not in _engines:
        _engines[key] = KokoroEngine(provider_pref) if kind == "kokoro" else PiperEngine(voice)
    return _engines[key]


def extract(html_text):
    """Return (title, [(kind, text), ...]) with everything before </nav> skipped."""
    m = re.search(r"<h1\b[^>]*>(.*?)</h1>", html_text, re.S | re.I)
    title = clean(m.group(1)) if m else ""
    nav = re.search(r"</nav\s*>", html_text, re.I)
    body = html_text[nav.end():] if nav else html_text
    blocks = []
    for m in re.finditer(r"<(h1|h2|p)\b[^>]*>(.*?)</\1\s*>", body, re.S | re.I):
        text = clean(m.group(2))
        if text:
            blocks.append((m.group(1).lower(), text))
    if not title:
        title = next((t for k, t in blocks if k == "h1"), "")
    return title, blocks


def clean(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _md_inline(s):
    """Strip inline Markdown so only speakable text remains."""
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)                 # images
    s = re.sub(r"\[\^[^\]]+\]", "", s)                          # footnote refs
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)              # [text](url) -> text
    s = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", s)             # [text][ref] -> text
    s = re.sub(r"<(https?://|mailto:)[^>]+>", "", s)            # autolinks
    s = re.sub(r"`+([^`]*)`+", r"\1", s)                        # inline code
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)                   # bold
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)  # *italic*
    s = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", s)    # _italic_
    s = re.sub(r"~~(.+?)~~", r"\1", s)                          # strikethrough
    s = re.sub(r"<[^>]+>", "", s)                               # raw html tags
    s = html.unescape(s)
    s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!>|~])", r"\1", s)       # backslash escapes
    return re.sub(r"\s+", " ", s).strip()


def markdown_blocks(md):
    """Return (title, [(kind, text), ...]); kind is h1/h2 (long pause) or p (short pause)."""
    md = md.replace("\r\n", "\n").replace("\r", "\n")
    md = re.sub(r"\A---\n.*?\n---\n", "", md, flags=re.S)       # YAML front matter
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)              # html comments
    blocks, buf, fence = [], [], None

    def flush():
        if buf:
            text = _md_inline(" ".join(buf))
            if text:
                blocks.append(("p", text))
            buf.clear()

    for line in md.split("\n"):
        st = line.strip()
        fm = re.match(r"^(```+|~~~+)", st)
        if fence:                                   # inside a code fence: skip silently
            if fm and st.startswith(fence):
                fence = None
            continue
        if fm:
            flush()
            fence = fm.group(1)
            continue
        if not st:
            flush()
            continue
        h = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", st)
        if h:
            flush()
            text = _md_inline(h.group(2))
            if text:
                blocks.append(("h1" if len(h.group(1)) == 1 else "h2", text))
            continue
        if re.match(r"^([-*_])(\s*\1){2,}$", st) or re.match(r"^[=-]{3,}$", st):
            flush()                                  # horizontal rule / setext underline
            continue
        if st.startswith("|") or re.match(r"^[-|: ]+$", st):
            flush()                                  # table rows are not read aloud
            continue
        li = re.match(r"^([-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*)$", st)
        if li:
            flush()
            buf.append(li.group(2))
            flush()                                  # each list item is its own block
            continue
        buf.append(re.sub(r"^>\s?", "", st))         # blockquote marker stripped
    flush()
    title = next((t for k, t in blocks if k == "h1"), "")
    return title, blocks


def start_ffmpeg(out_part, tags, sr=SR):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1",
           "-i", "pipe:0", "-c:a", "libmp3lame", "-b:a", "64k", "-id3v2_version", "3"]
    for k, v in tags.items():
        if v:  # skip empty tags
            cmd += ["-metadata", f"{k}={v}"]
    cmd += ["-f", "mp3", str(out_part)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def write_audio(proc, samples):
    proc.stdin.write(np.asarray(samples, dtype="<f4").tobytes())


def silence(sec, sr=SR):
    return np.zeros(int(sr * sec), dtype=np.float32)


def synth_blocks(engine, blocks, voice, lang, speed, proc, label=""):
    """Synthesize each block with `engine`; proc must have been started with engine.sr."""
    total = 0.0
    n = len(blocks)
    for i, (kind, text) in enumerate(blocks, 1):
        samples, sr = engine.synth(text, voice=voice, lang=lang, speed=speed)
        write_audio(proc, samples)
        pause = silence(PAUSE_HEADING if kind in ("h1", "h2") else PAUSE_PARA, sr)
        write_audio(proc, pause)
        total += (len(samples) + len(pause)) / sr
        if i % 25 == 0 or i == n:
            print(f"  {label}block {i}/{n}  audio={total/60:.1f} min", flush=True)
    return total


def finish(proc, part, final):
    proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg exited with {rc}")
    part.replace(final)


def run_test(a):
    out = Path(a.out_file) if a.out_file else HERE / "test.mp3"
    if a.lang.lower().startswith("de"):
        blocks = [("h1", "Test der deutschen Stimme."),
                  ("p", "Die Geburt eines neuen Mediums ist zugleich aufregend und beängstigend. "
                        "Größe, Straße und Fußball sind schöne Wörter.")]
    else:
        blocks = [("h1", "Test of the Kokoro voice."),
                  ("p", "The quick brown fox jumps over the lazy dog, while the holodeck hums quietly. "
                        "Hamlet considers, once again, whether to be or not to be.")]
    kind, voice, lang = resolve(a.lang, a.voice, " ".join(t for _, t in blocks))
    eng = get_engine(kind, voice, a.provider)
    print(f"[engine] {kind} voice={voice} lang={lang} provider={eng.provider}")
    eng.synth("Warm up.", voice=voice, lang=lang, speed=a.speed)  # first call includes setup cost
    part = out.with_suffix(".mp3.part")
    proc = start_ffmpeg(part, {"title": "Test", "artist": "Test"}, eng.sr)
    t0 = time.perf_counter()
    audio = synth_blocks(eng, blocks, voice, lang, a.speed, proc)
    dt = time.perf_counter() - t0
    finish(proc, part, out)
    print(f"[test] provider={eng.provider} synth_time={dt:.2f}s audio={audio:.2f}s "
          f"realtime_factor={audio/dt:.1f}x  file={out}")


def run_book(a):
    inp, outd = Path(a.input_dir), Path(a.output_dir)
    files = sorted([*inp.glob("*.html"), *inp.glob("*.md"), *inp.glob("*.markdown")],
                   key=lambda p: p.name)
    if not files:
        sys.exit(f"No .html or .md files in {inp}")
    outd.mkdir(parents=True, exist_ok=True)
    used = "?"
    nfiles = len(files)
    t_all, audio_all = time.perf_counter(), 0.0
    for idx, f in enumerate(files, 1):
        final = outd / (f.stem + ".mp3")
        if final.exists():
            print(f"[{idx}/{nfiles}] skip (exists): {final.name}")
            continue
        raw = f.read_text(encoding="utf-8", errors="replace")
        title, blocks = (markdown_blocks(raw) if f.suffix.lower() in (".md", ".markdown")
                         else extract(raw))
        if not blocks:
            print(f"[{idx}/{nfiles}] WARNING no text blocks in {f.name}; skipped")
            continue
        print(f"[{idx}/{nfiles}] {f.name}  title={title!r}  blocks={len(blocks)}", flush=True)
        kind, voice, lang = resolve(a.lang, a.voice, " ".join(t for _, t in blocks))
        eng = get_engine(kind, voice, a.provider)
        used = eng.provider
        print(f"  [engine] {kind} voice={voice} lang={lang} provider={used}", flush=True)
        part = final.with_suffix(".mp3.part")
        tags = {"title": a.title or title or f.stem, "artist": a.artist, "album": a.album,
                "track": f"{idx}/{nfiles}"}
        proc = start_ffmpeg(part, tags, eng.sr)
        t0 = time.perf_counter()
        try:
            audio = synth_blocks(eng, blocks, voice, lang, a.speed, proc)
            finish(proc, part, final)
        except BaseException:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            proc.kill()
            part.unlink(missing_ok=True)
            raise
        dt = time.perf_counter() - t0
        audio_all += audio
        print(f"  done {final.name}: {audio/60:.1f} min audio in {dt:.0f}s "
              f"-> realtime factor {audio/dt:.1f}x ({used})", flush=True)
    dt = time.perf_counter() - t_all
    if audio_all:
        print(f"[all] {audio_all/60:.1f} min audio in {dt/60:.1f} min -> {audio_all/dt:.1f}x ({used})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir", nargs="?")
    ap.add_argument("output_dir", nargs="?")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--out-file")
    ap.add_argument("--artist", default="Janet H. Murray")
    ap.add_argument("--album", default="Hamlet on the Holodeck")
    ap.add_argument("--title", default="", help="override the ID3 title for every file")
    ap.add_argument("--voice", default="", help="default: af_sky (English) / "
                    "de_DE-thorsten-medium (German)")
    ap.add_argument("--lang", default="auto", help="auto, en, de, or a Kokoro lang code")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--provider", default="auto", choices=["auto", "cuda", "dml", "cpu"])
    a = ap.parse_args()
    if a.test:
        run_test(a)
    elif a.input_dir and a.output_dir:
        run_book(a)
    else:
        ap.error("give INPUT_DIR OUTPUT_DIR, or --test")


if __name__ == "__main__":
    main()
