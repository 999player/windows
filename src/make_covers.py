from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Administrator\Downloads\albumcovers")
OUT = Path(__file__).resolve().parent / "ui" / "covers"
OUT.mkdir(parents=True, exist_ok=True)

MAP = [
    ("JUICED UP THE EP", "JUICED UP THE EP", "juiced-up-the-ep"),
    ("affliction", "Affliction", "affliction"),
    ("Heartbroken In Hollywood", "Heartbroken In Hollywood 999", "heartbroken-in-hollywood-999"),
    ("JuiceWRLD 9 9 9", "Juice WRLD 999", "juice-wrld-999"),
    ("BINGEDRINKINGMUSIC", "BINGEDRINKINGMUSIC", "bingedrinkingmusic"),
    ("NOTHING'S DIFFERENT", "NOTHING'S DIFFERENT </3", "nothings-different"),
    ("Goodbye & Good Riddance", "Goodbye & Good Riddance", "goodbye-good-riddance"),
    ("WRLD ON DRUGS", "WRLD On Drugs", "wrld-on-drugs"),
    ("Death Race For Love", "Death Race For Love", "death-race-for-love"),
    ("Outsiders", "Outsiders", "outsiders"),
    ("Posthumous", "Posthumous", "posthumous"),
]


def main() -> None:
    QGuiApplication(sys.argv)
    mapping: dict[str, str] = {}
    for needle, era, slug in MAP:
        folder = next((d for d in SRC.iterdir() if d.is_dir() and needle.lower() in d.name.lower()), None)
        files = [f for f in (folder.iterdir() if folder else []) if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
        if not files:
            print(f"  missing: {era}")
            continue
        img = QImage(str(files[0]))
        if img.isNull():
            print(f"  unreadable: {files[0]}")
            continue
        if max(img.width(), img.height()) > 800:
            img = img.scaled(800, 800, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        img = img.convertToFormat(QImage.Format.Format_RGB32)
        out = OUT / f"{slug}.jpg"
        img.save(str(out), "JPG", 90)
        mapping[era] = f"covers/{slug}.jpg"
        print(f"  ok: {era:30s} <- {files[0].name} ({img.width()}x{img.height()}, {out.stat().st_size // 1024} KB)")
    (OUT / "covers.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(mapping)} covers -> {OUT / 'covers.json'}")


if __name__ == "__main__":
    main()
