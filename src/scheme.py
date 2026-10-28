from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QBuffer, QByteArray, QFile, QIODevice
from PySide6.QtWebEngineCore import QWebEngineUrlRequestJob, QWebEngineUrlScheme, QWebEngineUrlSchemeHandler

log = logging.getLogger("999player.scheme")

SCHEME = b"jv"
ORIGIN = "jv://app"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


def register_scheme() -> None:
    scheme = QWebEngineUrlScheme(SCHEME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    F = QWebEngineUrlScheme.Flag
    flags = F.SecureScheme | F.LocalAccessAllowed | F.CorsEnabled | F.FetchApiAllowed | F.ContentSecurityPolicyIgnored
    scheme.setFlags(flags)
    QWebEngineUrlScheme.registerScheme(scheme)


class JvSchemeHandler(QWebEngineUrlSchemeHandler):
    def __init__(self, ui_dir: Path, catalog_bytes: Callable[[], bytes], parent=None,
                 local_file: Callable[[int, bool], tuple[str, str] | None] | None = None,
                 lyrics_index: Callable[[], bytes] | None = None) -> None:
        super().__init__(parent)
        self.ui_dir = ui_dir.resolve()
        self.catalog_bytes = catalog_bytes
        self.lyrics_index = lyrics_index
        self.local_file = local_file
        self._qwebchannel_js = self._load_resource(":/qtwebchannel/qwebchannel.js")

    @staticmethod
    def _load_resource(path: str) -> bytes:
        f = QFile(path)
        if f.open(QIODevice.OpenModeFlag.ReadOnly):
            try:
                return bytes(f.readAll().data())
            finally:
                f.close()
        return b""

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:  # noqa: N802 (Qt override)
        url = job.requestUrl()
        host, path = url.host(), url.path() or "/"
        if host != "app":
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        if path in ("", "/"):
            path = "/index.html"
        try:
            if path == "/__data/catalog.json":
                data = self.catalog_bytes()
                if not data:
                    job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                    return
                self._reply(job, "application/json; charset=utf-8", data)
                return
            if path == "/__data/lyrics_index.json":
                self._reply(job, "application/json; charset=utf-8", self.lyrics_index() if self.lyrics_index else b'{"songs":{}}')
                return
            if path == "/qwebchannel.js":
                self._reply(job, MIME[".js"], self._qwebchannel_js)
                return
            if path.startswith("/__local/") or path.startswith("/__localart/") or path.startswith("/__dl/"):
                sid = int(path.rsplit("/", 1)[-1].split(".")[0])
                key = abs(sid) if path.startswith("/__dl/") else -abs(sid)
                hit = self.local_file(key, path.startswith("/__localart/")) if self.local_file else None
                if not hit:
                    job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                    return
                fpath, mime = hit
                self._reply(job, mime, Path(fpath).read_bytes())
                return
            file = (self.ui_dir / path.lstrip("/")).resolve()
            if self.ui_dir not in file.parents or not file.is_file():
                job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                return
            mime = MIME.get(file.suffix.lower()) or mimetypes.guess_type(str(file))[0] or "application/octet-stream"
            self._reply(job, mime, file.read_bytes())
        except Exception as e:
            log.exception("scheme error for %s: %s", url.toString(), e)
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)

    @staticmethod
    def _reply(job: QWebEngineUrlRequestJob, mime: str, data: bytes) -> None:
        buf = QBuffer(job)
        buf.setData(QByteArray(data))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(mime.encode("ascii"), buf)
