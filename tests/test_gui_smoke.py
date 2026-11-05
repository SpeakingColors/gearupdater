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

    def test_resize_corners_scale_sides_change_one_dimension(self):
        win = self.make()
        self.assertEqual((win.LW, win.LH), (1047, 1150))
        ratio = win.LW / win.LH
        scr = self.A.screen_available()
        self.assertLessEqual(win.width(), scr[0])
        self.assertLessEqual(win.height(), scr[1])
        w0, h0, s0 = win.width(), win.height(), win.s
        win.resize(w0 + 100, h0 + 100)                  # corner: both change, shape kept
        self.app.processEvents()
        self.assertEqual((win.LW, win.LH), (1047, 1150))
        self.assertAlmostEqual(win.width() / win.height(), ratio, delta=0.01)
        self.assertGreater(win.s, s0)
        win.apply(1047, 1150, 1.0)
        win.resize(win.width() + 200, win.height())     # side: only the width changes, scale stays
        self.app.processEvents()
        self.assertEqual((win.LH, win.s), (1150, 1.0))
        self.assertEqual(win.LW, 1247)
        win.resize(win.width(), win.height() - 300)     # bottom edge: only the height
        self.app.processEvents()
        self.assertEqual((win.LW, win.LH), (1247, 850))
        win.resize(5000, win.height())                  # limits
        self.app.processEvents()
        self.assertEqual(win.LW, 1500)
        win.resize(win.width(), 10)
        self.app.processEvents()
        self.assertEqual(win.LH, 760)
        win.apply(100, 100, 1.0)
        self.assertEqual((win.LW, win.LH), (960, 760))

    def test_double_click_wood_resets_and_default_fits_screen(self):
        win = self.make()
        root = win.root
        win.apply(1400, 1000, 1.0)
        ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(10, 300), QPointF(10, 300), Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        root.mouseDoubleClickEvent(ev)
        self.assertEqual((win.LW, win.LH, win.s), (1047, 1150, win.s_fit))
        self.assertLessEqual(win.s_fit, 1.0)
        self.assertEqual(self.A.fit_scale((3000, 3000)), 1.0)
        self.assertLess(self.A.fit_scale((1366, 768)), 0.7)
        win.zoom(0.1)
        self.assertAlmostEqual(win.s, win.s_fit + 0.1)
        root.b_zoom_100.click()
        self.assertEqual(win.s, 1.0)
        root.b_zoom_fit.click()
        self.assertEqual(win.s, win.s_fit)

    def test_rows_keep_thumbnail_size_and_description_wraps_to_two_lines(self):
        self.make(staged={"Hairball": "0.1.0"})
        root = self.open_and_check()
        root.set_tab("all")
        self.assertEqual((self.A.THUMB_W, self.A.THUMB_H), (310, 162))
        n1 = len(root.view_rows)
        root.win.apply(1500, 1500, 1.0)
        rw = root.allrows[0]
        self.assertEqual(rw.W, 1500 - 88 - 14)
        self.assertEqual(rw.H, 172)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(self.A.font(px=17))
        lines = self.A.wrap_lines("word " * 200, fm, 400, 2)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].endswith("\u2026") or lines[1].endswith("..."))
        self.assertEqual(len(self.A.wrap_lines("short text", fm, 400, 2)), 1)

    def test_no_scrollbars_anywhere_in_main_view(self):
        win = self.make()
        from PySide6.QtWidgets import QScrollBar
        self.assertEqual(win.view.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual(win.view.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def test_opens_on_updates_with_empty_state_and_scrolling_list(self):
        self.make(staged={})
        root = self.open_and_check()
        self.assertEqual(root.tab, "updates")
        self.assertEqual(root.view_rows, [])
        self.assertIn("Everything is up to date", root.empty_text())
        self.assertTrue(root.b_browse.isVisibleTo(root))
        self.assertEqual(root.b_all.text(), "Update all (0)")
        root.set_tab("all")
        shown = [rw for rw in root.allrows if rw.row is not None]
        self.assertEqual(len(shown), len(root.rows), "every product is in the one scrolling list")
        self.assertGreater(root.inner.height(), root.scroll.height())
        self.assertEqual(root.scroll.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def test_all_tab_updates_first_and_contextual_buttons(self):
        self.make(staged={"Hairball": "0.1.0", "Cat Crusher": "0.2.4"})
        root = self.open_and_check()
        root.set_tab("all")
        names = [r.product.name for r in root.view_rows]
        self.assertEqual(names[0], "Hairball")
        rest = [n.lower() for n in names[1:]]
        self.assertEqual(rest, sorted(rest))
        rw = root.allrows[0]
        self.assertEqual(rw.b_main.text(), "Update")
        cc = next(w for w in root.allrows if w.row is not None and w.row.product.name == "Cat Crusher")
        self.assertEqual(cc.b_main.text(), "Up to date")
        self.assertFalse(cc.b_main.isEnabled())
        root.set_tab("notinstalled")
        self.assertTrue(root.view_rows)
        self.assertTrue(root.b_all.text().startswith("Install all"))
        self.assertNotIn("Update all", root.b_all.text())
        self.assertEqual(root.allrows[0].b_main.text(), "Install")

    def test_search_box_filters_as_you_type_and_tab_and_view_persist(self):
        self.make(staged={"Hairball": "0.1.0"})
        root = self.open_and_check()
        root.set_tab("all")
        root.search.setText("hair")
        self.assertEqual([r.product.name for r in root.view_rows], ["Hairball"])
        root.search.setText("controller")
        self.assertTrue(root.view_rows and all(r.product.cat == "controller" for r in root.view_rows))
        root.search.setText("zzzz")
        self.assertIn("matches", root.empty_text())
        root.search.setText("")
        root.set_tab("synth")
        self.assertEqual(root.tab, "synth")

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
        root.set_tab("all")
        hb = lambda: next(rw for rw in root.allrows if rw.row is not None and rw.row.product.name == "Hairball")
        rw = hb()
        rw.b_main.click()
        self.assertTrue(self.pump(lambda: not root.installing and "Refused" in hb().message))
        rw = hb()
        self.assertIn("SHA256", rw.message)
        self.assertEqual(json.loads((self.home / ".vst3" / "Hairball.vst3" / "Contents" / "Resources" / "moduleinfo.json").read_text())["Version"], "0.1.0")
        # now serve a zip whose digest matches what the release data claims
        row = rw.row
        row.releases[0].zip_asset().sha256 = hashlib.sha256(z).hexdigest()
        rw.b_main.click()
        self.assertTrue(self.pump(lambda: not root.installing and "Installed" in hb().message))
        info = json.loads((self.home / ".vst3" / "Hairball.vst3" / "Contents" / "Resources" / "moduleinfo.json").read_text())
        self.assertEqual(info["Version"], "0.1.1", "the bundle from the verified zip is now in place")
        self.assertEqual(row.status, "current")
        self.assertEqual(self.svc.record.get("hairball")["version"], "0.1.1")


if __name__ == "__main__":
    unittest.main()
