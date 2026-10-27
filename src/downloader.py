"""Background audio downloader with progress, safe filenames and optional tagging."""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

import requests
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger("999player.downloader")

AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a", ".opus", ".ogg", ".mp4", ".aac")


def safe_name(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s or "").strip(" .")
    s = re.sub(r"\s{2,}", " ", s)
    return (s or "song")[:110]


def ext_of(url: str) -> str:
    low = url.lower().split("?")[0]
    for e in AUDIO_EXTS:
        if low.endswith(e):
            return e
    return ".mp3"


def tag_file(path: Path, song: dict[str, Any], cover: bytes | None) -> None:
    """Write basic tags + cover art. Best effort; never raises."""
    try:
        import mutagen
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import APIC, ID3, ID3NoHeaderError
        from mutagen.flac import FLAC, Picture
        from mutagen.mp4 import MP4, MP4Cover

        title = song.get("title") or "Untitled"
        artist = song.get("author") or "Juice WRLD"
        album = song.get("era") or "999 player"
        ext = path.suffix.lower()
        if ext == ".mp3":
            try:
                tags = EasyID3(str(path))
            except ID3NoHeaderError:
                tags = EasyID3()
            tags["title"] = title
            tags["artist"] = artist
            tags["album"] = album
            tags["albumartist"] = "Juice WRLD"
            tags.save(str(path))
            if cover:
                id3 = ID3(str(path))
                id3.delall("APIC")
                id3.add(APIC(encoding=3, mime="image/webp" if cover[:4] == b"RIFF" else "image/jpeg", type=3, desc="Cover", data=cover))
                id3.save(str(path))
        elif ext == ".flac":
            f = FLAC(str(path))
            f["title"] = title; f["artist"] = artist; f["album"] = album
            if cover:
                pic = Picture(); pic.data = cover; pic.type = 3
                pic.mime = "image/webp" if cover[:4] == b"RIFF" else "image/jpeg"
                f.clear_pictures(); f.add_picture(pic)
            f.save()
        elif ext in (".m4a", ".mp4"):
            f = MP4(str(path))
            f["\xa9nam"] = [title]; f["\xa9ART"] = [artist]; f["\xa9alb"] = [album]
            if cover and cover[:4] != b"RIFF":
                f["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
            f.save()
        else:
            f = mutagen.File(str(path), easy=True)
            if f is not None:
                f["title"] = title; f["artist"] = artist; f["album"] = album
                f.save()
    except Exception as e:
        log.info("tagging skipped for %s: %s", path.name, e)


class _Signals(QObject):
    progress = Signal(int, int, int)           # song_id, received, total
    done = Signal(int, str, bool, str, int)    # song_id, path, ok, error, size


class _Job(QRunnable):
    def __init__(self, song: dict[str, Any], url: str, cover_url: str | None, out: Path, signals: _Signals, tag: bool) -> None:
        super().__init__()
        self.song, self.url, self.cover_url, self.out, self.signals, self.tag = song, url, cover_url, out, signals, tag

    def run(self) -> None:
        sid = int(self.song["id"])
        tmp = self.out.with_suffix(self.out.suffix + ".part")
        try:
            self.out.parent.mkdir(parents=True, exist_ok=True)
            with requests.get(self.url, stream=True, timeout=60, headers={"User-Agent": "999player/2.1"}) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                got, last_emit = 0, 0.0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=128 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        got += len(chunk)
                        now = time.time()
                        if now - last_emit > 0.08:
                            self.signals.progress.emit(sid, got, total)
                            last_emit = now
                self.signals.progress.emit(sid, got, total or got)
            cover = None
            if self.tag and self.cover_url:
                try:
                    if self.cover_url.startswith("file:"):
                        from urllib.request import url2pathname
                        from urllib.parse import urlparse
                        cover = Path(url2pathname(urlparse(self.cover_url).path)).read_bytes()
                    else:
                        cr = requests.get(self.cover_url, timeout=20, headers={"User-Agent": "999player/2.1"})
                        if cr.ok and len(cr.content) < 6_000_000:
                            cover = cr.content
                except Exception:
                    cover = None
            tmp.replace(self.out)
            if self.tag:
                tag_file(self.out, self.song, cover)
            self.signals.done.emit(sid, str(self.out), True, "", self.out.stat().st_size)
        except Exception as e:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            log.warning("download failed for %s: %s", sid, e)
            self.signals.done.emit(sid, "", False, str(e), 0)


class Downloader(QObject):
    progress = Signal(int, int, int)
    done = Signal(int, str, bool, str, int)

    def __init__(self) -> None:
        super().__init__()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(3)
        self._signals = _Signals()
        self._signals.progress.connect(self.progress)
        self._signals.done.connect(self._on_done)
        self.active: set[int] = set()

    def _on_done(self, sid: int, path: str, ok: bool, err: str, size: int) -> None:
        self.active.discard(sid)
        self.done.emit(sid, path, ok, err, size)

    def enqueue(self, song: dict[str, Any], url: str, cover_url: str | None, folder: Path, tag: bool) -> Path | None:
        sid = int(song["id"])
        if not url or sid in self.active:
            return None
        ext = ext_of(url)
        base = f"{safe_name(song.get('author') or 'Juice WRLD')} - {safe_name(song.get('title') or 'Untitled')}"
        out = folder / f"{base}{ext}"
        i = 2
        while out.exists():
            out = folder / f"{base} ({i}){ext}"
            i += 1
        self.active.add(sid)
        self._pool.start(_Job(song, url, cover_url, out, self._signals, tag))
        return out
