"""Register / unregister the MCP server in installed AI apps (used by the Inno Setup installer).

  register_clients.py add    --clients claude-desktop,cursor --python PY --script SERVER.py --state STATE.json
  register_clients.py remove --state STATE.json
  register_clients.py list

Every config file that already exists is backed up once (<name>.bak-audiobook-mcp-<time>) before it is
changed. Files that contain comments (JSONC) are not rewritten; the app is reported as FAIL instead.
Exit code: 0 = all fine, 2 = at least one client failed (details on stdout).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SERVER_NAME = "kokoro-tts"  # the skills refer to the server by this name


def home() -> Path:
    return Path(os.path.expanduser("~"))


def appdata() -> Path:
    return Path(os.environ.get("APPDATA") or (home() / "AppData" / "Roaming"))


# id -> (label, config file, top-level key, extra fields for the entry)
JSON_CLIENTS = {
    "claude-desktop": ("Claude Desktop", lambda: appdata() / "Claude" / "claude_desktop_config.json", "mcpServers", {}),
    "cursor": ("Cursor", lambda: home() / ".cursor" / "mcp.json", "mcpServers", {}),
    "windsurf": ("Windsurf", lambda: home() / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers", {}),
    "lmstudio": ("LM Studio", lambda: home() / ".lmstudio" / "mcp.json", "mcpServers", {}),
    "gemini-cli": ("Gemini CLI", lambda: home() / ".gemini" / "settings.json", "mcpServers", {}),
    "vscode": ("VS Code", lambda: appdata() / "Code" / "User" / "mcp.json", "servers", {"type": "stdio"}),
}
ALL_CLIENTS = [*JSON_CLIENTS, "claude-code"]


# ---------------------------------------------------------------- JSON helpers
def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments (outside strings) and trailing commas."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def read_json(path: Path):
    """Return (data, indent). Raises ValueError for unreadable files or files with comments."""
    if not path.exists() or not path.read_text(encoding="utf-8-sig").strip():
        return {}, 2
    raw = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            json.loads(_strip_jsonc(raw))
        except json.JSONDecodeError as e:
            raise ValueError(f"cannot parse {path.name}: {e}") from e
        raise ValueError(f"{path.name} contains comments; add the server by hand to keep them") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    m = re.search(r"\n([ \t]+)\"", raw)
    indent = ("\t" if m.group(1).startswith("\t") else len(m.group(1))) if m else 2
    return data, indent


def write_json(path: Path, data, indent, backed_up: set) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and str(path) not in backed_up:
        shutil.copy2(path, path.with_name(f"{path.name}.bak-audiobook-mcp-{time.strftime('%Y%m%d-%H%M%S')}"))
        backed_up.add(str(path))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- state file
def load_state(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(p: Path, st: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- Claude Code (CLI)
def claude_exe():
    return shutil.which("claude") or next(
        (str(p) for p in (home() / ".local" / "bin" / "claude.exe", home() / ".local" / "bin" / "claude") if p.exists()),
        None)


def run_cli(args, timeout=90):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------- actions
def add(a) -> int:
    state_path = Path(a.state)
    st = load_state(state_path)
    records = [r for r in st.get("mcp", []) if r["client"] not in a.clients.split(",")]
    backed_up, failed = set(), 0
    for cid in [c for c in a.clients.split(",") if c]:
        try:
            if cid == "claude-code":
                exe = claude_exe()
                if not exe:
                    raise RuntimeError("claude CLI not found")
                run_cli([exe, "mcp", "remove", "--scope", "user", SERVER_NAME])  # idempotent update
                rc, out = run_cli([exe, "mcp", "add", "--scope", "user", SERVER_NAME, "--", a.python, a.script])
                if rc != 0:
                    raise RuntimeError(out or f"claude mcp add exited {rc}")
                records.append({"client": cid, "script": a.script})
                print(f"OK   {cid}: added via 'claude mcp add' (user scope)")
                continue
            label, path_fn, key, extra = JSON_CLIENTS[cid]
            path = path_fn()
            data, indent = read_json(path)
            servers = data.setdefault(key, {})
            if not isinstance(servers, dict):
                raise ValueError(f"'{key}' in {path.name} is not an object")
            entry = {**extra, "command": a.python, "args": [a.script]}
            if servers.get(SERVER_NAME) != entry:
                servers[SERVER_NAME] = entry
                write_json(path, data, indent, backed_up)
            records.append({"client": cid, "path": str(path), "key": key, "script": a.script})
            print(f"OK   {cid}: {path}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {cid}: {e}")
    st["mcp"] = records
    save_state(state_path, st)
    return 2 if failed else 0


def remove(a) -> int:
    state_path = Path(a.state)
    st = load_state(state_path)
    backed_up, failed = set(), 0
    for r in st.get("mcp", []):
        cid = r["client"]
        try:
            if cid == "claude-code":
                exe = claude_exe()
                if exe:
                    run_cli([exe, "mcp", "remove", "--scope", "user", SERVER_NAME])
                print(f"OK   {cid}: removed")
                continue
            path = Path(r["path"])
            if not path.exists():
                print(f"OK   {cid}: config no longer exists")
                continue
            data, indent = read_json(path)
            servers = data.get(r["key"], {})
            cur = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
            if cur and cur.get("args") and cur["args"][0] == r["script"]:  # only remove what we added
                del servers[SERVER_NAME]
                write_json(path, data, indent, backed_up)
                print(f"OK   {cid}: removed from {path}")
            else:
                print(f"OK   {cid}: entry absent or changed by you, left alone")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {cid}: {e}")
    st["mcp"] = []
    save_state(state_path, st)
    return 2 if failed else 0


def list_(_a) -> int:
    for cid, (label, fn, key, _x) in JSON_CLIENTS.items():
        p = fn()
        print(f"{cid:15} {label:15} {p}  [{'config exists' if p.exists() else 'no config yet'}]")
    print(f"{'claude-code':15} {'Claude Code':15} CLI: {claude_exe() or 'not found'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("--clients", required=True, help="comma list of: " + ", ".join(ALL_CLIENTS))
    p.add_argument("--python", required=True)
    p.add_argument("--script", required=True)
    p.add_argument("--state", required=True)
    p.set_defaults(fn=add)
    p = sub.add_parser("remove")
    p.add_argument("--state", required=True)
    p.set_defaults(fn=remove)
    p = sub.add_parser("list")
    p.set_defaults(fn=list_)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
