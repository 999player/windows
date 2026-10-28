from __future__ import annotations

import hashlib
import logging
import time

import requests

log = logging.getLogger("999player.lastfm")
API = "https://ws.audioscrobbler.com/2.0/"


class LastFMError(Exception):
    pass


class LastFM:
    def __init__(self) -> None:
        self.api_key = ""
        self.secret = ""
        self.session_key = ""
        self.user = ""
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "999player/2.1 (desktop)"

    def configure(self, api_key: str, secret: str, session_key: str = "", user: str = "") -> None:
        self.api_key, self.secret = (api_key or "").strip(), (secret or "").strip()
        self.session_key, self.user = (session_key or "").strip(), (user or "").strip()

    @property
    def ready(self) -> bool:
        return bool(self.api_key and self.secret)

    @property
    def connected(self) -> bool:
        return self.ready and bool(self.session_key)

    def _sign(self, params: dict) -> str:
        s = "".join(f"{k}{params[k]}" for k in sorted(params) if k != "format") + self.secret
        return hashlib.md5(s.encode("utf-8")).hexdigest()

    def _call(self, method: str, params: dict, post: bool = False, signed: bool = True) -> dict:
        p = {"method": method, "api_key": self.api_key, **params}
        if signed:
            p["api_sig"] = self._sign(p)
        p["format"] = "json"
        r = self.session.post(API, data=p, timeout=20) if post else self.session.get(API, params=p, timeout=20)
        try:
            data = r.json()
        except Exception:
            raise LastFMError(f"bad response ({r.status_code})")
        if isinstance(data, dict) and "error" in data:
            raise LastFMError(f"{data.get('message') or 'error'} ({data.get('error')})")
        return data

    def get_token(self) -> str:
        return self._call("auth.getToken", {})["token"]

    def auth_url(self, token: str) -> str:
        return f"https://www.last.fm/api/auth/?api_key={self.api_key}&token={token}"

    def get_session(self, token: str) -> tuple[str, str]:
        d = self._call("auth.getSession", {"token": token})["session"]
        self.session_key, self.user = d["key"], d["name"]
        return self.session_key, self.user

    def now_playing(self, artist: str, track: str, album: str | None, duration: int | None) -> None:
        p = {"artist": artist, "track": track, "sk": self.session_key}
        if album:
            p["album"] = album
        if duration:
            p["duration"] = str(int(duration))
        self._call("track.updateNowPlaying", p, post=True)

    def scrobble(self, artist: str, track: str, album: str | None, timestamp: int, duration: int | None) -> None:
        p = {"artist": artist, "track": track, "timestamp": str(int(timestamp)), "sk": self.session_key}
        if album:
            p["album"] = album
        if duration:
            p["duration"] = str(int(duration))
        d = self._call("track.scrobble", p, post=True)
        acc = (d.get("scrobbles") or {}).get("@attr", {})
        log.info("scrobbled %s — %s (accepted=%s ignored=%s)", artist, track, acc.get("accepted"), acc.get("ignored"))
        if str(acc.get("ignored")) not in ("0", "None", ""):
            sc = (d.get("scrobbles") or {}).get("scrobble") or {}
            msg = (sc.get("ignoredMessage") or {}).get("#text") if isinstance(sc, dict) else None
            raise LastFMError(f"ignored: {msg or 'unknown reason'}")
