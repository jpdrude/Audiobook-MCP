"""MCP server (stdio) exposing the local TTS setup (Kokoro + Piper) to a desktop LLM.

English uses Kokoro (default voice af_sky); German uses Piper (default de_DE-thorsten-medium).
`language` = "auto" (default) guesses from the text; "en" / "de" force it.

Tools:
  list_voices()                      -> available voice names
  synthesize_text(text, output_path) -> short text to one MP3 (blocking)
  synthesize_markdown(markdown, output_path) -> Markdown to MP3 (long input = background job)
  start_book_render(input_dir, output_dir, ...) -> background job over HTML/MD chapters
  get_render_status(job_id)          -> progress of a job
  cancel_render_job(job_id)          -> stop a running job
  list_render_jobs()                 -> all jobs started by this server

Run:  C:\\tools\\kokoro-tts\\.venv\\Scripts\\python.exe C:\\tools\\kokoro-tts\\kokoro_mcp.py
NOTE: stdout is the MCP protocol channel; everything else must go to stderr.
"""
import contextlib
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
from mcp.server.mcpserver import MCPServer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import render_book as rb  # noqa: E402

JOBS_DIR = HERE / "jobs"
JOBS_DIR.mkdir(exist_ok=True)
DEFAULT_VOICE = rb.EN_DEFAULT_VOICE
DEFAULT_VOICE_DE = rb.DE_DEFAULT_VOICE

mcp = MCPServer(
    "kokoro-tts",
    instructions=(
        "Local, offline text-to-speech. English uses Kokoro on the GPU (default voice af_sky), "
        "German uses Piper (default de_DE-thorsten-medium). Leave language='auto' to detect it "
        "from the text. Use synthesize_text / synthesize_markdown for snippets and "
        "start_book_render for folders of HTML/Markdown chapters (poll get_render_status)."
    ),
)

_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def _prepare(language: str, voice: str, text: str):
    """Validate the voice, resolve engine + language, load the engine (stdout kept clean)."""
    if voice and voice not in _all_voices():
        raise ValueError(f"unknown voice {voice!r}; call list_voices")
    kind, voice, lang = rb.resolve(language, voice, text)
    with contextlib.redirect_stdout(sys.stderr):  # keep stdout clean for MCP
        eng = rb.get_engine(kind, voice, "auto")
    return eng, voice, lang


BACKGROUND_ABOVE_CHARS = 3000   # synthesize_markdown above this runs as a background job
CONFIRM_ABOVE_CHARS = 20000
CHARS_PER_AUDIO_SEC = 17.0   # measured: ~1350 chars -> ~75 s of speech
EST_REALTIME = 13.0          # measured on this GPU: 12-15x


def _needs_confirmation(chars: int, confirm: bool) -> dict | None:
    """For very long input return an ask-back payload (with time estimate) unless confirmed."""
    if chars <= CONFIRM_ABOVE_CHARS or confirm:
        return None
    audio_min = chars / CHARS_PER_AUDIO_SEC / 60
    synth_min = audio_min / EST_REALTIME
    return {
        "needs_confirmation": True,
        "characters": chars,
        "estimated_audio_minutes": round(audio_min, 1),
        "estimated_synthesis_minutes": round(synth_min, 1),
        "message": (
            f"This text is {chars:,} characters (over {CONFIRM_ABOVE_CHARS:,}): about "
            f"{audio_min:.0f} min of audio, roughly {synth_min:.1f} min to synthesize on the GPU. "
            "Ask the user whether to proceed, then call again with confirm=true. "
            "(synthesize_markdown then runs it as a background job you can poll with "
            "get_render_status and stop with cancel_render_job; synthesize_text blocks.)"),
    }


def _voices() -> list[str]:
    """Kokoro voices (English and other Kokoro languages)."""
    with np.load(rb.VOICES) as z:
        return sorted(z.files)


def _german_voices() -> list[str]:
    """Piper German voices that are downloaded to models/piper."""
    return sorted(p.stem for p in rb.PIPER_DIR.glob("*.onnx"))


def _all_voices() -> list[str]:
    return _voices() + _german_voices()


@mcp.tool()
def list_voices() -> dict:
    """List available voices. Kokoro prefixes: af/am = American female/male, bf/bm = British
    female/male (ef/em Spanish, ff French, if/im Italian, jf/jm Japanese, pf/pm Portuguese,
    zf/zm Chinese, hf/hm Hindi). German voices are Piper models named de_DE-<name>-<quality>.
    Leave `voice` empty in the synthesize tools to get the default for the language."""
    return {"defaults": {"en": DEFAULT_VOICE, "de": DEFAULT_VOICE_DE},
            "kokoro_voices": _voices(), "german_voices": _german_voices()}


@mcp.tool()
def synthesize_text(text: str, output_path: str, voice: str = "", speed: float = 1.0,
                    language: str = "auto", confirm: bool = False) -> dict:
    """Synthesize plain text into a single 64 kbps MP3 at output_path (must end in .mp3;
    parent folders are created). Blocks until finished. language: "auto" (detect English vs
    German), "en" or "de"; voice empty = default for the language (af_sky / de_DE-thorsten-
    medium). Above 20,000 characters it does nothing and returns needs_confirmation with a
    time estimate: ask the user, then repeat the call with confirm=true."""
    if not text.strip():
        raise ValueError("text is empty")
    ask = _needs_confirmation(len(text), confirm)
    if ask:
        return ask
    out = Path(output_path)
    if out.suffix.lower() != ".mp3":
        raise ValueError("output_path must end with .mp3")
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(".mp3.part")
    with _lock:
        eng, voice, lang = _prepare(language, voice, text)
        t0 = time.perf_counter()
        proc = rb.start_ffmpeg(part, {"title": text[:60], "artist": "Local TTS"}, eng.sr)
        try:
            samples, sr = eng.synth(text, voice=voice, lang=lang, speed=speed)
            rb.write_audio(proc, samples)
            rb.finish(proc, part, out)
        except BaseException:
            proc.kill()
            part.unlink(missing_ok=True)
            raise
        dt = time.perf_counter() - t0
    audio = len(samples) / sr
    return {"output": str(out), "voice": voice, "language": lang, "audio_seconds": round(audio, 2),
            "synth_seconds": round(dt, 2), "realtime_factor": round(audio / dt, 1),
            "provider": eng.provider}


@mcp.tool()
def synthesize_markdown(markdown: str, output_path: str, voice: str = "",
                        speed: float = 1.0, title: str = "", artist: str = "",
                        album: str = "", language: str = "auto", confirm: bool = False) -> dict:
    """Read a Markdown string aloud into one MP3 at output_path (must end in .mp3). Headings get
    a long pause, paragraphs and list items a short one. Formatting (bold, links, images,
    code fences, tables, front matter) is stripped, not spoken. Up to 3,000 characters it
    blocks and returns the finished MP3 info. Above that it starts a BACKGROUND job and returns
    immediately with a job_id (poll get_render_status, stop with cancel_render_job); the MP3
    appears at output_path when the job finishes, and an existing file there is replaced.
    Above 20,000 characters it first returns needs_confirmation with a time estimate: ask the
    user, then repeat the call with confirm=true. The ID3 title defaults to the first '# '
    heading. language: "auto" (detect English vs German), "en" or "de"; voice empty = default
    for the language (af_sky / de_DE-thorsten-medium)."""
    ask = _needs_confirmation(len(markdown), confirm)
    if ask:
        return ask
    if voice and voice not in _all_voices():
        raise ValueError(f"unknown voice {voice!r}; call list_voices")
    out = Path(output_path)
    if out.suffix.lower() != ".mp3":
        raise ValueError("output_path must end with .mp3")
    md_title, blocks = rb.markdown_blocks(markdown)
    if not blocks:
        raise ValueError("no speakable text found in markdown")
    out.parent.mkdir(parents=True, exist_ok=True)
    if len(markdown) > BACKGROUND_ABOVE_CHARS:
        # Long input: run as a background job so the call returns at once (no client timeout).
        job_id = time.strftime("%Y%m%d-%H%M%S")
        src = JOBS_DIR / f"{job_id}_src"
        src.mkdir(exist_ok=True)
        (src / (out.stem + ".md")).write_text(markdown, encoding="utf-8")
        out.unlink(missing_ok=True)  # render_book skips existing MP3s; overwrite like blocking mode
        job_id, log = _spawn_job(src, out.parent, voice, speed, artist or "Local TTS", album,
                                 title, output_file=out, language=language)
        audio_min = len(markdown) / CHARS_PER_AUDIO_SEC / 60
        return {"background": True, "job_id": job_id, "output": str(out),
                "estimated_audio_minutes": round(audio_min, 1),
                "estimated_synthesis_minutes": round(audio_min / EST_REALTIME, 1),
                "next": "Poll get_render_status(job_id); cancel_render_job(job_id) to stop."}
    part = out.with_suffix(".mp3.part")
    tags = {"title": title or md_title or out.stem, "artist": artist or "Local TTS"}
    if album:
        tags["album"] = album
    with _lock:
        eng, voice, lang = _prepare(language, voice, " ".join(t for _, t in blocks))
        t0 = time.perf_counter()
        proc = rb.start_ffmpeg(part, tags, eng.sr)
        try:
            with contextlib.redirect_stdout(sys.stderr):  # synth_blocks prints progress
                audio = rb.synth_blocks(eng, blocks, voice, lang, speed, proc)
            rb.finish(proc, part, out)
        except BaseException:
            proc.kill()
            part.unlink(missing_ok=True)
            raise
        dt = time.perf_counter() - t0
    return {"output": str(out), "voice": voice, "language": lang, "blocks": len(blocks),
            "audio_seconds": round(audio, 2), "synth_seconds": round(dt, 2),
            "realtime_factor": round(audio / dt, 1), "provider": eng.provider}


@mcp.tool()
def start_book_render(input_dir: str, output_dir: str, voice: str = "",
                      speed: float = 1.0, artist: str = "", album: str = "",
                      language: str = "auto") -> dict:
    """Start a background job rendering every .html or .md chapter in input_dir (sorted by name) to
    one MP3 per chapter in output_dir. Chapters whose MP3 already exists are skipped, so
    re-running resumes. language: "auto" detects English vs German per chapter (so mixed
    folders work), or force "en" / "de"; voice empty = default for the language (af_sky /
    de_DE-thorsten-medium). Returns a job_id; poll get_render_status. Only one job runs at a
    time."""
    inp = Path(input_dir)
    if not inp.is_dir() or not any(f for pat in ("*.html", "*.md", "*.markdown")
                                   for f in inp.glob(pat)):
        raise ValueError(f"no .html or .md files in {input_dir}")
    if voice and voice not in _all_voices():
        raise ValueError(f"unknown voice {voice!r}; call list_voices")
    job_id, log = _spawn_job(inp, Path(output_dir), voice, speed, artist, album,
                             language=language)
    return {"job_id": job_id, "log": str(log)}


def _spawn_job(inp: Path, out_dir: Path, voice: str, speed: float, artist: str = "",
               album: str = "", title: str = "", output_file: Path | None = None,
               language: str = "auto"):
    """Start render_book.py as a background process. One GPU job at a time."""
    running = [j for j, v in _jobs.items() if v["proc"].poll() is None]
    if running:
        raise RuntimeError(f"job {running[0]} is still running; wait for it to finish or "
                           "cancel it with cancel_render_job")
    job_id = time.strftime("%Y%m%d-%H%M%S")
    log = JOBS_DIR / f"{job_id}.log"
    cmd = [sys.executable, "-X", "utf8", str(HERE / "render_book.py"), str(inp), str(out_dir),
           "--voice", voice, "--lang", language, "--speed", str(speed)]
    # Always pass these (empty = no tag) so MCP jobs don't inherit render_book's Hamlet defaults.
    cmd += ["--artist", artist, "--album", album]
    if title:
        cmd += ["--title", title]
    logf = open(log, "wb")
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=0x08000000,  # no window
                            env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"})
    _jobs[job_id] = {"proc": proc, "log": log, "output_dir": str(out_dir),
                     "input_dir": str(inp), "voice": voice, "started": time.time(),
                     "output_file": str(output_file) if output_file else None}
    return job_id, log


def _status(job_id: str) -> dict:
    j = _jobs.get(job_id)
    if j is None:
        raise ValueError(f"unknown job_id {job_id!r}")
    text = j["log"].read_text(encoding="utf-8", errors="replace")
    done = re.findall(r"^\s*done (\S+\.mp3): (.+)$", text, re.M)
    cur = re.findall(r"^\[(\d+)/(\d+)\] (\S+)\s+title=", text, re.M)
    rc = j["proc"].poll()
    if j.get("cancelled"):
        state = "cancelled"
    else:
        state = "running" if rc is None else ("finished" if rc == 0 else f"failed (exit {rc})")
    errors = [l for l in text.splitlines() if "Traceback" in l or l.startswith(("RuntimeError", "ValueError"))]
    out = Path(j["output_dir"])
    extra = {}
    if j.get("output_file"):
        extra = {"output_file": j["output_file"], "output_exists": Path(j["output_file"]).exists()}
    return {
        **extra,
        "job_id": job_id, "state": state, "voice": j["voice"],
        "elapsed_seconds": round(time.time() - j["started"]),
        "current_chapter": (f"{cur[-1][0]}/{cur[-1][1]} {cur[-1][2]}" if cur else None),
        "chapters_done_this_run": [{"file": f, "detail": d} for f, d in done],
        "mp3_files_in_output_dir": len(list(out.glob("*.mp3"))) if out.is_dir() else 0,
        "errors": errors[:3],
    }


@mcp.tool()
def get_render_status(job_id: str) -> dict:
    """Progress of a book render job: state, current chapter, chapters finished, errors."""
    return _status(job_id)


@mcp.tool()
def cancel_render_job(job_id: str) -> dict:
    """Cancel a running book render job. Stops the renderer and its ffmpeg process, and deletes
    the unfinished .mp3.part file. Chapters already finished are kept, so starting the same
    job again resumes after them."""
    j = _jobs.get(job_id)
    if j is None:
        raise ValueError(f"unknown job_id {job_id!r}")
    proc = j["proc"]
    if proc.poll() is not None:
        return {"job_id": job_id, "cancelled": False,
                "reason": f"job already ended (exit {proc.returncode})"}
    j["cancelled"] = True
    # /T kills the whole tree (python + ffmpeg); /F forces it.
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   capture_output=True, creationflags=0x08000000)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    removed = []
    out = Path(j["output_dir"])
    if out.is_dir():
        inp = Path(j["input_dir"])
        for src in [*inp.glob("*.html"), *inp.glob("*.md"), *inp.glob("*.markdown")]:
            part = out / (src.stem + ".mp3.part")   # only this job's own partial files
            if part.exists():
                try:
                    part.unlink()
                    removed.append(part.name)
                except OSError:
                    pass
    return {"job_id": job_id, "cancelled": True, "removed_partial_files": removed,
            "mp3_files_kept": len(list(out.glob("*.mp3"))) if out.is_dir() else 0}


@mcp.tool()
def list_render_jobs() -> list[dict]:
    """All render jobs started since this server launched, with their state."""
    return [_status(j) for j in _jobs]


if __name__ == "__main__":
    mcp.run("stdio")
