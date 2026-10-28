from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QThread, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QIcon, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

try:
    from version import APP_VERSION
except ImportError:
    APP_VERSION = "0.0.0"

APP_NAME = "999 player"
EXE_NAME = "999player.exe"
OLD_EXE = "JuiceVault.exe"
REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\999player"
OLD_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\JuiceVault"
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
COVERS_DIR = BUNDLE_DIR / "ui" / "covers"
FONTS_DIR = BUNDLE_DIR / "ui" / "fonts"
ICON = BUNDLE_DIR / "assets" / "icon.png"
NO_WINDOW = 0x08000000
NEW_GROUP = 0x00000200
DETACHED = 0x00000008
SANDBOX = os.environ.get("JV_SETUP_SANDBOX") == "1"

ERAS = [
    ("juiced up the ep", "juiced-up-the-ep.jpg"), ("affliction", "affliction.jpg"),
    ("heartbroken in hollywood 999", "heartbroken-in-hollywood-999.jpg"), ("juice wrld 999", "juice-wrld-999.jpg"),
    ("bingedrinkingmusic", "bingedrinkingmusic.jpg"), ("nothing's different </3", "nothings-different.jpg"),
    ("goodbye & good riddance", "goodbye-good-riddance.jpg"), ("wrld on drugs", "wrld-on-drugs.jpg"),
    ("death race for love", "death-race-for-love.jpg"), ("outsiders", "outsiders.jpg"),
    ("posthumous", "posthumous.jpg"), ("jw3", "jw3.jpg"),
]

FACTS = [
    "999 flips 666 on its head: whatever hell you're going through, turn it into something good.",
    "jarad anthony higgins · chicago, illinois · december 2, 1998",
    "\"all girls are the same\" blew up on soundcloud and got him signed.",
    "\"lucid dreams\" peaked at #2 on the billboard hot 100.",
    "goodbye & good riddance dropped on may 23, 2018.",
    "wrld on drugs: a whole tape with future, october 2018.",
    "death race for love debuted at #1 on the billboard 200.",
    "he freestyled for over an hour straight on tim westwood's show.",
    "legends never die put five songs in the hot 100's top 10 in one week.",
    "\"lucid dreams\" is built on sting's \"shape of my heart\".",
    "nick mira produced both \"lucid dreams\" and \"all girls are the same\".",
]


def _rgba(rgb, a) -> str:
    return "rgba(%d,%d,%d,%d)" % (rgb[0], rgb[1], rgb[2], a)


def load_fonts() -> None:
    for p in sorted((FONTS_DIR / "inter").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(p))


def _has_family(name: str) -> bool:
    return name in QFontDatabase.families()


def display_family() -> str:
    for f in ("Inter", "Segoe UI Variable Display", "Segoe UI"):
        if _has_family(f):
            return f
    return "sans-serif"


def text_family() -> str:
    for f in ("Inter", "Segoe UI Variable Text", "Segoe UI"):
        if _has_family(f):
            return f
    return "sans-serif"


def glow(widget: QWidget, radius: int = 28, alpha: int = 110) -> None:
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(radius)
    fx.setOffset(0, 0)
    fx.setColor(QColor(255, 255, 255, alpha))
    widget.setGraphicsEffect(fx)


def rounded_pixmap(img: QImage, size: int, radius: int, gray: bool = False) -> QPixmap:
    src = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    if gray:
        src = src.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_ARGB32)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    p.drawImage(QRect((size - src.width()) // 2, (size - src.height()) // 2, src.width(), src.height()), src)
    p.setClipping(False)
    p.setPen(QPen(QColor(255, 255, 255, 60), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.end()
    return out


def frosted(img: QImage, w: int, h: int) -> QPixmap:
    fit = img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    fit = fit.copy((fit.width() - w) // 2, (fit.height() - h) // 2, w, h)
    tiny = fit.scaled(max(6, w // 40), max(4, h // 40), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    mid = tiny.scaled(max(12, w // 12), max(8, h // 12), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return QPixmap.fromImage(mid.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))


def accent_of(img: QImage) -> tuple:
    try:
        from accent import accent_from_bytes
        from PySide6.QtCore import QBuffer, QByteArray
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        img.scaled(64, 64).save(buf, "PNG")
        return tuple(accent_from_bytes(bytes(ba.data()))["rgb"])
    except Exception:
        return (155, 107, 255)


def human(n: float) -> str:
    for unit in ("b", "kb", "mb", "gb", "tb"):
        if n < 1024 or unit == "tb":
            return ("%.0f %s" if unit in ("b", "kb", "mb") else "%.1f %s") % (n, unit)
        n /= 1024
    return "%.0f" % n


def default_target() -> Path:
    drive = os.environ.get("SystemDrive", "C:")
    return Path(drive + "\\") / "999player"


def existing_install() -> Path | None:
    import winreg
    for key in (REG_KEY, OLD_REG_KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                loc = Path(winreg.QueryValueEx(k, "InstallLocation")[0])
            if (loc / EXE_NAME).exists() or (loc / OLD_EXE).exists():
                return loc
        except Exception:
            continue
    return None


def payload_path() -> Path | None:
    for i, a in enumerate(sys.argv):
        if a == "--payload" and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1])
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return None


def ps(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)


def _q(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def make_shortcut(folder_kind: str, target: Path) -> None:
    script = (f"$d=[Environment]::GetFolderPath('{folder_kind}'); "
              f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d {_q(APP_NAME + '.lnk')})); "
              f"$s.TargetPath={_q(target)}; $s.WorkingDirectory={_q(target.parent)}; "
              f"$s.IconLocation={_q(str(target) + ',0')}; $s.Description={_q('the vault, on your desktop')}; $s.Save()")
    r = ps(script)
    if r.returncode != 0:
        raise RuntimeError("shortcut failed: " + (r.stderr or r.stdout).strip()[:300])


def shortcut_exists(folder_kind: str) -> bool:
    if SANDBOX:
        return False
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.shell32.SHGetFolderPathW(None, {"Desktop": 0x10, "Programs": 0x02}[folder_kind], None, 0, buf)
        return (Path(buf.value) / f"{APP_NAME}.lnk").exists()
    except Exception:
        return False


def remove_shortcut(folder_kind: str) -> None:
    ps(f"$d=[Environment]::GetFolderPath('{folder_kind}'); Remove-Item -LiteralPath (Join-Path $d {_q(APP_NAME + '.lnk')}) -Force -ErrorAction SilentlyContinue")


def write_registry(target: Path, size_bytes: int) -> None:
    import winreg
    exe = target / EXE_NAME
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
        def s(name, val):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        s("DisplayName", APP_NAME)
        s("DisplayVersion", APP_VERSION)
        s("Publisher", APP_NAME)
        s("DisplayIcon", f'"{exe}",0')
        s("InstallLocation", str(target))
        s("UninstallString", f'"{exe}" --uninstall')
        s("InstallDate", time.strftime("%Y%m%d"))
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, int(size_bytes // 1024))
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, OLD_REG_KEY)
    except Exception:
        pass


def remove_registry() -> None:
    import winreg
    for key in (REG_KEY, OLD_REG_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except Exception:
            pass


def app_locked(target: Path) -> bool:
    for exe in (target / EXE_NAME, target / OLD_EXE):
        if not exe.exists():
            continue
        try:
            with open(exe, "ab"):
                continue
        except PermissionError:
            return True
        except OSError:
            continue
    return False


def kill_app() -> None:
    for name in (EXE_NAME, OLD_EXE):
        subprocess.run(["taskkill", "/f", "/fi", f"PID ne {os.getpid()}", "/im", name], capture_output=True, creationflags=NO_WINDOW)
    time.sleep(1.5)


class InstallWorker(QThread):
    progress = Signal(int, int, str)
    locked = Signal()
    done = Signal()
    failed = Signal(str)

    def __init__(self, payload: Path, target: Path, desktop: bool, startmenu: bool, register: bool = True, auto_close: bool = False):
        super().__init__()
        self.payload, self.target, self.desktop, self.startmenu = payload, target, desktop, startmenu
        self.register, self.auto_close = register, auto_close
        self.decision = None

    def phase_for(self, name: str) -> str:
        if "/assets/lyrics/" in name:
            return "lyrics"
        if "/PySide6/" in name:
            return "player"
        if "/ui/" in name:
            return "glass"
        return "vault"

    def run(self) -> None:
        try:
            self.progress.emit(0, 1, "open")
            with zipfile.ZipFile(self.payload) as zf:
                infos = [i for i in zf.infolist() if not i.is_dir()]
                total = sum(i.file_size for i in infos) or 1
                if self.auto_close:
                    for _ in range(120):
                        if not app_locked(self.target):
                            break
                        time.sleep(0.1)
                if app_locked(self.target):
                    if self.auto_close:
                        self.decision = "kill"
                    else:
                        self.locked.emit()
                    while self.decision is None:
                        time.sleep(0.1)
                    if self.decision != "kill":
                        self.failed.emit("cancelled")
                        return
                    kill_app()
                    if app_locked(self.target):
                        self.failed.emit("999 player is still running. close it, then try again.")
                        return
                self.target.mkdir(parents=True, exist_ok=True)
                if (self.target / "_internal").exists():
                    shutil.rmtree(self.target / "_internal", ignore_errors=True)
                (self.target / OLD_EXE).unlink(missing_ok=True)
                done = 0
                root = self.target.resolve()
                last = 0.0
                for info in infos:
                    rel = info.filename.replace("\\", "/")
                    dest = (root / rel).resolve()
                    if root not in dest.parents:
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(dest, "wb") as out:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            out.write(chunk)
                            done += len(chunk)
                            now = time.monotonic()
                            if now - last > 0.03:
                                last = now
                                self.progress.emit(done, total, self.phase_for("/" + rel))
                self.progress.emit(total, total, "shortcuts")
                exe = self.target / EXE_NAME
                if self.desktop:
                    make_shortcut("Desktop", exe)
                elif not self.auto_close and not SANDBOX:
                    remove_shortcut("Desktop")
                if self.startmenu:
                    make_shortcut("Programs", exe)
                elif not self.auto_close and not SANDBOX:
                    remove_shortcut("Programs")
                if self.register and not SANDBOX:
                    write_registry(self.target, total)
                self.progress.emit(total, total, "done")
                self.done.emit()
        except PermissionError as e:
            self.failed.emit(f"windows won't let me write there ({e.filename or ''}). pick a folder inside your user profile, or run setup as administrator.")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


class UninstallWorker(QThread):
    step = Signal(str)
    done = Signal()
    failed = Signal(str)

    def __init__(self, install_dir: Path, wipe_data: bool, preview: bool = False):
        super().__init__()
        self.install_dir, self.wipe_data, self.preview = install_dir, wipe_data, preview

    def run(self) -> None:
        try:
            self.step.emit("closing the vault…")
            if not self.preview:
                kill_app()
            self.step.emit("removing shortcuts…")
            if not self.preview:
                remove_shortcut("Desktop")
                remove_shortcut("Programs")
                remove_registry()
            if self.wipe_data:
                self.step.emit("wiping likes, playlists and settings…")
                base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                for data in (base / "999player", base / "JuiceVault"):
                    if not self.preview and data.exists():
                        shutil.rmtree(data, ignore_errors=True)
            time.sleep(0.6)
            self.done.emit()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


def schedule_self_delete(install_dir: Path) -> None:
    d = str(install_dir)
    bat = Path(os.environ.get("TEMP", "C:\\")) / "999player-uninstall.cmd"
    lines = [
        "@echo off",
        "for /l %%i in (1,1,15) do (",
        "  waitfor /t 1 jv999 >nul 2>&1",
        f'  rmdir /s /q "{d}" >nul 2>&1',
        f'  if not exist "{d}" goto done',
        ")",
        ":done",
        '(goto) 2>nul & del "%~f0"',
    ]
    bat.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(bat.parent), creationflags=NO_WINDOW | NEW_GROUP,
                     close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Switch(QAbstractButton):
    def __init__(self, checked=True, accent=(155, 107, 255), parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.accent = accent
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 26)
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._tick)
        self.toggled.connect(self._go)

    def _go(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _tick(self, v):
        self._pos = float(v)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        off = QColor(255, 255, 255, 38)
        on = QColor(*self.accent, 230)
        fill = QColor(int(off.red() + (on.red() - off.red()) * self._pos), int(off.green() + (on.green() - off.green()) * self._pos),
                      int(off.blue() + (on.blue() - off.blue()) * self._pos), int(off.alpha() + (on.alpha() - off.alpha()) * self._pos))
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        p.setBrush(fill)
        p.drawRoundedRect(r, 13, 13)
        x = 3 + (self.width() - 26) * self._pos
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawEllipse(QRectF(x, 4.5, 20, 20))
        p.setBrush(QColor(255, 255, 255, 245))
        p.drawEllipse(QRectF(x, 3, 20, 20))


class SwitchRow(QWidget):
    def __init__(self, text: str, checked: bool, accent, hint: str = ""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.sw = Switch(checked, accent)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(text)
        lab.setObjectName("opt")
        col.addWidget(lab)
        if hint:
            h = QLabel(hint)
            h.setObjectName("hint")
            col.addWidget(h)
        lay.addWidget(self.sw, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(col, 1)
        lab.mousePressEvent = lambda _e: self.sw.toggle()
        lab.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self):
        return self.sw.isChecked()


class Progress(QWidget):
    def __init__(self, accent):
        super().__init__()
        self.accent = accent
        self.value = 0.0
        self.shown = 0.0
        self.setFixedHeight(10)
        self._anim = QVariantAnimation(self, duration=260, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._tick)

    def set(self, v: float):
        v = max(0.0, min(1.0, v))
        if abs(v - self.value) < 0.0005:
            return
        self.value = v
        self._anim.stop()
        self._anim.setStartValue(self.shown)
        self._anim.setEndValue(v)
        self._anim.start()

    def _tick(self, v):
        self.shown = float(v)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(r, 5, 5)
        w = max(10.0, r.width() * self.shown)
        g = QLinearGradient(0, 0, w, 0)
        a = QColor(*self.accent)
        b = QColor(*self.accent).lighter(135)
        g.setColorAt(0, a)
        g.setColorAt(1, b)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(0, 0, w, r.height()), 5, 5)
        p.setBrush(QColor(255, 255, 255, 70))
        p.drawRoundedRect(QRectF(1, 1, w - 2, r.height() / 2 - 1), 3, 3)


class EraTimeline(QWidget):

    def __init__(self, covers: list[tuple[str, QImage]], accent):
        super().__init__()
        self.accent = accent
        self.items = [(name, rounded_pixmap(img, 112, 22), rounded_pixmap(img, 112, 22, gray=True)) for name, img in covers]
        self.progress = 0.0
        self.setFixedHeight(118)

    def set(self, v: float):
        self.progress = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, _e):
        n = len(self.items)
        if not n:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        size = 56
        gap = (self.width() - n * size) / (n - 1) if n > 1 else 0
        cy = 36
        reached = self.progress * (n - 1)
        cur = min(n - 1, int(round(reached)))
        p.setPen(QPen(QColor(255, 255, 255, 40), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(size / 2, cy), QPointF(self.width() - size / 2, cy))
        if reached > 0:
            p.setPen(QPen(QColor(*self.accent, 220), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(size / 2, cy), QPointF(size / 2 + reached * (size + gap), cy))
        for i, (name, pix, gray) in enumerate(self.items):
            x = i * (size + gap)
            lit = i <= reached + 0.01
            s = size + (8 if i == cur else 0)
            rect = QRectF(x + (size - s) / 2, cy - s / 2, s, s)
            if lit and i == cur:
                glow = QRadialGradient(rect.center(), s * 0.95)
                glow.setColorAt(0, QColor(*self.accent, 120))
                glow.setColorAt(1, QColor(*self.accent, 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(glow))
                p.drawEllipse(rect.adjusted(-14, -14, 14, 14))
            p.setOpacity(1.0 if lit else 0.38)
            p.drawPixmap(rect.toRect(), pix if lit else gray)
            p.setOpacity(1.0)
        name = self.items[cur][0]
        f = QFont(text_family(), 11)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 190))
        p.drawText(QRectF(0, cy + 40, self.width(), 24), Qt.AlignmentFlag.AlignCenter, name)


class CoverFan(QWidget):

    def __init__(self, covers: list[QImage]):
        super().__init__()
        self.pix = [rounded_pixmap(c, 440, 44) for c in covers[:3]]
        self.t = 0.0
        self.setMinimumSize(360, 360)
        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self):
        self.t += 0.033
        self.update()

    def paintEvent(self, _e):
        if not self.pix:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        size = min(self.width(), self.height()) * 0.56
        cx, cy = self.width() / 2, self.height() / 2 + 10
        for i, (pix, ang, dx) in enumerate(zip(self.pix, (-11, 0, 11), (-0.33, 0, 0.33))):
            drift = math.sin(self.t * 0.9 + i * 1.7) * 6
            p.save()
            p.translate(cx + dx * size, cy + drift)
            p.rotate(ang + math.sin(self.t * 0.6 + i) * 1.2)
            r = QRectF(-size / 2, -size / 2, size, size)
            p.setPen(Qt.PenStyle.NoPen)
            for k in range(6, 0, -1):
                p.setBrush(QColor(0, 0, 0, 14))
                p.drawRoundedRect(r.adjusted(-k * 2, -k * 2 + 10, k * 2, k * 2 + 10), 36, 36)
            p.drawPixmap(r.toRect(), pix)
            p.restore()


class TitleBar(QWidget):
    def __init__(self, win: "GlassWindow", caption: str):
        super().__init__(win)
        self.win = win
        self.setFixedHeight(46)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 0, 14, 0)
        self.cap = QLabel(caption)
        self.cap.setObjectName("brand")
        lay.addWidget(self.cap)
        lay.addStretch(1)
        for name, fn in (("—", win.showMinimized), ("✕", win.close)):
            b = QPushButton(name)
            b.setObjectName("winbtn")
            b.setFixedSize(30, 30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            lay.addWidget(b)
        self._drag = None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.win.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        self._drag = None


class PageTransition(QWidget):

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.old = self.new = None
        self.t = 0.0
        self.anim = QVariantAnimation(self, duration=420, easingCurve=QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._tick)
        self._on_done = None
        self.anim.finished.connect(self._finished)
        self.hide()

    def _finished(self):
        self.hide()
        if self._on_done:
            self._on_done()

    def run(self, old: QPixmap, new: QPixmap, geo: QRect, on_done):
        self.old, self.new = old, new
        self.setGeometry(geo)
        self.t = 0.0
        self.show()
        self.raise_()
        self._on_done = on_done
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def _tick(self, v):
        self.t = float(v)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        t = self.t
        if self.old:
            p.setOpacity(max(0.0, 1 - t * 1.6))
            p.drawPixmap(QPoint(int(-34 * t), 0), self.old)
        if self.new:
            p.setOpacity(min(1.0, t * 1.25))
            p.drawPixmap(QPoint(int(44 * (1 - t)), 0), self.new)


class StackHost(QWidget):
    def __init__(self):
        super().__init__()
        self.stack = QStackedWidget(self)

    def resizeEvent(self, e):
        self.stack.setGeometry(self.rect())
        super().resizeEvent(e)


class GlassWindow(QWidget):
    SHADOW = 26
    RADIUS = 26
    BG_ERA = "outsiders"
    RENDER_DOWN = 3
    BLOBS = (
        (46, 1, -0.09, -0.06, 1.0, 0.92, False),
        (63, -1, 0.11, 0.07, 0.92, 0.5, True),
        (85, -1, -0.05, 0.10, 1.06, 0.45, False),
    )

    def __init__(self, caption: str, covers: list[tuple[str, QImage]], size=(940, 600)):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(f"{APP_NAME} — {caption}")
        if ICON.exists():
            self.setWindowIcon(QIcon(str(ICON)))
        self.covers = covers
        self.inner_size = QSize(*size)
        self.resize(size[0] + 2 * self.SHADOW, size[1] + 2 * self.SHADOW)
        self.setFixedSize(self.size())
        bg = next((img for n, img in covers if n == self.BG_ERA), covers[0][1] if covers else None)
        self.accent = accent_of(bg) if bg is not None else (155, 107, 255)
        self._blob = self._make_blob(bg) if bg is not None else None
        self._t0 = time.monotonic()
        self._canvas = QImage(max(1, size[0] // self.RENDER_DOWN), max(1, size[1] // self.RENDER_DOWN), QImage.Format.Format_RGB32)
        self._bg_timer = QTimer(self, interval=40)
        self._bg_timer.timeout.connect(self.update)
        self._bg_timer.start()
        self._pose = 0.0
        self._snapshot: QPixmap | None = None
        self._closing = False
        self._pose_anim = QVariantAnimation(self, duration=560, easingCurve=QEasingCurve.Type.OutBack)
        self._pose_anim.valueChanged.connect(self._on_pose)
        self._pose_done = None
        self._pose_anim.finished.connect(lambda: self._pose_done and self._pose_done())

        self.body = QWidget(self)
        self.body.setGeometry(self.SHADOW, self.SHADOW, size[0], size[1])
        root = QVBoxLayout(self.body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(self, f"{APP_NAME}  ·  {caption}")
        root.addWidget(self.titlebar)
        self.host = StackHost()
        root.addWidget(self.host, 1)
        self.stack = self.host.stack
        self.trans = PageTransition(self.body)
        self.apply_style()

    def _make_blob(self, img: QImage) -> QPixmap:
        vmax = max(self.inner_size.width(), self.inner_size.height())
        size = int(1.65 * vmax / self.RENDER_DOWN)
        tiny = img.scaled(14, 14, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        tiny = tiny.convertToFormat(QImage.Format.Format_ARGB32)
        for y in range(tiny.height()):
            for x in range(tiny.width()):
                c = tiny.pixelColor(x, y)
                h, s, v, a = c.getHsvF()
                c.setHsvF(h if h >= 0 else 0, min(1.0, s * 1.9), min(1.0, v * 0.62), a)
                tiny.setPixelColor(x, y, c)
        soft = tiny.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        big = soft.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        out = QPixmap(size, size)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, size, size), size * 0.4, size * 0.4)
        p.setClipPath(path)
        p.drawImage(0, 0, big)
        p.end()
        return out

    def _paint_backdrop(self, p: QPainter, inner: QRectF):
        if self._blob is None:
            p.fillRect(inner, QColor(7, 7, 12))
            return
        c = self._canvas
        c.fill(QColor(7, 7, 12))
        q = QPainter(c)
        q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        t = time.monotonic() - self._t0
        cx, cy = c.width() / 2, c.height() / 2
        s = self._blob.width()
        for secs, direction, ox, oy, scale, opacity, screen in self.BLOBS:
            q.save()
            q.setOpacity(opacity)
            if screen:
                q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
            q.translate(cx + ox * s, cy + oy * s)
            q.rotate(direction * (t / secs) * 360.0)
            q.scale(scale, scale)
            q.drawPixmap(QPointF(-s / 2, -s / 2), self._blob)
            q.restore()
        q.end()
        p.drawImage(inner.toRect(), c)

    def showEvent(self, e):
        super().showEvent(e)
        if self._pose == 0.0 and self._pose_anim.state() != QVariantAnimation.State.Running:
            self.setWindowOpacity(0.0)
            QTimer.singleShot(0, self._pop_in)

    def _pop_in(self):
        self._snapshot = self.body.grab()
        self.body.hide()
        self._pose_anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._pose_anim.setDuration(560)
        self._pose_anim.setStartValue(0.0)
        self._pose_anim.setEndValue(1.0)
        self._pose_done = self._pop_done
        self._pose_anim.start()

    def _pop_done(self):
        self._snapshot = None
        self.body.show()
        self.setWindowOpacity(1.0)
        self.update()

    def _on_pose(self, v):
        self._pose = float(v)
        self.setWindowOpacity(max(0.0, min(1.0, self._pose * 1.4)))
        self.update()

    def closeEvent(self, e):
        if self._closing:
            super().closeEvent(e)
            return
        e.ignore()
        self._closing = True
        self._snapshot = self.body.grab()
        self.body.hide()
        self._pose_anim.stop()
        self._pose_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._pose_anim.setDuration(240)
        self._pose_anim.setStartValue(self._pose)
        self._pose_anim.setEndValue(0.0)
        self._pose_done = self.close
        self._pose_anim.start()

    def go(self, index: int):
        if index == self.stack.currentIndex() or not self.body.isVisible():
            self.stack.setCurrentIndex(index)
            return
        old = self.stack.grab()
        self.stack.setCurrentIndex(index)
        self.stack.hide()

        def swap():
            self.stack.show()
            new = self.stack.grab()
            self.stack.hide()
            self.trans.run(old, new, self.host.geometry(), self.stack.show)
        QTimer.singleShot(0, swap)

    def apply_style(self):
        a = self.accent
        d, t = display_family(), text_family()
        self.setStyleSheet(f"""
        QWidget {{ color: rgba(255,255,255,236); font-family: '{t}'; font-size: 14px; background: transparent; }}
        QLabel#brand {{ font-family: '{d}'; font-weight: 700; font-size: 13px; color: rgba(255,255,255,170); }}
        QLabel#h1 {{ font-family: '{d}'; font-weight: 800; font-size: 46px; color: white; }}
        QLabel#h2 {{ font-family: '{d}'; font-weight: 700; font-size: 30px; color: white; }}
        QLabel#sub {{ font-size: 15px; color: rgba(255,255,255,185); }}
        QLabel#muted {{ font-size: 13px; color: rgba(255,255,255,140); }}
        QLabel#hint {{ font-size: 12px; color: rgba(255,255,255,120); }}
        QLabel#opt {{ font-size: 14px; font-weight: 600; }}
        QLabel#chip {{ font-family: '{d}'; font-weight: 800; font-size: 12px; padding: 3px 10px; border-radius: 11px;
                       background: {_rgba(a, 150)}; border: 1px solid rgba(255,255,255,90); color: white; }}
        QLabel#tag {{ font-family: '{d}'; font-weight: 700; font-size: 13px; color: {_rgba(a, 255)}; }}
        QLabel#fact {{ font-size: 13px; color: rgba(255,255,255,150); font-style: italic; }}
        QLabel#err {{ font-size: 13px; color: rgba(255,210,210,230); background: rgba(255,80,80,40);
                      border: 1px solid rgba(255,120,120,90); border-radius: 12px; padding: 10px 14px; }}
        QLabel#warn {{ font-size: 12px; color: rgba(255,225,170,230); }}
        QPushButton {{ font-family: '{d}'; font-weight: 700; font-size: 14px; color: white; min-height: 40px; padding: 0 24px;
                       border-radius: 20px; background: rgba(255,255,255,24); border: 1px solid rgba(255,255,255,46); }}
        QPushButton:hover {{ background: rgba(255,255,255,44); border-color: rgba(255,255,255,90); }}
        QPushButton:pressed {{ background: rgba(255,255,255,16); }}
        QPushButton:disabled {{ color: rgba(255,255,255,90); background: rgba(255,255,255,12); border-color: rgba(255,255,255,20); }}
        QPushButton#primary {{ background: {_rgba(a, 165)}; border: 1px solid rgba(255,255,255,95); }}
        QPushButton#primary:hover {{ background: {_rgba(a, 215)}; }}
        QPushButton#primary:disabled {{ background: {_rgba(a, 70)}; }}
        QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: rgba(255,255,255,165); }}
        QPushButton#ghost:hover {{ background: rgba(255,255,255,20); color: white; }}
        QPushButton#winbtn {{ min-height: 0; padding: 0; border-radius: 15px; font-size: 11px; font-weight: 400;
                              background: transparent; border: none; color: rgba(255,255,255,140); }}
        QPushButton#winbtn:hover {{ background: rgba(255,255,255,30); color: white; }}
        QPushButton#browse {{ min-height: 36px; border-radius: 18px; padding: 0 18px; font-size: 13px; }}
        QLineEdit {{ background: rgba(0,0,0,70); border: 1px solid rgba(255,255,255,46); border-radius: 18px; padding: 8px 16px;
                     font-size: 14px; color: white; selection-background-color: {_rgba(a, 170)}; min-height: 20px; }}
        QLineEdit:focus {{ border: 1px solid {_rgba(a, 230)}; background: rgba(0,0,0,90); }}
        QFrame#card {{ background: rgba(255,255,255,14); border: 1px solid rgba(255,255,255,36); border-radius: 22px; }}
        """)
        for w in self.findChildren(Switch):
            w.accent = a
            w.update()
        for w in self.findChildren(Progress):
            w.accent = a
            w.update()
        for w in self.findChildren(EraTimeline):
            w.accent = a
            w.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        S, R = self.SHADOW, self.RADIUS
        inner = QRectF(S, S, self.inner_size.width(), self.inner_size.height())
        if self._pose < 1.0 or self._snapshot is not None:
            k = 0.92 + 0.08 * self._pose
            p.translate(inner.center())
            p.scale(k, k)
            p.translate(-inner.center())
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(S, 0, -2):
            p.setBrush(QColor(0, 0, 0, int(3 + (S - k) * 0.55)))
            p.drawRoundedRect(inner.adjusted(-k, -k + 6, k, k + 6), R + k, R + k)
        path = QPainterPath()
        path.addRoundedRect(inner, R, R)
        p.setClipPath(path)
        self._paint_backdrop(p, inner)
        g = QLinearGradient(inner.topLeft(), inner.bottomLeft())
        g.setColorAt(0, QColor(6, 6, 11, 76))
        g.setColorAt(0.55, QColor(6, 6, 11, 107))
        g.setColorAt(1, QColor(6, 6, 11, 199))
        p.fillRect(inner, QBrush(g))
        sheen = QLinearGradient(inner.topLeft(), QPointF(inner.left(), inner.top() + 120))
        sheen.setColorAt(0, QColor(255, 255, 255, 26))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(inner, QBrush(sheen))
        if self._snapshot is not None:
            p.drawPixmap(inner.toRect(), self._snapshot)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 58), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(inner.adjusted(0.5, 0.5, -0.5, -0.5), R, R)

    @staticmethod
    def label(text, oid, wrap=False) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName(oid)
        lab.setWordWrap(wrap)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if oid in ("h1", "h2"):
            f = QFont(display_family())
            f.setPixelSize(46 if oid == "h1" else 30)
            f.setWeight(QFont.Weight.ExtraBold if oid == "h1" else QFont.Weight.Bold)
            f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 97)
            lab.setFont(f)
            glow(lab, 34 if oid == "h1" else 26, 120)
        elif oid == "sub":
            glow(lab, 18, 55)
        return lab

    @staticmethod
    def button(text, oid="") -> QPushButton:
        b = QPushButton(text)
        if oid:
            b.setObjectName(oid)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    @staticmethod
    def page(margins=(56, 26, 56, 40)) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(*margins)
        lay.setSpacing(12)
        return w, lay


class SetupWindow(GlassWindow):
    def __init__(self, covers, payload: Path | None, update_dir: Path | None = None):
        super().__init__("update" if update_dir else "setup", covers)
        self.payload = payload
        self.worker: InstallWorker | None = None
        self.need_bytes = 0
        self.previous = existing_install()
        self.update_dir = update_dir
        self.target = update_dir or self.previous or default_target()
        self._read_payload()
        self.build_welcome()
        self.build_setup()
        self.build_installing()
        self.build_done()
        self.build_error()
        if update_dir:
            self.go(2)
            if self.payload_error:
                QTimer.singleShot(400, lambda: self.on_failed(self.payload_error))
            else:
                QTimer.singleShot(500, self.start_update)
        else:
            self.go(0)

    def start_update(self):
        self.target = Path(self.update_dir)
        self.i_sub.setText(f"999 player {APP_VERSION}  ·  {self.target}")
        self._fact_i = 0
        self._next_fact()
        self._fact_timer.start()
        self.bar.set(0)
        self.timeline.set(0)
        self.worker = InstallWorker(self.payload, self.target, shortcut_exists("Desktop"), shortcut_exists("Programs"),
                                    register=(existing_install() or Path()).resolve() == self.target.resolve(), auto_close=True)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def _read_payload(self):
        if self.payload and self.payload.exists():
            try:
                with zipfile.ZipFile(self.payload) as zf:
                    self.need_bytes = sum(i.file_size for i in zf.infolist() if not i.is_dir())
            except Exception as e:  # noqa: BLE001
                self.payload_error = f"the installer's payload is damaged ({e}). re-download setup."
                return
        else:
            self.payload_error = "no app payload found — this exe was built without one."
            return
        self.payload_error = ""

    def build_welcome(self):
        w, lay = self.page((56, 10, 40, 36))
        row = QHBoxLayout()
        row.setSpacing(24)
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addStretch(2)
        title = self.label("update the vault" if self.previous else APP_NAME, "h1", wrap=True)
        left.addWidget(title)
        sub = ("a newer version is ready. your likes, playlists, downloads and settings stay where they are."
               if self.previous else
               "a desktop player for juice wrld's catalog: 3,808 songs with synced lyrics, playlists, downloads and offline play.")
        left.addWidget(self.label(sub, "sub", wrap=True))
        left.addSpacing(6)
        left.addWidget(self.label(f"about {human(self.need_bytes)} on disk  ·  no admin needed  ·  v{APP_VERSION}", "muted"))
        if self.payload_error:
            left.addWidget(self.label(self.payload_error, "err", wrap=True))
        left.addStretch(3)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.b_start = self.button("update" if self.previous else "install", "primary")
        self.b_start.setEnabled(not self.payload_error)
        self.b_start.clicked.connect(lambda: self.go(1))
        q = self.button("quit", "ghost")
        q.clicked.connect(self.close)
        btns.addWidget(self.b_start)
        btns.addWidget(q)
        btns.addStretch(1)
        left.addLayout(btns)
        row.addLayout(left, 11)
        fan = CoverFan([img for _n, img in self.covers[6:9]] or [img for _n, img in self.covers])
        row.addWidget(fan, 9)
        lay.addLayout(row, 1)
        self.stack.addWidget(w)

    def build_setup(self):
        w, lay = self.page()
        lay.addWidget(self.label("where should the vault live?", "h2"))
        lay.addWidget(self.label("pick a folder for the app. everything it needs goes in there.", "sub", wrap=True))
        lay.addSpacing(6)
        prow = QHBoxLayout()
        prow.setSpacing(10)
        self.path = QLineEdit(str(self.target))
        self.path.textChanged.connect(self.validate)
        self.path.returnPressed.connect(self.start_install)
        prow.addWidget(self.path, 1)
        br = self.button("browse…", "browse")
        br.clicked.connect(self.browse)
        prow.addWidget(br)
        lay.addLayout(prow)
        self.space = self.label("", "muted")
        lay.addWidget(self.space)
        self.warn = self.label("", "warn", wrap=True)
        lay.addWidget(self.warn)
        lay.addSpacing(6)
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 18, 22, 18)
        cl.setSpacing(14)
        self.o_desktop = SwitchRow("desktop shortcut", True, self.accent, "puts a shortcut on your desktop")
        self.o_start = SwitchRow("start menu entry", True, self.accent, "so windows search finds it")
        self.o_launch = SwitchRow("open the vault when setup finishes", True, self.accent)
        for o in (self.o_desktop, self.o_start, self.o_launch):
            cl.addWidget(o)
        lay.addWidget(card)
        lay.addStretch(1)
        btns = QHBoxLayout()
        back = self.button("back", "ghost")
        back.clicked.connect(lambda: self.go(0))
        self.b_install = self.button("update" if self.previous else "install", "primary")
        self.b_install.clicked.connect(self.start_install)
        btns.addWidget(back)
        btns.addStretch(1)
        btns.addWidget(self.b_install)
        lay.addLayout(btns)
        self.stack.addWidget(w)
        self.validate()

    def browse(self):
        start = self.path.text().strip() or str(default_target().parent)
        while start and not Path(start).exists():
            start = str(Path(start).parent)
        d = QFileDialog.getExistingDirectory(self, "where should the vault live?", start)
        if not d:
            return
        d = Path(d)
        if d.name.lower() not in (APP_NAME, "999player", "999 player", "juicewrldvault") and not (d / EXE_NAME).exists() and not (d / OLD_EXE).exists():
            d = d / "999player"
        self.path.setText(str(d))

    def validate(self):
        txt = self.path.text().strip().strip('"')
        ok, warn, space = True, "", ""
        try:
            p = Path(txt)
            if not txt or not p.is_absolute() or not p.drive:
                ok, warn = False, "give me a full path, like D:\\999player"
            else:
                anchor = p
                while not anchor.exists() and anchor.parent != anchor:
                    anchor = anchor.parent
                if not anchor.exists():
                    ok, warn = False, f"drive {p.drive} doesn't exist"
                else:
                    free = shutil.disk_usage(anchor).free
                    space = f"needs {human(self.need_bytes)}  ·  {human(free)} free on {p.drive.lower()}"
                    if free < self.need_bytes * 1.1:
                        ok, warn = False, "not enough space on that drive"
                    elif p.exists() and ((p / EXE_NAME).exists() or (p / OLD_EXE).exists()):
                        warn = "there's a vault here already — it'll be updated in place."
                    elif p.exists() and any(p.iterdir()):
                        warn = "that folder isn't empty. the app's files will be mixed in with what's there."
                    low = str(p).lower()
                    if ok and (low.startswith("c:\\windows") or low.startswith("c:\\program files")):
                        warn = "windows usually blocks writing there without admin. a folder in your user profile is safer."
        except Exception:
            ok, warn = False, "that path doesn't look right"
        self.space.setText(space)
        self.warn.setText(warn)
        self.b_install.setEnabled(ok and not self.payload_error)

    def build_installing(self):
        w, lay = self.page()
        self.i_title = self.label("opening the vault…", "h2")
        lay.addWidget(self.i_title)
        self.i_sub = self.label("", "sub")
        lay.addWidget(self.i_sub)
        lay.addStretch(1)
        self.timeline = EraTimeline(self.covers, self.accent)
        lay.addWidget(self.timeline)
        lay.addSpacing(4)
        self.bar = Progress(self.accent)
        lay.addWidget(self.bar)
        self.i_detail = self.label("", "muted")
        lay.addWidget(self.i_detail)
        lay.addStretch(1)
        self.lock_card = QFrame()
        self.lock_card.setObjectName("card")
        ll = QHBoxLayout(self.lock_card)
        ll.setContentsMargins(20, 14, 14, 14)
        ll.addWidget(self.label("999 player is still open. want me to close it and carry on?", "sub", wrap=True), 1)
        k = self.button("close it and continue", "primary")
        k.clicked.connect(self._kill_and_go)
        c = self.button("cancel", "ghost")
        c.clicked.connect(self._cancel_locked)
        ll.addWidget(k)
        ll.addWidget(c)
        self.lock_card.hide()
        lay.addWidget(self.lock_card)
        self.fact = self.label("", "fact", wrap=True)
        self.fact.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.fact)
        self._fact_i = 0
        self._fact_timer = QTimer(self, interval=6000)
        self._fact_timer.timeout.connect(self._next_fact)
        self.stack.addWidget(w)

    def _next_fact(self):
        self.fact.setText(FACTS[self._fact_i % len(FACTS)])
        self._fact_i += 1

    def start_install(self):
        if not self.b_install.isEnabled():
            return
        self.target = Path(self.path.text().strip().strip('"'))
        self.go(2)
        self.i_sub.setText(f"into {self.target}")
        self._fact_i = 0
        self._next_fact()
        self._fact_timer.start()
        self.bar.set(0)
        self.timeline.set(0)
        self.worker = InstallWorker(self.payload, self.target, self.o_desktop.isChecked(), self.o_start.isChecked())
        self.worker.progress.connect(self.on_progress)
        self.worker.locked.connect(lambda: self.lock_card.show())
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def _kill_and_go(self):
        self.lock_card.hide()
        if self.worker:
            self.worker.decision = "kill"

    def _cancel_locked(self):
        self.lock_card.hide()
        if self.worker:
            self.worker.decision = "cancel"

    PHASES = {"open": "opening the vault…", "vault": "unpacking the vault…", "player": "building the player…",
              "glass": "polishing the glass…", "lyrics": "tucking in 1,740 lyric sheets…", "shortcuts": "wiring up shortcuts…",
              "done": "999."}

    def on_progress(self, done, total, phase):
        self.bar.set(done / total)
        self.timeline.set(done / total)
        self.i_title.setText(self.PHASES.get(phase, "unpacking the vault…"))
        self.i_detail.setText(f"{human(done)} of {human(total)}" if phase not in ("shortcuts", "done") else "")

    def build_done(self):
        w, lay = self.page((56, 10, 40, 36))
        row = QHBoxLayout()
        row.setSpacing(24)
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addStretch(2)
        left.addWidget(self.label("legends never die.", "h1"))
        self.d_sub = self.label("", "sub", wrap=True)
        left.addWidget(self.d_sub)
        left.addStretch(3)
        left.addWidget(self.label("jarad anthony higgins  ·  1998 – 2019", "muted"))
        btns = QHBoxLayout()
        self.b_open = self.button("open the vault", "primary")
        self.b_open.clicked.connect(self.launch_and_close)
        cl = self.button("close", "ghost")
        cl.clicked.connect(self.close)
        btns.addWidget(self.b_open)
        btns.addWidget(cl)
        btns.addStretch(1)
        left.addLayout(btns)
        row.addLayout(left, 11)
        row.addWidget(CoverFan([img for _n, img in self.covers[9:12]] or [img for _n, img in self.covers]), 9)
        lay.addLayout(row, 1)
        self.stack.addWidget(w)

    def on_done(self):
        self._fact_timer.stop()
        if self.update_dir:
            self.i_title.setText("999.")
            QTimer.singleShot(500, self.launch_and_close)
            return
        self.d_sub.setText(f"installed at {self.target}. "
                           + ("there's a shortcut on your desktop. " if self.o_desktop.isChecked() else "")
                           + "likes, playlists and settings are saved in %localappdata%\\999player. downloads go to music\\999 player.")
        self.go(3)
        if self.o_launch.isChecked():
            QTimer.singleShot(900, self.launch_and_close)

    def launch_and_close(self):
        exe = self.target / EXE_NAME
        try:
            subprocess.Popen([str(exe)], cwd=str(self.target), creationflags=DETACHED | NEW_GROUP, close_fds=True)
        except Exception as e:  # noqa: BLE001
            self.e_text.setText(f"installed, but the app did not open: {e}")
            self.go(4)
            return
        self.close()

    def build_error(self):
        w, lay = self.page()
        lay.addStretch(1)
        lay.addWidget(self.label("something went wrong", "h2"))
        self.e_text = self.label("", "err", wrap=True)
        lay.addWidget(self.e_text)
        lay.addWidget(self.label("your likes, playlists and downloads weren't touched.", "muted", wrap=True))
        lay.addStretch(2)
        btns = QHBoxLayout()
        again = self.button("try again", "primary")
        again.clicked.connect(lambda: self.go(1))
        q = self.button("quit", "ghost")
        q.clicked.connect(self.close)
        btns.addWidget(again)
        btns.addWidget(q)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.stack.addWidget(w)

    def on_failed(self, msg):
        self._fact_timer.stop()
        if msg == "cancelled":
            self.go(1)
            return
        self.e_text.setText(msg)
        self.go(4)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            i = self.stack.currentIndex()
            if i == 0 and self.b_start.isEnabled():
                self.go(1)
            elif i == 1:
                self.start_install()
            elif i == 3:
                self.launch_and_close()
        elif e.key() == Qt.Key.Key_Escape and self.stack.currentIndex() in (0, 1, 3, 4):
            self.close()
        else:
            super().keyPressEvent(e)


class UninstallWindow(GlassWindow):
    def __init__(self, covers, install_dir: Path, preview: bool = False):
        super().__init__("uninstall", covers, size=(760, 480))
        self.install_dir, self.preview = install_dir, preview
        self.worker = None
        w, lay = self.page((48, 20, 48, 36))
        lay.addStretch(1)
        lay.addWidget(self.label("remove 999 player?", "h2"))
        lay.addWidget(self.label(f"this removes the app at {install_dir}.", "sub", wrap=True))
        lay.addSpacing(8)
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 16, 22, 16)
        cl.setSpacing(12)
        self.o_wipe = SwitchRow("also wipe my likes, playlists, settings and saved lyrics", False, self.accent,
                                "%localappdata%\\999player, leave this off if you might come back")
        cl.addWidget(self.o_wipe)
        cl.addWidget(self.label("downloaded songs in music\\999 player are yours and stay where they are.", "hint", wrap=True))
        lay.addWidget(card)
        lay.addStretch(2)
        btns = QHBoxLayout()
        keep = self.button("keep it", "ghost")
        keep.clicked.connect(self.close)
        go = self.button("remove", "primary")
        go.clicked.connect(self.start)
        btns.addWidget(keep)
        btns.addStretch(1)
        btns.addWidget(go)
        lay.addLayout(btns)
        self.stack.addWidget(w)
        w, lay = self.page((48, 20, 48, 36))
        lay.addStretch(1)
        self.u_step = self.label("closing the vault…", "h2")
        lay.addWidget(self.u_step)
        lay.addStretch(1)
        self.stack.addWidget(w)
        w, lay = self.page((48, 20, 48, 36))
        lay.addStretch(2)
        lay.addWidget(self.label("removed.", "h1"))
        lay.addWidget(self.label("999 player is off this pc. its folder clears itself a few seconds after this window closes.", "sub", wrap=True))
        lay.addStretch(3)
        btns = QHBoxLayout()
        cl_ = self.button("close", "primary")
        cl_.clicked.connect(self.close)
        btns.addWidget(cl_)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.stack.addWidget(w)
        self._armed = False

    def start(self):
        self.go(1)
        self.worker = UninstallWorker(self.install_dir, self.o_wipe.isChecked(), self.preview)
        self.worker.step.connect(self.u_step.setText)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(lambda m: (self.u_step.setText("couldn't finish: " + m)))
        self.worker.start()

    def _done(self):
        self._armed = True
        self.go(2)

    def closeEvent(self, e):
        if self._armed and not self.preview:
            schedule_self_delete(self.install_dir)
        super().closeEvent(e)


def load_covers() -> list[tuple[str, QImage]]:
    out = []
    for name, fn in ERAS:
        img = QImage(str(COVERS_DIR / fn))
        if not img.isNull():
            out.append((name, img))
    return out


def _app() -> QApplication:
    QApplication.setApplicationName(APP_NAME)
    app = QApplication.instance() or QApplication(sys.argv)
    load_fonts()
    if ICON.exists():
        app.setWindowIcon(QIcon(str(ICON)))
    return app


def _dev_hooks(win: GlassWindow) -> None:
    if "--shot" not in sys.argv:
        return
    shot = sys.argv[sys.argv.index("--shot") + 1]
    if "--page" in sys.argv:
        win.stack.setCurrentIndex(int(sys.argv[sys.argv.index("--page") + 1]))

    def go():
        win.grab().save(shot)
        QApplication.quit()

    if "--go" in sys.argv:
        QTimer.singleShot(900, lambda: win.go(int(sys.argv[sys.argv.index("--go") + 1])))
        QTimer.singleShot(1060, go)
        return
    if "--auto" in sys.argv and isinstance(win, SetupWindow):
        win.path.setText(sys.argv[sys.argv.index("--target") + 1])
        win.o_launch.sw.setChecked(False)
        if SANDBOX:
            win.o_desktop.sw.setChecked(False)
            win.o_start.sw.setChecked(False)
        win.stack.setCurrentIndex(1)
        QTimer.singleShot(300, win.start_install)
        QTimer.singleShot(600, lambda: win.worker and (win.worker.done.connect(lambda: QTimer.singleShot(700, go)),
                                                       win.worker.failed.connect(lambda _m: QTimer.singleShot(700, go))))
        return
    QTimer.singleShot(900, go)


def run_install() -> int:
    app = _app()
    update_dir = Path(sys.argv[sys.argv.index("--update") + 1]) if "--update" in sys.argv and sys.argv.index("--update") + 1 < len(sys.argv) else None
    win = SetupWindow(load_covers(), payload_path(), update_dir)
    win.show()
    _dev_hooks(win)
    return app.exec()


def run_uninstall() -> int:
    app = _app()
    preview = "--uninstall-preview" in sys.argv
    if "--install-dir" in sys.argv:
        d = Path(sys.argv[sys.argv.index("--install-dir") + 1])
    elif getattr(sys, "frozen", False):
        d = Path(sys.executable).resolve().parent
    else:
        d = existing_install() or default_target()
    win = UninstallWindow(load_covers(), d, preview)
    win.show()
    _dev_hooks(win)
    return app.exec()


if __name__ == "__main__":
    if "--uninstall" in sys.argv or "--uninstall-preview" in sys.argv:
        sys.exit(run_uninstall())
    sys.exit(run_install())
