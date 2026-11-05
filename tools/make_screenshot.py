#!/usr/bin/env python3
"""Renders the REAL window offscreen and saves docs/screenshot.png.

No GitHub access needed: a stub transport replays recorded public GitHub release data and the
products' own docs/screenshot.png files (tools/screenshot_data). To show every state, a temporary
fake 'VST3 folder' holds bundles whose moduleinfo.json carries older versions; the real
installed-version detection reads them. Usage:
    QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 python3 tools/make_screenshot.py [out.png] [tab] [page]
"""
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from replay import ReplayTransport  # noqa: E402
from studio87_updater.gui import app as A  # noqa: E402
from studio87_updater.service import Service  # noqa: E402

STAGED = {"Hairball": "0.1.0", "Cat Crusher": "0.2.2", "Cat Spacer": "0.2.3", "Fat Cat": "0.2.1", "Whisker Scope": "0.3.0",
          "Meowximizer": "0.2.0", "Meowbass": "0.2.4", "PunchPaw": "0.1.0", "Furchild": "0.1.0"}


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshot.png"
    tab = sys.argv[2] if len(sys.argv) > 2 else "updates"
    page = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    home = Path(tempfile.mkdtemp())
    vst3 = home / "vst3"
    for name, ver in STAGED.items():
        res = vst3 / (name + ".vst3") / "Contents" / "Resources"
        res.mkdir(parents=True)
        (res / "moduleinfo.json").write_text(json.dumps({"Name": name, "Version": ver}))
    svc = Service(system="linux", env={"XDG_DATA_HOME": str(home / "d"), "XDG_CACHE_HOME": str(home / "c")}, home=home,
                  transport=ReplayTransport(), vst3_dirs=[vst3], flatpak_probe=lambda: ("absent", set()))
    app = QApplication.instance() or QApplication([])
    A.load_fonts()
    win = A.MainWindow(svc)
    win.apply(int(os.environ.get("SHOT_W", 1047)), int(os.environ.get("SHOT_H", 1150)), float(os.environ.get("SHOT_SCALE", 1.0)))
    win.show()
    win.root.start_open_check()
    t0 = time.time()
    while time.time() - t0 < 20:
        app.processEvents()
        if not win.root.checking and win.root.rows and win.root.pool.activeThreadCount() == 0:
            break
        time.sleep(0.03)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    win.root.tab = tab
    pass
    win.root.refresh_list()
    for _ in range(10):
        app.processEvents()
    out.parent.mkdir(parents=True, exist_ok=True)
    pm = win.grab()
    pm.save(str(out))
    print("saved", out, pm.width(), "x", pm.height(), "rows", len(win.root.rows), "updates", sum(1 for r in win.root.rows if r.status == "update"))
    win.close()


if __name__ == "__main__":
    main()
