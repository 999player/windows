from __future__ import annotations

import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "dist" / "999player"
WORK = ROOT / "build" / "installer"
PAYLOAD = WORK / "payload.zip"
STUB_NAME = "999 player setup"
OUT = ROOT / "dist" / f"{STUB_NAME}.exe"


def zip_app() -> None:
    if not (APP_DIR / "999player.exe").exists():
        sys.exit("dist\\999player\\999player.exe missing — run build_exe.ps1 first")
    readme = ROOT / "README-for-friend.txt"
    if readme.exists():
        shutil.copy2(readme, APP_DIR / "README.txt")
    WORK.mkdir(parents=True, exist_ok=True)
    files = [p for p in APP_DIR.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    print(f"zipping {len(files)} files, {total / 1e6:.0f} MB …", flush=True)
    t0 = time.time()
    with zipfile.ZipFile(PAYLOAD, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in files:
            zf.write(p, p.relative_to(APP_DIR).as_posix())
    print(f"payload.zip {PAYLOAD.stat().st_size / 1e6:.0f} MB in {time.time() - t0:.0f}s", flush=True)


def build_stub() -> Path:
    print("pyinstaller …", flush=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--name", STUB_NAME,
           "--distpath", str(WORK / "dist"), "--workpath", str(WORK / "work"), "--specpath", str(WORK),
           "--icon", str(ROOT / "assets" / "icon.ico"),
           "--version-file", str(ROOT / "assets" / "version_info_setup.txt"),
           "--add-data", f"{ROOT / 'ui' / 'covers'};ui/covers",
           "--add-data", f"{ROOT / 'ui' / 'fonts'};ui/fonts",
           "--add-data", f"{ROOT / 'assets' / 'icon.png'};assets",
           "--exclude-module", "tkinter", "--exclude-module", "unittest", "--exclude-module", "pydoc"]
    for m in ("QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel", "QtNetwork", "QtQml", "QtQuick", "QtMultimedia",
              "QtOpenGL", "QtOpenGLWidgets", "QtPdf", "QtSvg", "QtPrintSupport", "QtDBus", "QtTest", "QtXml", "QtSql",
              "QtCharts", "QtDataVisualization", "Qt3DCore", "Qt3DRender", "QtBluetooth", "QtNfc", "QtSerialPort",
              "QtSensors", "QtDesigner", "QtRemoteObjects", "QtScxml", "QtStateMachine", "QtPositioning", "QtLocation",
              "QtWebSockets", "QtTextToSpeech", "QtSpatialAudio", "QtHttpServer", "QtGraphs", "QtQuick3D"):
        cmd += ["--exclude-module", f"PySide6.{m}"]
    cmd.append(str(ROOT / "installer.py"))
    subprocess.run(cmd, check=True, cwd=ROOT)
    stub = WORK / "dist" / f"{STUB_NAME}.exe"
    print(f"stub {stub.stat().st_size / 1e6:.0f} MB", flush=True)
    return stub


def glue(stub: Path) -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out_path = OUT
    try:
        out = open(out_path, "wb")
    except PermissionError:
        out_path = OUT.with_name(OUT.stem + " (new)" + OUT.suffix)
        out = open(out_path, "wb")
    with out, open(stub, "rb") as a, open(PAYLOAD, "rb") as b:
        shutil.copyfileobj(a, out, 1 << 22)
        shutil.copyfileobj(b, out, 1 << 22)
    with zipfile.ZipFile(out_path) as zf:
        n = len(zf.infolist())
    print(f"OK -> {out_path}  ({out_path.stat().st_size / 1e6:.0f} MB, {n} files inside)", flush=True)
    return out_path


def main() -> None:
    if "--skip-zip" not in sys.argv or not PAYLOAD.exists():
        zip_app()
    stub = build_stub()
    built = glue(stub)
    if "--copy-to" in sys.argv:
        dest = Path(sys.argv[sys.argv.index("--copy-to") + 1]) / OUT.name
        shutil.copy2(built, dest)
        print(f"copied -> {dest}")


if __name__ == "__main__":
    main()
