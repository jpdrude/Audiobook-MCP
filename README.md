# Audiobook-MCP

Fast, fully offline text-to-speech on your own PC, packaged as an **MCP server** for Claude Desktop and as a
**command-line renderer** that turns a folder of HTML or Markdown chapters into one MP3 per chapter.

- **English** is spoken by [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) through ONNX Runtime, on the
  GPU when one is available (default voice `af_sky`).
- **German** is spoken by "Martin", a community German fine-tune of the Kokoro architecture
  ([Godelaune/Kokoro-82M-ONNX-German-Martin](https://huggingface.co/Godelaune/Kokoro-82M-ONNX-German-Martin),
  Apache 2.0), because the official Kokoro model ships no German voices. It runs on the same runtime and GPU.
- Nothing leaves your machine. No API keys, no cloud.

Measured on a Windows 11 laptop with an NVIDIA RTX PRO 500 (Blackwell): English on CUDA renders about 13-15x
faster than real time (a 90-minute chapter in about 6 minutes), German about 3x; on the CPU English runs about 3x
and German only about 1x real time, so a GPU is recommended for German books.

## Features

- One MP3 per chapter (64 kbps mono) with ID3 title, artist, album and track number.
- Resumable: it writes `.part` files and renames them when a chapter is finished, and skips chapters whose MP3
  already exists.
- Language is chosen per file (`auto`, `en` or `de`), so a folder can mix English and German chapters.
- German text is prepared before it is spoken (`german_prep.py`): years are read the German way (1913 becomes
  "neunzehnhundertdreizehn"), English terms inside German sentences ("postcolonial turn", quoted words, titles)
  are pronounced with English rules, and whole English paragraphs, such as block quotes in a thesis, are read by
  the English voice. A few exceptions can be added with optional `english_terms.txt` and `german_words.txt`
  files (one entry per line) next to the chapters, for example proper names that must not be switched.
- Markdown input is cleaned for listening: bold, links, images, code fences, tables and front matter are not
  read aloud. Headings get a 1.2 s pause, paragraphs and list items 0.45 s.
- Long jobs run in the background and can be polled and cancelled from the MCP client.

## Requirements

- Windows 11 (the only platform tested; the scripts themselves are portable Python)
- **Python 3.12** (kokoro-onnx does not support 3.14)
- **ffmpeg** on `PATH` (for example `winget install Gyan.FFmpeg`)
- Optional: an NVIDIA GPU for Kokoro (CUDA). Without one it runs on the CPU, only slower.

## Installer (recommended)

`installer\Audiobook-MCP.iss` is an [Inno Setup](https://jrsoftware.org/isinfo.php) 6 script. Build it with
`ISCC.exe installer\Audiobook-MCP.iss`; the result is `installer\Output\Audiobook-MCP-Setup-<version>.exe` (about
2 MB: the large parts are downloaded while installing, so the PC must be online). It installs for the current
user only (no administrator rights) and lets you choose:

- **Voices:** English (Kokoro, about 350 MB) and/or German (Martin, about 330 MB). Downloads are verified against
  pinned SHA-256 checksums.
- **Acceleration:** NVIDIA CUDA (preselected if an NVIDIA driver 580 or newer is found) or CPU. German is slow on
  the CPU (about real time), so choose CUDA if you can.
- **MCP server in your AI apps:** it detects Claude Desktop, Claude Code, Cursor, VS Code, Windsurf, LM Studio and
  Gemini CLI and adds the server to the ones you tick. Each changed config file is backed up first, files with
  comments are left alone, and the uninstaller removes only the entry it added.
- **Claude skills:** each of the three bundled skills has its own checkbox and a name field to rename it
  (references between the skills are renamed too). They can be installed into Claude Code and/or exported as
  `.skill` packages to upload in Claude Desktop or claude.ai (Settings > Skills). They use Claude's own tools, so
  they are only offered for Claude.

It also creates the Python 3.12 environment (installing Python 3.12 for your user if it is missing) and downloads
ffmpeg if none is on `PATH`.

Silent install, all choices on the command line:

```powershell
Audiobook-MCP-Setup-0.2.0.exe /VERYSILENT /SUPPRESSMSGBOXES /DIR="C:\Tools\Audiobook-MCP" `
    /COMPONENTS="core,english,german" /ACCEL=cuda /MCPCLIENTS=claude-desktop,cursor `
    /SKILLS=all /SKILLTARGETS=export
```

`/ACCEL` is `auto`, `cuda` or `cpu`; `/MCPCLIENTS` is `none`, `auto` (every detected app) or a list of
`claude-desktop, claude-code, cursor, vscode, windsurf, lmstudio, gemini-cli`; `/SKILLS` is `none`, `all` or a list
of skill names; `/SKILLTARGETS` is `none`, `all`, `export` or `claude-code`. Without these switches the wizard
defaults apply, which tick every detected app.

Verification status: the silent install, upgrade and uninstall paths were run end to end (including CUDA, the
Claude Desktop, Cursor and Claude Code registration, and skill export/install), and the config helpers were
exercised for every supported app against fake config files. Not yet verified: the interactive wizard pages
themselves, the step that downloads Python (it was already installed), and registration in real Windsurf, LM Studio,
Gemini CLI and VS Code installations.

## Manual setup

If you prefer not to use the installer. Replace `<repo>` with the folder you cloned into.

```powershell
git clone https://github.com/jpdrude/Audiobook-MCP.git
cd Audiobook-MCP
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install kokoro-onnx soundfile numpy mcp
```

### ONNX Runtime: install exactly one variant

`kokoro-onnx` pulls in the plain CPU `onnxruntime`. Keep only the variant that matches your hardware:

```powershell
# NVIDIA GPU, driver 580 or newer (CUDA 13 runtime libraries are installed as pip wheels inside the venv)
.\.venv\Scripts\python.exe -m pip uninstall -y onnxruntime
.\.venv\Scripts\python.exe -m pip install -r installer\requirements-cuda.txt

# No NVIDIA GPU: nothing to do, the CPU onnxruntime is already installed.
```

DirectML (AMD / Intel GPUs) is not supported: the Kokoro v1.0 model fails in its `ConvTranspose` layers there
(tested with onnxruntime-directml 1.21 to 1.24 on two GPUs). Use the CPU on those machines (about 3x real time).

Check which provider loads: `render_book.py --test` prints `provider=CUDAExecutionProvider` (or
`CPUExecutionProvider`). If CUDA fails to load, the CUDA/cuDNN wheel versions do not match your `onnxruntime-gpu`
build; the error message names the missing DLL.

### German voice (Martin)

Martin runs on `kokoro-onnx` as well, so nothing else is needed for the voice itself. English-term detection in
German text uses the `wordfreq` word-frequency list:

```powershell
.\.venv\Scripts\python.exe -m pip install -r installer\requirements-german.txt
```

### Download the models

Models are not part of the repository. Put them in `models\` (the folder is git-ignored):

```powershell
mkdir models, models\kokoro-de-martin

# Kokoro, English (about 350 MB)
$k = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
curl.exe -L --fail -o models\kokoro-v1.0.onnx $k/kokoro-v1.0.onnx
curl.exe -L --fail -o models\voices-v1.0.bin  $k/voices-v1.0.bin

# Martin, German (about 330 MB), pinned to a repository revision
$m = "https://huggingface.co/Godelaune/Kokoro-82M-ONNX-German-Martin/resolve/a1cba7fbf0e72fbae38f0a3a48ce0dc8e6077804"
curl.exe -L --fail -o models\kokoro-de-martin\kokoro-martin.onnx $m/kokoro-martin.onnx
curl.exe -L --fail -o models\kokoro-de-martin\voices-martin.npz  $m/voices-martin.npz
```

SHA-256 of the two Martin files: `c302f1d8bc7adf40a842cb550e18c39a5026bdb1afdd29dbb700b501cb49276b`
(`kokoro-martin.onnx`) and `5b9c8553398d7abf67498ce500c186cefaa7b68fed3e3d415da5380670105acd`
(`voices-martin.npz`).

## Command line

```powershell
# Quick test (writes test.mp3 and prints the provider and speed)
.\.venv\Scripts\python.exe render_book.py --test
.\.venv\Scripts\python.exe render_book.py --test --lang de

# Render a folder of chapters (.html, .md, .markdown), sorted by file name
.\.venv\Scripts\python.exe render_book.py "C:\books\MyBook" "C:\books\MyBook\mp3" `
    --artist "Author Name" --album "Book Title"
```

Options: `--lang auto|en|de|<kokoro code>` (default `auto`), `--voice NAME`, `--speed 1.0`,
`--provider auto|cuda|cpu`, `--title` (override the ID3 title). Without `--voice` the defaults are `af_sky`
(English) and `martin` (German).

`render_book.bat` does the same with a double-click: it activates the venv and asks for the input and output
folders. Name chapter files `NN_Title.html` so they sort in reading order; track order and the default track
title (the first `<h1>` or `#` heading) come from there.

HTML input: everything before `</nav>` (the table of contents) is skipped; then `<h1>`, `<h2>` and `<p>` blocks
are read in order.

## Use it from Claude Desktop (MCP)

Add the server to `%APPDATA%\Claude\claude_desktop_config.json` under `mcpServers`, with your own paths, then
**fully quit** Claude Desktop (tray icon > Quit) and reopen it:

```json
"kokoro-tts": {
  "command": "C:\\path\\to\\Audiobook-MCP\\.venv\\Scripts\\python.exe",
  "args": ["C:\\path\\to\\Audiobook-MCP\\kokoro_mcp.py"]
}
```

The server is registered as `kokoro-tts`; the packaged skills below refer to it by that name.

| Tool | What it does |
|---|---|
| `list_voices` | Defaults per language, all Kokoro voices, installed German voices. |
| `synthesize_text` | Plain text to one MP3. Blocks until done. |
| `synthesize_markdown` | Markdown to one MP3. Up to 3,000 characters it blocks; longer input starts a background job and returns a `job_id`. |
| `start_book_render` | Background job over a folder of `.html` / `.md` chapters; returns a `job_id`. Existing MP3s are skipped, so re-running resumes. |
| `get_render_status` | State, current chapter, finished chapters and errors of a job. |
| `cancel_render_job` | Stops a running job (renderer and ffmpeg) and removes its partial files. |
| `list_render_jobs` | All jobs started since the server launched. |

Notes:

- `language` on the synthesize and render tools is `auto` (default), `en` or `de`. `voice` empty means the default
  for that language.
- `auto` is a small word-count heuristic. For short texts, or text full of quotations in another language, set
  `language` explicitly.
- Giving a Kokoro voice together with German text makes that voice read German with an accent. Leave `voice`
  empty for German to get Martin.
- Above 20,000 characters, `synthesize_text` and `synthesize_markdown` first return `needs_confirmation` with a
  time estimate; call again with `confirm=true` to proceed.
- Only one background job runs at a time.
- Jobs write their logs to `jobs\` (git-ignored).

## Claude skills

`claude_skills\` contains packaged skills that use this server: `text-to-mp3` (render files or text),
`pdf-to-tts` (PDF to a read-along HTML page) and `pdf-to-mp3` (PDF to a chapter-by-chapter audiobook).

## Licenses and credits

This project is MIT licensed (see `LICENSE`). It builds on, but does not include or redistribute:

- [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) and the Kokoro-82M model
- The German "Martin" model: ONNX export by Godelaune of
  [kikiri-tts/kikiri-german-martin](https://huggingface.co/kikiri-tts/kikiri-german-martin), trained on a German
  multispeaker base by dida-80b (voice recordings of Martin Harbecke, according to the model card)
- [wordfreq](https://github.com/rspeer/wordfreq), used to tell English words from German ones
- [ONNX Runtime](https://onnxruntime.ai/), [ffmpeg](https://ffmpeg.org/) and the
  [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

Each of these has its own license; check their repositories before redistributing anything built from them. The
Martin model is a community model whose provenance chain (Kokoro, a German multispeaker base, a single-speaker
fine-tune, an ONNX export) is documented only on its model cards. The model files you download are covered by their own licenses, not by this one.

Rendering audio from a copyrighted book is fine for your own use, but do not redistribute the resulting MP3s.
