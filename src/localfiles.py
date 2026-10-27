"""Scans the user's local music folders into catalog-shaped entries (negative ids) with tags and embedded art."""
from __future__ import annotations

import json
import logging
import os
import time
import zlib
from pathlib import Path
from typing import Any

from appdata import CACHE_DIR

log = logging.getLogger("999player.local")

# audio only — video containers (mp4/mkv/mov…) are deliberately ignored
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".opus", ".ogg", ".aac", ".aiff", ".aif"}
MIME = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac", ".m4a": "audio/mp4",
        ".opus": "audio/ogg", ".ogg": "audio/ogg", ".aac": "audio/aac", ".aiff": "audio/aiff", ".aif": "audio/aiff"}
ART_DIR = CACHE_DIR / "localart"
ART_DIR.mkdir(parents=True, exist_ok=True)
INDEX_FILE = CACHE_DIR / "local.json"


def local_id(path: str) -> int:
    return -(zlib.crc32(path.lower().encode("utf-8")) % 2_000_000_000 or 1)


def _extract_art(path: Path) -> bytes | None:
    try:
        from mutagen.flac import FLAC
        from mutagen.id3 import ID3
        from mutagen.mp4 import MP4
        ext = path.suffix.lower()
        if ext == ".mp3":
            tags = ID3(str(path))
            for k, v in tags.items():
                if k.startswith("APIC") and getattr(v, "data", None):
                    return bytes(v.data)
        elif ext in (".m4a", ".mp4"):
            f = MP4(str(path))
            covr = f.tags.get("covr") if f.tags else None
            if covr:
                return bytes(covr[0])
        elif ext == ".flac":
            f = FLAC(str(path))
            if f.pictures:
                return bytes(f.pictures[0].data)
    except Exception:
        return None
    return None


def _tags(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"title": None, "artist": None, "album": None, "dur": 0, "track": None}
    try:
        import mutagen
        f = mutagen.File(str(path), easy=True)
        if f is not None:
            g = lambda k: (f.get(k) or [None])[0]  # noqa: E731
            out["title"], out["artist"], out["album"] = g("title"), g("artist"), g("album")
            tn = g("tracknumber")
            out["track"] = int(str(tn).split("/")[0]) if tn and str(tn).split("/")[0].isdigit() else None
            if getattr(f, "info", None) and getattr(f.info, "length", None):
                out["dur"] = int(round(f.info.length))
    except Exception as e:
        log.debug("tag read failed for %s: %s", path, e)
    return out


def scan(folders: list[str]) -> list[dict[str, Any]]:
    songs: list[dict[str, Any]] = []
    seen: set[int] = set()
    for folder in folders:
        root = Path(folder)
        if not root.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                p = Path(dirpath) / name
                if p.suffix.lower() not in AUDIO_EXT:
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                sid = local_id(str(p))
                if sid in seen:
                    continue
                seen.add(sid)
                t = _tags(p)
                art_path = ART_DIR / f"{abs(sid)}.jpg"
                has_art = art_path.exists()
                if not has_art:
                    data = _extract_art(p)
                    if data:
                        try:
                            art_path.write_bytes(data)
                            has_art = True
                        except OSError:
                            pass
                dur = int(t["dur"] or 0)
                songs.append({
                    "id": sid, "local": True, "title": (t["title"] or p.stem).strip(), "author": (t["artist"] or "unknown artist").strip(),
                    "path": str(p), "nativeUrl": p.resolve().as_uri(), "img": None, "localArt": has_art,
                    "dur": dur, "len": f"{dur // 60}:{dur % 60:02d}" if dur else None,
                    "cat": "local", "era": (t["album"] or "").strip() or None,
                    "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)),
                    "plays": 0, "prod": None, "eng": None, "loc": None, "rec": None, "rel": None, "prev": None, "leaked": None,
                    "leakType": None, "up": None, "src": "local", "alt": [], "disp": None, "sub": None, "lyr": False, "wt": False, "est": False,
                    "size": st.st_size, "track": t["track"], "folder": str(root),
                })
    songs.sort(key=lambda s: ((s.get("era") or "").lower(), s.get("track") or 0, s["title"].lower()))
    try:
        INDEX_FILE.write_text(json.dumps(songs, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    log.info("local scan: %d tracks in %d folders", len(songs), len(folders))
    return songs


def load_index() -> list[dict[str, Any]]:
    try:
        return json.loads(INDEX_FILE.read_text("utf-8")) if INDEX_FILE.exists() else []
    except Exception:
        return []


def mime_for(path: str) -> str:
    return MIME.get(Path(path).suffix.lower(), "application/octet-stream")


def art_path(sid: int) -> Path:
    return ART_DIR / f"{abs(int(sid))}.jpg"
