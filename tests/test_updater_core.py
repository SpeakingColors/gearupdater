import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from studio87_updater import checksum as C
from studio87_updater import installed as I
from studio87_updater import install as INS
from studio87_updater import manifest as M
from studio87_updater import model as MD
from studio87_updater import releases as R
from studio87_updater import version as V
from studio87_updater import paths as P
from studio87_updater.github import GitHubClient, HttpError, Offline, RateLimited, UrlLibTransport

from helpers import FakeTransport, make_release_zip, make_vst3_tar, release_json


class T(unittest.TestCase):
    def tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return Path(d)


class VersionTests(T):
    def test_parse_and_clean(self):
        self.assertEqual(V.clean("v0.1.2"), "0.1.2")
        self.assertEqual(V.clean("1.2"), "1.2.0")
        self.assertEqual(V.clean("v1.0.0-rc1"), "1.0.0-rc1")
        self.assertIsNone(V.clean("latest"))
        self.assertIsNone(V.clean(None))

    def test_compare_numeric_not_text(self):
        self.assertEqual(V.compare("0.9.0", "0.10.0"), -1)
        self.assertEqual(V.compare("v1.2.3", "1.2.3"), 0)
        self.assertEqual(V.compare("2.0.0", "1.99.99"), 1)

    def test_prerelease_is_older_than_release(self):
        self.assertTrue(V.is_update("1.0.0-rc1", "1.0.0"))
        self.assertFalse(V.is_update("1.0.0", "1.0.0-rc1"))
        self.assertTrue(V.is_update("1.0.0-rc1", "1.0.0-rc2"))
        self.assertTrue(V.is_update("1.0.0-rc2", "1.0.0-rc10"))

    def test_unknown_stays_unknown(self):
        self.assertIsNone(V.is_update("garbage", "1.0.0"))
        self.assertIsNone(V.is_update("1.0.0", "nightly"))

    def test_update_direction(self):
        self.assertTrue(V.is_update("0.1.0", "0.1.1"))
        self.assertFalse(V.is_update("0.1.1", "0.1.0"))
        self.assertFalse(V.is_update("0.1.1", "0.1.1"))


class ManifestTests(T):
    def test_real_manifest_is_valid(self):
        m = M.load_manifest()
        self.assertGreater(len(m.products), 40)
        pp = m.by_repo()["punchpaw"]
        self.assertEqual(pp.method("linux"), "vst3")
        self.assertEqual(pp.method("windows"), "exe")
        self.assertEqual(pp.detect["vst3"], "PunchPaw")

    def test_logue_units_are_guided_only(self):
        m = M.load_manifest().by_repo()
        self.assertEqual(m["hypersaw-xd"].method("linux"), "guided")

    def test_override_and_validation(self):
        m = M.parse_manifest({"products": [{"repo": "a", "name": "A", "kind": "app", "install": {"linux": "guided"}}],
                              "defaults": {"app": {"linux": "flatpak-app", "windows": "exe"}}})
        self.assertEqual(m.products[0].method("linux"), "guided")
        self.assertEqual(m.products[0].method("windows"), "exe")
        with self.assertRaises(M.ManifestError):
            M.parse_manifest({"products": [{"repo": "a", "name": "A", "kind": "app", "install": {"linux": "exe"}}]})
        with self.assertRaises(M.ManifestError):
            M.parse_manifest({"products": [{"repo": "a", "name": "A"}, {"repo": "A", "name": "B"}]})
        with self.assertRaises(M.ManifestError):
            M.parse_manifest({"products": [{"repo": "a", "name": "A", "kind": "weird"}]})

    def test_unknown_kind_is_view_on_github_and_not_polled(self):
        m = M.parse_manifest({"products": [{"repo": "a", "name": "A", "kind": "unknown", "install": {"linux": "vst3"}}]})
        self.assertFalse(m.products[0].checks_releases)

    def test_discovered_repos(self):
        m = M.parse_manifest({"products": [{"repo": "known", "name": "K", "kind": "vst3", "install": {"linux": "vst3"}}],
                              "ignore": ["cat-ui"]})
        out = M.merge_discovered(m, ["Known", "cat-ui", "brand-new"])
        names = [p.repo for p in out]
        self.assertEqual(names, ["known", "brand-new"])
        self.assertTrue(out[1].discovered and not out[1].checks_releases)


class ReleaseTests(T):
    def test_parse_digest_and_zip(self):
        r = R.parse_release(release_json("v0.1.0", [("P-v0.1.0.zip", b"zz"), ("SHA256SUMS", b"s")]))
        self.assertEqual(r.version, "0.1.0")
        self.assertEqual(r.zip_asset().name, "P-v0.1.0.zip")
        self.assertEqual(r.zip_asset().sha256, hashlib.sha256(b"zz").hexdigest())
        self.assertIsNotNone(r.sums_asset())
        self.assertTrue(r.is_test_build)

    def test_drafts_skipped_and_newest_first_by_version_not_date(self):
        items = [release_json("v0.9.0"), release_json("v0.10.0"), release_json("v1.0.0", draft=True)]
        rels = R.parse_releases(items)
        self.assertEqual([r.tag for r in rels], ["v0.10.0", "v0.9.0"])

    def test_changelog_line_strips_markdown_and_cuts(self):
        self.assertEqual(R.changelog_line("\n\n## **Big** [fix](http://x) `now`\nmore"), "Big fix now")
        long = "word " * 60
        out = R.changelog_line(long, 40)
        self.assertTrue(len(out) <= 44 and out.endswith("..."))
        self.assertEqual(R.changelog_line(""), "")

    def test_notes_since(self):
        rels = R.parse_releases([release_json("v0.3.0"), release_json("v0.2.0"), release_json("v0.1.0")])
        self.assertEqual([r.tag for r in R.notes_since(rels, "0.1.0")], ["v0.3.0", "v0.2.0"])
        self.assertEqual(len(R.notes_since(rels, None)), 3)


class ChecksumTests(T):
    def test_parse_sums_formats(self):
        h = "a" * 64
        d = C.parse_sums("%s  ./windows/x.exe\n%s *linux/y.tar.gz\nnot a line\n" % (h, h.upper()))
        self.assertEqual(d, {"windows/x.exe": h, "linux/y.tar.gz": h})

    def test_digest_mismatch_refused(self):
        d = self.tmp()
        f = d / "f"
        f.write_bytes(b"abc")
        self.assertTrue(C.check_digest(f, hashlib.sha256(b"abc").hexdigest()))
        with self.assertRaises(C.ChecksumError):
            C.check_digest(f, hashlib.sha256(b"abd").hexdigest())

    def test_verify_tree(self):
        d = self.tmp()
        (d / "a").write_bytes(b"1")
        good = {"a": hashlib.sha256(b"1").hexdigest()}
        self.assertTrue(C.verify_tree(d, good, required=["a"]))
        with self.assertRaises(C.ChecksumError):
            C.verify_tree(d, {"a": hashlib.sha256(b"2").hexdigest()})
        with self.assertRaises(C.ChecksumError):
            C.verify_tree(d, {"gone": "0" * 64})
        with self.assertRaises(C.ChecksumError):
            C.verify_tree(d, good, required=["b"])
        with self.assertRaises(C.ChecksumError):
            C.verify_tree(d, {})

    def test_zip_slip_refused(self):
        d = self.tmp()
        z = d / "bad.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../evil.txt", "x")
        with self.assertRaises(C.UnsafeArchive):
            C.safe_extract_zip(z, d / "out")
        self.assertFalse((d / "evil.txt").exists())

    def test_tar_rules(self):
        d = self.tmp()
        good = d / "g.tar.gz"
        good.write_bytes(make_vst3_tar("Cat Crusher.vst3"))
        out = C.safe_extract_tar(good, d / "o1")
        self.assertEqual(out.name, "Cat Crusher.vst3")
        self.assertTrue((out / "Contents" / "Resources" / "moduleinfo.json").exists())
        for name, build in (("two", lambda t: [t.addfile(tarfile.TarInfo("A.vst3/x")), t.addfile(tarfile.TarInfo("B.vst3/x"))]),
                            ("notvst", lambda t: t.addfile(tarfile.TarInfo("evil/x"))),
                            ("abs", lambda t: t.addfile(tarfile.TarInfo("/etc/x.vst3/x"))),
                            ("dots", lambda t: t.addfile(tarfile.TarInfo("A.vst3/../../x")))):
            p = d / (name + ".tar")
            with tarfile.open(p, "w") as t:
                build(t)
            with self.assertRaises(C.UnsafeArchive, msg=name):
                C.safe_extract_tar(p, d / ("o_" + name))
        link = d / "link.tar"
        with tarfile.open(link, "w") as t:
            ti = tarfile.TarInfo("A.vst3/l")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "/etc/passwd"
            t.addfile(ti)
        with self.assertRaises(C.UnsafeArchive):
            C.safe_extract_tar(link, d / "o_link")


class GitHubTests(T):
    URL = "https://api.github.com/repos/o/r/releases?per_page=6"

    def client(self, routes):
        t = FakeTransport(routes)
        return t, GitHubClient(t, self.tmp(), now=lambda: 1000.0)

    def test_etag_roundtrip_uses_304_and_cache(self):
        body = json.dumps([release_json()]).encode()
        t, c = self.client({self.URL: lambda h: (304, {}, b"") if h.get("If-None-Match") == '"e1"' else (200, {"ETag": '"e1"'}, body)})
        d1, s1 = c.get_json(self.URL)
        d2, s2 = c.get_json(self.URL)
        self.assertEqual((s1, s2), ("network", "not-modified"))
        self.assertEqual(d1, d2)
        self.assertEqual(t.log[1][1].get("If-None-Match"), '"e1"')

    def test_only_expected_headers_are_sent(self):
        t, c = self.client({self.URL: (200, {"ETag": '"e"'}, b"[]")})
        c.get_json(self.URL)
        c.get_json(self.URL)
        for _, h in t.log:
            self.assertLessEqual(set(h), {"Accept", "If-None-Match"})

    def test_user_agent_is_generic(self):
        req = UrlLibTransport()._req("https://api.github.com/x", {"Accept": "a"})
        self.assertEqual(req.get_header("User-agent"), "Studio87-Updater")
        self.assertEqual(sorted(k.lower() for k in req.headers), ["accept", "user-agent"])

    def test_offline_falls_back_to_cache_else_raises(self):
        t, c = self.client({self.URL: (200, {"ETag": '"e"'}, b"[]")})
        with self.assertRaises(Offline):
            t.offline = True
            c.get_json(self.URL)
        t.offline = False
        c.get_json(self.URL)
        t.offline = True
        d, src = c.get_json(self.URL)
        self.assertEqual((d, src), ([], "cache"))

    def test_rate_limit_detected_and_stops_requests(self):
        t, c = self.client({self.URL: (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "4600"}, b"{}")})
        with self.assertRaises(RateLimited) as cm:
            c.get_json(self.URL)
        self.assertIn("min", cm.exception.message(1000.0))
        n = len(t.log)
        with self.assertRaises(RateLimited):
            c.get_json(self.URL)
        self.assertEqual(len(t.log), n, "must not hit the network again while limited")

    def test_other_403_is_an_error_not_a_rate_limit(self):
        t, c = self.client({self.URL: (403, {"X-RateLimit-Remaining": "40"}, b"{}")})
        with self.assertRaises(HttpError):
            c.get_json(self.URL)

    def test_missing_is_cached_negatively(self):
        t, c = self.client({})
        self.assertEqual(c.fetch("https://raw.test/a.png"), (None, "missing"))
        self.assertEqual(c.fetch("https://raw.test/a.png"), (None, "missing"))
        self.assertEqual(len(t.log), 1)

    def test_download_writes_file_and_cleans_part_on_cancel(self):
        t, c = self.client({"https://dl.test/f": (200, {}, b"x" * 1000)})
        d = self.tmp()
        got = []
        c.download("https://dl.test/f", d / "f", progress=lambda a, b: got.append((a, b)))
        self.assertEqual((d / "f").read_bytes(), b"x" * 1000)
        self.assertEqual(got[-1], (1000, 1000))
        with self.assertRaises(InterruptedError):
            c.download("https://dl.test/f", d / "g", cancel=lambda: True)
        self.assertFalse((d / "g").exists() or (d / "g.part").exists())


class InstalledTests(T):
    def product(self, **kw):
        return M.Product(repo="PunchPaw", name="PunchPaw", kind="vst3", detect=kw or {"vst3": "PunchPaw", "flatpak": "PunchPaw"})

    def bundle(self, d, name="PunchPaw", ver="0.1.0"):
        b = d / (name + ".vst3") / "Contents" / "Resources"
        b.mkdir(parents=True)
        if ver:
            (b / "moduleinfo.json").write_text(json.dumps({"Name": name, "Version": ver}))
        return d / (name + ".vst3")

    def test_reads_bundle_metadata(self):
        d = self.tmp()
        self.bundle(d, ver="0.1.4")
        rec = I.Record(d / "rec.json")
        info = I.detect(self.product(), "linux", rec, [d])
        self.assertEqual((info.state, info.version, info.source), ("installed", "0.1.4", "vst3-metadata"))

    def test_plist_version_on_macos_style_bundle(self):
        import plistlib
        d = self.tmp()
        b = self.bundle(d, ver=None)
        (b / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.3.1"}))
        self.assertEqual(I.read_bundle_version(b), "0.3.1")

    def test_not_installed_is_honest(self):
        d = self.tmp()
        info = I.detect(self.product(), "linux", I.Record(d / "r.json"), [d])
        self.assertEqual(info.state, "not-installed")

    def test_bundle_without_version_and_no_record_is_unknown_version(self):
        d = self.tmp()
        self.bundle(d, ver=None)
        info = I.detect(self.product(), "linux", I.Record(d / "r.json"), [d])
        self.assertEqual((info.state, info.version), ("installed", None))

    def test_record_used_only_while_the_bundle_exists(self):
        d = self.tmp()
        rec = I.Record(d / "r.json")
        rec.set("PunchPaw", "0.2.0", "v0.2.0", "vst3-tarball")
        self.assertEqual(I.detect(self.product(), "linux", rec, [d]).state, "not-installed")
        self.bundle(d, ver=None)
        info = I.detect(self.product(), "linux", I.Record(d / "r.json"), [d])
        self.assertEqual((info.state, info.version, info.source), ("installed", "0.2.0", "install-record"))

    def test_flatpak_extension_found_and_error_is_unknown(self):
        d = self.tmp()
        ids = {I.EXT_PREFIX + "PunchPaw"}
        info = I.detect(self.product(), "linux", I.Record(d / "r.json"), [d], ("ok", ids))
        self.assertEqual((info.state, info.version), ("installed", None))
        info = I.detect(self.product(), "linux", I.Record(d / "r.json"), [d], ("error", set()))
        self.assertEqual(info.state, "unknown")

    def test_product_without_detect_hints_is_unknown_never_not_installed(self):
        d = self.tmp()
        p = M.Product(repo="X", name="X", kind="vst3", detect={})
        self.assertEqual(I.detect(p, "linux", I.Record(d / "r.json"), [d]).state, "unknown")

    def test_flatpak_probe_parsing(self):
        class R:
            returncode, stdout = 0, "org.a.B\n org.freedesktop.LinuxAudio.Plugins.X \n\n"
        self.assertEqual(I.probe_flatpak(lambda *a, **k: R(), in_sandbox=False), ("ok", {"org.a.B", "org.freedesktop.LinuxAudio.Plugins.X"}))

        def boom(*a, **k):
            raise FileNotFoundError
        self.assertEqual(I.probe_flatpak(boom, in_sandbox=False)[0], "absent")
        self.assertEqual(I.probe_flatpak(boom, in_sandbox=True)[0], "error")

    def test_record_survives_reload_and_bad_file(self):
        d = self.tmp()
        r = I.Record(d / "r.json")
        r.set("a", "1.0.0", "v1.0.0", "exe", [Path("/x")])
        self.assertEqual(I.Record(d / "r.json").get("a")["version"], "1.0.0")
        (d / "r.json").write_text("{broken")
        self.assertIsNone(I.Record(d / "r.json").get("a"))


class ModelTests(T):
    def prod(self, repo="p", kind="vst3"):
        return M.Product(repo=repo, name=repo, kind=kind, install={"linux": "vst3"} if kind != "unknown" else {})

    def rels(self, *tags):
        return R.parse_releases([release_json(t) for t in tags])

    def test_status_matrix(self):
        p = self.prod()
        inst = lambda v: I.InstalledInfo("installed", v)
        self.assertEqual(MD.compute_status(p, self.rels("v0.2.0"), inst("0.1.0")), MD.UPDATE)
        self.assertEqual(MD.compute_status(p, self.rels("v0.2.0"), inst("0.2.0")), MD.CURRENT)
        self.assertEqual(MD.compute_status(p, self.rels("v0.2.0"), inst("0.3.0")), MD.CURRENT)
        self.assertEqual(MD.compute_status(p, self.rels("v0.2.0"), I.InstalledInfo("not-installed")), MD.NOT_INSTALLED)
        self.assertEqual(MD.compute_status(p, self.rels("v0.2.0"), I.InstalledInfo("unknown")), MD.UNKNOWN_INSTALL)
        self.assertEqual(MD.compute_status(p, self.rels("v0.2.0"), inst(None)), MD.UNKNOWN_INSTALL)
        self.assertEqual(MD.compute_status(p, [], inst("0.1.0")), MD.NO_RELEASE)
        self.assertEqual(MD.compute_status(self.prod(kind="unknown"), [], None), MD.GITHUB_ONLY)
        self.assertEqual(MD.compute_status(p, None, inst("1.0.0"), error="x"), MD.ERROR)
        self.assertEqual(MD.compute_status(p, self.rels("nightly"), inst("1.0.0")), MD.UNKNOWN_INSTALL)

    def test_update_all_only_means_real_updates(self):
        r1 = MD.Row(self.prod("a"), status=MD.UPDATE)
        r2 = MD.Row(self.prod("b"), status=MD.UNKNOWN_INSTALL)
        self.assertEqual([r.product.repo for r in [r1, r2] if r.status == MD.UPDATE], ["a"])

    def make_client(self, repos):
        routes = {}
        for repo, items in repos.items():
            routes["https://api.github.com/repos/SpeakingColors/%s/releases?per_page=6" % repo] = (200, {"ETag": '"%s"' % repo, "X-RateLimit-Remaining": "50"}, json.dumps(items).encode())
        t = FakeTransport(routes)
        return t, GitHubClient(t, self.tmp(), now=lambda: 1000.0)

    def test_build_rows_skips_unknown_products(self):
        t, c = self.make_client({"a": [release_json("v0.2.0")]})
        prods = [self.prod("a"), self.prod("mystery", "unknown")]
        rows, notice = MD.build_rows(c, prods, lambda p: I.InstalledInfo("installed", "0.1.0"))
        self.assertEqual([r.status for r in rows], [MD.UPDATE, MD.GITHUB_ONLY])
        self.assertEqual(len(t.log), 1, "unknown products must not be requested")
        self.assertEqual(notice, "")

    def test_offline_shows_cached_list(self):
        t, c = self.make_client({"a": [release_json("v0.2.0")]})
        prods = [self.prod("a")]
        MD.build_rows(c, prods, lambda p: I.InstalledInfo("installed", "0.1.0"))
        t.offline = True
        rows, notice = MD.build_rows(c, prods, lambda p: I.InstalledInfo("installed", "0.1.0"))
        self.assertEqual(notice, "offline")
        self.assertEqual(rows[0].status, MD.UPDATE)
        self.assertTrue(rows[0].from_cache)

    def test_offline_without_cache_is_unchecked_not_no_release(self):
        t, c = self.make_client({})
        t.offline = True
        rows, notice = MD.build_rows(c, [self.prod("a")], lambda p: I.InstalledInfo("installed", "0.1.0"))
        self.assertEqual(rows[0].status, MD.UNCHECKED)

    def test_rate_limit_mid_run_stops_and_uses_cache(self):
        t, c = self.make_client({"a": [release_json("v0.2.0")]})
        prods = [self.prod("a"), self.prod("b"), self.prod("c")]
        t.routes["https://api.github.com/repos/SpeakingColors/b/releases?per_page=6"] = (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "4600"}, b"{}")
        rows, notice = MD.build_rows(c, prods, lambda p: I.InstalledInfo("installed", "0.1.0"))
        self.assertIn("rate limit", notice.lower())
        self.assertEqual(rows[0].status, MD.UPDATE)
        self.assertEqual([r.status for r in rows[1:]], [MD.UNCHECKED, MD.UNCHECKED])
        self.assertEqual(len(t.log), 2, "after the limit no more requests")

    def test_repo_with_no_releases(self):
        t, c = self.make_client({"a": []})
        rows, _ = MD.build_rows(c, [self.prod("a")], lambda p: I.InstalledInfo("not-installed"))
        self.assertEqual(rows[0].status, MD.NO_RELEASE)


class InstallTests(T):
    def prod(self, **kw):
        d = dict(repo="PunchPaw", name="PunchPaw", kind="vst3", detect={"vst3": "PunchPaw"},
                 install={"linux": "vst3", "windows": "exe", "macos": "pkg"})
        d.update(kw)
        return M.Product(**d)

    def tree(self, files):
        d = self.tmp()
        for p, b in files.items():
            f = d / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b)
        return d

    def test_plan_matrix(self):
        root = self.tree({"linux/A-linux-vst3.tar.gz": b"t", "linux/A-flatpak-25.08.flatpak": b"f",
                          "windows/A-Setup.exe": b"e", "macos/A-macOS.pkg": b"p"})
        p = self.prod()
        self.assertEqual(INS.choose_plan(p, "linux", root).method, "vst3-tarball")
        self.assertEqual(INS.choose_plan(p, "linux", root, "auto", ext_installed=True).method, "flatpak-ext")
        self.assertEqual(INS.choose_plan(p, "linux", root, "flatpak").method, "flatpak-ext")
        self.assertEqual(INS.choose_plan(p, "linux", root, "native", ext_installed=True).method, "vst3-tarball")
        self.assertEqual(INS.choose_plan(p, "windows", root).method, "exe")
        self.assertEqual(INS.choose_plan(p, "macos", root).method, "pkg")
        self.assertEqual(INS.choose_plan(self.prod(kind="logue", install={"linux": "guided"}), "linux", root).method, "guided")
        empty = self.tree({"INSTALL.txt": b"x"})
        for s in ("linux", "windows", "macos"):
            self.assertEqual(INS.choose_plan(p, s, empty).method, "guided")

    def test_tarball_install_replaces_and_rolls_back(self):
        d = self.tmp()
        tar = d / "t.tar.gz"
        tar.write_bytes(make_vst3_tar("PunchPaw.vst3", b"new"))
        vst3 = d / "vst3"
        (vst3 / "PunchPaw.vst3").mkdir(parents=True)
        (vst3 / "PunchPaw.vst3" / "old.txt").write_text("old")
        (vst3 / "Other.vst3").mkdir()
        out = INS.install_vst3_tarball(tar, vst3)
        self.assertTrue((out / "Contents" / "x86_64-linux" / "PunchPaw.so").exists())
        self.assertFalse((out / "old.txt").exists())
        self.assertTrue((vst3 / "Other.vst3").exists(), "other plugins untouched")
        self.assertEqual(sorted(x.name for x in vst3.iterdir()), ["Other.vst3", "PunchPaw.vst3"], "no temp leftovers")

    def installer(self, zip_bytes, release_assets=None, system="linux", runner=None, sums_asset=None):
        d = self.tmp()
        name = "PunchPaw-v0.2.0.zip"
        routes = {"https://dl.test/" + name: (200, {}, zip_bytes)}
        t = FakeTransport(routes)
        client = GitHubClient(t, d / "cache")
        rel = R.parse_release(release_json("v0.2.0", [(name, zip_bytes)] if release_assets is None else release_assets))
        rec = I.Record(d / "rec.json")
        opened = []
        ins = INS.Installer(client, rec, system, d / "work", d / "vst3", d / "guided", runner=runner or (lambda *a, **k: None),
                            opener=opened.append)
        row = MD.Row(self.prod(), releases=[rel], installed=I.InstalledInfo("installed", "0.1.0"), status=MD.UPDATE)
        return d, ins, row, rec, opened

    def test_full_install_linux_verified(self):
        d, ins, row, rec, _ = self.installer(make_release_zip())
        res = ins.install(row)
        self.assertTrue(res["ok"])
        self.assertTrue((d / "vst3" / "PunchPaw.vst3" / "Contents" / "Resources" / "moduleinfo.json").exists())
        self.assertEqual(rec.get("PunchPaw")["version"], "0.2.0")
        self.assertFalse((d / "work" / "PunchPaw-v0.2.0").exists(), "work folder cleaned")

    def test_corrupt_file_inside_zip_is_refused_and_nothing_installed(self):
        d, ins, row, rec, _ = self.installer(make_release_zip(corrupt="linux/PunchPaw-linux-vst3.tar.gz"))
        with self.assertRaises(C.ChecksumError):
            ins.install(row)
        self.assertFalse((d / "vst3").exists() and any((d / "vst3").iterdir()))
        self.assertIsNone(rec.get("PunchPaw"))

    def test_zip_digest_mismatch_with_github_digest_is_refused(self):
        z = make_release_zip()
        d, ins, row, rec, _ = self.installer(z)
        row.latest.zip_asset().sha256 = "0" * 64
        with self.assertRaises(C.ChecksumError):
            ins.install(row)
        self.assertIsNone(rec.get("PunchPaw"))

    def test_release_without_any_checksum_is_refused(self):
        z = make_release_zip(sums=False)
        d, ins, row, rec, _ = self.installer(z)
        row.latest.zip_asset().sha256 = None
        with self.assertRaises(C.ChecksumError):
            ins.install(row)
        self.assertIsNone(rec.get("PunchPaw"))

    def test_separate_sums_asset_is_checked(self):
        z = make_release_zip(sums=False)
        name = "PunchPaw-v0.2.0.zip"
        d, ins, row, rec, _ = self.installer(z, release_assets=[(name, z), ("SHA256SUMS", b"")])
        row.latest.zip_asset().sha256 = None
        ins.client.t.routes["https://dl.test/SHA256SUMS"] = (200, {}, ("%s  %s\n" % ("0" * 64, name)).encode())
        with self.assertRaises(C.ChecksumError):
            ins.install(row)
        good = ("%s  %s\n" % (hashlib.sha256(z).hexdigest(), name)).encode()
        ins.client.t.routes["https://dl.test/SHA256SUMS"] = (200, {}, good)
        self.assertTrue(ins.install(row)["ok"])

    def test_windows_runs_exe_silently_and_records(self):
        calls = []

        def runner(cmd, **k):
            calls.append(cmd)
            class R: returncode, stdout, stderr = 0, "", ""
            return R()
        d, ins, row, rec, _ = self.installer(make_release_zip(), system="windows", runner=runner)
        res = ins.install(row)
        self.assertEqual(res["method"], "exe")
        self.assertTrue(calls[0][0].endswith("PunchPaw-Setup.exe") and "/SILENT" in calls[0])
        self.assertEqual(rec.get("PunchPaw")["version"], "0.2.0")

    def test_failed_installer_is_not_recorded(self):
        def runner(cmd, **k):
            class R: returncode, stdout, stderr = 5, "", "boom"
            return R()
        d, ins, row, rec, _ = self.installer(make_release_zip(), system="windows", runner=runner)
        with self.assertRaises(INS.InstallError):
            ins.install(row)
        self.assertIsNone(rec.get("PunchPaw"))

    def test_guided_when_zip_has_no_installer_opens_folder_and_never_runs(self):
        z = make_release_zip(files={"INSTALL.txt": b"do it by hand", "linux/install.sh": b"#!/bin/sh"})
        d, ins, row, rec, opened = self.installer(z, runner=lambda *a, **k: self.fail("must not run anything"))
        res = ins.install(row)
        self.assertEqual(res["method"], "guided")
        self.assertEqual(len(opened), 1)
        self.assertTrue((opened[0] / "INSTALL.txt").exists())
        self.assertIsNone(rec.get("PunchPaw"))

    def test_presets_folder_is_never_touched(self):
        d, ins, row, rec, _ = self.installer(make_release_zip())
        presets = d / "cfg" / "Studio 87" / "PunchPaw" / "presets"
        presets.mkdir(parents=True)
        (presets / "mine.json").write_text("keep")
        ins.install(row)
        self.assertEqual((presets / "mine.json").read_text(), "keep")


class PathTests(T):
    def test_brand_folders(self):
        h = Path("/h")
        self.assertEqual(P.data_dir("linux", {}, h), Path("/h/.local/share/Studio 87/Updater"))
        self.assertEqual(P.data_dir("windows", {"APPDATA": "C:/A"}, h), Path("C:/A/Studio 87/Updater"))
        self.assertEqual(P.data_dir("macos", {}, h), Path("/h/Library/Application Support/Studio 87/Updater"))
        self.assertEqual(P.user_vst3_dir("linux", {}, h), Path("/h/.vst3"))
        self.assertEqual(P.user_vst3_dir("macos", {}, h), Path("/h/Library/Audio/Plug-Ins/VST3"))


if __name__ == "__main__":
    unittest.main()


class DescribeTests(T):
    def test_texts_are_honest(self):
        p = M.Product(repo="a", name="A", kind="vst3", install={"linux": "vst3"})
        row = MD.Row(p, status=MD.UNKNOWN_INSTALL, installed=I.InstalledInfo("unknown"))
        self.assertEqual(MD.status_line(row), "Cannot tell if it is installed")
        self.assertEqual(MD.installed_text(row), "unknown")
        row.installed = I.InstalledInfo("installed", None)
        self.assertEqual(MD.status_line(row), "Installed, version not readable")
        row.installed = I.InstalledInfo("not-installed")
        self.assertEqual(MD.installed_text(row), "not installed")
        self.assertEqual(MD.method_text(row, "linux"), "VST3 (native or Flatpak)")
