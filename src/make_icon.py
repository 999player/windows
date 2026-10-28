from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPolygonF, QRadialGradient)

OUT = Path(__file__).resolve().parent / "assets"
OUT.mkdir(exist_ok=True)


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = size * 0.23
    rect = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    tile = QPainterPath()
    tile.addRoundedRect(rect, r, r)

    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0.0, QColor("#6d7cff"))
    g.setColorAt(0.5, QColor("#9b6bff"))
    g.setColorAt(1.0, QColor("#ff5fb0"))
    p.fillPath(tile, QBrush(g))

    glow = QRadialGradient(QPointF(size * 0.3, size * 0.2), size * 0.7)
    glow.setColorAt(0.0, QColor(255, 255, 255, 110))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(tile, QBrush(glow))

    p.save()
    p.setClipPath(tile)
    band = QLinearGradient(QPointF(0, rect.top()), QPointF(0, rect.center().y()))
    band.setColorAt(0.0, QColor(255, 255, 255, 70))
    band.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.5), QBrush(band))
    p.restore()

    p.setPen(QColor(255, 255, 255, 60))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(tile)

    cx, cy = size * 0.54, size * 0.5
    w, h = size * 0.30, size * 0.36
    tri = QPolygonF([QPointF(cx - w * 0.45, cy - h / 2), QPointF(cx + w * 0.65, cy), QPointF(cx - w * 0.45, cy + h / 2)])
    path = QPainterPath()
    path.addPolygon(tri)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.translate(0, size * 0.015)
    p.fillPath(path, QColor(40, 20, 80, 90))
    p.translate(0, -size * 0.015)
    p.fillPath(path, QColor("#ffffff"))
    p.end()
    return img


def main() -> None:
    QGuiApplication(sys.argv)
    big = draw(512)
    big.save(str(OUT / "icon.png"))
    ok = draw(256).save(str(OUT / "icon.ico"), "ICO")
    print("icon.png written; icon.ico", "written" if ok else "FAILED")


if __name__ == "__main__":
    main()
