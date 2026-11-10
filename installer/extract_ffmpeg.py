"""Extract ffmpeg.exe (and its license) from the downloaded Gyan essentials zip into <dest>\\bin.

  extract_ffmpeg.py ZIP DEST_DIR
"""
import sys
import zipfile
from pathlib import Path


def main() -> int:
    zip_path, dest = Path(sys.argv[1]), Path(sys.argv[2])
    (dest / "bin").mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            parts = info.filename.split("/")
            if info.is_dir() or len(parts) < 2:
                continue
            if parts[-2] == "bin" and parts[-1] == "ffmpeg.exe":
                target = dest / "bin" / "ffmpeg.exe"
            elif len(parts) == 2 and parts[-1] in ("LICENSE", "README.txt"):
                target = dest / parts[-1]
            else:
                continue
            with z.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)
    ok = (dest / "bin" / "ffmpeg.exe").exists()
    print("ffmpeg.exe extracted" if ok else "ffmpeg.exe not found in archive")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
