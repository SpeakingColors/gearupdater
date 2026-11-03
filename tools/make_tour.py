#!/usr/bin/env python3
"""Builds the manual's interface tour FROM THE REAL WINDOW: renders it offscreen, reads every control's position,
label and hover-bubble text from the widget tree, draws numbered badges (controls, pink) and lettered badges
(displays, teal), and writes docs/tour/*.png and docs/tour/tour.json. Run: QT_QPA_PLATFORM=offscreen python3 tools/make_tour.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from replay import ReplayTransport  # noqa: E402
from studio87_updater.gui import app as A  # noqa: E402
from studio87_updater.service import Service  # noqa: E402
from make_screenshot import STAGED  # noqa: E402

OUT = ROOT / "docs" / "tour"
SCALE = 1.5


def pump(app, n=15):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    import json as _j
    home = Path(tempfile.mkdtemp())
    vst3 = home / "vst3"
    for name, ver in STAGED.items():
        res = vst3 / (name + ".vst3") / "Contents" / "Resources"
        res.mkdir(parents=True)
        (res / "moduleinfo.json").write_text(_j.dumps({"Version": ver}))
    svc = Service(system="linux", env={"XDG_DATA_HOME": str(home / "d"), "XDG_CACHE_HOME": str(home / "c")}, home=home,
                  transport=ReplayTransport(), vst3_dirs=[vst3], flatpak_probe=lambda: ("absent", set()))
    app = QApplication.instance() or QApplication([])
    A.load_fonts()
    win = A.MainWindow(svc)
    win.resize(int(1000 * SCALE), int(676 * SCALE))
    win.show()
    root = win.root
    root.start_open_check()
    t0 = time.time()
    while time.time() - t0 < 20 and not (not root.checking and root.rows and root.pool.activeThreadCount() == 0):
        app.processEvents()
        time.sleep(0.03)
    pump(app)
    root.tab, root.page = "all", 0
    root.refresh_list()
    pump(app)
    shot = OUT / "window.png"
    win.grab().save(str(shot))

    def box(w):
        p = w.mapTo(root, QPoint(0, 0))
        return [p.x(), p.y(), w.width(), w.height()]

    row = next(rw for rw in root.allrows if rw.row is not None and rw.row.status == "update")
    controls = []

    def add(name, w, tip=None):
        t = tip if tip is not None else w.property("tip")
        t = t() if callable(t) else t
        controls.append({"name": name, "box": box(w), "tip": t or ""})

    add("Check for updates", root.b_check)
    add("Settings", root.b_set)
    add("About", root.b_about)
    for k, label in (("updates", "Updates tab"), ("all", "All tab"), ("fx", "VST and FX tab"), ("synth", "Synths tab"), ("controller", "Controllers tab"), ("apps", "Apps and logue tab"),
                     ("installed", "Installed tab"), ("notinstalled", "Not installed tab")):
        add(label, root.tabs[k])
    add("Search box", root.search)
    add("Scrolling / pages switch", root.b_view)
    add("Update / Install selected", root.b_sel)
    add("Update all / Install all", root.b_all)
    add("Row tick box", row.check)
    add("Update / Install button", row.b_main)
    add("Changelog button", row.b_log)
    add("GitHub button", row.b_git)
    add("Smaller window", root.b_zoom_out)
    add("Back to 100 percent", root.b_zoom_100)
    add("Larger window", root.b_zoom_in)
    rb = box(row)
    displays = [
        {"name": "Screenshot and cat icon", "box": [rb[0] + 34, rb[1] + 4, 156, 76],
         "text": "The product's own docs/screenshot.png, small, with the cat icon on it, so you recognise it at a glance. Fetched during the check and saved on disk."},
        {"name": "Name, kind and build type", "box": [rb[0] + 204, rb[1] + 2, 300, 22],
         "text": "Product name, its kind (VST3 plugin, standalone app, hardware controller, logue unit) and TEST BUILD when the release is marked as one."},
        {"name": "Installed and latest version", "box": [rb[0] + 204, rb[1] + 24, 300, 15],
         "text": "What is really installed (read from the plugin's own metadata or from what this updater installed) and the newest release on GitHub. 'unknown' and 'not installed' are shown honestly."},
        {"name": "Status", "box": [rb[0] + 204, rb[1] + 39, 300, 16],
         "text": "Update available, Up to date, Not installed, Installed version unknown, No release yet, Could not check, or View on GitHub. While updating it turns into Downloading, Verifying SHA256, Installing."},
        {"name": "Changelog line", "box": [rb[0] + 204, rb[1] + 55, 576, 15],
         "text": "The first line of the release notes. The Changelog button shows the notes of every version newer than yours."},
        {"name": "Date, size and install route", "box": [rb[0] + 204, rb[1] + 69, 576, 13],
         "text": "Release date, download size and how this product gets installed on this system. 'saved list' means the answer came from disk (offline or rate limited)."},
        {"name": "Status line", "box": [44, 550, 380, 36],
         "text": "When the last check happened and how many updates were found. Offline and rate-limit messages appear here and in red on the right."},
        {"name": "Scrolling list", "box": [root.scroll.x() + root.scroll.width() - 18, root.scroll.y(), 18, 60],
         "text": "One long list of the tab you are on. Use the mouse wheel or the thin scrollbar. The switch button next to the search box shows pages of five instead (off by default)."},
        {"name": "Size read-out", "box": [444, 598, 200, 42], "text": "Window size in pixels and, on the 100% button, the zoom relative to the default size."},
        {"name": "Wood sides", "box": [0, 0, 34, 676], "text": "Double click on either wood side to go back to the default size (100%)."},
    ]
    img = Image.open(shot).convert("RGBA")
    s = img.width / 1000.0
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(str(A.ASSETS / "BarlowCondensed-Bold.ttf"), int(17 * s / 1.0 * 0.9))

    def badge(x, y, label, fill):
        r = int(11 * s)
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill, outline=(0, 0, 0, 255), width=2)
        d.text((x, y), label, font=f, fill=(0, 0, 0, 255), anchor="mm")

    for i, c in enumerate(controls, 1):
        x, y, w, h = c["box"]
        bx, by = (x + w + 6, y + 2) if w < 30 else ((x + w / 2, y - 3) if (y > 540 and w < 60) else (x + 6, y + 4))
        badge(int(bx * s), int(by * s), str(i), (255, 123, 177, 255))
        c["n"] = i
    anchors = [(rb[0] + 182, rb[1] + 10), (rb[0] + 700, rb[1] + 13), (rb[0] + 700, rb[1] + 31), (rb[0] + 700, rb[1] + 47),
               (rb[0] + 760, rb[1] + 62), (rb[0] + 760, rb[1] + 76), (392, 556), (root.scroll.x() + root.scroll.width() - 9, root.scroll.y() + 12), (610, 620), (17, 330)]
    for i, (dsp, (ax, ay)) in enumerate(zip(displays, anchors)):
        L = chr(ord("A") + i)
        badge(int(ax * s), int(ay * s), L, (2, 235, 186, 255))
        dsp["letter"] = L
    img.convert("RGB").save(OUT / "window-badges.png")
    # crop of one row for the 'row' page
    rc = [int(rb[0] * s) - 4, int(rb[1] * s) - 4, int((rb[0] + 912) * s) + 4, int((rb[1] + 84) * s) + 4]
    Image.open(shot).convert("RGB").crop(rc).save(OUT / "row.png")
    # overlays
    hb = next(r for r in root.rows if r.product.name == "Hairball")
    for key, fn in (("changelog", lambda: root.show_changelog(hb)), ("settings", root.show_settings), ("about", root.show_about),
                    ("confirm", lambda: root.show_confirm(root.rows[:4]))):
        fn()
        pump(app, 8)
        win.grab().save(str(OUT / ("%s.png" % key)))
        root.close_overlay()
        pump(app, 5)
    (OUT / "tour.json").write_text(json.dumps({"controls": controls, "displays": displays, "design": [1000, 676]}, indent=1))
    print("tour written:", len(controls), "controls,", len(displays), "displays")
    win.close()


def DWc(root):
    return root.width()


if __name__ == "__main__":
    main()
