"""Drives the real Qt window offscreen with a stub GitHub. Skipped when PySide6 is not installed."""
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:      # the pure-core tests still run
    HAVE_QT = False

from helpers import make_release_zip, make_vst3_tar  # noqa: E402


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class GuiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, files=None, staged=None):
        from replay import ReplayTransport
        from studio87_updater.gui import app as A
        from studio87_updater.service import Service
        home = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, home, True)
        vst3 = home / ".vst3"
        for name, ver in (staged or {}).items():
            r = vst3 / (name + ".vst3") / "Contents" / "Resources"
            r.mkdir(parents=True)
            (r / "moduleinfo.json").write_text(json.dumps({"Version": ver}))
        self.transport = ReplayTransport(files)
        svc = Service(system="linux", env={"XDG_DATA_HOME": str(home / "d"), "XDG_CACHE_HOME": str(home / "c")}, home=home,
                      transport=self.transport, flatpak_probe=lambda: ("absent", set()))
        A.load_fonts()
        win = A.MainWindow(svc)
        self.addCleanup(win.close)
        win.show()
        self.home, self.svc, self.win, self.A = home, svc, win, A
        return win

    def pump(self, cond, secs=15):
        t0 = time.time()
        while time.time() - t0 < secs:
            self.app.processEvents()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def open_and_check(self):
        root = self.win.root
        root.start_open_check()
        self.assertTrue(self.pump(lambda: not root.checking and root.rows and root.pool.activeThreadCount() == 0))
        return root

    def test_open_checks_once_and_lists_updates(self):
        self.make(staged={"Hairball": "0.1.0", "Cat Crusher": "0.2.4"})
        root = self.open_and_check()
        ups = [r.product.name for r in root.rows if r.status == "update"]
        self.assertEqual(ups, ["Hairball"])
        api = [u for u in self.transport.transport_log] if hasattr(self.transport, "transport_log") else self.transport.log
        self.assertEqual(len([u for u in api if "/releases?per_page" in u]), len([p for p in self.svc.products if p.checks_releases]),
                         "exactly one request per product, no polling")
        before = len(self.transport.log)
        for _ in range(30):
            self.app.processEvents()
            time.sleep(0.02)
        self.assertEqual(len(self.transport.log), before, "no background requests after the check")

    def test_no_timers_other_than_hover_bubble(self):
        self.make()
        from PySide6.QtCore import QTimer
        timers = self.win.root.findChildren(QTimer)
        self.assertEqual(len(timers), 1)
        self.assertFalse(timers[0].isActive())

    def test_aspect_lock_and_reset(self):
        win = self.make()
        for size in ((1400, 700), (700, 900), (640, 300), (1200, 1200)):
            win.resize(*size)
            self.app.processEvents()
            self.assertLessEqual(abs(win.width() / win.height() - 1000 / 640), 0.01, size)
        win.resize(1500, 960)
        self.app.processEvents()
        root = win.root
        ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(10, 300), QPointF(10, 300), Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        root.mouseDoubleClickEvent(ev)
        self.app.processEvents()
        self.assertEqual((win.width(), win.height()), (1000, 640))
        win.zoom(0.5)
        self.assertEqual(win.width(), 1500)
        root.b_zoom_100.click()
        self.assertEqual(win.width(), 1000)

    def test_no_scrollbars_anywhere_in_main_view(self):
        win = self.make()
        from PySide6.QtWidgets import QScrollBar
        self.assertEqual(win.view.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual(win.view.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def test_paging_and_tabs(self):
        self.make(staged={})
        root = self.open_and_check()
        root.set_tab("all")
        self.assertEqual(len(root.view_rows), 51)
        shown = [rw for rw in root.rowws if rw.row is not None and rw.isVisible()]
        self.assertEqual(len(shown), 5)
        root.goto(99)
        self.assertEqual(root.page, 10)
        self.assertEqual(len([rw for rw in root.rowws if rw.row is not None]), 1)
        root.set_tab("updates")
        self.assertEqual(root.view_rows, [])
        self.assertIn("up to date", root.empty_text())

    def test_hover_bubble_after_delay_and_setting_off(self):
        self.make()
        root = self.open_and_check()
        mgr = root.bubbles
        self.assertEqual(mgr.timer.interval(), 1000)
        mgr.target = root.b_check
        mgr._show()
        self.assertTrue(mgr.bubble.isVisible())
        self.assertIn("nothing is sent", mgr.bubble.text().lower())
        mgr.bubble.hide()
        self.svc.settings.set("bubbles", False)
        mgr._show()
        self.assertFalse(mgr.bubble.isVisible())

    def test_overlays_render_without_errors(self):
        self.make(staged={"Hairball": "0.1.0"})
        root = self.open_and_check()
        row = next(r for r in root.rows if r.product.name == "Hairball")
        for fn in (lambda: root.show_changelog(row), root.show_settings, root.show_about,
                   lambda: root.show_confirm([row, row])):
            fn()
            self.app.processEvents()
            self.assertIsNotNone(root.overlay)
            self.assertFalse(root.overlay.grab().isNull())
            root.close_overlay()
        root.show_changelog(row)
        from PySide6.QtWidgets import QTextBrowser
        tb = root.overlay.findChild(QTextBrowser)
        self.assertIn("0.1.1", tb.toPlainText())
        self.assertEqual(tb.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def test_look_switch_saves_and_repaints(self):
        self.make()
        root = self.open_and_check()
        for k in ("navy", "soda", "purr"):
            root.set_look(k)
            self.assertEqual(self.svc.settings["theme"], k)
            self.assertFalse(self.win.grab().isNull())

    def test_click_update_installs_verified_zip_into_vst3_folder(self):
        tag = "v0.1.1"
        zip_name = "Hairball-%s.zip" % tag
        data = json.loads((ROOT / "tools" / "screenshot_data" / "releases" / "hairball.json").read_text())
        url = next(a["browser_download_url"] for r in data if r["tag_name"] == tag for a in r["assets"] if a["name"] == zip_name)
        z = make_release_zip(top="Hairball-v0.1.1", files={"linux/Hairball-linux-vst3.tar.gz": make_vst3_tar("Hairball.vst3", version="0.1.1"),
                                                          "INSTALL.txt": b"x"})
        # GitHub's own digest in the recorded data belongs to the real zip, so the stub zip must be refused first
        win = self.make(files={url: z}, staged={"Hairball": "0.1.0"})
        root = self.open_and_check()
        rw = next(rw for rw in root.rowws if rw.row is not None and rw.row.product.name == "Hairball")
        rw.b_main.click()
        self.assertTrue(self.pump(lambda: not root.installing and "Refused" in rw.message))
        self.assertIn("SHA256", rw.message)
        self.assertEqual(json.loads((self.home / ".vst3" / "Hairball.vst3" / "Contents" / "Resources" / "moduleinfo.json").read_text())["Version"], "0.1.0")
        # now serve a zip whose digest matches what the release data claims
        row = rw.row
        row.releases[0].zip_asset().sha256 = hashlib.sha256(z).hexdigest()
        rw.b_main.click()
        self.assertTrue(self.pump(lambda: not root.installing and "Installed" in rw.message))
        info = json.loads((self.home / ".vst3" / "Hairball.vst3" / "Contents" / "Resources" / "moduleinfo.json").read_text())
        self.assertEqual(info["Version"], "0.1.1", "the bundle from the verified zip is now in place")
        self.assertEqual(row.status, "current")
        self.assertEqual(self.svc.record.get("hairball")["version"], "0.1.1")


if __name__ == "__main__":
    unittest.main()
