"""QWebChannel bridge: everything the web UI needs from the OS/Python side."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QFileDialog

from appdata import APP_NAME, DATA_DIR, LOG_DIR, UI_DIR, Library, default_music_dir
from catalog import Catalog, audio_url, image_url
from discord_rpc import DiscordRPC, build_activity
from downloader import Downloader
from lastfm import LastFM
import localfiles
import lyrics_store
from native_player import NativePlayer
import updater
from version import APP_VERSION

log = logging.getLogger("999player.bridge")


class _Done(QObject):
    finished = Signal(object, object)  # result, error


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], done: _Done) -> None:
        super().__init__()
        self.fn, self.done = fn, done

    def run(self) -> None:
        try:
            result, error = self.fn(), None
        except Exception as e:  # pragma: no cover
            log.warning("background task failed: %s", e)
            result, error = None, str(e)
        try:
            self.done.finished.emit(result, error)
        except RuntimeError:
            pass  # receiver already destroyed (app shutting down)


class Bridge(QObject):
    # ---- signals to JS
    init = Signal(str)
    catalogChanged = Signal(int, int, float)       # count, version, fetchedAt
    catalogError = Signal(str)
    catalogProgress = Signal(int, int)
    detail = Signal(int, str)                      # id, json
    detailError = Signal(int, str)
    downloadProgress = Signal(int, int, int)
    downloadDone = Signal(int, str, bool, str, int)
    downloadsChanged = Signal(str)                 # json of downloads map
    settingChanged = Signal(str, str)              # key, json value
    winState = Signal(bool)                        # maximized
    mediaKey = Signal(str)
    nativePosition = Signal(int, int)
    nativeState = Signal(str)
    nativeError = Signal(str)
    toast = Signal(str, str)                       # kind, message
    discordStatus = Signal(str)
    accent = Signal(str, str)                      # ref, json {rgb:[r,g,b], rgb2:[r,g,b], hex}
    lastfmStatus = Signal(str)                     # json {connected, user, pending, error}
    localChanged = Signal(str)                     # json list of local tracks
    lyricsStatus = Signal(str)                     # json {user, bundled, synced, bundledAt, dir, busy, n, t, error}
    updateStatus = Signal(str)                     # json {state, current, version, notes, size, done, total, error}

    def __init__(self, window, catalog: Catalog, library: Library) -> None:
        super().__init__()
        self.window = window
        self.catalog = catalog
        self.library = library
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self._keep: list[_Done] = []
        self.downloader = Downloader()
        self.downloader.progress.connect(self.downloadProgress)
        self.downloader.done.connect(self._on_download_done)
        self.native = NativePlayer(self)
        self.native.position.connect(self.nativePosition)
        self.native.state.connect(self.nativeState)
        self.native.error.connect(self.nativeError)
        self.discord = DiscordRPC(self)
        self.discord.status.connect(self.discordStatus)
        self.lastfm = LastFM()
        self._lastfm_token = ""
        self._lastfm_error = ""
        st = self.library.settings
        self.lastfm.configure(st.get("lastfmApiKey", ""), st.get("lastfmSecret", ""), st.get("lastfmSession", ""), st.get("lastfmUser", ""))
        self.library.prune_downloads()
        self.local: list[dict[str, Any]] = localfiles.load_index()
        self._local_index = {int(s["id"]): s for s in self.local}
        self._upd: dict[str, Any] = {"state": "idle", "current": APP_VERSION}
        self._upd_rel: updater.Release | None = None
        self._upd_busy = False
        self._upd_apply = False

    # ---- local files
    def local_file(self, sid: int, art: bool):
        if int(sid) > 0:  # a downloaded vault song: play the file on disk (works offline)
            info = self.library.data["downloads"].get(str(int(sid)))
            p = info.get("path") if info else None
            return (p, localfiles.mime_for(p)) if p and Path(p).exists() and not art else None
        s = self._local_index.get(int(sid))
        if not s:
            return None
        if art:
            p = localfiles.art_path(sid)
            return (str(p), "image/jpeg") if p.exists() else None
        return (s["path"], localfiles.mime_for(s["path"])) if Path(s["path"]).exists() else None

    @Slot(result=str)
    def getLocal(self) -> str:
        return json.dumps(self.local, ensure_ascii=False)

    @Slot()
    def rescanLocal(self) -> None:
        folders = [str(f) for f in (self.library.settings.get("localFolders") or [])]

        def done(res: Any, err: Any) -> None:
            if err:
                self.toast.emit("err", f"local scan failed: {err}")
                return
            self.local = res
            self._local_index = {int(s["id"]): s for s in res}
            self.localChanged.emit(json.dumps(res, ensure_ascii=False))
        self._bg(lambda: localfiles.scan(folders), done)

    @Slot(result=str)
    def addLocalFolder(self) -> str:
        folder = QFileDialog.getExistingDirectory(self.window, "add a music folder", str(Path.home() / "Music"))
        if not folder:
            return ""
        folders = [str(f) for f in (self.library.settings.get("localFolders") or [])]
        if folder not in folders:
            folders.append(folder)
            self.library.set_setting("localFolders", folders)
            self.settingChanged.emit("localFolders", json.dumps(folders))
        self.rescanLocal()
        return folder

    @Slot(str)
    def removeLocalFolder(self, folder: str) -> None:
        folders = [f for f in (self.library.settings.get("localFolders") or []) if f != folder]
        self.library.set_setting("localFolders", folders)
        self.settingChanged.emit("localFolders", json.dumps(folders))
        self.rescanLocal()

    # ---- last.fm
    def _lastfm_state(self) -> dict[str, Any]:
        return {"enabled": bool(self.library.settings.get("lastfmEnabled", True)), "ready": self.lastfm.ready,
                "connected": self.lastfm.connected, "user": self.lastfm.user, "pending": bool(self._lastfm_token),
                "error": self._lastfm_error}

    def _emit_lastfm(self) -> None:
        self.lastfmStatus.emit(json.dumps(self._lastfm_state()))

    @Slot(str, str, bool)
    def lastfmConfigure(self, api_key: str, secret: str, enabled: bool) -> None:
        api_key, secret = (api_key or "").strip(), (secret or "").strip()
        changed_keys = api_key != self.lastfm.api_key or secret != self.lastfm.secret
        self.library.set_setting("lastfmApiKey", api_key)
        self.library.set_setting("lastfmSecret", secret)
        self.library.set_setting("lastfmEnabled", bool(enabled))
        if changed_keys:
            self.library.set_setting("lastfmSession", "")
            self.library.set_setting("lastfmUser", "")
            self.lastfm.configure(api_key, secret)
        self._lastfm_error = ""
        self._emit_lastfm()

    @Slot()
    def lastfmConnect(self) -> None:
        """Step 1: get a request token and open the approval page in the browser."""
        if not self.lastfm.ready:
            self._lastfm_error = "enter your api key and shared secret first"
            self._emit_lastfm()
            return

        def work() -> str:
            return self.lastfm.get_token()

        def done(res: Any, err: Any) -> None:
            if err:
                self._lastfm_error = str(err).lower()
            else:
                self._lastfm_token = res
                self._lastfm_error = ""
                QDesktopServices.openUrl(QUrl(self.lastfm.auth_url(res)))
            self._emit_lastfm()
        self._bg(work, done)

    @Slot()
    def lastfmFinish(self) -> None:
        """Step 2 (after the user approved in the browser): exchange the token for a session key."""
        token = self._lastfm_token
        if not token:
            self._lastfm_error = "press connect first"
            self._emit_lastfm()
            return

        def work() -> tuple[str, str]:
            return self.lastfm.get_session(token)

        def done(res: Any, err: Any) -> None:
            if err:
                self._lastfm_error = str(err).lower()
            else:
                sk, user = res
                self.library.set_setting("lastfmSession", sk)
                self.library.set_setting("lastfmUser", user)
                self._lastfm_token = ""
                self._lastfm_error = ""
            self._emit_lastfm()
        self._bg(work, done)

    @Slot()
    def lastfmDisconnect(self) -> None:
        self.library.set_setting("lastfmSession", "")
        self.library.set_setting("lastfmUser", "")
        self.lastfm.session_key, self.lastfm.user = "", ""
        self._lastfm_token = ""
        self._lastfm_error = ""
        self._emit_lastfm()

    @Slot(str)
    def lastfmNowPlaying(self, payload_json: str) -> None:
        if not (self.lastfm.connected and self.library.settings.get("lastfmEnabled", True)):
            return
        try:
            p = json.loads(payload_json)
        except Exception:
            return
        self._bg(lambda: self.lastfm.now_playing(p.get("artist") or "Juice WRLD", p.get("track") or "", p.get("album"), p.get("duration")),
                 lambda res, err: self._lastfm_fail(err) if err else None)

    @Slot(str)
    def lastfmScrobble(self, payload_json: str) -> None:
        if not (self.lastfm.connected and self.library.settings.get("lastfmEnabled", True)):
            return
        try:
            p = json.loads(payload_json)
        except Exception:
            return
        self._bg(lambda: self.lastfm.scrobble(p.get("artist") or "Juice WRLD", p.get("track") or "", p.get("album"), int(p.get("timestamp") or time.time()), p.get("duration")),
                 lambda res, err: self._lastfm_fail(err) if err else self.toast.emit("ok", f"scrobbled “{p.get('track')}”"))

    def _lastfm_fail(self, err: Any) -> None:
        self._lastfm_error = str(err).lower()
        log.warning("last.fm: %s", err)
        self._emit_lastfm()

    # ---- helpers
    def _bg(self, fn: Callable[[], Any], on_done: Callable[[Any, Any], None]) -> None:
        done = _Done()
        self._keep.append(done)

        def _finish(result: Any, error: Any) -> None:
            try:
                on_done(result, error)
            finally:
                if done in self._keep:
                    self._keep.remove(done)

        done.finished.connect(_finish, Qt.ConnectionType.QueuedConnection)
        self.pool.start(_Task(fn, done))

    def _song(self, song_id: int) -> dict[str, Any] | None:
        return next((s for s in self.catalog.songs if s["id"] == song_id), None)

    def library_json(self) -> dict[str, Any]:
        d = self.library.data
        return {
            "likes": d["likes"], "likedAt": d["likedAt"], "playlists": d["playlists"],
            "history": d["history"][-200:], "playCounts": d["playCounts"], "downloads": d["downloads"],
        }

    # ---- lifecycle
    @Slot()
    def ready(self) -> None:
        payload = {
            "app": {"name": APP_NAME, "version": APP_VERSION, "dataDir": str(DATA_DIR), "logDir": str(LOG_DIR),
                    "frozen": bool(getattr(sys, "frozen", False)), "platform": sys.platform},
            "settings": self.library.settings,
            "library": self.library_json(),
            "catalog": {"count": len(self.catalog.songs), "version": self.catalog.version, "fetchedAt": self.catalog.fetched_at},
            "maximized": self.window.isMaximized(),
            "discordStatus": self.discord.state,
            "lastfm": self._lastfm_state(),
            "local": self.local,
            "lyrics": lyrics_store.status(),
            "update": self._upd,
        }
        self.init.emit(json.dumps(payload, ensure_ascii=False))
        st = self.library.settings
        self.discord.configure(str(st.get("discordClientId") or ""), bool(st.get("discordEnabled", True)))
        # every launch syncs with the vault; the saved copy keeps the app usable if that fails
        self.refreshCatalog()
        # offline lyrics ship with the app; refresh the user's copy quietly about once a week so new ones land on their own
        synced = lyrics_store.status().get("synced") or 0
        if time.time() - float(synced) > 7 * 86400:
            QTimer.singleShot(20_000, lambda: self._sync_lyrics(quiet=True))
        self._periodic = QTimer(self)
        self._periodic.setInterval(15 * 60 * 1000)
        self._periodic.timeout.connect(self.refreshCatalog)
        self._periodic.start()
        # updates: a quiet look at github half a minute in, then every six hours
        QTimer.singleShot(30_000, lambda: self._check_updates(quiet=True))
        self._upd_timer = QTimer(self)
        self._upd_timer.setInterval(6 * 3600 * 1000)
        self._upd_timer.timeout.connect(lambda: self._check_updates(quiet=True))
        self._upd_timer.start()

    @Slot()
    def refreshCatalog(self) -> None:
        def work() -> int:
            return self.catalog.refresh(progress=lambda n, t: self.catalogProgress.emit(n, t))

        def done(result: Any, error: Any) -> None:
            if error:
                self.catalogError.emit(str(error))
            else:
                self.catalogChanged.emit(len(self.catalog.songs), self.catalog.version, self.catalog.fetched_at)
        self._bg(work, done)

    # ---- updates
    def _upd_emit(self, **changes: Any) -> None:
        self._upd.update(changes)
        self.updateStatus.emit(json.dumps(self._upd, ensure_ascii=False))

    @Slot()
    def checkUpdates(self) -> None:
        self._check_updates(quiet=False)

    def _check_updates(self, quiet: bool) -> None:
        if self._upd_busy:
            return
        self._upd_busy = True
        updater.cleanup()
        self._upd_emit(state="checking", error="")

        def done(result: Any, error: Any) -> None:
            self._upd_busy = False
            if error:
                log.info("update check failed: %s", error)
                self._upd_emit(state="error" if not quiet else "idle", error="could not reach github, try again later" if not quiet else "")
                return
            rel: updater.Release | None = result
            if not rel or not updater.newer(rel.version):
                self._upd_rel = None
                self._upd_emit(state="none", version="", notes="", checked=time.time())
                return
            self._upd_rel = rel
            self._upd_emit(state="available", version=rel.version, notes=rel.notes, size=rel.size, checked=time.time())
            if updater.have(rel):
                self._upd_emit(state="ready")
            elif self.library.settings.get("autoUpdate", True):
                self._download_update()
        self._bg(updater.check, done)

    def _download_update(self) -> None:
        rel = self._upd_rel
        if not rel or self._upd_busy:
            return
        self._upd_busy = True
        self._upd_emit(state="downloading", done=0, total=rel.size)
        last = [0.0]

        def progress(done_b: int, total_b: int) -> None:
            now = time.monotonic()
            if now - last[0] > 0.25 or done_b == total_b:
                last[0] = now
                self._upd_emit(done=done_b, total=total_b)

        def done(result: Any, error: Any) -> None:
            self._upd_busy = False
            if error:
                log.warning("update download failed: %s", error)
                self._upd_apply = False
                self._upd_emit(state="error", error=f"download failed: {error}")
                return
            self._upd_emit(state="ready")
            if self._upd_apply:
                self._upd_apply = False
                self.installUpdate()
            else:
                self.toast.emit("ok", f"999 player {rel.version} is downloaded, it installs next time you open the app")
        self._bg(lambda: updater.download(rel, progress), done)

    @Slot()
    def installUpdate(self) -> None:
        """update button: download if needed, then hand over to the setup and quit."""
        rel = self._upd_rel
        if not rel:
            self._check_updates(quiet=False)
            return
        exe = updater.have(rel)
        if not exe:
            self._upd_apply = True
            self._download_update()
            return
        if not updater.install_dir():
            self._upd_emit(state="error", error=f"not an installed copy, run {exe} yourself")
            return
        if updater.apply(exe, rel.version):
            self._upd_emit(state="installing")
            QTimer.singleShot(300, self.window.close)
        else:
            self._upd_emit(state="error", error="could not start the setup")

    # ---- offline lyrics
    @Slot()
    def downloadLyrics(self) -> None:
        self._sync_lyrics(quiet=False)

    def _sync_lyrics(self, quiet: bool) -> None:
        if getattr(self, "_lyrics_busy", False):
            return
        self._lyrics_busy = True

        def emit(extra: dict[str, Any]) -> None:
            st = lyrics_store.status()
            st.update(extra)
            self.lyricsStatus.emit(json.dumps(st, ensure_ascii=False))

        def done(res: Any, err: Any) -> None:
            self._lyrics_busy = False
            if err:
                emit({"busy": False, "error": str(err)})
                if not quiet:
                    self.toast.emit("err", f"lyrics refresh failed: {err}")
            else:
                emit({"busy": False})
                if not quiet:
                    self.toast.emit("ok", f"lyrics refreshed for {int(res):,} songs")
        emit({"busy": True, "n": 0, "t": 0})
        self._bg(lambda: lyrics_store.sync(self.catalog, progress=lambda n, t: emit({"busy": True, "n": n, "t": t})), done)

    @Slot()
    def openLyricsFolder(self) -> None:
        lyrics_store.USER_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(lyrics_store.USER_DIR)))

    @Slot(int)
    def getDetail(self, song_id: int) -> None:
        self._bg(lambda: self.catalog.detail(int(song_id)),
                 lambda res, err: self.detailError.emit(int(song_id), str(err)) if err
                 else self.detail.emit(int(song_id), json.dumps(res, ensure_ascii=False)))

    # ---- library
    @Slot(int, bool)
    def setLiked(self, song_id: int, liked: bool) -> None:
        self.library.set_liked(int(song_id), bool(liked))

    @Slot(int)
    def recordPlay(self, song_id: int) -> None:
        self.library.record_play(int(song_id))

    @Slot(str, str, result=str)
    def createPlaylist(self, name: str, ids_json: str) -> str:
        try:
            ids = [int(x) for x in json.loads(ids_json or "[]")]
        except Exception:
            ids = []
        return json.dumps(self.library.create_playlist(name, ids))

    @Slot(str, str, result=str)
    def updatePlaylist(self, pid: str, changes_json: str) -> str:
        try:
            changes = json.loads(changes_json or "{}")
        except Exception:
            changes = {}
        pl = self.library.update_playlist(pid, **changes)
        return json.dumps(pl) if pl else ""

    @Slot(str, result=bool)
    def deletePlaylist(self, pid: str) -> bool:
        return self.library.delete_playlist(pid)

    @Slot(result=str)
    def getLibrary(self) -> str:
        return json.dumps(self.library_json(), ensure_ascii=False)

    # ---- settings
    @Slot(str, str)
    def setSetting(self, key: str, value_json: str) -> None:
        try:
            value = json.loads(value_json)
        except Exception:
            value = value_json
        self.library.set_setting(key, value)

    @Slot(result=str)
    def getSettings(self) -> str:
        return json.dumps(self.library.settings)

    # ---- downloads
    @Slot(int, str)
    def download(self, song_id: int, local_cover: str = "") -> None:
        song = self._song(int(song_id))
        if not song:
            self.downloadDone.emit(int(song_id), "", False, "song not in catalog", 0)
            return
        folder = Path(self.library.settings.get("downloadDir") or default_music_dir())
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.downloadDone.emit(int(song_id), "", False, f"cannot create folder: {e}", 0)
            return
        cover: str | None = image_url(song.get("img"))
        if local_cover:
            p = (UI_DIR / local_cover.replace("/", os.sep)).resolve()
            if UI_DIR.resolve() in p.parents and p.is_file():
                cover = p.as_uri()
        self.downloader.enqueue(song, audio_url(song["path"]), cover, folder,
                                bool(self.library.settings.get("tagAudio", True)))

    def _on_download_done(self, sid: int, path: str, ok: bool, err: str, size: int) -> None:
        if ok:
            song = self._song(sid) or {}
            self.library.set_download(sid, {"path": path, "title": song.get("title"), "author": song.get("author"),
                                            "size": size, "at": time.time()})
            self.downloadsChanged.emit(json.dumps(self.library.data["downloads"]))
        self.downloadDone.emit(sid, path, ok, err, size)

    @Slot(int, bool)
    def removeDownload(self, song_id: int, delete_file: bool) -> None:
        info = self.library.data["downloads"].get(str(int(song_id)))
        if info and delete_file:
            try:
                Path(info["path"]).unlink(missing_ok=True)
            except Exception as e:
                self.toast.emit("error", f"Could not delete file: {e}")
        self.library.set_download(int(song_id), None)
        self.downloadsChanged.emit(json.dumps(self.library.data["downloads"]))

    @Slot()
    def openDownloads(self) -> None:
        folder = Path(self.library.settings.get("downloadDir") or default_music_dir())
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    @Slot(str)
    def revealFile(self, path: str) -> None:
        p = Path(path)
        if sys.platform == "win32" and p.exists():
            subprocess.Popen(["explorer", "/select,", str(p)])
        elif p.parent.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))

    @Slot(str)
    def openPath(self, path: str) -> None:
        if Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(result=str)
    def chooseDownloadFolder(self) -> str:
        cur = self.library.settings.get("downloadDir") or str(Path.home() / "Music")
        folder = QFileDialog.getExistingDirectory(self.window, "Choose download folder", cur)
        if folder:
            self.library.set_setting("downloadDir", folder)
            self.settingChanged.emit("downloadDir", json.dumps(folder))
        return folder or ""

    # ---- artwork accent colour (browser can't read pixels of cross-origin covers)
    @Slot(str)
    def requestAccent(self, ref: str) -> None:
        if not ref:
            return
        cache = getattr(self, "_accent_cache", None)
        if cache is None:
            cache = self._accent_cache = {}
        if ref in cache:
            self.accent.emit(ref, cache[ref])
            return

        def work() -> str:
            from accent import accent_from_bytes
            if ref.startswith(("http://", "https://")):
                data = self.catalog.session.get(ref, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).content
            else:
                p = (UI_DIR / ref.replace("/", os.sep)).resolve()
                if UI_DIR.resolve() not in p.parents:
                    raise ValueError("bad cover path")
                data = p.read_bytes()
            return json.dumps(accent_from_bytes(data))

        def done(res: Any, err: Any) -> None:
            if err or not res:
                log.info("accent failed for %s: %s", ref[:80], err)
                return
            cache[ref] = res
            self.accent.emit(ref, res)
        self._bg(work, done)

    # ---- discord rich presence
    @Slot(str)
    def presence(self, payload_json: str) -> None:
        if not payload_json:
            self.discord.set_activity(None)
            return
        try:
            self.discord.set_activity(build_activity(json.loads(payload_json)))
        except Exception as e:
            log.warning("presence payload rejected: %s", e)

    @Slot(str, bool)
    def configureDiscord(self, client_id: str, enabled: bool) -> None:
        self.library.set_setting("discordClientId", (client_id or "").strip())
        self.library.set_setting("discordEnabled", bool(enabled))
        self.discord.configure(client_id, enabled)
        self.discordStatus.emit(self.discord.state)

    # ---- native audio engine
    @Slot(str, bool)
    def nativeLoad(self, url: str, autoplay: bool) -> None:
        # jv://app/__dl/<id> and /__local/<id> are files on disk: hand Qt the real path
        m = re.match(r"^(?:jv://app)?/__(dl|local)/(\d+)", url or "")
        if m:
            hit = self.local_file(int(m.group(2)) if m.group(1) == "dl" else -int(m.group(2)), False)
            if not hit:
                self.nativeError.emit("file not found on disk")
                return
            url = QUrl.fromLocalFile(hit[0]).toString()
        self.native.load(url, autoplay)

    @Slot()
    def nativePlay(self) -> None:
        self.native.play()

    @Slot()
    def nativePause(self) -> None:
        self.native.pause()

    @Slot()
    def nativeStop(self) -> None:
        self.native.stop()

    @Slot(int)
    def nativeSeek(self, ms: int) -> None:
        self.native.seek(ms)

    @Slot(float)
    def nativeVolume(self, v: float) -> None:
        self.native.set_volume(v)

    @Slot(bool)
    def nativeMuted(self, m: bool) -> None:
        self.native.set_muted(m)

    # ---- window
    @Slot()
    def winMinimize(self) -> None:
        self.window.showMinimized()

    @Slot()
    def winToggleMax(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    @Slot()
    def winClose(self) -> None:
        self.window.close()

    @Slot()
    def winDrag(self) -> None:
        wh = self.window.windowHandle()
        if wh and not self.window.isMaximized():
            wh.startSystemMove()

    @Slot(str)
    def winResize(self, edges: str) -> None:
        wh = self.window.windowHandle()
        if not wh or self.window.isMaximized():
            return
        e = Qt.Edge(0)
        if "top" in edges:
            e |= Qt.Edge.TopEdge
        if "bottom" in edges:
            e |= Qt.Edge.BottomEdge
        if "left" in edges:
            e |= Qt.Edge.LeftEdge
        if "right" in edges:
            e |= Qt.Edge.RightEdge
        if e:
            wh.startSystemResize(e)

    # ---- misc
    @Slot(str)
    def openExternal(self, url: str) -> None:
        if url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))

    @Slot(str)
    def copyText(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    @Slot()
    def openLogs(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR)))

    @Slot(str, str)
    def log(self, level: str, msg: str) -> None:
        getattr(log, level if level in ("debug", "info", "warning", "error") else "info")("[ui] %s", msg)
