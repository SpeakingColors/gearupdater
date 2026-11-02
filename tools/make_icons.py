#!/usr/bin/env python3
"""Writes the app icon (cat head on navy with an update arrow) as svg, png, ico and icns."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "studio87_updater" / "assets"
SVG = '''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512"><rect width="512" height="512" rx="104" fill="#14183a"/><g transform="translate(46 40) scale(5.7)"><path d="M8 6 L24 22 H40 L56 6 L60 36 Q60 58 32 60 Q4 58 4 36 Z" fill="#FF7BB1"/><path d="M12 14 L21 23 H14 Z M52 14 L43 23 H50 Z" fill="#FBBDD0"/><ellipse cx="22" cy="36" rx="4" ry="5" fill="#16171a"/><ellipse cx="42" cy="36" rx="4" ry="5" fill="#16171a"/><path d="M29 44 H35 L32 48 Z" fill="#16171a"/><path d="M32 48 Q28 53 24 50 M32 48 Q36 53 40 50" stroke="#16171a" stroke-width="2" fill="none"/><path d="M2 40 H14 M2 46 H14 M62 40 H50 M62 46 H50" stroke="#FBBDD0" stroke-width="1.6"/></g><circle cx="396" cy="396" r="84" fill="#02EBBA" stroke="#14183a" stroke-width="12"/><path d="M396 442 V352 M360 386 L396 350 L432 386" stroke="#04201a" stroke-width="22" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon.svg").write_text(SVG)
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    app = QGuiApplication.instance() or QGuiApplication([])
    img = QImage(512, 512, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    QSvgRenderer(QByteArray(SVG.encode())).render(p)
    p.end()
    img.save(str(OUT / "icon.png"))
    from PIL import Image
    im = Image.open(OUT / "icon.png").convert("RGBA")
    im.save(OUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    im.save(OUT / "icon.icns")
    print("icons written to", OUT)


if __name__ == "__main__":
    sys.exit(main())
