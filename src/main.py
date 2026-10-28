from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

if getattr(sys, "frozen", False):
    _pyside_dir = os.path.join(sys._MEIPASS, "PySide6")  # type: ignore[attr-defined]
    if os.path.isdir(_pyside_dir):
        os.environ["PATH"] = _pyside_dir + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(_pyside_dir)
        except Exception:
            pass

if "--uninstall" in sys.argv:
    from installer import run_uninstall
    sys.exit(run_uninstall())


def _gpu_off_requested() -> bool:
    if "--no-gpu" in sys.argv:
        return True
    try:
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        lib = next(p for p in (base / "999player" / "library.json", base / "JuiceVault" / "library.json") if p.exists())
        return bool(json.loads(lib.read_text("utf-8")).get("settings", {}).get("gpuOff"))
    except Exception:
        return False


_CHROMIUM_FLAGS = "--autoplay-policy=no-user-gesture-required --disable-features=TranslateUI --js-flags=--expose-gc"
_CHROMIUM_FLAGS += " --disable-gpu --disable-gpu-compositing" if _gpu_off_requested() else " --enable-gpu-rasterization"
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", _CHROMIUM_FLAGS)

from PySide6.QtCore import QEvent, QTimer, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QIcon, QKeySequence, QShortcut  # noqa: E402
from PySide6.QtWebChannel import QWebChannel  # noqa: E402
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from appdata import APP_ID, APP_NAME, BUNDLE_DIR, CACHE_DIR, DATA_DIR, LOG_DIR, UI_DIR, Library, setup_logging  # noqa: E402
from bridge import Bridge  # noqa: E402
from catalog import Catalog  # noqa: E402
import lyrics_store  # noqa: E402
import updater  # noqa: E402
from scheme import ORIGIN, JvSchemeHandler, register_scheme  # noqa: E402

log = setup_logging()
log.info("chromium flags: %s", os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS"))


def _install_crash_logging() -> None:
    import faulthandler
    import threading
    try:
        fh = open(LOG_DIR / "crash.log", "a", encoding="utf-8", buffering=1)
        fh.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()} ===\n")
        faulthandler.enable(file=fh, all_threads=True)
        _install_crash_logging.fh = fh  # type: ignore[attr-defined]  # keep the handle alive
    except Exception as e:
        log.warning("faulthandler unavailable: %s", e)

    def hook(exc_type, exc, tb):
        log.critical("unhandled exception", exc_info=(exc_type, exc, tb))
    sys.excepthook = hook
    threading.excepthook = lambda a: log.critical("unhandled thread exception in %s", a.thread, exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


_install_crash_logging()


class Page(QWebEnginePage):
    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self.console: list[str] = []

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        lvl = {0: "debug", 1: "warning", 2: "error"}.get(int(level.value) if hasattr(level, "value") else int(level), "info")
        text = f"js[{lvl}] {message} ({Path(source).name}:{line})"
        self.console.append(text)
        if len(self.console) > 300:
            del self.console[:100]
        getattr(log, lvl if lvl != "info" else "info")(text)


class MainWindow(QMainWindow):
    MIN_W, MIN_H = 1140, 680

    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__()
        self.args = args
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(self.MIN_W, self.MIN_H)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowSystemMenuHint)

        self.library = Library()
        self.catalog = Catalog()
        self.catalog.load_cache()

        self.profile = QWebEngineProfile("999player", self)
        self.profile.setCachePath(str(CACHE_DIR / "web"))
        self.profile.setPersistentStoragePath(str(DATA_DIR / "webstorage"))
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setHttpCacheMaximumSize(256 * 1024 * 1024)
        self.handler = JvSchemeHandler(UI_DIR, lambda: self.catalog.json_bytes, self, local_file=lambda sid, art: self.bridge.local_file(sid, art),
                                       lyrics_index=lyrics_store.index_bytes)
        self.profile.installUrlSchemeHandler(b"jv", self.handler)

        self.view = QWebEngineView(self)
        self.page = Page(self.profile, self.view)
        self._render_crashes = 0
        self.page.renderProcessTerminated.connect(self._on_render_crash)
        self.view.setPage(self.page)
        s = self.page.settings()
        A = QWebEngineSettings.WebAttribute
        s.setAttribute(A.PlaybackRequiresUserGesture, False)
        s.setAttribute(A.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(A.LocalContentCanAccessFileUrls, True)
        s.setAttribute(A.JavascriptCanAccessClipboard, True)
        s.setAttribute(A.ShowScrollBars, True)
        s.setAttribute(A.Accelerated2dCanvasEnabled, True)
        s.setAttribute(A.WebGLEnabled, True)
        s.setAttribute(A.FocusOnNavigationEnabled, True)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu if not args.devtools else Qt.ContextMenuPolicy.DefaultContextMenu)
        self.setCentralWidget(self.view)

        self.channel = QWebChannel(self.page)
        self.bridge = Bridge(self, self.catalog, self.library)
        self.channel.registerObject("bridge", self.bridge)
        self.page.setWebChannel(self.channel)

        self._restore_geometry()
        self.page.loadFinished.connect(self._on_loaded)
        self.page.titleChanged.connect(lambda t: self.setWindowTitle(t or APP_NAME))
        url = f"{ORIGIN}/index.html" + ("?selftest=1" if args.selftest else "")
        self.view.load(QUrl(url))

        for key, name in ((Qt.Key.Key_MediaPlay, "playpause"), (Qt.Key.Key_MediaTogglePlayPause, "playpause"),
                          (Qt.Key.Key_MediaPause, "pause"), (Qt.Key.Key_MediaStop, "stop"),
                          (Qt.Key.Key_MediaNext, "next"), (Qt.Key.Key_MediaPrevious, "prev")):
            QShortcut(QKeySequence(key), self, activated=lambda n=name: self.bridge.mediaKey.emit(n))
        if args.devtools:
            QShortcut(QKeySequence("F12"), self, activated=self._open_devtools)
        self._devtools = None

    def _restore_geometry(self) -> None:
        geo = self.library.settings.get("windowGeometry")
        screen = QApplication.primaryScreen().availableGeometry()
        if isinstance(geo, list) and len(geo) == 4 and geo[2] >= self.MIN_W and geo[3] >= self.MIN_H:
            x, y, w, h = geo
            w, h = min(w, screen.width()), min(h, screen.height())
            x = max(screen.left(), min(x, screen.right() - w))
            y = max(screen.top(), min(y, screen.bottom() - h))
            self.setGeometry(x, y, w, h)
        else:
            w, h = min(1400, screen.width() - 80), min(880, screen.height() - 80)
            self.resize(w, h)
            self.move(screen.center().x() - w // 2, screen.center().y() - h // 2)
        if self.library.settings.get("windowMaximized"):
            QTimer.singleShot(0, self.showMaximized)

    def changeEvent(self, ev) -> None:  # noqa: N802
        if ev.type() == QEvent.Type.WindowStateChange:
            self.bridge.winState.emit(self.isMaximized())
        super().changeEvent(ev)

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if sys.platform == "win32" and not getattr(self, "_snap_ready", False):
            self._snap_ready = True
            try:
                import ctypes
                u = ctypes.windll.user32
                hwnd = int(self.winId())
                GWL_STYLE = -16
                WS_CAPTION, WS_THICKFRAME, WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00C00000, 0x00040000, 0x00020000, 0x00010000
                u.SetWindowLongW(hwnd, GWL_STYLE, u.GetWindowLongW(hwnd, GWL_STYLE) | WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
                u.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004)
            except Exception:
                log.exception("window frame styles")

    def nativeEvent(self, event_type, message):  # noqa: N802
        if sys.platform == "win32" and event_type == b"windows_generic_MSG":
            try:
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0083 and msg.wParam:
                    u = ctypes.windll.user32
                    if u.IsZoomed(msg.hWnd):
                        rect = wintypes.RECT.from_address(msg.lParam)
                        dpi = u.GetDpiForWindow(msg.hWnd) or 96
                        fx = u.GetSystemMetricsForDpi(32, dpi) + u.GetSystemMetricsForDpi(92, dpi)
                        fy = u.GetSystemMetricsForDpi(33, dpi) + u.GetSystemMetricsForDpi(92, dpi)
                        rect.left += fx; rect.top += fy; rect.right -= fx; rect.bottom -= fy
                    return True, 0
            except Exception:
                log.exception("nativeEvent")
        return super().nativeEvent(event_type, message)

    def closeEvent(self, ev) -> None:  # noqa: N802
        try:
            self.library.set_setting("windowMaximized", self.isMaximized())
            if not self.isMaximized():
                g = self.geometry()
                self.library.set_setting("windowGeometry", [g.x(), g.y(), g.width(), g.height()])
            self.bridge.native.stop()
            self.bridge.discord.close()
        except Exception:
            pass
        super().closeEvent(ev)

    def _open_devtools(self) -> None:
        if self._devtools is None:
            self._devtools = QWebEngineView()
            self._devtools.setWindowTitle("DevTools")
            self._devtools.resize(1100, 700)
            self.page.setDevToolsPage(self._devtools.page())
        self._devtools.show()
        self._devtools.raise_()

    def _on_loaded(self, ok: bool) -> None:
        log.info("ui loaded ok=%s", ok)
        if self.args.devtools:
            self._open_devtools()
        if self.args.js:
            QTimer.singleShot(int(self.args.delay), lambda: self.page.runJavaScript(self.args.js))
        if self.args.screenshot:
            QTimer.singleShot(int(self.args.delay) + (int(self.args.wait) if self.args.js else 0), self._screenshot)
        if self.args.selftest:
            self._selftest_started = time.time()
            QTimer.singleShot(1200, self._poll_selftest)

    def _on_render_crash(self, status, code) -> None:
        self._render_crashes += 1
        log.error("web renderer terminated: status=%s code=%s (#%d) — reloading", status, code, self._render_crashes)
        if self._render_crashes >= 3 and not _gpu_off_requested():
            try:
                self.library.set_setting("gpuOff", True)
                log.error("repeated renderer crashes: gpu acceleration turned off for the next start")
            except Exception:
                pass
        QTimer.singleShot(800, lambda: self.view.setUrl(QUrl(ORIGIN + "/")))

    def _screenshot(self) -> None:
        out = Path(self.args.screenshot)
        img = self.view.grab().toImage()
        if img.isNull() or _looks_blank(img):
            img = QApplication.primaryScreen().grabWindow(int(self.winId())).toImage()
        ok = img.save(str(out))
        log.info("screenshot %s -> %s (%dx%d)", "saved" if ok else "FAILED", out, img.width(), img.height())
        if self.args.exit_after:
            QTimer.singleShot(200, QApplication.quit)

    def _poll_selftest(self) -> None:
        def cb(result):
            if result:
                try:
                    data = json.loads(result) if isinstance(result, str) else result
                except Exception:
                    data = {"raw": result}
                data["console_tail"] = self.page.console[-15:]
                text = json.dumps(data, indent=1)
                (LOG_DIR / "selftest.json").write_text(text, encoding="utf-8")
                print(text)
                log.info("selftest: %s", text)
                QApplication.exit(0 if data.get("ok") else 2)
                return
            if time.time() - self._selftest_started > 60:
                print(json.dumps({"ok": False, "error": "selftest timeout", "console_tail": self.page.console[-20:]}, indent=1))
                QApplication.exit(3)
                return
            QTimer.singleShot(500, self._poll_selftest)
        self.page.runJavaScript("window.__selftestResult ? JSON.stringify(window.__selftestResult) : ''", cb)


def _looks_blank(img) -> bool:
    w, h = img.width(), img.height()
    if w == 0 or h == 0:
        return True
    pts = [(w // 2, h // 2), (w // 4, h // 4), (3 * w // 4, 3 * h // 4), (10, 10)]
    return all(img.pixelColor(x, y).alpha() == 0 or img.pixelColor(x, y).value() == 0 for x, y in pts)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="999player")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--devtools", action="store_true")
    p.add_argument("--screenshot", metavar="PNG")
    p.add_argument("--js", metavar="CODE", help="JavaScript to run after load (dev)")
    p.add_argument("--delay", default=3500, type=int, help="ms after load before running --js / taking the screenshot")
    p.add_argument("--wait", default=1500, type=int, help="extra ms after --js before the screenshot")
    p.add_argument("--exit-after", action="store_true")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--no-gpu", action="store_true", help="software rendering (also: settings → appearance → gpu acceleration)")
    p.add_argument("--no-update", action="store_true", help="do not install a downloaded update at launch")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.debug:
        setup_logging(debug=True)
    register_scheme()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("999player.Desktop")
        except Exception:
            pass
    if not (args.no_update or args.selftest or args.screenshot):
        waiting = updater.pending()
        if waiting and updater.apply(*waiting):
            log.info("installing update %s", waiting[1])
            return 0
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(APP_ID)
    app = QApplication(sys.argv)
    icon = BUNDLE_DIR / "assets" / "icon.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    win = MainWindow(args)
    if args.selftest:
        win.showMinimized()
    else:
        win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
