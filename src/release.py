"""one command from source to a published update:

  py release.py 2.1.0 --notes "what changed"          build, package, publish v2.1.0 on github (the app picks it up)
  py release.py 2.1.0 --notes-file notes.txt           same, notes from a file (markdown is fine)
  py release.py 2.1.0 --draft ...                      publish as a draft: nothing updates until you press publish on github
  py release.py 2.1.0 --skip-build ...                 reuse dist\\ from the last build (only when nothing changed)
  py release.py 2.1.0 --bump-only                      just write the version into version.py + the exe version resources

steps: version bump -> build_exe.ps1 -> make_installer.py -> package.py -> gh release create vX.Y.Z with
999player-setup.exe (what installed apps download) and 999player-ptb.zip (portable). the repo is UPDATE_REPO in version.py;
it has to be public for installed apps to download from it. needs the github cli logged in (gh auth status).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from version import UPDATE_REPO  # noqa: E402

INSTALLER = ROOT / "dist" / "999 player setup.exe"
ASSET = ROOT / "dist" / "999player-setup.exe"
PORTABLE = Path(r"C:\Projects\JuicePlayer") / "999player-ptb.zip"


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def bump(version: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit("version must look like 2.1.0")
    vp = ROOT / "version.py"
    vp.write_text(re.sub(r'APP_VERSION = "[^"]*"', f'APP_VERSION = "{version}"', vp.read_text("utf-8")), "utf-8")
    tup = ", ".join(version.split(".") + ["0"])
    for name in ("version_info.txt", "version_info_setup.txt"):
        p = ROOT / "assets" / name
        s = p.read_text("utf-8")
        s = re.sub(r"filevers=\([^)]*\)", f"filevers=({tup})", s)
        s = re.sub(r"prodvers=\([^)]*\)", f"prodvers=({tup})", s)
        s = re.sub(r"StringStruct\('(FileVersion|ProductVersion)', '[^']*'\)", lambda m: f"StringStruct('{m.group(1)}', '{version}')", s)
        p.write_text(s, "utf-8")
    print(f"version {version} written to version.py, assets/version_info*.txt", flush=True)


def build() -> None:
    run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "build_exe.ps1")])
    run([sys.executable, str(ROOT / "make_installer.py")])
    run([sys.executable, str(ROOT / "package.py")])


def publish(version: str, notes: str, draft: bool) -> None:
    if not INSTALLER.exists():
        sys.exit(f"{INSTALLER} missing, run without --skip-build")
    if not PORTABLE.exists():
        sys.exit(f"{PORTABLE} missing, run without --skip-build")
    shutil.copy2(INSTALLER, ASSET)   # the asset name the app looks for (no spaces in the download url)
    tag = f"v{version}"
    cmd = ["gh", "release", "create", tag, "--repo", UPDATE_REPO, "--title", f"999 player {version}", "--notes", notes or f"999 player {version}",
           f"{ASSET}#999 player {version} setup (windows)", f"{PORTABLE}#999 player {version} portable (windows, unzip and run)"]
    if draft:
        cmd.append("--draft")
    run(cmd)
    print(f"\npublished {tag} on https://github.com/{UPDATE_REPO}/releases" + (" (draft)" if draft else "") +
          "\ninstalled apps see it on their next check (at launch and every six hours).", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="build and publish a 999 player release")
    ap.add_argument("version", help="like 2.1.0")
    ap.add_argument("--notes", default="", help="release notes shown inside the app")
    ap.add_argument("--notes-file", help="read the notes from this file")
    ap.add_argument("--draft", action="store_true", help="create the github release as a draft")
    ap.add_argument("--skip-build", action="store_true", help="publish what is in dist/ already")
    ap.add_argument("--bump-only", action="store_true", help="only write the version, no build, no publish")
    a = ap.parse_args()
    notes = Path(a.notes_file).read_text("utf-8").strip() if a.notes_file else a.notes.strip()
    t0 = time.time()
    bump(a.version)
    if a.bump_only:
        return
    if not a.skip_build:
        build()
    publish(a.version, notes, a.draft)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
