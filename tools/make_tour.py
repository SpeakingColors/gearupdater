#!/usr/bin/env python3
"""Builds the manual's interface tour FROM THE REAL WINDOW (v0.1.2 and later).

It renders the app offscreen with recorded GitHub data, reads every control's position, label and hover-bubble text
from the widget tree (nothing about a control is typed here), draws numbered pink badges on controls and lettered teal
badges on displays, and writes docs/tour/*.png plus docs/tour/tour.json. Explanations of displays and the flow text live
in docs/tour/extra.json; the 'Under the hood' facts are computed here from the code's own constants.

Scenes: main (full window), working (Stop after this one), bars (offline bar, update-the-updater bar), and one card per
pop-up: changelog, confirm, results, settings, signin, about, firstrun.
Run: QT_QPA_PLATFORM=offscreen python3 tools/make_tour.py
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

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QTextBrowser  # noqa: E402

from replay import ReplayTransport  # noqa: E402
from make_screenshot import STAGED  # noqa: E402
from studio87_updater import backup as BK  # noqa: E402
from studio87_updater import cache as CA  # noqa: E402
from studio87_updater import paths as P  # noqa: E402
from studio87_updater import auth as AU  # noqa: E402
from studio87_updater import mode as MODE  # noqa: E402
from studio87_updater import github as GH  # noqa: E402
from studio87_updater.batch import ItemResult  # noqa: E402
from studio87_updater.gui import app as A  # noqa: E402
from studio87_updater.gui.widgets import Btn  # noqa: E402
from studio87_updater.releases import Release  # noqa: E402
from studio87_updater.service import DEFAULT_SETTINGS, Service  # noqa: E402

OUT = ROOT / "docs" / "tour"
EXTRA = json.loads((OUT / "extra.json").read_text(encoding="utf-8"))
SCALE = 1.5
PINK, TEAL = (255, 123, 177, 255), (2, 235, 186, 255)


def pump(app, n=15):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


def tip_of(w):
    t = w.property("tip")
    t = t() if callable(t) else t
    return t or ""


def draw_badge(d, f, s, x, y, label, fill):
    r = int(11 * s)
    x, y = int(x * s), int(y * s)
    d.ellipse([x - r, y - r, x + r, y + r], fill=fill, outline=(0, 0, 0, 255), width=2)
    d.text((x, y), label, font=f, fill=(0, 0, 0, 255), anchor="mm")


def font_for(s):
    return ImageFont.truetype(str(A.ASSETS / "BarlowCondensed-Bold.ttf"), int(15 * s))


def build_service():
    home = Path(tempfile.mkdtemp())
    vst3 = home / "vst3"
    for name, ver in STAGED.items():
        res = vst3 / (name + ".vst3") / "Contents" / "Resources"
        res.mkdir(parents=True)
        (res / "moduleinfo.json").write_text(json.dumps({"Name": name, "Version": ver}))
    svc = Service(system="linux", env={"XDG_DATA_HOME": str(home / "d"), "XDG_CACHE_HOME": str(home / "c")}, home=home,
                  transport=ReplayTransport(), vst3_dirs=[vst3], flatpak_probe=lambda: ("absent", set()))
    # one kept previous version, so the Roll back button shows on a row (an example: the same way a real update leaves one)
    old = home / "old-bundle"
    (old / "Contents").mkdir(parents=True)
    (old / "Contents" / "x.txt").write_text("example")
    svc.backups.put("catcrusher-vst", old, STAGED["Cat Crusher"], "v" + STAGED["Cat Crusher"], "tarball", vst3 / "Cat Crusher.vst3")
    return svc


def row_boxes(root, row):
    """Boxes (design pixels, in the root's coordinates) of a row's controls."""
    def box(w):
        p = w.mapTo(root, QPoint(0, 0))
        return [p.x(), p.y(), w.width(), w.height()]
    return box


def meta_for(scene, name):
    """Range and default for a control, from extra.json (the explanations) with code-derived values filled in."""
    return EXTRA["controls"].get(scene + "|" + name) or EXTRA["controls"].get(name) or {"range": "Click", "default": "-"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    svc = build_service()
    app = QApplication.instance() or QApplication([])
    A.load_fonts()
    win = A.MainWindow(svc)
    win.apply(1047, 1150, SCALE)
    win.show()
    root = win.root
    root.open_url = lambda u: None
    root.start_open_check()
    t0 = time.time()
    while time.time() - t0 < 20 and not (not root.checking and root.rows and root.pool.activeThreadCount() == 0):
        app.processEvents()
        time.sleep(0.03)
    pump(app)
    root.tab = "updates"
    root.refresh_list()
    pump(app)
    S = SCALE
    f = font_for(S)
    scenes = {}

    def grab():
        pump(app, 6)
        shot = OUT / "_grab.png"
        win.grab().save(str(shot))
        return Image.open(shot).convert("RGBA")

    def box(w):
        p = w.mapTo(root, QPoint(0, 0))
        return [p.x(), p.y(), w.width(), w.height()]

    # ---------------- main window ----------------
    img = grab()
    img.convert("RGB").save(OUT / "window.png")
    row = next(rw for rw in root.allrows if rw.row is not None and rw.row.product.repo == "catcrusher-vst")
    assert row.b_roll.isVisible(), "the staged Roll back button is not showing"
    controls = []

    def add(name, w):
        controls.append({"name": name, "box": box(w), "tip": tip_of(w)})
    add("Check for updates", root.b_check)
    add("Settings", root.b_set)
    add("About", root.b_about)
    for k, label in (("updates", "Updates tab"), ("all", "All tab"), ("fx", "VST and FX tab"), ("synth", "Synths tab"), ("controller", "Controllers tab"),
                     ("apps", "Apps and logue tab"), ("installed", "Installed tab"), ("notinstalled", "Not installed tab")):
        add(label, root.tabs[k])
    add("Search box", root.search)
    add("Update / Install selected", root.b_sel)
    add("Update all / Install all", root.b_all)
    add("Row tick box", row.check)
    add("Update / Install button", row.b_main)
    add("Changelog button", row.b_log)
    add("GitHub button", row.b_git)
    add("Roll back button", row.b_roll)
    add("Smaller window", root.b_zoom_out)
    add("Fit to screen", root.b_zoom_fit)
    add("One to one", root.b_zoom_100)
    add("Larger window", root.b_zoom_in)
    rb = box(row)
    X, H = rb[0] + 366, root.H
    disp_defs = EXTRA["displays"]["main"]
    boxes = {
        "Screenshot": ([rb[0] + 36, rb[1] + 4, 310, 162], (rb[0] + 330, rb[1] + 20)),
        "Name, kind and build type": ([X, rb[1] + 6, 400, 28], (rb[0] + 352, rb[1] + 20)),
        "Installed and latest version": ([X, rb[1] + 36, 500, 20], (rb[0] + 352, rb[1] + 46)),
        "Status": ([X, rb[1] + 60, 500, 22], (rb[0] + 352, rb[1] + 71)),
        "Description": ([X, rb[1] + 86, 500, 44], (rb[0] + 352, rb[1] + 108)),
        "Date, size and install route": ([X, rb[1] + 136, 500, 18], (rb[0] + 352, rb[1] + 145)),
        "Status line": ([44, H - 92, 380, 30], (400, H - 78)),
        "Scrolling list": ([root.scroll.x() + root.scroll.width() - 18, root.scroll.y(), 18, 60], (root.scroll.x() + root.scroll.width() - 9, root.scroll.y() + 12)),
        "Size read-out": ([root.W // 2 - 60, H - 44, 200, 44], (root.W // 2 + 130, H - 22)),
        "Wood sides": ([0, 0, 34, H], (17, 330)),
    }
    displays = []
    for i, d in enumerate(disp_defs):
        b, anchor = boxes[d["name"]]
        displays.append({"name": d["name"], "box": b, "text": d["text"], "letter": chr(65 + i), "anchor": list(anchor)})
    im = img.copy()
    dr = ImageDraw.Draw(im)
    for i, c in enumerate(controls, 1):
        x, y, w, h = c["box"]
        bx, by = (x + w + 6, y + 2) if w < 30 else ((x + w / 2, y - 3) if (y > 540 and w < 60) else (x + 6, y + 4))
        if c["name"] == "Roll back button":
            bx, by = x - 4, y + 14
        draw_badge(dr, f, S, bx, by, str(i), PINK)
        c["n"] = i
    for d in displays:
        draw_badge(dr, f, S, d["anchor"][0], d["anchor"][1], d["letter"], TEAL)
    im.convert("RGB").save(OUT / "window-badges.png")
    scenes["main"] = {"image": "window-badges.png", "controls": controls, "displays": displays}
    # one row crop with its own badges (the row page)
    rcrop = [int(rb[0] * S) - 4, int(rb[1] * S) - 4, int((rb[0] + row.W) * S) + 4, int((rb[1] + 172) * S) + 4]
    Image.open(OUT / "window.png").convert("RGB").crop(rcrop).save(OUT / "row.png")

    # ---------------- working (Stop after this one) ----------------
    root.installing = True
    root.b_stop.show()
    row.set_busy("Downloading 42%", 0.42)
    img = grab()
    c = [int(CHEEK_X * S) for CHEEK_X in (34,)][0]
    crop = (c, int(90 * S), int((root.W - 34) * S), int((rb[1] + 180) * S))
    sub = img.crop(crop)
    d2 = ImageDraw.Draw(sub)
    ctr = []

    def sub_add(name, w, label, off=(6, 4)):
        p = box(w)
        ctr.append({"name": name, "box": p, "tip": tip_of(w), "n": len(ctr) + 1})
        draw_badge(d2, f, S, p[0] + off[0] - 34, p[1] + off[1] - 90, str(len(ctr)), PINK)
    sub_add("Stop after this one", root.b_stop, "")
    sub_add("Update all / Install all (waiting)", root.b_all, "")
    sub_add("Row progress (status area of the row)", row, "", (358, 71))
    ctr[-1]["tip"] = EXTRA["notes"]["row_progress"]
    sub.convert("RGB").save(OUT / "working.png")
    scenes["working"] = {"image": "working.png", "controls": ctr, "displays": []}
    root.installing = False
    root.b_stop.hide()
    row.busy = None
    row.refresh_buttons()

    # ---------------- bars: update the updater + offline ----------------
    root.self_rel = Release(tag="v0.1.3", name="Studio 87 Gear Updater v0.1.3 (example)", body="", published="2026-12-01T00:00:00Z", prerelease=True, html_url="")
    root.offline_line = "Offline, showing saved list from 2026-11-15 14:05"
    root.relayout(root.W, root.H)
    root.refresh_list()
    img = grab()
    crop = (int(34 * S), 0, int((root.W - 34) * S), int((root.list_y() + 190) * S))
    sub = img.crop(crop)
    d2 = ImageDraw.Draw(sub)
    ctr = []
    p = box(root.b_self)
    ctr.append({"name": "Update the updater", "box": p, "tip": tip_of(root.b_self), "n": 1})
    draw_badge(d2, f, S, p[0] + 6 - 34, p[1] + 4, "1", PINK)
    p = box(root.b_check)
    ctr.append({"name": "Check for updates (leaves offline mode)", "box": p, "tip": tip_of(root.b_check), "n": 2})
    draw_badge(d2, f, S, p[0] + 6 - 34, p[1] + 4, "2", PINK)
    by = 140 - 8
    dsp = [{"name": "Update the updater first bar", "letter": "A", "text": EXTRA["notes"]["bar_self"], "box": [44, by, 900, 28], "anchor": [26, by + 14]},
           {"name": "Offline bar", "letter": "B", "text": EXTRA["notes"]["bar_offline"], "box": [44, by + 34, 900, 28], "anchor": [26, by + 34 + 14]}]
    for dd in dsp:
        draw_badge(d2, f, S, 12, dd["anchor"][1], dd["letter"], TEAL)
    sub.convert("RGB").save(OUT / "bars.png")
    scenes["bars"] = {"image": "bars.png", "controls": ctr, "displays": dsp}
    root.self_rel = None
    root.offline_line = ""
    root.relayout(root.W, root.H)
    root.refresh_list()

    # ---------------- pop-up cards ----------------
    def card_scene(key, opener, dkeys=()):
        opener()
        pump(app, 10)
        ov = root.overlay
        img = grab()
        cx, cy = 34 + ov.card.x(), ov.card.y()
        crop = (int(cx * S) - 6, int(cy * S) - 6, int((cx + ov.card.width()) * S) + 6, int((cy + ov.card.height()) * S) + 6)
        sub = img.crop(crop)
        d3 = ImageDraw.Draw(sub)
        btns = sorted([b for b in ov.holder.findChildren(Btn) if b.isVisible() and b.text()], key=lambda b: (b.y() // 20, b.x()))
        ctr = []
        for b in btns:
            name = b.text()
            if b.text().startswith("Clear ("):
                name = "Clear (size)"
            if b.text().startswith("Retry failed"):
                name = "Retry failed"
            lab = [t for (t, lx, ly) in ov._labels if abs(ly - 4 - b.y()) <= 8 and lx < b.x()]
            if lab:
                name = "%s: %s" % (lab[0], name)
            if name.startswith("Hover bubbles: "):
                name = "Hover bubbles: On or Off"
            if name.startswith("GitHub account: "):
                name = "GitHub account: Sign in with GitHub / Sign out"
            ctr.append({"name": name, "box": [b.x(), b.y(), b.width(), b.height()], "tip": tip_of(b), "n": len(ctr) + 1, "checked": b.isChecked()})
            draw_badge(d3, f, S, b.x() + 5 + 6 / S, b.y() + 4 + 6 / S, str(len(ctr)), PINK)
        dsp = []
        for spec in EXTRA["displays"].get(key, []):
            kind = spec["find"]
            if kind == "browser":
                tb = ov.holder.findChildren(QTextBrowser)[0]
                bx = [tb.x(), tb.y(), tb.width(), tb.height()]
            elif kind == "sub":
                bx = [24, 50, ov.w - 48, 24]
            elif kind == "lines":
                bx = [24, 84, ov.w - 48, 100]
            elif kind.startswith("info"):
                n = int(kind.split(":")[1])
                t, x, y, w = ov._infos[n]
                bx = [x, y, w, 36]
            elif kind == "note":
                bx = [28, getattr(ov, "note_y", 330), ov.w - 56, 80]
            else:
                bx = [24, 14, ov.w - 48, 36]
            dsp.append({"name": spec["name"], "letter": chr(65 + len(dsp)), "text": spec["text"], "box": bx})
            ax = bx[0] + bx[2] + 12 if kind.startswith("info") or kind == "note" else 12
            draw_badge(d3, f, S, min(ax, ov.w - 12), bx[1] + 12, dsp[-1]["letter"], TEAL)
        sub.convert("RGB").save(OUT / (key + ".png"))
        scenes[key] = {"image": key + ".png", "controls": ctr, "displays": dsp}
        root.close_overlay()
        pump(app, 5)

    hb = next(r for r in root.rows if r.product.name == "Hairball")
    card_scene("changelog", lambda: root.show_changelog(hb))
    card_scene("confirm", lambda: root.show_confirm([r for r in root.rows if r.status == "update"][:3]))
    root.last_results = [ItemResult("catcrusher-vst", "Cat Crusher", True, "Installed Cat Crusher 0.2.4 (tarball). Checksums verified. The version you had is kept for Roll back.", "0.2.4"),
                         ItemResult("catspacer", "Cat Spacer", False, "Refused: the download failed (HTTP 502). The part that was downloaded is kept."),
                         ItemResult("hairball", "Hairball", False, "Skipped (stopped).", cancelled=True)]
    card_scene("results", root.show_results)
    card_scene("settings", root.show_settings)
    # sign in: a stub GitHub answer, so nothing leaves this computer
    au = svc.auth
    au.post = lambda url, data, **kw: ({"device_code": "x", "user_code": "WDJB-MJHT", "verification_uri": "https://github.com/login/device", "interval": 5, "expires_in": 900}
                                       if "device/code" in url else {"error": "authorization_pending"})
    au.sleep = lambda s_: time.sleep(0.05)

    def signin():
        root.start_signin()
        t = time.time()
        while time.time() - t < 3 and not (root.overlay is not None and root.overlay.lines and root.overlay.lines[0].startswith("Open ")):
            app.processEvents()
            time.sleep(0.02)
    card_scene("signin", signin)
    root.signin_cancel = True
    card_scene("about", root.show_about)
    svc.settings.set("mode_seen", False)
    card_scene("firstrun", root.show_first_run)
    for k, sc in scenes.items():
        for c in sc["controls"]:
            m = meta_for(k, c["name"])
            c["range"], c["default"] = m["range"], m["default"]
    # settings and sign in values that come from the code itself
    st = scenes["settings"]
    for c in st["controls"]:
        if c["name"].startswith("Look: "):
            c["range"] = "One of three looks"
            c["default"] = "yes" if c["name"].endswith(A.LOOKS[DEFAULT_SETTINGS["theme"]]["label"]) else "no"
        if c["name"].startswith("Clear (size)"):
            cap = CA.DEFAULT_CAP if c["name"].startswith("Saved list") else BK.DEFAULT_CAP
            c["range"] = "Click; capped at %d MB" % (cap // 1048576)
    # ---------------- under the hood (computed from the code) ----------------
    hood = build_hood()
    (OUT / "tour.json").write_text(json.dumps({"scenes": scenes, "hood": hood, "design": [1047, 1150], "version": __import__("studio87_updater").__version__}, indent=1))
    (OUT / "key.txt").write_text("tour v2 built from the real window by tools/make_tour.py\n")
    os.remove(OUT / "_grab.png")
    print("tour written:", {k: (len(v["controls"]), len(v["displays"])) for k, v in scenes.items()})
    win.close()


def build_hood():
    home = Path("~")
    paths = {}
    for sysname, env in (("linux", {}), ("windows", {"APPDATA": "%APPDATA%", "LOCALAPPDATA": "%LOCALAPPDATA%"}), ("macos", {})):
        paths[sysname] = (str(P.data_dir(sysname, env, home)).replace("\\", "/") if sysname != "windows" else r"%APPDATA%\Studio 87\Gear Updater",
                          str(P.cache_dir(sysname, env, home)).replace("\\", "/") if sysname != "windows" else r"%LOCALAPPDATA%\Studio 87\Gear Updater")
    mb = lambda n: "%d MB" % (n // 1048576)
    return {
        "paths": paths,
        "caps": {"saved_list": mb(CA.DEFAULT_CAP), "backups": mb(BK.DEFAULT_CAP), "zips": "%d GB" % (CA.ZIP_CAP // 2 ** 30), "zip_days": CA.ZIP_MAX_AGE // 86400},
        "downloads": {"retries": 4, "pauses": [GH_PAUSE * 2 ** i for i, GH_PAUSE in enumerate([1.5] * 4)], "timeout": GH.UrlLibTransport().timeout},
        "token": {"service": AU.SERVICE, "account": AU.ACCOUNT, "kinds": AU.KIND_TEXT},
        "status_lines": {"signed_in": ["Signed in, token stored in: %s" % v for v in AU.KIND_TEXT.values()],
                         "expired": "Your GitHub sign in expired. Please sign in again (the list works without it).",
                         "out": "Not signed in (optional). A new sign in would be kept in: <where it would go>"},
        "modes": {"labels": MODE.MODE_LABEL, "default": {s: MODE.default_mode(s) for s in ("windows", "macos", "linux")}},
        "defaults": {k: v for k, v in DEFAULT_SETTINGS.items() if k in ("theme", "bubbles", "linux_target", "token_storage")},
    }


if __name__ == "__main__":
    main()
