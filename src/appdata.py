"""App directories, logging, and the local library store (likes, playlists, history, settings, downloads)."""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

APP_NAME = "999 player"
APP_ID = "999player"
OLD_APP_ID = "JuiceVault"   # builds before 2.1.0: their data folder is adopted on first start

FROZEN = getattr(sys, "frozen", False)
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
UI_DIR = BUNDLE_DIR / "ui"

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_ID
OLD_DATA_DIR = DATA_DIR.with_name(OLD_APP_ID)
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"


def _adopt_old_data() -> None:
    """likes, playlists, settings and lyrics from a build that still called itself JuiceVault: the folder is renamed, nothing is lost."""
    if DATA_DIR.exists() or not OLD_DATA_DIR.exists():
        return
    try:
        OLD_DATA_DIR.rename(DATA_DIR)
    except OSError:
        pass   # something has it open; the app starts fresh and the old folder stays for a later run


_adopt_old_data()
for _d in (DATA_DIR, CACHE_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

LIBRARY_FILE = DATA_DIR / "library.json"


def setup_logging(debug: bool = False) -> logging.Logger:
    log = logging.getLogger(APP_ID)
    log.setLevel(logging.DEBUG)
    if log.handlers:
        return log
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(LOG_DIR / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    log.addHandler(fh)
    if debug or not FROZEN:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.setLevel(logging.DEBUG if debug else logging.INFO)
        log.addHandler(sh)
    return log


def default_music_dir() -> Path:
    base = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(base) / "Music" / "999 player"


def old_music_dir() -> Path:
    base = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(base) / "Music" / "Juice WRLD Vault"


DEFAULT_SETTINGS: dict[str, Any] = {
    "downloadDir": str(default_music_dir()),
    "volume": 0.8,
    "muted": False,
    "shuffle": False,
    "repeat": "off",          # off | all | one
    "glass": "full",          # full | reduced | off
    "rightPanel": "lyrics",   # lyrics | queue | details | none
    "rightPanelOpen": True,
    "sidebarCollapsed": False,
    "tagAudio": True,
    "discordEnabled": True,
    "discordClientId": "1561232525852938250",
    "lastfmEnabled": True,
    "lastfmApiKey": "",
    "lastfmSecret": "",
    "lastfmSession": "",
    "lastfmUser": "",
    "localFolders": [],
    "windowGeometry": None,
    "windowMaximized": False,
    "autoUpdate": True,
}


class Library:
    """Single JSON document, written atomically, guarded by a lock."""

    def __init__(self, path: Path = LIBRARY_FILE) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.data: dict[str, Any] = {
            "likes": [],            # [songId,...] newest last
            "likedAt": {},          # songId -> epoch
            "playlists": [],        # [{id, name, songs:[ids], created, updated, cover?}]
            "history": [],          # [{id, at}] newest last (max 500)
            "playCounts": {},       # songId -> int
            "downloads": {},        # songId -> {path, title, author, size, at}
            "settings": dict(DEFAULT_SETTINGS),
        }
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text("utf-8"))
                for k, v in raw.items():
                    if k == "settings":
                        self.data["settings"].update(v or {})
                    else:
                        self.data[k] = v
        except Exception as e:  # corrupt file: keep defaults, back it up
            try:
                self.path.rename(self.path.with_suffix(f".corrupt-{int(time.time())}.json"))
            except Exception:
                pass
            logging.getLogger(APP_ID).warning("library load failed: %s", e)
        self._adopt_old_music_dir()

    def _adopt_old_music_dir(self) -> None:
        """downloads used to go to music/juice wrld vault; when that folder is still the download folder it is renamed to
        music/999 player and every saved download path follows. a custom folder is left alone."""
        old, new = old_music_dir(), default_music_dir()
        cur = str(self.data["settings"].get("downloadDir") or "")
        if cur.lower().rstrip("\\/") != str(old).lower() or not old.exists():
            return
        if not new.exists():
            try:
                old.rename(new)
            except OSError:
                return
        elif any(old.iterdir()):
            return   # both exist with files in them: keep using the old one rather than guess
        self.data["settings"]["downloadDir"] = str(new)
        prefix = str(old).lower()
        for info in self.data["downloads"].values():
            p = str(info.get("path") or "")
            if p.lower().startswith(prefix):
                info["path"] = str(new) + p[len(prefix):]
        try:
            self.save()
        except Exception:
            pass

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    # ---- likes
    def set_liked(self, song_id: int, liked: bool) -> None:
        with self._lock:
            likes = self.data["likes"]
            if liked and song_id not in likes:
                likes.append(song_id)
                self.data["likedAt"][str(song_id)] = time.time()
            elif not liked and song_id in likes:
                likes.remove(song_id)
                self.data["likedAt"].pop(str(song_id), None)
            self.save()

    # ---- playlists
    def create_playlist(self, name: str, song_ids: list[int] | None = None) -> dict[str, Any]:
        with self._lock:
            pl = {"id": uuid.uuid4().hex[:12], "name": name.strip() or "New Playlist",
                  "songs": list(dict.fromkeys(song_ids or [])), "created": time.time(), "updated": time.time()}
            self.data["playlists"].append(pl)
            self.save()
            return pl

    def _playlist(self, pid: str) -> dict[str, Any] | None:
        return next((p for p in self.data["playlists"] if p["id"] == pid), None)

    def update_playlist(self, pid: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            pl = self._playlist(pid)
            if not pl:
                return None
            if "name" in changes and changes["name"] is not None:
                pl["name"] = str(changes["name"]).strip() or pl["name"]
            if "songs" in changes and changes["songs"] is not None:
                pl["songs"] = list(dict.fromkeys(int(x) for x in changes["songs"]))
            if "add" in changes and changes["add"]:
                for sid in changes["add"]:
                    if int(sid) not in pl["songs"]:
                        pl["songs"].append(int(sid))
            if "remove" in changes and changes["remove"]:
                rm = {int(x) for x in changes["remove"]}
                pl["songs"] = [s for s in pl["songs"] if s not in rm]
            pl["updated"] = time.time()
            self.save()
            return pl

    def delete_playlist(self, pid: str) -> bool:
        with self._lock:
            before = len(self.data["playlists"])
            self.data["playlists"] = [p for p in self.data["playlists"] if p["id"] != pid]
            self.save()
            return len(self.data["playlists"]) < before

    # ---- history
    def record_play(self, song_id: int) -> None:
        with self._lock:
            hist = self.data["history"]
            hist.append({"id": song_id, "at": time.time()})
            if len(hist) > 500:
                del hist[: len(hist) - 500]
            pc = self.data["playCounts"]
            pc[str(song_id)] = int(pc.get(str(song_id), 0)) + 1
            self.save()

    # ---- downloads
    def set_download(self, song_id: int, info: dict[str, Any] | None) -> None:
        with self._lock:
            if info is None:
                self.data["downloads"].pop(str(song_id), None)
            else:
                self.data["downloads"][str(song_id)] = info
            self.save()

    def prune_downloads(self) -> None:
        with self._lock:
            gone = [k for k, v in self.data["downloads"].items() if not Path(v.get("path", "")).exists()]
            for k in gone:
                self.data["downloads"].pop(k, None)
            if gone:
                self.save()

    # ---- settings
    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self.data["settings"][key] = value
            self.save()

    @property
    def settings(self) -> dict[str, Any]:
        return self.data["settings"]
