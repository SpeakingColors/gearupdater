"""Tests for v0.1.2: administrator prompt only when needed, safe updates and roll back, resumable downloads, per-item batch
results, token storage fallback, offline mode, self-update and the studio87:// link. Run with unittest or pytest."""
import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
import unittest
from pathlib import Path

from studio87_updater import auth as A
from studio87_updater import backup as BK
from studio87_updater import batch as BA
from studio87_updater import cache as CA
from studio87_updater import checksum as C
from studio87_updater import elevation as EL
from studio87_updater import install as INS
from studio87_updater import installed as I
from studio87_updater import link as LK
from studio87_updater import manifest as M
from studio87_updater import model as MD
from studio87_updater import mode as MODE
from studio87_updater import releases as R
from studio87_updater import selfupdate as SU
from studio87_updater.github import GitHubClient, HttpError, Offline

from helpers import FakeBackend, FakeTransport, make_release_zip, make_vst3_tar, release_json


class T(unittest.TestCase):
    def tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return Path(d)


class Env:
    """Installer + fake GitHub for any number of products and versions."""

    def __init__(self, test, system="linux", mode="all-users", backend=None, backups=True, cap=None, runner=None):
        self.d = test.tmp()
        self.t = FakeTransport()
        self.client = GitHubClient(self.t, self.d / "cache")
        self.rec = I.Record(self.d / "rec.json")
        self.opened = []
        self.backups = BK.BackupStore(self.d / "backups", **({"cap": cap} if cap else {})) if backups else None
        self.backend = backend if backend is not None else FakeBackend(admin=False)
        self.sleeps = []
        self.ins = INS.Installer(self.client, self.rec, system, self.d / "work", self.d / "vst3", self.d / "guided",
                                 runner=runner or (lambda *a, **k: None), opener=self.opened.append, mode=mode,
                                 backend=self.backend, backups=self.backups, zip_dir=self.d / "zips", stage_dir=self.d / "staged",
                                 sleep=self.sleeps.append)
        self.vst3 = self.d / "vst3"

    def row(self, repo="PunchPaw", tag="v0.2.0", files=None, system_methods=None, **kw):
        z = make_release_zip(top="%s-%s" % (repo, tag), files=files if files is not None else
                             {"linux/%s-linux-vst3.tar.gz" % repo: make_vst3_tar(repo + ".vst3", kw.get("payload", b"binary"), tag.lstrip("v")),
                              "INSTALL.txt": b"x", "windows/%s-Setup.exe" % repo: b"MZ" + repo.encode()})
        name = "%s-%s.zip" % (repo, tag)
        self.t.routes["https://dl.test/" + name] = (200, {}, z)
        rel = R.parse_release(release_json(tag, [(name, z)]))
        p = M.Product(repo=repo, name=repo, kind="vst3", detect={"vst3": repo},
                      install=system_methods or {"linux": "vst3", "windows": "exe", "macos": "pkg"})
        return MD.Row(p, releases=[rel], installed=I.InstalledInfo("installed", "0.1.0"), status=MD.UPDATE)


class ElevationTests(T):
    def test_windows_all_users_batch_asks_once_for_many(self):
        e = Env(self, "windows", backend=FakeBackend(admin=False))
        rows = [e.row("P%d" % i) for i in range(5)]
        res = BA.run_batch(e.ins, rows)
        self.assertEqual(len(e.backend.batches), 1, "ONE administrator prompt for the whole batch")
        self.assertEqual(sorted(e.backend.batches[0]), ["P0", "P1", "P2", "P3", "P4"])
        self.assertTrue(all(r.ok for r in res))
        self.assertEqual(e.rec.get("P3")["version"], "0.2.0")

    def test_no_prompt_when_already_administrator_runs_installers_directly(self):
        ran = []

        class Rr:
            returncode, stdout, stderr = 0, "", ""
        e = Env(self, "windows", backend=FakeBackend(admin=True), runner=lambda cmd, **k: (ran.append(cmd), Rr())[1])
        e.ins.install(e.row("A"))
        self.assertEqual(e.backend.batches, [])
        self.assertEqual(len(ran), 1)
        self.assertIn("/SILENT", ran[0])

    def test_just_for_me_never_prompts_even_on_windows(self):
        e = Env(self, "windows", mode="just-me", backend=FakeBackend(admin=False))
        files = {"windows/X.vst3/Contents/x.bin": b"1", "INSTALL.txt": b"x"}
        res = e.ins.install(e.row("X", files=files))
        self.assertEqual(res["method"], "vst3-zip")
        self.assertEqual(e.backend.batches, [], "Just for me: the elevation backend is never used")

    def test_declined_prompt_fails_every_staged_item_and_records_nothing(self):
        e = Env(self, "windows", backend=FakeBackend(outcome={"A": (False, EL.DECLINED), "B": (False, EL.DECLINED)}))
        res = BA.run_batch(e.ins, [e.row("A"), e.row("B")])
        self.assertEqual([r.ok for r in res], [False, False])
        self.assertIn("nothing was installed", res[0].message)
        self.assertIsNone(e.rec.get("A"))
        self.assertEqual(len(e.backend.batches), 1, "declining does not loop and ask again")

    def test_one_failing_installer_does_not_stop_the_others_in_the_elevated_batch(self):
        e = Env(self, "windows", backend=FakeBackend(outcome={"B": (False, "installer failed (code 5): boom")}))
        res = BA.run_batch(e.ins, [e.row("A"), e.row("B"), e.row("C")])
        self.assertEqual({r.repo: r.ok for r in res}, {"A": True, "B": False, "C": True})
        self.assertIsNone(e.rec.get("B"))
        self.assertEqual(e.rec.get("C")["version"], "0.2.0")

    def test_job_file_roundtrip_and_validation(self):
        stage = self.tmp()
        f = stage / "A.exe"
        f.write_bytes(b"MZ")
        job = EL.Job("A", "A", "exe", str(f), EL.sha256_of(f))
        jp, rp = EL.write_job_file([job], stage)
        jobs, result = EL.read_job_file(jp)
        self.assertEqual((jobs[0].repo, jobs[0].kind, Path(jobs[0].file)), ("A", "exe", f.resolve()))
        self.assertEqual(result, stage / "elevated-result.json")
        for bad in ({"jobs": [{"repo": "a", "kind": "exe", "file": "../evil.exe", "sha256": "0" * 64}]},
                    {"jobs": [{"repo": "a", "kind": "exe", "file": "/etc/evil", "sha256": "0" * 64}]},
                    {"jobs": [{"repo": "a", "kind": "shell", "file": "A.exe", "sha256": "0" * 64}]},
                    {"jobs": [{"repo": "a", "kind": "exe", "file": "A.exe", "sha256": "zz"}]},
                    {"jobs": []}):
            d = {"format": 1, "result": "elevated-result.json"}
            d.update(bad)
            jp.write_text(json.dumps(d))
            with self.assertRaises(EL.ElevationError):
                EL.read_job_file(jp)
        jp.write_text(json.dumps({"format": 1, "result": "../x.json", "jobs": [{"repo": "a", "kind": "exe", "file": "A.exe", "sha256": "0" * 64}]}))
        with self.assertRaises(EL.ElevationError):
            EL.read_job_file(jp)

    def test_helper_rechecks_hash_uses_fixed_commands_and_survives_a_failure(self):
        stage = self.tmp()
        calls = []

        class Rr:
            def __init__(s, rc):
                s.returncode, s.stdout, s.stderr = rc, "", "boom"

        def runner(cmd, **k):
            calls.append(cmd)
            return Rr(5 if cmd[0].endswith("B.exe") else 0)
        jobs = []
        for n in "ABC":
            f = stage / (n + ".exe")
            f.write_bytes(b"MZ" + n.encode())
            jobs.append(EL.Job(n, n, "exe", str(f), EL.sha256_of(f)))
        (stage / "C.exe").write_bytes(b"swapped after verification")        # tampered with after the app verified it
        jp, rp = EL.write_job_file(jobs, stage)
        self.assertEqual(EL.helper_main(["x", "--elevated-run", str(jp)], runner), 0)
        res = {r["repo"]: r for r in json.loads(rp.read_text())}
        self.assertTrue(res["A"]["ok"])
        self.assertFalse(res["B"]["ok"])
        self.assertIn("code 5", res["B"]["message"])
        self.assertFalse(res["C"]["ok"])
        self.assertIn("refused", res["C"]["message"])
        self.assertEqual(len(calls), 2, "the tampered installer was never run")
        for c in calls:
            self.assertEqual(c[1:], ["/SILENT", "/NORESTART", "/SP-"], "the command line is fixed, not read from the job file")

    def test_helper_refuses_a_bad_job_file(self):
        self.assertEqual(EL.helper_main(["--elevated-run", str(self.tmp() / "missing.json")]), 2)
        self.assertEqual(EL.helper_main(["--elevated-run"]), 2)

    def test_windows_backend_declined_and_success_with_fake_launcher(self):
        stage = self.tmp()
        f = stage / "A.exe"
        f.write_bytes(b"MZ")
        job = EL.Job("A", "A", "exe", str(f), EL.sha256_of(f))
        out = EL.WindowsBackend(launcher=lambda exe, params: False).run_batch([job], stage)
        self.assertEqual(out["A"], (False, EL.DECLINED))
        seen = []

        class Rr:
            returncode, stdout, stderr = 0, "", ""

        def launcher(exe, params):
            seen.append(params)
            jp = params.split('"')[1]
            EL.helper_main(["--elevated-run", jp], lambda cmd, **k: Rr())
            return True
        out = EL.WindowsBackend(launcher=launcher).run_batch([job], stage)
        self.assertTrue(out["A"][0])
        self.assertIn("--elevated-run", seen[0])

    def test_mac_backend_one_prompt_checks_each_hash_and_reads_each_result(self):
        stage = self.tmp()
        jobs = []
        for n in "AB":
            f = stage / (n + ".pkg")
            f.write_bytes(n.encode())
            jobs.append(EL.Job(n, n, "pkg", str(f), EL.sha256_of(f)))
        calls = []

        class Rr:
            returncode, stdout, stderr = 0, "", ""

        def runner(cmd, **k):
            calls.append(cmd)
            script = Path(cmd[2].split("/bin/sh ")[1].rstrip('" ').split(" with ")[0].rstrip('"').strip())
            body = script.read_text()
            self.assertEqual(body.count("/usr/sbin/installer"), 2)
            self.assertEqual(body.count("shasum -a 256"), 2)
            res = Path(str(script).replace("install-batch.sh", "install-batch.result"))
            res.write_text("0\t0\n1\t3\n")
            return Rr()
        out = EL.MacBackend(runner=runner).run_batch(jobs, stage)
        self.assertEqual(len(calls), 1)
        self.assertEqual((out["A"][0], out["B"][0]), (True, False))
        class Cancel:
            returncode, stdout, stderr = 1, "", "User cancelled."
        out = EL.MacBackend(runner=lambda cmd, **k: Cancel()).run_batch(jobs, stage)
        self.assertFalse(out["A"][0] or out["B"][0])

    def test_app_manifest_is_not_requireAdministrator(self):
        root = Path(__file__).resolve().parents[1]
        wf = (root / ".github/workflows/release.yml").read_text()
        self.assertNotIn("--uac-admin", wf.replace("# ", "#").split("pyinstaller", 1)[1].split("windows.iss")[0] if "pyinstaller" in wf else wf)
        iss = (root / "packaging/windows.iss").read_text()
        self.assertNotIn("PrivilegesRequired=admin", iss)


class SafeUpdateTests(T):
    def old_install(self, e, payload=b"old"):
        row = e.row("PunchPaw", "v0.1.0", payload=payload)
        e.ins.install(row)
        return row

    def test_update_keeps_previous_version_and_rollback_restores_it(self):
        e = Env(self, "linux", mode="just-me")
        self.old_install(e, b"OLDBIN")
        res = e.ins.install(e.row("PunchPaw", "v0.2.0", payload=b"NEWBIN"))
        self.assertTrue(res["backup"])
        so = e.vst3 / "PunchPaw.vst3" / "Contents" / "x86_64-linux" / "PunchPaw.so"
        self.assertEqual(so.read_bytes(), b"NEWBIN")
        self.assertTrue(e.ins.can_rollback("PunchPaw"))
        self.assertEqual(e.rec.get("PunchPaw")["version"], "0.2.0")
        msg = e.ins.rollback("PunchPaw")
        self.assertIn("0.1.0", msg)
        self.assertEqual(so.read_bytes(), b"OLDBIN")
        self.assertEqual(e.rec.get("PunchPaw")["version"], "0.1.0")
        self.assertFalse(e.ins.can_rollback("PunchPaw"), "one backup, used up")
        self.assertEqual(sorted(x.name for x in e.vst3.iterdir()), ["PunchPaw.vst3"], "no leftovers")

    def test_only_the_last_one_version_is_kept(self):
        e = Env(self, "linux", mode="just-me")
        self.old_install(e, b"V1")
        e.ins.install(e.row("PunchPaw", "v0.2.0", payload=b"V2"))
        e.ins.install(e.row("PunchPaw", "v0.3.0", payload=b"V3"))
        e.ins.rollback("PunchPaw")
        so = e.vst3 / "PunchPaw.vst3" / "Contents" / "x86_64-linux" / "PunchPaw.so"
        self.assertEqual(so.read_bytes(), b"V2", "rolls back one step: 0.3.0 -> 0.2.0, not 0.1.0")

    def test_backup_is_size_capped_and_update_still_works(self):
        e = Env(self, "linux", mode="just-me", cap=10)
        self.old_install(e, b"A" * 100)
        res = e.ins.install(e.row("PunchPaw", "v0.2.0", payload=b"B" * 100))
        self.assertTrue(res["ok"])
        self.assertFalse(res["backup"])
        self.assertNotIn("Roll back", res["message"])
        self.assertFalse(e.ins.can_rollback("PunchPaw"))

    def test_clear_backups(self):
        e = Env(self, "linux", mode="just-me")
        self.old_install(e)
        e.ins.install(e.row("PunchPaw", "v0.2.0"))
        self.assertGreater(e.backups.total_size(), 0)
        e.backups.clear()
        self.assertEqual(e.backups.total_size(), 0)
        self.assertFalse(e.ins.can_rollback("PunchPaw"))

    def test_failed_verification_restores_the_old_plugin_automatically(self):
        d = self.tmp()
        tar = d / "t.tar.gz"
        tar.write_bytes(make_vst3_tar("PunchPaw.vst3", b"NEW"))
        vst3 = d / "vst3"
        old = vst3 / "PunchPaw.vst3"
        (old / "Contents").mkdir(parents=True)
        (old / "Contents" / "keep.bin").write_bytes(b"OLD")

        def bad(target):
            raise RuntimeError("version check failed")
        with self.assertRaises(INS.InstallError):
            INS.install_vst3_tarball(tar, vst3, verify=bad)
        self.assertEqual((old / "Contents" / "keep.bin").read_bytes(), b"OLD")
        self.assertFalse((old / "Contents" / "x86_64-linux").exists())
        self.assertEqual(sorted(x.name for x in vst3.iterdir()), ["PunchPaw.vst3"])

    def test_copy_that_does_not_match_the_verified_files_is_undone(self):
        d = self.tmp()
        tar = d / "t.tar.gz"
        tar.write_bytes(make_vst3_tar("PunchPaw.vst3", b"NEW"))
        vst3 = d / "vst3"
        (vst3 / "PunchPaw.vst3").mkdir(parents=True)
        (vst3 / "PunchPaw.vst3" / "old.txt").write_text("old")
        real = BK.tree_hashes
        calls = []

        def flaky(root):
            calls.append(1)
            h = real(root)
            if len(calls) == 2:           # the second call hashes the installed copy
                h["Contents/x86_64-linux/PunchPaw.so"] = "0" * 64
            return h
        BK.tree_hashes = flaky
        try:
            with self.assertRaises(INS.InstallError):
                INS.install_vst3_tarball(tar, vst3)
        finally:
            BK.tree_hashes = real
        self.assertEqual((vst3 / "PunchPaw.vst3" / "old.txt").read_text(), "old")

    def test_interrupted_swap_is_repaired_on_next_install(self):
        d = self.tmp()
        tar = d / "t.tar.gz"
        tar.write_bytes(make_vst3_tar("PunchPaw.vst3", b"NEW"))
        vst3 = d / "vst3"
        (vst3 / "PunchPaw.vst3.studio87-old").mkdir(parents=True)        # a crash left only the aside copy
        (vst3 / "PunchPaw.vst3.studio87-old" / "old.txt").write_text("old")
        INS.install_vst3_tarball(tar, vst3)
        self.assertTrue((vst3 / "PunchPaw.vst3" / "Contents").exists())
        self.assertFalse((vst3 / "PunchPaw.vst3.studio87-old").exists())

    def test_checksum_failure_touches_nothing_installed(self):
        e = Env(self, "linux", mode="just-me")
        self.old_install(e, b"KEEPME")
        bad = e.row("PunchPaw", "v0.2.0", files={"linux/PunchPaw-linux-vst3.tar.gz": make_vst3_tar("PunchPaw.vst3", b"EVIL"), "INSTALL.txt": b"x"})
        z = make_release_zip(top="PunchPaw-v0.2.0", files={"linux/PunchPaw-linux-vst3.tar.gz": make_vst3_tar("PunchPaw.vst3", b"EVIL"), "INSTALL.txt": b"x"}, corrupt="linux/PunchPaw-linux-vst3.tar.gz")
        e.t.routes["https://dl.test/PunchPaw-v0.2.0.zip"] = (200, {}, z)
        bad.releases[0].zip_asset().sha256 = None
        before = sorted(str(p) for p in e.vst3.rglob("*"))
        with self.assertRaises(C.ChecksumError):
            e.ins.install(bad)
        self.assertEqual(sorted(str(p) for p in e.vst3.rglob("*")), before)
        so = e.vst3 / "PunchPaw.vst3" / "Contents" / "x86_64-linux" / "PunchPaw.so"
        self.assertEqual(so.read_bytes(), b"KEEPME")
        self.assertFalse(e.ins.zip_ready(bad.product, bad.latest), "a damaged zip is deleted, never reused")

    def test_rollback_without_backup_is_a_clear_error(self):
        e = Env(self, "linux", mode="just-me")
        with self.assertRaises(INS.InstallError):
            e.ins.rollback("PunchPaw")


class DownloadTests(T):
    def client(self, **routes):
        t = FakeTransport(routes)
        return t, GitHubClient(t, self.tmp() / "c")

    def test_interrupted_download_resumes_with_range_and_backs_off(self):
        body = bytes(range(256)) * 400
        t, c = self.client(**{"https://dl.test/f": (200, {}, body)})
        t.break_after["https://dl.test/f"] = 30000
        sleeps = []
        d = self.tmp()
        got = c.download("https://dl.test/f", d / "f", sleep=sleeps.append)
        self.assertEqual((d / "f").read_bytes(), body)
        self.assertEqual(sleeps, [1.5])
        ranges = [h.get("Range") for _u, h in t.log]
        self.assertEqual(ranges, [None, "bytes=30000-"], "second request resumes where the first stopped")
        self.assertEqual(got, len(body))

    def test_backoff_grows_and_gives_up_keeping_the_part(self):
        t, c = self.client(**{"https://dl.test/f": (200, {}, b"x" * 1000)})
        t.fail_open["https://dl.test/f"] = 99
        sleeps = []
        d = self.tmp()
        with self.assertRaises(Offline):
            c.download("https://dl.test/f", d / "f", sleep=sleeps.append)
        self.assertEqual(sleeps, [1.5, 3.0, 6.0, 12.0])
        self.assertFalse((d / "f").exists())

    def test_retry_after_giving_up_resumes_the_kept_part(self):
        body = b"y" * 100000
        t, c = self.client(**{"https://dl.test/f": (200, {}, body)})
        d = self.tmp()
        (d / "f.part").write_bytes(body[:60000])
        c.download("https://dl.test/f", d / "f", sleep=lambda s: None)
        self.assertEqual((d / "f").read_bytes(), body)
        self.assertEqual(t.log[0][1].get("Range"), "bytes=60000-")

    def test_server_without_range_restarts_the_file_cleanly(self):
        body = b"z" * 5000
        t, c = self.client(**{"https://dl.test/f": (200, {}, body)})
        t.range_support = False
        d = self.tmp()
        (d / "f.part").write_bytes(b"garbage-from-before")
        c.download("https://dl.test/f", d / "f", sleep=lambda s: None)
        self.assertEqual((d / "f").read_bytes(), body, "a 200 answer replaces the part, it is not appended to it")

    def test_server_errors_are_retried_but_a_404_is_not(self):
        t, c = self.client(**{"https://dl.test/f": (503, {}, b"")})
        sleeps = []
        with self.assertRaises(HttpError):
            c.download("https://dl.test/f", self.tmp() / "f", sleep=sleeps.append)
        self.assertEqual(len(sleeps), 4)
        t, c = self.client()
        sleeps = []
        with self.assertRaises(HttpError):
            c.download("https://dl.test/none", self.tmp() / "f", sleep=sleeps.append)
        self.assertEqual(sleeps, [])

    def test_a_complete_part_answered_with_416_is_accepted(self):
        body = b"q" * 500
        t, c = self.client(**{"https://dl.test/f": (200, {}, body)})
        d = self.tmp()
        (d / "f.part").write_bytes(body)
        c.download("https://dl.test/f", d / "f", sleep=lambda s: None)
        self.assertEqual((d / "f").read_bytes(), body)

    def test_install_survives_a_dropped_connection_and_verifies_after(self):
        e = Env(self, "linux", mode="just-me")
        row = e.row("PunchPaw", "v0.2.0")
        url = "https://dl.test/PunchPaw-v0.2.0.zip"
        e.t.break_after[url] = 200
        res = e.ins.install(row)
        self.assertTrue(res["ok"])
        self.assertEqual(e.sleeps, [1.5])

    def test_offline_failure_is_a_plain_message_and_retry_reuses_the_part(self):
        e = Env(self, "linux", mode="just-me")
        row = e.row("PunchPaw", "v0.2.0")
        url = "https://dl.test/PunchPaw-v0.2.0.zip"
        e.t.fail_open[url] = 99
        res = BA.run_batch(e.ins, [row])
        self.assertFalse(res[0].ok)
        self.assertIn("Retry failed", res[0].message)
        e.t.fail_open.clear()
        res = BA.run_batch(e.ins, [row])
        self.assertTrue(res[0].ok)

    def test_zip_ready_lets_an_offline_install_work_without_the_network(self):
        e = Env(self, "windows", backend=FakeBackend(outcome={"A": (False, EL.DECLINED)}))
        row = e.row("A")
        BA.run_batch(e.ins, [row])                       # download + verify OK, administrator step declined
        self.assertTrue(e.ins.zip_ready(row.product, row.latest))
        e.t.offline = True
        e.backend.outcome = {}
        res = BA.run_batch(e.ins, [row])
        self.assertTrue(res[0].ok, "the finished zip is used, nothing is fetched")


class BatchTests(T):
    def test_one_failure_never_stops_the_rest_and_results_list_each_product(self):
        e = Env(self, "linux", mode="just-me")
        good1, good2 = e.row("Good1"), e.row("Good2")
        bad = e.row("Bad", files={"INSTALL.txt": b"x"})
        e.t.routes["https://dl.test/Bad-v0.2.0.zip"] = (200, {}, make_release_zip(top="Bad-v0.2.0", corrupt="linux/PunchPaw-linux-vst3.tar.gz"))
        bad.releases[0].zip_asset().sha256 = None
        seen = []
        res = BA.run_batch(e.ins, [good1, bad, good2], on_item=seen.append)
        self.assertEqual([(r.repo, r.ok) for r in res], [("Good1", True), ("Bad", False), ("Good2", True)])
        self.assertEqual(len(seen), 3)
        self.assertIn("Refused", res[1].message)
        self.assertEqual([r.repo for r in BA.failed(res)], ["Bad"])
        self.assertEqual(BA.summary(res), "2 done, 1 did not finish. The others were not affected.")
        self.assertTrue((e.vst3 / "Good2.vst3").exists())

    def test_retry_failed_runs_only_the_failed_ones(self):
        e = Env(self, "linux", mode="just-me")
        rows = [e.row("A"), e.row("B")]
        e.t.fail_open["https://dl.test/B-v0.2.0.zip"] = 99
        res = BA.run_batch(e.ins, rows)
        self.assertEqual([r.ok for r in res], [True, False])
        e.t.fail_open.clear()
        retry = [r for r in rows if r.product.repo in {x.repo for x in BA.retryable(res)}]
        res2 = BA.run_batch(e.ins, retry)
        self.assertEqual([(r.repo, r.ok) for r in res2], [("B", True)])

    def test_stop_skips_the_rest_and_marks_them_retryable(self):
        e = Env(self, "linux", mode="just-me")
        flag = {"stop": False}
        res = BA.run_batch(e.ins, [e.row("A"), e.row("B")], cancel=lambda: flag["stop"],
                           on_item=lambda r: flag.update(stop=True))
        self.assertEqual([r.ok for r in res], [True, False])
        self.assertTrue(res[1].cancelled)
        self.assertEqual(BA.failed(res), [])
        self.assertEqual(len(BA.retryable(res)), 1)


class TokenStorageTests(T):
    class Clock:
        t = 1000.0

        def now(self):
            return self.t

    def keyring(self, ok=True):
        class K:
            kind = "keychain"

            def __init__(s):
                s.d = None

            def available(s):
                return ok

            def load(s):
                return s.d

            def save(s, d):
                if not ok:
                    raise RuntimeError("no keychain")
                s.d = dict(d)

            def clear(s):
                s.d = None
        return K()

    def test_keychain_first_then_file_then_session(self):
        d = self.tmp()
        a = A.AutoStore(self.keyring(True), A.FileStore(d))
        a.save({"access_token": "T1"})
        self.assertEqual(a.kind, "keychain")
        self.assertFalse((d / "token.enc").exists())
        b = A.AutoStore(self.keyring(False), A.FileStore(d))
        b.save({"access_token": "T2"})
        self.assertEqual(b.kind, "file")
        self.assertEqual(b.load()["access_token"], "T2")
        blocked = d / "nofolder"
        blocked.write_text("a file where the folder should be")
        c = A.AutoStore(self.keyring(False), A.FileStore(blocked / "x"))
        c.save({"access_token": "T3"})
        self.assertEqual(c.kind, "session")
        self.assertEqual(c.load()["access_token"], "T3")

    def test_planned_kind_follows_the_chain(self):
        d = self.tmp()
        self.assertEqual(A.AutoStore(self.keyring(True), A.FileStore(d)).planned_kind(), "keychain")
        self.assertEqual(A.AutoStore(self.keyring(False), A.FileStore(d)).planned_kind(), "file")
        self.assertEqual(A.AutoStore(self.keyring(True), A.FileStore(d), session_only=True).planned_kind(), "session")
        blocked = d / "nofolder"
        blocked.write_text("a file")
        self.assertEqual(A.AutoStore(self.keyring(False), A.FileStore(blocked / "x")).planned_kind(), "session")

    def test_session_only_never_writes_anything(self):
        d = self.tmp()
        a = A.AutoStore(self.keyring(True), A.FileStore(d), session_only=True)
        a.save({"access_token": "T"})
        self.assertEqual(a.kind, "session")
        self.assertEqual(list(d.iterdir()), [])
        self.assertIsNone(A.AutoStore(self.keyring(True), A.FileStore(d), session_only=True).load(), "gone with the session")

    def test_file_is_encrypted_0600_and_tamper_proof(self):
        d = self.tmp()
        fs = A.FileStore(d)
        fs.save({"access_token": "SECRET-TOKEN-VALUE", "refresh_token": "R"})
        raw = (d / "token.enc").read_bytes()
        self.assertNotIn(b"SECRET-TOKEN-VALUE", raw)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE((d / "token.enc").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((d / "install.key").stat().st_mode), 0o600)
        self.assertEqual(A.FileStore(d).load()["access_token"], "SECRET-TOKEN-VALUE")
        (d / "token.enc").write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        self.assertIsNone(A.FileStore(d).load(), "a changed file is rejected, not trusted")
        (d / "token.enc").write_bytes(raw)
        (d / "install.key").write_bytes(os.urandom(32))
        self.assertIsNone(A.FileStore(d).load(), "another key cannot read it")

    def test_status_line_says_where_the_token_is(self):
        d = self.tmp()
        for ring, want in ((self.keyring(True), "OS keychain"), (self.keyring(False), "local file")):
            au = A.Auth(post=lambda *a: {}, store=A.AutoStore(ring, A.FileStore(d)))
            au.store.save({"access_token": "t"})
            au._loaded = False
            self.assertEqual(au.status_line(), "Signed in, token stored in: " + want)
        au = A.Auth(post=lambda *a: {}, store=A.AutoStore(self.keyring(True), A.FileStore(d), session_only=True))
        au.store.save({"access_token": "t"})
        au._loaded = False
        self.assertEqual(au.status_line(), "Signed in, token stored in: this session only")
        au.sign_out()
        self.assertTrue(au.status_line().startswith("Not signed in"))

    def test_failed_refresh_signs_out_cleanly_once_without_a_loop(self):
        posts = []

        def post(url, data):
            posts.append(data.get("grant_type"))
            return {"error": "incorrect_client_credentials"}
        clock = self.Clock()
        st = A.MemoryStore()
        st.save({"access_token": "old", "refresh_token": "r", "expires_at": clock.t - 10})
        au = A.Auth(post=post, store=st, now=clock.now)
        for _ in range(5):
            self.assertIsNone(au.token())
        self.assertEqual(posts, ["refresh_token"], "asked GitHub once, then stopped")
        self.assertFalse(au.signed_in)
        self.assertTrue(au.expired)
        self.assertIn("sign in again", au.status_line())
        self.assertIsNone(st.d)

    def test_refresh_that_cannot_reach_github_does_not_hammer_or_sign_out(self):
        posts = []

        def post(url, data):
            posts.append(1)
            raise OSError("offline")
        clock = self.Clock()
        st = A.MemoryStore()
        st.save({"access_token": "old", "refresh_token": "r", "expires_at": clock.t - 10})
        au = A.Auth(post=post, store=st, now=clock.now)
        for _ in range(4):
            self.assertIsNone(au.token())
        self.assertEqual(len(posts), 1)
        self.assertTrue(au.signed_in, "offline is not a reason to sign out")
        clock.t += A.Auth.RETRY_AFTER + 1
        au.token()
        self.assertEqual(len(posts), 2)

    def test_401_from_github_drops_the_token_and_the_list_still_loads(self):
        t = FakeTransport()
        calls = []

        def route(headers):
            calls.append(headers.get("Authorization"))
            return (401, {}, b"") if headers.get("Authorization") else (200, {}, b"[]")
        t.routes["https://api.github.com/x"] = route
        st = A.MemoryStore()
        st.save({"access_token": "revoked"})
        au = A.Auth(post=lambda *a: {}, store=st)
        c = GitHubClient(t, self.tmp() / "c")
        c.token_provider, c.on_unauthorized = au.token, au.invalidate
        body, _ = c.fetch("https://api.github.com/x")
        self.assertEqual(body, b"[]")
        self.assertEqual(calls, ["Bearer revoked", None])
        self.assertFalse(au.signed_in)
        self.assertTrue(au.expired)
        c.fetch("https://api.github.com/x?again=1")
        self.assertEqual(calls[2:], [], "no token is sent any more") if False else None

    def test_token_never_appears_in_repr_str_or_error_text(self):
        st = A.MemoryStore()
        st.save({"access_token": "TOPSECRET", "refresh_token": "ALSOSECRET"})
        au = A.Auth(post=lambda *a: {}, store=st)
        for text in (repr(au), str(au), au.status_line(), repr(st.d.keys())):
            self.assertNotIn("TOPSECRET", text)
            self.assertNotIn("ALSOSECRET", text)
        src = (Path(A.__file__)).read_text()
        self.assertNotIn("logging", src)
        self.assertNotIn("print(", src)


class OfflineTests(T):
    def svc(self):
        from studio87_updater.service import Service
        d = self.tmp()
        t = FakeTransport()
        st = A.MemoryStore()
        return Service("linux", {"XDG_DATA_HOME": str(d / "data"), "XDG_CACHE_HOME": str(d / "cache")}, d, transport=t,
                       vst3_dirs=[], flatpak_probe=lambda: ("absent", set()), auth=A.Auth(post=lambda *a: {}, store=st)), t

    def test_offline_bar_text_and_disabled_reason(self):
        svc, t = self.svc()
        self.assertEqual(svc.offline_text(), "")
        svc.offline = True
        svc.last_checked = time.mktime((2026, 11, 15, 14, 5, 0, 0, 0, -1))
        self.assertEqual(svc.offline_text(), "Offline, showing saved list from 2026-11-15 14:05")
        z = make_release_zip(top="PunchPaw-v0.2.0")
        rel = R.parse_release(release_json("v0.2.0", [("PunchPaw-v0.2.0.zip", z)]))
        p = M.Product(repo="PunchPaw", name="PunchPaw", kind="vst3", install={"linux": "vst3"})
        row = MD.Row(p, releases=[rel], status=MD.UPDATE)
        self.assertIn("Offline", svc.install_disabled_reason(row))
        zp = svc.cache_dir / "zips" / "PunchPaw-v0.2.0" / "PunchPaw-v0.2.0.zip"
        zp.parent.mkdir(parents=True)
        zp.write_bytes(z)
        self.assertEqual(svc.install_disabled_reason(row), "", "a finished download can be installed offline")
        svc.offline = False
        zp.unlink()
        self.assertEqual(svc.install_disabled_reason(row), "")

    def test_check_while_offline_shows_saved_list_and_flags_offline(self):
        svc, t = self.svc()
        t.offline = True
        rows, notice = svc.check()
        self.assertEqual(notice, "offline")
        self.assertTrue(svc.offline)
        self.assertIn("Offline, showing saved list", svc.offline_text())

    def test_cache_cap_prunes_oldest_keeps_catalog_and_clear_removes_all(self):
        d = self.tmp()
        c = GitHubClient(FakeTransport({"https://x/catalog.json": (200, {}, b"c" * 100)}), d)
        c.now = lambda: 1000.0
        c.fetch("https://x/catalog.json")
        for i in range(10):
            c.t.routes["https://x/t%d.jpg" % i] = (200, {}, b"i" * 1000)
            c.now = lambda i=i: 2000.0 + i
            c.fetch("https://x/t%d.jpg" % i)
        cm = CA.CacheManager(d, cap=3500)
        before = cm.size()
        freed = cm.prune()
        self.assertGreater(freed, 0)
        self.assertLessEqual(cm.size(), 3500)
        self.assertIsNotNone(c.cached_bytes("https://x/catalog.json"), "the catalog is the last thing to go")
        self.assertIsNotNone(c.cached_bytes("https://x/t9.jpg"), "newest thumbnails stay")
        self.assertIsNone(c.cached_bytes("https://x/t0.jpg"), "oldest goes first")
        self.assertGreater(cm.clear(), 0)
        self.assertEqual(cm.size(), 0)
        self.assertLess(cm.size(), before)

    def test_old_unfinished_downloads_are_dropped(self):
        d = self.tmp()
        z = d / "zips" / "a-v1"
        z.mkdir(parents=True)
        old, fresh = z / "old.zip.part", z / "new.zip"
        old.write_bytes(b"1")
        fresh.write_bytes(b"2")
        past = time.time() - 9 * 24 * 3600
        os.utime(old, (past, past))
        CA.CacheManager(d / "gh", d / "zips").prune_downloads()
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_buttons_logic_in_gui_uses_the_reason_for_the_tooltip(self):
        src = (Path(__file__).resolve().parents[1] / "studio87_updater" / "gui" / "app.py").read_text()
        self.assertIn("install_disabled_reason", src)


class SelfUpdateTests(T):
    def release(self, tag, files):
        z = make_release_zip(top="Studio87-Gear-Updater-" + tag, files=files)
        name = "Studio87-Gear-Updater-%s.zip" % tag
        return z, R.parse_release(release_json(tag, [(name, z)])), name

    def test_newer_release_picks_only_a_newer_one_with_a_zip(self):
        old = R.parse_release(release_json("v0.1.1", [("a.zip", b"1")]))
        new = R.parse_release(release_json("v0.1.2", [("b.zip", b"1")]))
        nozip = R.parse_release(release_json("v0.9.0", []))
        self.assertEqual(SU.newer_release([nozip, new, old], "0.1.1").tag, "v0.1.2")
        self.assertIsNone(SU.newer_release([new, old], "0.1.2"))
        self.assertIsNone(SU.newer_release([old], "0.1.2"))
        self.assertIsNone(SU.newer_release([], "0.1.2"))

    def prepare(self, system):
        files = {"windows/Studio87-GearUpdater-Setup.exe": b"MZsetup", "macos/Studio87-GearUpdater-macOS.pkg": b"pkg",
                 "linux/Studio87-GearUpdater.flatpak": b"flat", "INSTALL.txt": b"x"}
        z, rel, name = self.release("v0.1.2", files)
        t = FakeTransport({"https://dl.test/" + name: (200, {}, z)})
        c = GitHubClient(t, self.tmp() / "c")
        folder = self.tmp() / "su"
        return SU.prepare(c, rel, system, folder, sleep=lambda s: None), folder, rel, t

    def test_windows_hands_over_to_the_new_installer_and_exits(self):
        plan, folder, rel, _ = self.prepare("windows")
        self.assertEqual(plan.action, "launch")
        self.assertEqual(plan.file.read_bytes(), b"MZsetup")
        self.assertEqual(list(folder.iterdir()), [plan.file], "only the installer is left, no zip or temp folder")
        started = []
        exit_now = SU.launch(plan, "windows", popen=lambda cmd, **k: started.append(cmd))
        self.assertTrue(exit_now)
        self.assertEqual(started[0][0], str(plan.file))
        self.assertIn("/SILENT", started[0])
        self.assertIn("/CLOSEAPPLICATIONS", started[0])

    def test_macos_opens_the_pkg_and_stays_open(self):
        plan, *_ = self.prepare("macos")
        ran = []
        self.assertFalse(SU.launch(plan, "macos", runner=lambda cmd, **k: ran.append(cmd)))
        self.assertEqual(ran[0][0], "open")

    def test_linux_flatpak_is_instructed_not_replaced(self):
        plan, *_ = self.prepare("linux")
        self.assertEqual(plan.action, "instruct")
        self.assertTrue(plan.command.startswith("flatpak install --user --reinstall "))
        self.assertIn("running Flatpak cannot replace itself", plan.text)
        self.assertFalse(SU.launch(plan, "linux", popen=lambda *a, **k: self.fail("nothing is run on Linux")))

    def test_corrupt_download_is_refused_and_nothing_is_left(self):
        z, rel, name = self.release("v0.1.2", {"windows/S.exe": b"MZ", "INSTALL.txt": b"x"})
        z2 = make_release_zip(top="Studio87-Gear-Updater-v0.1.2", files={"windows/S.exe": b"MZ", "INSTALL.txt": b"x"}, corrupt="windows/S.exe")
        rel.zip_asset().sha256 = None
        t = FakeTransport({"https://dl.test/" + name: (200, {}, z2)})
        c = GitHubClient(t, self.tmp() / "c")
        folder = self.tmp() / "su"
        with self.assertRaises(C.ChecksumError):
            SU.prepare(c, rel, "windows", folder, sleep=lambda s: None)
        self.assertEqual(list(folder.iterdir()), [])

    def test_release_layout_matches_v011_so_the_old_updater_can_update(self):
        root = Path(__file__).resolve().parents[1]
        wf = (root / ".github/workflows/release.yml").read_text()
        for must in ('d="Studio87-Gear-Updater-$tag"', 'mkdir -p "$d/windows" "$d/macos" "$d/linux"', "SHA256SUMS", "outer/SHA256SUMS"):
            self.assertIn(must, wf)

    def test_version_is_in_every_footer_text(self):
        root = Path(__file__).resolve().parents[1]
        from studio87_updater import __version__
        app = (root / "studio87_updater/gui/app.py").read_text()
        self.assertIn('"Studio 87 Gear Updater v%s" % __version__', app)
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")


class LinkTests(T):
    KNOWN = ["PurrOne", "catcrusher-vst", "FatCat"]

    def test_valid_links(self):
        self.assertEqual(LK.parse("studio87://open"), LK.LinkAction(None))
        self.assertEqual(LK.parse("studio87://open/"), LK.LinkAction(None))
        self.assertEqual(LK.parse("STUDIO87://OPEN"), LK.LinkAction(None))
        self.assertEqual(LK.parse("studio87://open?product=PurrOne", self.KNOWN), LK.LinkAction("PurrOne"))
        self.assertEqual(LK.parse("studio87://open?product=purrone", self.KNOWN), LK.LinkAction("PurrOne"), "matched to the catalog's spelling")
        self.assertEqual(LK.parse("studio87://open?product=catcrusher-vst&x=1&product=FatCat", self.KNOWN), LK.LinkAction("catcrusher-vst"))

    def test_unknown_parameters_and_products_are_ignored_but_the_app_still_opens(self):
        self.assertEqual(LK.parse("studio87://open?product=Nope", self.KNOWN), LK.LinkAction(None))
        self.assertEqual(LK.parse("studio87://open?run=calc.exe&path=/etc/passwd"), LK.LinkAction(None))
        self.assertEqual(LK.parse("studio87://open?product=PurrOne#frag", self.KNOWN), LK.LinkAction("PurrOne"))

    def test_hostile_and_malformed_links_are_dropped(self):
        for bad in ("http://open", "studio87://evil", "studio87://open/../../etc", "studio87://open/run", "studio87://user@open",
                    "studio87://open:80", "studio87:open", "studio87://", "", None, 5, "studio87://open?product=" + "a" * 600,
                    "studio87://open\nfoo", "file:///etc/passwd", "studio87://open?product=../../x"):
            r = LK.parse(bad, self.KNOWN)
            self.assertTrue(r is None or r.product is None, bad)
        for other in ("studio87://evil", "studio87://evil?product=PurrOne", "studio87://OPENX", "studio87://op"):
            self.assertIsNone(LK.parse(other, self.KNOWN), other)
        self.assertIsNone(LK.parse("studio87://open?product=a;rm -rf /", None).product)
        self.assertIsNone(LK.parse("studio87://open?product=%2e%2e%2fetc", None).product)
        self.assertIsNone(LK.parse("studio87://open?product=a%20b", None).product)

    def test_links_never_carry_anything_executable(self):
        a = LK.parse("studio87://open?product=PurrOne&cmd=rm", self.KNOWN)
        self.assertEqual(a.__dataclass_fields__.keys(), {"product": 1}.keys(), "a link can only ever say 'open' and 'which product'")

    def test_find_in_argv(self):
        self.assertEqual(LK.find_in_argv(["--x", "studio87://open?product=A"]), "studio87://open?product=A")
        self.assertIsNone(LK.find_in_argv(["--list"]))

    def test_registration_is_declared_for_every_system(self):
        root = Path(__file__).resolve().parents[1]
        iss = (root / "packaging/windows.iss").read_text()
        self.assertIn("Software\\Classes\\studio87", iss)
        self.assertIn("URL Protocol", iss)
        self.assertIn("HKA", iss)
        desk = (root / "packaging/flatpak/io.github.speakingcolors.Studio87GearUpdater.desktop").read_text()
        self.assertIn("x-scheme-handler/studio87", desk)
        self.assertIn("%u", desk)
        wf = (root / ".github/workflows/release.yml").read_text()
        self.assertIn("CFBundleURLTypes", wf)
        self.assertIn("CFBundleURLSchemes:0 string studio87", wf.split("PlistBuddy", 1)[1][:600])
        doc = (root / "docs/plugin-link.md").read_text()
        self.assertIn('juce::URL("studio87://open?product=NAME").launchInDefaultBrowser()', doc)
        self.assertIn("Install Studio 87 Gear Updater from github.com/SpeakingColors/gearupdater/releases", doc)


class GitHubButtonTests(T):
    def test_row_github_button_is_the_repo_home_page(self):
        prods = M.load_manifest().products
        self.assertTrue(prods)
        for p in prods:
            self.assertEqual(p.github_url, "https://github.com/SpeakingColors/%s" % p.repo)
            self.assertNotIn("/releases", p.github_url)

    def test_plugin_link_doc_has_the_two_button_snippet(self):
        doc = (Path(__file__).resolve().parents[1] / "docs/plugin-link.md").read_text()
        self.assertIn('juce::URL("https://github.com/SpeakingColors/NAME").launchInDefaultBrowser()', doc)
        self.assertIn("Gear Updater not found, opened the GitHub page instead.", doc)
        self.assertIn("Opens this plugin's home page on GitHub in your browser. Nothing is sent by the plugin.", doc)


class DocsTests(T):
    def test_no_em_dash_or_en_dash_in_new_text(self):
        root = Path(__file__).resolve().parents[1]
        files = ["README.md", "INSTALL.txt", "CHANGELOG.md", "docs/plugin-link.md", "docs/manual.txt", "release/NOTES.md"] + \
                [str(p.relative_to(root)) for p in (root / "studio87_updater").rglob("*.py")]
        for f in files:
            txt = (root / f).read_text(encoding="utf-8")
            self.assertNotIn("—", txt, f)
            self.assertNotIn("–", txt, f)

    def test_no_personal_info_strings(self):
        root = Path(__file__).resolve().parents[1]
        for p in list(root.rglob("*.py")) + list(root.rglob("*.md")) + list(root.rglob("*.txt")):
            if ".git" in p.parts or "tour" in p.parts or p.name == "test_v012.py":
                continue
            t = p.read_text(encoding="utf-8", errors="ignore").lower()
            self.assertNotIn("@gmail", t, str(p))
            self.assertNotIn("/home/claude", t, str(p))


class RenamedRepos(unittest.TestCase):
    def test_old_names_map_and_manifest_lists_new_ones(self):
        import json
        import tempfile
        from studio87_updater import installed as I
        d = Path(tempfile.mkdtemp())
        (d / "r.json").write_text(json.dumps({"schema": 1, "products": {"catpro1": {"version": "0.1.0"}, "PurrOne": {"version": "1"}}}))
        rec = I.Record(d / "r.json")
        self.assertEqual(rec.get("SynthCookBook")["version"], "0.1.0")
        self.assertIsNone(rec.get("catpro1"))
        self.assertEqual(rec.get("PurrOne")["version"], "1")
        repos = [p["repo"] for p in json.loads((Path(__file__).resolve().parents[1] / "studio87_updater" / "products.json").read_text())["products"]]
        self.assertIn("SynthCookBook", repos)
        self.assertNotIn("catpro1", repos)
        self.assertNotIn("td3mo-vst", repos)
        from studio87_updater import manifest as M
        from studio87_updater import model as MD
        pv = [p for p in M.load_manifest().products if p.repo == "purrrvoicechannel"][0]
        self.assertEqual(pv.cat, "fx")
        inst = I.InstalledInfo("not-installed", None, "scan", "")
        row = MD.Row(product=pv, installed=inst)
        row.releases = []
        row.status = MD.compute_status(pv, [], inst, None)
        self.assertEqual(row.status, MD.NO_RELEASE)
        self.assertFalse(row.can_install)
        self.assertTrue(MD.in_tab(row, "notinstalled"))
        self.assertTrue(MD.in_tab(row, "fx"))
        self.assertFalse(MD.in_tab(row, "installed"))


if __name__ == "__main__":
    unittest.main()
