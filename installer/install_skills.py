"""Install / export the packaged Claude skills, optionally under new names (used by the Inno installer).

  install_skills.py add --src claude_skills --skills pdf-to-mp3=my-name,text-to-mp3=text-to-mp3
                        [--export DIR] [--claude-code] --state STATE.json
  install_skills.py remove --state STATE.json

--export writes <new-name>.skill packages (for Claude Desktop / claude.ai: Settings > Skills > upload).
--claude-code installs the skill folders into ~/.claude/skills/<new-name>/.
When a skill is renamed, its `name:` and every mention of the other bundled skills' names are updated.
Exit code: 0 = ok, 2 = at least one skill was skipped or failed (details on stdout).
"""
import argparse
import io
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

BUNDLED = ["pdf-to-mp3", "pdf-to-tts", "text-to-mp3"]
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".html", ".py", ".js", ".css", ".csv"}


def home() -> Path:
    return Path(os.path.expanduser("~"))


def load_state(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(p: Path, st: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=2), encoding="utf-8")


def read_skill(src: Path, name: str) -> dict:
    """Return {relative path inside the skill: bytes} from <src>/<name>.skill."""
    with zipfile.ZipFile(src / f"{name}.skill") as z:
        entries = [i for i in z.infolist() if not i.is_dir()]
        top = {i.filename.split("/")[0] for i in entries}
        strip = f"{top.pop()}/" if len(top) == 1 and all("/" in i.filename for i in entries) else ""
        return {i.filename[len(strip):]: z.read(i) for i in entries}


def rewrite(files: dict, rename: dict) -> dict:
    """Apply renames to text files (name: line and cross-references between bundled skills)."""
    changed = {o: n for o, n in rename.items() if o != n}
    if not changed:
        return files
    pat = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, changed), key=len, reverse=True)) + r")(?![\w-])")
    out = {}
    for rel, data in files.items():
        if Path(rel).suffix.lower() in TEXT_SUFFIXES:
            try:
                data = pat.sub(lambda m: changed[m.group(1)], data.decode("utf-8")).encode("utf-8")
            except UnicodeDecodeError:
                pass
        out[rel] = data
    return out


def _pair(item: str):
    old, _, new = item.partition("=")
    return old.strip(), (new.strip() or old.strip())


def add(a) -> int:
    src, state_path = Path(a.src), Path(a.state)
    rename = dict(_pair(x) for x in a.skills.split(",") if x) if a.skills else {}
    for old, new in rename.items():
        if old not in BUNDLED:
            print(f"FAIL {old}: unknown skill")
            return 2
        if not NAME_RE.match(new) or len(new) > 64:
            print(f"FAIL {old}: '{new}' is not a valid skill name (lowercase letters, digits, hyphens)")
            return 2
    if len(set(rename.values())) != len(rename):
        print("FAIL: two skills have the same new name")
        return 2
    full_map = {n: rename.get(n, n) for n in BUNDLED}  # unselected skills keep their names
    st = load_state(state_path)
    recs = st.get("skills", [])
    owned = {r["path"] for r in recs if "path" in r}
    failed = 0
    for old, new in rename.items():
        try:
            files = rewrite(read_skill(src, old), full_map)
            if a.export:
                exp = Path(a.export)
                exp.mkdir(parents=True, exist_ok=True)
                target = exp / f"{new}.skill"
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
                    for rel, data in files.items():
                        z.writestr(f"{new}/{rel}", data)
                print(f"OK   {old} -> {new}: exported {target}")
            if a.claude_code:
                dest = home() / ".claude" / "skills" / new
                if dest.exists() and str(dest) not in owned:
                    failed += 1
                    print(f"SKIP {old} -> {new}: {dest} already exists and is not ours; pick another name")
                    continue
                if dest.exists():
                    shutil.rmtree(dest)
                for rel, data in files.items():
                    f = dest / rel
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(data)
                recs = [r for r in recs if r.get("path") != str(dest)] + [{"path": str(dest), "name": new}]
                print(f"OK   {old} -> {new}: installed in {dest}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {old}: {e}")
    st["skills"] = recs
    save_state(state_path, st)
    return 2 if failed else 0


def remove(a) -> int:
    state_path = Path(a.state)
    st = load_state(state_path)
    failed = 0
    for r in st.get("skills", []):
        d = Path(r["path"])
        try:
            if d.exists() and (d / "SKILL.md").exists():
                shutil.rmtree(d)
                print(f"OK   removed {d}")
        except OSError as e:
            failed += 1
            print(f"FAIL {d}: {e}")
    st["skills"] = []
    save_state(state_path, st)
    return 2 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("--src", required=True)
    p.add_argument("--skills", required=True, help="old=new[,old=new...] for each skill to install")
    p.add_argument("--export")
    p.add_argument("--claude-code", action="store_true")
    p.add_argument("--state", required=True)
    p.set_defaults(fn=add)
    p = sub.add_parser("remove")
    p.add_argument("--state", required=True)
    p.set_defaults(fn=remove)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
