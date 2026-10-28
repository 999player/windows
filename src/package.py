from __future__ import annotations

import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else Path(r"C:\Projects\JuicePlayer")
APP_DIR = ROOT / "dist" / "999player"
INSTALLER = ROOT / "dist" / "999 player setup.exe"

SKIP_DIRS = {"dist", "build", "__pycache__", ".git", ".pytest_cache", "x", "github", "web", "mobile", "keys", ".claude"}
SKIP_FILES = {"README-for-friend.txt", "package2.py"}
NEVER = (".dev.vars", "secrets.cmd", "Secrets.swift", ".env")
SKIP_SUFFIX = {".pyc", ".log", ".png", ".spec"}
INSTALLER_FILES = ["installer.py", "make_installer.py", "accent.py", "assets/icon.ico", "assets/icon.png", "HOW_TO_COMPILE.md"]
INSTALLER_DIRS = ["ui/fonts/inter", "ui/covers"]


def add_tree(zf: zipfile.ZipFile, base: Path, arc_root: str = "") -> int:
    n = 0
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        zf.write(p, (Path(arc_root) / rel).as_posix())
        n += 1
    return n


def app_src() -> int:
    n = 0
    with zipfile.ZipFile(OUT / "app-src.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(ROOT.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(ROOT)
            if any(part in SKIP_DIRS for part in rel.parts[:-1]) or rel.name in SKIP_FILES:
                continue
            if rel.suffix in SKIP_SUFFIX and rel.as_posix() != "assets/icon.png":
                continue
            if rel.name in NEVER or rel.suffix == ".env":
                sys.exit(f"refusing to pack {rel}: secrets never go in app-src.zip")
            zf.write(p, rel.as_posix())
            n += 1
    return n


def installer_src() -> int:
    n = 0
    with zipfile.ZipFile(OUT / "installer-src.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in INSTALLER_FILES:
            p = ROOT / f
            if p.exists():
                zf.write(p, Path(f).as_posix())
                n += 1
        for d in INSTALLER_DIRS:
            n += add_tree(zf, ROOT / d, d)
    return n


def portable() -> int:
    readme = ROOT / "README-for-friend.txt"
    if readme.exists():
        shutil.copy2(readme, APP_DIR / "README.txt")
    with zipfile.ZipFile(OUT / "999player-ptb.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        return add_tree(zf, APP_DIR, "999player")


def main() -> None:
    if not (APP_DIR / "999player.exe").exists():
        sys.exit("dist\\999player missing — run build_exe.ps1 first")
    if not INSTALLER.exists():
        sys.exit("dist\\999 player setup.exe missing — run make_installer.py first")
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print(f"app-src.zip        {app_src()} files", flush=True)
    print(f"installer-src.zip  {installer_src()} files", flush=True)
    shutil.copy2(INSTALLER, OUT / "999player-setup.exe")
    print("999player-setup.exe copied", flush=True)
    print(f"999player-ptb.zip       {portable()} files", flush=True)
    print(f"\ndone in {time.time() - t0:.0f}s -> {OUT}")
    for p in sorted(OUT.iterdir()):
        print(f"  {p.name:22s} {p.stat().st_size / 1e6:7.1f} MB")


if __name__ == "__main__":
    main()
