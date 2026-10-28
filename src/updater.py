from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from appdata import DATA_DIR, FROZEN
from version import APP_VERSION, UPDATE_REPO

log = logging.getLogger("999player.updater")
UPDATES_DIR = DATA_DIR / "updates"
ASSET = "999player-setup.exe"
API = os.environ.get("JV_UPDATE_URL") or f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
HEADERS = {"User-Agent": f"999player/{APP_VERSION}", "Accept": "application/vnd.github+json"}
DETACHED, NEW_GROUP = 0x00000008, 0x00000200


@dataclass
class Release:
    version: str
    notes: str
    url: str
    size: int
    sha256: str
    published: str


def parse_version(s: str | None) -> tuple[int, ...]:
    nums = re.findall(r"\d+", str(s or ""))
    return tuple(int(x) for x in nums[:4]) or (0,)


def newer(candidate: str | None, than: str = APP_VERSION) -> bool:
    return parse_version(candidate) > parse_version(than)


def install_dir() -> Path | None:
    if not FROZEN:
        return None
    d = Path(sys.executable).resolve().parent
    return d if (d / "999player.exe").exists() else None


def check(timeout: float = 15) -> Release | None:
    r = requests.get(API, headers=HEADERS, timeout=timeout)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    d = r.json()
    asset = next((a for a in d.get("assets") or [] if a.get("name") == ASSET), None)
    if not asset:
        log.info("latest release %s has no %s", d.get("tag_name"), ASSET)
        return None
    digest = str(asset.get("digest") or "")
    return Release(version=str(d.get("tag_name") or d.get("name") or "").lstrip("vV"), notes=str(d.get("body") or "").strip(),
                   url=str(asset.get("browser_download_url") or ""), size=int(asset.get("size") or 0),
                   sha256=digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "",
                   published=str(d.get("published_at") or ""))


def local_file(version: str) -> Path:
    return UPDATES_DIR / f"999player-setup-{version}.exe"


def _meta_path(exe: Path) -> Path:
    return exe.with_suffix(".json")


def _read_meta(exe: Path) -> dict:
    try:
        return json.loads(_meta_path(exe).read_text("utf-8"))
    except Exception:
        return {}


def _write_meta(exe: Path, meta: dict) -> None:
    _meta_path(exe).write_text(json.dumps(meta), "utf-8")


def _looks_like_setup(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return "999player.exe" in zf.namelist()
    except Exception:
        return False


def have(rel: Release) -> Path | None:
    exe = local_file(rel.version)
    meta = _read_meta(exe)
    if exe.exists() and meta.get("version") == rel.version and (not rel.sha256 or meta.get("sha256") == rel.sha256) \
            and exe.stat().st_size == int(meta.get("size") or -1):
        return exe
    return None


def download(rel: Release, progress: Callable[[int, int], None] | None = None, cancelled: Callable[[], bool] | None = None) -> Path:
    exe = have(rel)
    if exe:
        return exe
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    exe = local_file(rel.version)
    for old in UPDATES_DIR.iterdir():
        if old.stem.split(".")[0] != exe.stem:
            try:
                old.unlink()
            except OSError:
                pass
    part = exe.with_suffix(".part")
    h = hashlib.sha256()
    done = 0
    with requests.get(rel.url, headers={"User-Agent": HEADERS["User-Agent"]}, stream=True, timeout=(15, 90), allow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or rel.size or 0)
        with open(part, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                if cancelled and cancelled():
                    raise RuntimeError("cancelled")
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    try:
        if rel.sha256 and h.hexdigest() != rel.sha256:
            raise RuntimeError("the download did not match the published checksum")
        if rel.size and done != rel.size:
            raise RuntimeError("the download stopped early")
        if not _looks_like_setup(part):
            raise RuntimeError("the downloaded file is not a 999 player setup")
    except Exception:
        part.unlink(missing_ok=True)
        raise
    part.replace(exe)
    _write_meta(exe, {"version": rel.version, "sha256": rel.sha256 or h.hexdigest(), "size": done, "notes": rel.notes[:2000], "at": time.time()})
    return exe


def pending() -> tuple[Path, str] | None:
    try:
        metas = sorted(UPDATES_DIR.glob("999player-setup-*.json"))
    except OSError:
        return None
    for mp in metas:
        exe = mp.with_suffix(".exe")
        meta = _read_meta(exe)
        v = str(meta.get("version") or "")
        if exe.exists() and newer(v) and not meta.get("tried") and exe.stat().st_size == int(meta.get("size") or -1):
            return exe, v
    return None


def cleanup() -> None:
    try:
        for mp in UPDATES_DIR.glob("999player-setup-*.json"):
            exe = mp.with_suffix(".exe")
            if not newer(str(_read_meta(exe).get("version") or "")):
                for p in (exe, mp, exe.with_suffix(".part")):
                    p.unlink(missing_ok=True)
    except OSError:
        pass


def apply(exe: Path, version: str) -> bool:
    target = install_dir()
    if not target or not exe.exists():
        return False
    meta = _read_meta(exe)
    meta["tried"] = time.time()
    _write_meta(exe, meta)
    try:
        subprocess.Popen([str(exe), "--update", str(target)], cwd=str(exe.parent), creationflags=DETACHED | NEW_GROUP, close_fds=True)
    except OSError as e:
        log.warning("could not start the update: %s", e)
        return False
    log.info("update %s handed to %s", version, exe)
    return True
