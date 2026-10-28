from __future__ import annotations

import colorsys
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


def accent_from_bytes(data: bytes) -> dict:
    img = QImage()
    img.loadFromData(data)
    if img.isNull():
        raise ValueError("unreadable image")
    img = img.convertToFormat(QImage.Format.Format_RGB32).scaled(40, 40, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    sx = sy = wsum = 0.0
    ssum = vsum = 0.0
    grays = []
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            h, s, v = colorsys.rgb_to_hsv(c.redF(), c.greenF(), c.blueF())
            if v < 0.12:
                continue
            grays.append(v)
            if s < 0.18:
                continue
            w = (s ** 1.5) * v
            a = h * 2 * math.pi
            sx += math.cos(a) * w
            sy += math.sin(a) * w
            ssum += s * w
            vsum += v * w
            wsum += w
    if wsum < 1.0:
        base = (0.68, 0.18, 0.72)
    else:
        h = (math.atan2(sy, sx) / (2 * math.pi)) % 1.0
        s = ssum / wsum
        v = vsum / wsum
        base = (h, min(0.78, max(0.5, s * 1.05)), min(0.7, max(0.5, v * 0.92)))
    h, s, v = base
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    r2, g2, b2 = colorsys.hsv_to_rgb((h + 0.08) % 1.0, max(0.4, s * 0.85), min(0.8, v * 1.1))
    rgb = [round(r * 255), round(g * 255), round(b * 255)]
    rgb2 = [round(r2 * 255), round(g2 * 255), round(b2 * 255)]
    return {"rgb": rgb, "rgb2": rgb2, "hex": "#%02x%02x%02x" % tuple(rgb)}
