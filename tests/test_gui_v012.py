"""Window tests for v0.1.2 (offscreen Qt, stub GitHub): offline bar and disabled installs, results list with Retry failed,
Roll back, studio87:// links, one instance, Settings, and the update-the-updater bar."""
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
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

from helpers import make_release_zip, make_vst3_tar  # noqa: E402


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class GuiV012(unittest.TestCase):
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
        svc.settings.set("token_storage", "session")
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

    def hb_zip(self, tag="v0.1.1"):
        data = json.loads((ROOT / "tools" / "screenshot_data" / "releases" / "hairball.json").read_text())
        name = "Hairball-%s.zip" % tag
        url = next(a["browser_download_url"] for r in data if r["tag_name"] == tag for a in r["assets"] if a["name"] == name)
        z = make_release_zip(top="Hairball-" + tag, files={"linux/Hairball-linux-vst3.tar.gz": make_vst3_tar("Hairball.vst3", b"NEW", tag.lstrip("v")),
                                                           "INSTALL.txt": b"x"})
        return url, z

    # ---- offline ---------------------------------------------------------
    def test_offline_bar_and_install_buttons_disabled_with_a_tooltip(self):
        self.make(staged={"Hairball": "0.1.0"})
        root = self.open_and_check()
        self.assertEqual(root.offline_line, "")
        self.assertEqual(root.bars(), [])
        from studio87_updater.github import Offline

        def down(*a, **k):
            raise Offline("no network")
        self.transport.request = down
        self.transport.open_stream = down
        self.svc.client.t = self.transport
        self.svc.catalog = None
        root.start_check()
        self.assertTrue(self.pump(lambda: not root.checking and root.pool.activeThreadCount() == 0))
        self.assertTrue(self.svc.offline)
        self.assertTrue(root.offline_line.startswith("Offline, showing saved list"), root.offline_line)
        self.assertEqual(root.bars(), ["offline"])
        self.assertEqual(root.list_y(), self.A.LIST_Y + self.A.BAR_H)
        root.set_tab("all")
        rw = next(r for r in root.allrows if r.row is not None and r.row.product.name == "Hairball")
        self.assertFalse(rw.b_main.isEnabled(), "Update is disabled while offline")
        self.assertIn("Offline", rw.main_tip())
        self.assertFalse(root.b_all.isEnabled())
        self.assertFalse(self.win.grab().isNull())
        # a finished download of the newest zip makes the button work offline
        row = rw.row
        zp = self.svc.installer().zip_path_for(row.product, row.latest, row.latest.zip_asset())
        zp.parent.mkdir(parents=True)
        zp.write_bytes(b"x" * row.latest.zip_asset().size)
        rw.refresh_buttons()
        self.assertTrue(rw.b_main.isEnabled())

    # ---- results list and retry ------------------------------------------
    def test_update_all_shows_a_result_per_product_and_retry_failed(self):
        url, z = self.hb_zip()
        self.make(files={url: z}, staged={"Hairball": "0.1.0", "Whisker Scope": "0.1.0"})
        root = self.open_and_check()
        root.set_tab("all")
        rows = [r for r in root.rows if r.product.name in ("Hairball", "Whisker Scope") and r.status == "update"]
        self.assertEqual(len(rows), 2)
        hb = next(r for r in rows if r.product.name == "Hairball")
        hb.releases[0].zip_asset().sha256 = hashlib.sha256(z).hexdigest()
        root.run_queue(rows)
        self.assertTrue(self.pump(lambda: not root.installing and root.overlay is not None))
        self.assertEqual(root.overlay.title, "Results")
        res = {r.repo: r for r in root.last_results}
        self.assertEqual(len(res), 2)
        self.assertTrue(res[hb.product.repo].ok, "one failing product did not stop the other")
        other = next(r for r in rows if r is not hb)
        self.assertFalse(res[other.product.repo].ok)
        self.assertIn("1 done, 1 did not finish", root.overlay.sub)
        self.assertFalse(root.overlay.grab().isNull())
        root.close_overlay()
        root.retry_failed()
        self.assertTrue(root.installing, "Retry failed runs only the failed product again")
        self.assertEqual([r.product.repo for r in root.queue], [other.product.repo])
        self.assertTrue(self.pump(lambda: not root.installing))

    # ---- roll back -------------------------------------------------------
    def test_roll_back_button_after_an_update(self):
        url, z = self.hb_zip()
        self.make(files={url: z}, staged={"Hairball": "0.1.0"})
        root = self.open_and_check()
        root.set_tab("all")
        hb = lambda: next(rw for rw in root.allrows if rw.row is not None and rw.row.product.name == "Hairball")
        row = hb().row
        row.releases[0].zip_asset().sha256 = hashlib.sha256(z).hexdigest()
        self.assertFalse(hb().b_roll.isVisibleTo(root), "no Roll back before there is something to roll back to")
        hb().b_main.click()
        self.assertTrue(self.pump(lambda: not root.installing and "Installed" in hb().message))
        self.assertIn("Roll back", hb().message)
        self.assertTrue(hb().b_roll.isVisibleTo(root))
        hb().b_roll.click()
        self.app.processEvents()
        info = json.loads((self.home / ".vst3" / "Hairball.vst3" / "Contents" / "Resources" / "moduleinfo.json").read_text())
        self.assertEqual(info["Version"], "0.1.0")
        self.assertEqual(row.status, "update", "back on the old version, the update is offered again")
        self.assertFalse(hb().b_roll.isVisibleTo(root))

    # ---- links -----------------------------------------------------------
    def test_link_jumps_to_the_product_and_ignores_everything_else(self):
        self.make(staged={"Hairball": "0.1.0"})
        root = self.open_and_check()
        root.set_tab("fx")
        root.search.setText("zzzz")
        self.app.processEvents()
        root.handle_link("studio87://open?product=hairball")
        self.assertEqual(root.tab, "all")
        self.assertEqual(root.search.text(), "")
        self.assertEqual(root.focus_repo, next(p.repo for p in self.svc.products if p.name == "Hairball"))
        self.assertFalse(self.win.grab().isNull())
        before = (root.tab, root.focus_repo)
        root.set_tab("fx")
        for bad in ("studio87://open?product=NoSuchThing", "studio87://evil", "http://open?product=Hairball", "rm -rf /", "", None):
            root.handle_link(bad)
        self.assertEqual(root.tab, "fx", "an invalid or unknown link changes nothing")
        self.assertIsNone(root.focus_repo)
        root.handle_link("studio87://open")
        self.assertEqual(root.tab, "fx", "plain open only brings the window forward")
        self.assertIsNotNone(before)

    def test_link_that_arrives_before_the_list_is_remembered(self):
        self.make(staged={"Hairball": "0.1.0"})
        root = self.win.root
        self.assertEqual(root.rows, [])
        root.handle_link("studio87://open?product=hairball")
        self.assertEqual(root.pending_link, "studio87://open?product=hairball")
        root.start_open_check()
        self.assertTrue(self.pump(lambda: not root.checking and root.rows and root.pool.activeThreadCount() == 0))
        self.assertIsNone(root.pending_link)
        self.assertIsNotNone(root.focus_repo)

    def test_second_start_hands_its_link_to_the_running_window(self):
        from studio87_updater.gui import single
        name = "studio87-test-%d" % os.getpid()
        got = []
        rec = single.Receiver(name)
        self.assertTrue(rec.ok)
        rec.got.connect(got.append)
        self.assertTrue(single.send("studio87://open?product=PurrOne", name))
        self.assertTrue(self.pump(lambda: bool(got), 5))
        self.assertEqual(got, ["studio87://open?product=PurrOne"])
        self.assertFalse(single.send("focus", "studio87-nobody-home-%d" % os.getpid(), timeout=100), "nothing listening: this process becomes the window")

    # ---- settings and the update-the-updater bar -------------------------
    def test_settings_shows_token_storage_cache_and_backup_controls(self):
        self.make()
        root = self.open_and_check()
        root.show_settings()
        self.app.processEvents()
        from studio87_updater.gui.widgets import Btn
        texts = [b.text() for b in root.overlay.holder.findChildren(Btn)]
        self.assertTrue(any(t.startswith("Clear (") for t in texts))
        self.assertEqual(sum(1 for t in texts if t.startswith("Clear (")), 2, "one for the saved list, one for kept previous versions")
        self.assertIn("This session only", texts)
        self.assertTrue(any("Signed in" in i[0] or "Not signed in" in i[0] for i in root.overlay._infos))
        self.assertFalse(root.overlay.grab().isNull())
        self.svc.backups.base.mkdir(parents=True, exist_ok=True)
        (self.svc.backups.base / "junk").write_bytes(b"x" * 10)
        clears = [b for b in root.overlay.holder.findChildren(Btn) if b.text().startswith("Clear (")]
        for b in clears:
            b.click()                                   # both clear buttons work and the overlay is rebuilt
            self.app.processEvents()
        self.assertEqual(self.svc.backups.total_size(), 0)
        self.assertEqual(self.svc.caches.size(), 0)

    def test_update_the_updater_bar(self):
        from studio87_updater import releases as R
        from helpers import release_json
        self.make()
        root = self.open_and_check()
        base = root.list_y()
        root.self_rel = R.parse_release(release_json("v9.9.9", [("Studio87-Gear-Updater-v9.9.9.zip", b"z")]))
        root.refresh_list()
        self.assertEqual(root.bars(), ["self"])
        self.assertEqual(root.list_y(), base + self.A.BAR_H)
        self.assertTrue(root.b_self.isVisibleTo(root))
        self.assertTrue(root.b_self.isEnabled())
        self.assertFalse(self.win.grab().isNull())
        from studio87_updater import manifest as M
        from studio87_updater import model as MD
        me = MD.Row(M.Product(repo="gearupdater", name="Studio 87 Gear Updater", kind="app", install={"linux": "flatpak-app"}))
        self.assertIn("Update the updater", root.blocked(me), "the updater never installs itself through the normal queue")

    def test_self_update_flow_linux_instructs_and_failure_keeps_working(self):
        from studio87_updater import releases as R
        from studio87_updater import selfupdate as SU
        from helpers import release_json
        self.make()
        root = self.open_and_check()
        root.self_rel = R.parse_release(release_json("v9.9.9", [("Studio87-Gear-Updater-v9.9.9.zip", b"z")]))
        root.refresh_list()
        real = SU.prepare
        try:
            def boom(*a, **k):
                raise SU.INS.InstallError("download failed")
            SU.prepare = boom
            root.start_self_update()
            self.assertTrue(self.pump(lambda: "could not be updated" in root.status, 10))
            self.assertIn("keeps working", root.status)
            self.assertFalse(root.self_busy)
            plan = SU.SelfPlan("instruct", self.home / "new.flatpak", "9.9.9", "Run this in a terminal.", "flatpak install --user new.flatpak")
            SU.prepare = lambda *a, **k: plan
            root.start_self_update()
            self.assertTrue(self.pump(lambda: getattr(root, "overlay", None) is not None, 10))
            self.assertIn("9.9.9", root.overlay.sub)
            self.assertIn("flatpak install --user", " ".join(root.overlay.lines))
            self.assertFalse(root.self_busy)
        finally:
            SU.prepare = real

    def test_footer_text_has_the_version(self):
        self.make()
        from studio87_updater import __version__
        src = (ROOT / "studio87_updater" / "gui" / "app.py").read_text()
        self.assertIn('"Studio 87 Gear Updater v%s" % __version__', src)
        self.assertTrue(__version__)


if __name__ == "__main__":
    unittest.main()
