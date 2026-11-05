import hashlib
import json
import time
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
        self.assertEqual(req.get_header("User-agent"), "Studio87-GearUpdater")
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

    def test_product_without_hints_is_found_by_display_name(self):
        d = self.tmp()
        p = M.Product(repo="X", name="Stretch Cat", kind="vst3", detect={})
        self.assertEqual(I.detect(p, "linux", I.Record(d / "r.json"), [d]).state, "not-installed")
        self.bundle(d, name="StretchCat", ver=None)
        info = I.detect(p, "linux", I.Record(d / "r.json"), [d])
        self.assertEqual((info.state, info.version), ("installed", None), "present but no version: never 'not installed'")

    def test_app_without_hints_and_nothing_found_is_unknown_not_missing(self):
        d = self.tmp()
        p = M.Product(repo="Z", name="Zed", kind="app", detect={})
        self.assertEqual(I.detect(p, "linux", I.Record(d / "r.json"), [d]).state, "unknown")

    def test_logue_unit_without_hints_stays_unknown(self):
        d = self.tmp()
        p = M.Product(repo="L", name="Sawwiden", kind="logue", detect={})
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
        self.assertEqual(P.data_dir("linux", {}, h), Path("/h/.local/share/Studio 87/Gear Updater"))
        self.assertEqual(P.data_dir("windows", {"APPDATA": "C:/A"}, h), Path("C:/A/Studio 87/Gear Updater"))
        self.assertEqual(P.data_dir("macos", {}, h), Path("/h/Library/Application Support/Studio 87/Gear Updater"))
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
        self.assertTrue(MD.status_line(row).startswith("Installed, version unknown"))
        self.assertEqual((row.sync, row.action_label), (True, "Update to sync"))
        row.installed = I.InstalledInfo("not-installed")
        self.assertEqual(MD.installed_text(row), "not installed")
        self.assertEqual(MD.method_text(row, "linux"), "VST3 (native or Flatpak)")


class MigrationTests(T):
    def test_old_updater_folder_is_copied_not_lost(self):
        h = self.tmp()
        old = P.data_dir("linux", {}, h).parent / "Updater"
        old.mkdir(parents=True)
        (old / "installed-versions.json").write_text('{"schema": 1, "products": {"a": {"version": "1.0.0"}}}')
        P.migrate_old_data("linux", {}, h)
        new = P.data_dir("linux", {}, h)
        self.assertEqual(new.name, "Gear Updater")
        self.assertEqual(I.Record(new / "installed-versions.json").get("a")["version"], "1.0.0")
        self.assertTrue((old / "installed-versions.json").exists(), "old copy stays")
        (new / "installed-versions.json").write_text("{}")
        P.migrate_old_data("linux", {}, h)
        self.assertEqual((new / "installed-versions.json").read_text(), "{}", "never overwrites the new folder")


class CatalogTests(T):
    def rows(self):
        m = M.load_manifest()
        out = []
        for p in m.products:
            out.append(MD.Row(p, status=MD.UPDATE if p.repo == "hairball" else MD.NOT_INSTALLED, installed=I.InstalledInfo("not-installed")))
        return out

    def test_category_mapping(self):
        by = {r.product.repo: r.product for r in self.rows()}
        self.assertEqual(by["SupurrrSaw-VST"].cat, "synth")
        self.assertEqual(by["PunchPaw"].cat, "fx")
        self.assertEqual(by["mx400-vst-linux"].cat, "controller")
        self.assertEqual(by["hypersaw-xd"].cat, "apps")
        self.assertEqual(by["whiskermix"].cat, "apps")
        self.assertEqual([k for k, _ in MD.TABS], ["updates", "all", "fx", "synth", "controller", "apps", "installed", "notinstalled"])

    def test_tabs(self):
        rows = self.rows()
        self.assertEqual(len(MD.filter_rows(rows, "all")), len(rows))
        self.assertEqual([r.product.repo for r in MD.filter_rows(rows, "updates")], ["hairball"])
        for tab in ("fx", "synth", "controller", "apps"):
            got = MD.filter_rows(rows, tab)
            self.assertTrue(got and all(r.product.cat == tab for r in got), tab)

    def test_search_by_name_kind_and_status(self):
        rows = self.rows()
        names = lambda q: [r.product.name for r in MD.filter_rows(rows, "all", q)]
        self.assertEqual(names("hairball"), ["Hairball"])
        self.assertIn("PunchPaw", names("PUNCH"))
        got = MD.filter_rows(rows, "all", "logue")
        self.assertTrue(got and all(r.product.kind == "logue" or r.product.cat == "apps" or "logue" in r.product.name.lower() for r in got))
        self.assertEqual(names("update available"), ["Hairball"])
        self.assertIn("Furchild", names("not installed"))
        self.assertEqual(names("hairball furchild"), [])
        self.assertEqual(len(names("   ")), len(rows))
        self.assertEqual(names("hair"), ["Hairball"])
        self.assertEqual([r.product.name for r in MD.filter_rows(rows, "fx", "hair")], ["Hairball"])
        self.assertEqual(MD.filter_rows(rows, "synth", "hair"), [])

    def test_exclusions_and_no_private_names(self):
        m = M.load_manifest()
        repos = {p.repo.lower() for p in m.products}
        for r in ("cat-ui", "claude-skills", ".github", "speakingcolors"):
            self.assertNotIn(r, repos)
            self.assertIn(r, m.ignore)
        out = M.merge_discovered(m, ["cat-ui", "claude-skills", ".github", "SpeakingColors", "a-new-public-repo"])
        self.assertEqual([p.repo for p in out][len(m.products):], ["a-new-public-repo"])
        root = Path(__file__).resolve().parents[1]
        banned = "place" + "holder" + "game"
        for f in root.rglob("*"):
            if f.is_file() and ".git" not in f.parts and f.suffix in (".py", ".json", ".md", ".txt", ".yml", ".html", ".iss", ".xml", ".desktop", ".applescript"):
                self.assertNotIn(banned, f.read_text(errors="ignore").lower(), str(f))

    def test_repo_returning_404_is_never_shown(self):
        t = FakeTransport({})
        c = GitHubClient(t, self.tmp(), now=lambda: 1000.0)
        p = M.Product(repo="gone-or-private", name="X", kind="vst3", install={"linux": "vst3"})
        rows, _ = MD.build_rows(c, [p], lambda p: I.InstalledInfo("not-installed"))
        self.assertEqual(rows, [])


class BulkLabelTests(T):
    def mk(self, repo, status):
        p = M.Product(repo=repo, name=repo, kind="vst3", install={"linux": "vst3"})
        r = MD.Row(p, status=status, installed=I.InstalledInfo("not-installed"))
        r.releases = [type("R", (), {"zip_asset": lambda self: object(), "version": "1", "tag": "v1"})()]
        return r

    def test_labels(self):
        u1, u2 = self.mk("a", MD.UPDATE), self.mk("b", MD.UPDATE)
        n1, n2 = self.mk("c", MD.NOT_INSTALLED), self.mk("d", MD.NOT_INSTALLED)
        cur = self.mk("e", MD.CURRENT)
        self.assertEqual(MD.selected_label([u1, u2]), "Update selected (2)")
        self.assertEqual(MD.selected_label([n1, n2]), "Install selected (2)")
        self.assertEqual(MD.selected_label([u1, n1, n2]), "Apply selected (1 update, 2 installs)")
        self.assertEqual(MD.selected_label([u1, u2, n1]), "Apply selected (2 updates, 1 install)")
        self.assertEqual(MD.selected_label([]), "Update selected")
        self.assertEqual(MD.selected_label([cur]), "Update selected")
        self.assertEqual(MD.all_label([u1, n1, n2, cur]), "Update all (1)")
        self.assertEqual(MD.all_label([n1, n2, cur]), "Install all (2)")
        self.assertEqual(MD.all_label([cur]), "Update all (0)")

    def test_only_updates_count_as_updates(self):
        u, n, cur = self.mk("a", MD.UPDATE), self.mk("c", MD.NOT_INSTALLED), self.mk("e", MD.CURRENT)
        self.assertEqual(MD.all_targets([u, n, cur]), [u])
        self.assertEqual(MD.all_targets([n, cur]), [n])
        upd, ins = MD.split_actions([u, n, cur])
        self.assertEqual((upd, ins), ([u], [n]))

    def test_confirm_and_progress_wording(self):
        u, n1, n2 = self.mk("a", MD.UPDATE), self.mk("c", MD.NOT_INSTALLED), self.mk("d", MD.NOT_INSTALLED)
        self.assertEqual(MD.confirm_title([n1, n2]), "Install 2 products?")
        self.assertEqual(MD.confirm_title([n1]), "Install 1 product?")
        self.assertEqual(MD.confirm_title([u, n1]), "Apply 1 update and 1 install?")
        self.assertEqual(MD.confirm_title([u, u]), "Update 2 products?")
        self.assertEqual(MD.confirm_button([n1, n2]), "Install 2")
        self.assertEqual(MD.confirm_button([u, n1]), "Apply 2")
        self.assertEqual(MD.confirm_button([u]), "Update 1")
        self.assertEqual((MD.progress_word(u), MD.progress_word(n1)), ("Updating", "Installing"))

    def test_installed_and_not_installed_tabs(self):
        rows = [self.mk("a", MD.UPDATE), self.mk("c", MD.NOT_INSTALLED), self.mk("e", MD.CURRENT)]
        self.assertEqual([r.product.repo for r in MD.filter_rows(rows, "installed")], ["a", "e"])
        self.assertEqual([r.product.repo for r in MD.filter_rows(rows, "notinstalled")], ["c"])


class DetectionLayoutTests(T):
    """Synthetic bundles in each OS's standard folders: presence apart from version, name matching, version order."""

    def prod(self, name="Stretch Cat", vst3="Stretch Cat", ext="StretchCat", **kw):
        return M.Product(repo="stretch-cat-vst", name=name, kind="vst3", detect={"vst3": vst3, "flatpak": ext, **kw})

    def bundle(self, d, stem, ver=None, plist=None):
        r = d / (stem + ".vst3") / "Contents" / "Resources"
        r.mkdir(parents=True)
        if ver:
            (r / "moduleinfo.json").write_text(json.dumps({"Version": ver}))
        if plist:
            import plistlib
            (d / (stem + ".vst3") / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": plist}))
        return d / (stem + ".vst3")

    def test_name_matching_display_vs_bundle(self):
        self.assertEqual(I.norm("Stretch Cat"), I.norm("StretchCat.vst3".replace(".vst3", "")))
        d = self.tmp()
        self.bundle(d, "StretchCat", "1.2.3")
        info = I.detect(self.prod(vst3="Stretch Cat"), "linux", I.Record(d / "r.json"), [d])
        self.assertEqual((info.state, info.version), ("installed", "1.2.3"))
        self.bundle(d, "Other Thing", "9.9.9")
        self.assertIsNone(I.scan_vst3([d], {I.norm("Nothing")}))

    def test_linux_layouts(self):
        home = self.tmp()
        sysdir = self.tmp()
        self.bundle(sysdir, "Stretch Cat", "0.5.0")
        info = I.detect(self.prod(), "linux", I.Record(home / "r.json"), [home / ".vst3", sysdir])
        self.assertEqual(info.version, "0.5.0")
        ids = ("ok", {I.EXT_PREFIX + "StretchCat"})
        info = I.detect(self.prod(), "linux", I.Record(home / "r.json"), [home / ".vst3"], ids, flatpak_version=lambda i: "0.7.0")
        self.assertEqual((info.state, info.version, info.source), ("installed", "0.7.0", "flatpak-info"))
        info = I.detect(self.prod(), "linux", I.Record(home / "r.json"), [home / ".vst3"], ids)
        self.assertEqual((info.state, info.version), ("installed", None))

    def test_windows_layout_and_registry(self):
        common = self.tmp()
        reg = {"Stretch Cat 0.4.0": "0.4.0"}
        info = I.detect(self.prod(), "windows", I.Record(common / "r.json"), [common / "VST3"], win_uninstall=reg)
        self.assertEqual((info.state, info.version, info.source), ("installed", "0.4.0", "inno-registry"))
        self.bundle(common / "VST3", "Stretch Cat", None)
        info = I.detect(self.prod(), "windows", I.Record(common / "r.json"), [common / "VST3"], win_uninstall={"Stretch Cat": None})
        self.assertEqual((info.state, info.version), ("installed", None))
        info = I.detect(self.prod(), "windows", I.Record(common / "r.json"), [common / "VST3"])
        self.assertEqual(info.state, "installed")
        self.assertEqual(I.detect(self.prod(), "windows", I.Record(common / "r.json"), [common / "nope"]).state, "not-installed")

    def test_macos_layout_plist_and_pkgutil(self):
        lib = self.tmp()
        self.bundle(lib, "Stretch Cat", None, plist="0.6.1")
        info = I.detect(self.prod(), "macos", I.Record(lib / "r.json"), [lib])
        self.assertEqual((info.version, info.source), ("0.6.1", "vst3-metadata"))
        empty = self.tmp()
        info = I.detect(self.prod(), "macos", I.Record(empty / "r.json"), [empty], mac_pkgs={"io.studio87.StretchCat": "0.6.2"})
        self.assertEqual((info.state, info.version, info.source), ("installed", "0.6.2", "pkgutil"))

    def test_version_source_order_record_first(self):
        d = self.tmp()
        self.bundle(d, "Stretch Cat", "0.1.0")
        rec = I.Record(d / "r.json")
        rec.set("stretch-cat-vst", "0.2.0", "v0.2.0", "vst3-tarball")
        self.assertEqual(I.detect(self.prod(), "linux", rec, [d]).version, "0.2.0")
        self.assertEqual(I.detect(self.prod(), "linux", rec, [self.tmp()]).state, "not-installed", "a record whose files are gone is stale")

    def test_pkgutil_and_registry_readers(self):
        class R:
            def __init__(self, out): self.returncode, self.stdout = 0, out
        def run(cmd, **k):
            if cmd[1] == "--pkgs":
                return R("com.apple.x\nio.studio87.StretchCat\n")
            return R("package-id: x\nversion: 0.9.0\n")
        self.assertEqual(I.read_pkgutil(run), {"io.studio87.StretchCat": "0.9.0"})
        self.assertEqual(I.read_inno_uninstall(winreg=type("W", (), {"HKEY_LOCAL_MACHINE": 1, "HKEY_CURRENT_USER": 2,
                         "OpenKey": staticmethod(lambda *a: (_ for _ in ()).throw(OSError()))})), {})


from studio87_updater import mode as MODE


class ModeTests(T):
    def test_defaults_and_effective_mode(self):
        self.assertEqual(MODE.default_mode("windows"), "all-users")
        self.assertEqual(MODE.default_mode("macos"), "all-users")
        self.assertEqual(MODE.default_mode("linux"), "just-me")
        self.assertEqual(MODE.effective_mode("linux", "all-users"), "just-me", "Linux never needs admin")
        self.assertEqual(MODE.effective_mode("windows", ""), "all-users")
        self.assertEqual(MODE.effective_mode("windows", "just-me"), "just-me")
        self.assertEqual(MODE.effective_mode("macos", "junk"), "all-users")

    def test_user_vst3_folders_match_steinberg(self):
        h = Path("/h")
        self.assertEqual(MODE.user_vst3_dir("windows", {"LOCALAPPDATA": "/h/AppData/Local"}, h), Path("/h/AppData/Local/Programs/Common/VST3"))
        self.assertEqual(MODE.user_vst3_dir("windows", {}, h), Path("/h/AppData/Local/Programs/Common/VST3"))
        self.assertEqual(MODE.user_vst3_dir("macos", {}, h), Path("/h/Library/Audio/Plug-Ins/VST3"))
        self.assertEqual(MODE.user_vst3_dir("linux", {}, h), Path("/h/.vst3"))

    def test_startup_elevation_only_windows_all_users_once(self):
        self.assertEqual(MODE.startup_elevation("windows", "all-users", False), "relaunch")
        self.assertEqual(MODE.startup_elevation("windows", "all-users", True), "none")
        self.assertEqual(MODE.startup_elevation("windows", "all-users", False, already_tried=True), "none", "no relaunch loop if UAC is declined")
        self.assertEqual(MODE.startup_elevation("windows", "just-me", False), "none", "just-me starts normally")
        self.assertEqual(MODE.startup_elevation("macos", "all-users", False), "none")
        self.assertEqual(MODE.startup_elevation("linux", "all-users", False), "none")

    def test_batch_has_at_most_one_prompt(self):
        b = MODE.batch_plan("macos", "all-users", ["pkg"] * 50)
        self.assertEqual(b["prompts"], 1)
        self.assertEqual(len(b["elevated"]), 50)
        self.assertEqual(MODE.batch_plan("macos", "just-me", ["pkg", "vst3-zip"])["prompts"], 0)
        self.assertEqual(MODE.batch_plan("windows", "all-users", ["exe"] * 50)["prompts"], 0, "the app itself is already elevated")
        self.assertEqual(MODE.batch_plan("linux", "just-me", ["vst3-tarball", "flatpak-ext"])["prompts"], 0)
        self.assertFalse(MODE.method_needs_admin("windows", "just-me", "exe"))
        self.assertTrue(MODE.method_needs_admin("windows", "all-users", "exe"))


class InstallModeTests(T):
    def prod(self):
        return M.Product(repo="x", name="X", kind="vst3", install={"windows": "exe", "macos": "pkg", "linux": "vst3"})

    def tree(self, files):
        d = self.tmp()
        for f in files:
            p = d / f
            p.parent.mkdir(parents=True, exist_ok=True)
            if f.endswith(".vst3"):
                (p / "Contents").mkdir(parents=True)
                (p / "Contents" / "x.bin").write_bytes(b"1")
            else:
                p.write_bytes(b"x")
        return d

    def test_plan_per_mode(self):
        root = self.tree(["windows/Setup.exe", "macos/X.pkg"])
        self.assertEqual(INS.choose_plan(self.prod(), "windows", root, mode="all-users").method, "exe")
        self.assertEqual(INS.choose_plan(self.prod(), "windows", root, mode="just-me").method, "exe-user")
        self.assertEqual(INS.choose_plan(self.prod(), "macos", root, mode="all-users").method, "pkg")
        self.assertEqual(INS.choose_plan(self.prod(), "macos", root, mode="just-me").method, "pkg-user")
        root2 = self.tree(["windows/Setup.exe", "windows/X.vst3"])
        self.assertEqual(INS.choose_plan(self.prod(), "windows", root2, mode="just-me").method, "vst3-zip")
        self.assertEqual(INS.choose_plan(self.prod(), "windows", root2, mode="all-users").method, "exe")

    def test_user_commands_need_no_admin(self):
        calls = []

        class R:
            returncode, stdout, stderr = 0, "", ""
        run = lambda cmd, **k: (calls.append(cmd), R())[1]
        INS.run_plan(INS.Plan("exe-user", Path("S.exe")), "windows", run)
        INS.run_plan(INS.Plan("pkg-user", Path("X.pkg")), "macos", run)
        self.assertIn("/CURRENTUSER", calls[0])
        self.assertEqual(calls[1][-2:], ["-target", "CurrentUserHomeDirectory"])

    def test_vst3_zip_install_records_files_and_uninstall_removes_exactly_them(self):
        root = self.tree(["windows/X.vst3"])
        dest = self.tmp() / "VST3"
        t = INS.install_vst3_zip(root / "windows" / "X.vst3", dest)
        files = INS.bundle_files(t)
        self.assertTrue(files and all(Path(f).is_file() for f in files))
        other = dest / "Other.vst3"
        other.mkdir()
        (other / "keep").write_bytes(b"k")
        rec = I.Record(self.tmp() / "r.json")
        rec.set("x", "1.0.0", "v1.0.0", "vst3-zip", files)
        inst = INS.Installer(None, rec, "windows", self.tmp(), dest, self.tmp())
        n = inst.uninstall_recorded("x")
        self.assertEqual(n, len(files))
        self.assertFalse((dest / "X.vst3").exists())
        self.assertTrue((other / "keep").exists(), "files that were not recorded are never removed")
        self.assertIsNone(rec.get("x"))

    def test_elevated_pkg_script_runs_every_pkg_in_one_helper(self):
        sc = INS.elevated_pkg_script([Path("/a/one.pkg"), Path("/a/it's.pkg")])
        self.assertEqual(sc.count("/usr/sbin/installer"), 2)
        cmd = INS.elevation_command(Path("/t/s.sh"))
        self.assertEqual(cmd[0], "osascript")
        self.assertIn("with administrator privileges", cmd[2])

    def test_staged_pkgs_are_installed_in_one_elevated_call(self):
        stage = self.tmp()
        calls = []

        class R:
            returncode, stdout, stderr = 0, "", ""
        run = lambda cmd, **k: (calls.append(cmd), R())[1]
        rec = I.Record(self.tmp() / "r.json")
        inst = INS.Installer(None, rec, "macos", self.tmp(), self.tmp(), self.tmp(), runner=run, stage_dir=stage)
        for n in range(5):
            f = stage / ("p%d.pkg" % n)
            f.write_bytes(b"x")
            inst.staged.append(("r%d" % n, "N", f, "1.0", "v1"))
        out = inst.finish_batch()
        self.assertEqual(len(calls), 1, "one administrator prompt for the whole batch")
        self.assertEqual(len(out), 5)
        self.assertTrue(all(ok for ok, _ in out.values()))
        self.assertEqual(rec.get("r3")["version"], "1.0")

    def test_failed_elevated_batch_records_nothing(self):
        stage = self.tmp()

        class R:
            returncode, stdout, stderr = 1, "", "user cancelled"
        rec = I.Record(self.tmp() / "r.json")
        inst = INS.Installer(None, rec, "macos", self.tmp(), self.tmp(), self.tmp(), runner=lambda cmd, **k: R(), stage_dir=stage)
        f = stage / "p.pkg"
        f.write_bytes(b"x")
        inst.staged.append(("r1", "N", f, "1.0", "v1"))
        out = inst.finish_batch()
        self.assertFalse(out["r1"][0])
        self.assertIsNone(rec.get("r1"))

    def test_norm_keeps_digits(self):
        self.assertEqual(I.norm("JPurrr-8000"), "jpurrr8000")
        self.assertNotEqual(I.norm("MX400"), I.norm("MX"))

    def test_sync_row_is_not_part_of_update_all_but_counts_when_selected(self):
        p = M.Product(repo="s", name="S", kind="vst3", install={"linux": "vst3"})
        row = MD.Row(p, status=MD.UNKNOWN_INSTALL, installed=I.InstalledInfo("installed", None))
        row.releases = [type("R", (), {"zip_asset": lambda self: object(), "version": "1", "tag": "v1"})()]
        self.assertEqual(MD.all_targets([row]), [])
        self.assertEqual(MD.selected_label([row]), "Update selected (1)")
        self.assertEqual(MD.progress_word(row), "Updating")
        self.assertEqual(len(MD.filter_rows([row], "installed")), 1)
        self.assertEqual(MD.filter_rows([row], "notinstalled"), [])


from studio87_updater import shots as SH


class ShotTests(T):
    def test_candidates_use_head_and_png_then_jpg(self):
        u = SH.candidate_urls("SpeakingColors", "Hairball")
        self.assertEqual(u[0], "https://raw.githubusercontent.com/SpeakingColors/Hairball/HEAD/docs/screenshot.png")
        self.assertTrue(u[1].endswith("docs/screenshot.jpg"))

    def test_readme_image_skips_icons_svgs_badges_and_foreign_hosts(self):
        md = ('<img src="assets/icon.svg" width=64>\n![badge](https://img.shields.io/x.png)\n![ext](https://example.com/a.png)\n'
              '![Kick Kitten](docs/manual-shot.png)\n')
        self.assertEqual(SH.readme_image(md, "SpeakingColors", "KickKitten"),
                         "https://raw.githubusercontent.com/SpeakingColors/KickKitten/HEAD/docs/manual-shot.png")
        self.assertIsNone(SH.readme_image('<img src="assets/icon.svg">', "o", "r"))
        self.assertIsNone(SH.readme_image("", "o", "r"))

    def test_service_falls_back_to_readme_then_none(self):
        from studio87_updater.service import Service
        h = self.tmp()
        base = "https://raw.githubusercontent.com/SpeakingColors/Kick/HEAD/"
        t = FakeTransport({base + "README.md": (200, {}, b"![x](docs/shot.png)"), base + "docs/shot.png": (200, {}, b"PNGDATA")})
        svc = Service(system="linux", env={"XDG_DATA_HOME": str(h / "d"), "XDG_CACHE_HOME": str(h / "c")}, home=h, transport=t,
                      flatpak_probe=lambda: ("absent", set()))
        p = M.Product(repo="Kick", name="Kick", kind="vst3")
        self.assertEqual(svc.screenshot(p), b"PNGDATA")
        self.assertNotIn("Kick", svc.no_shot)
        q = M.Product(repo="Nothing", name="N", kind="vst3")
        self.assertIsNone(svc.screenshot(q))
        self.assertIn("Nothing", svc.no_shot)


from studio87_updater import catalog as CAT
from studio87_updater.service import Service


def _cat(gen=1_700_000_000, **products):
    return json.dumps({"schema": 1, "generated_epoch": gen, "public_repos": ["PunchPaw", "NewOne"], "products": products})


def _entry(tag="v0.2.0"):
    return {"status": "ok", "thumb": True, "releases": [{"tag_name": tag, "name": tag, "body": "x", "published_at": "2026-11-01T00:00:00Z",
            "prerelease": True, "html_url": "u", "assets": [{"name": "P-%s.zip" % tag, "size": 5, "browser_download_url": "d", "digest": "sha256:" + "a" * 64}]}]}


class CatalogFileTests(T):
    def test_parse_and_lookup(self):
        c = CAT.parse_catalog(_cat(PunchPaw=_entry(), Gone={"status": "missing"}))
        self.assertEqual(c.releases("PunchPaw")[0].tag, "v0.2.0")
        self.assertEqual(c.releases("PunchPaw")[0].zip_asset().sha256, "a" * 64)
        self.assertEqual(c.releases("Gone"), CAT.MISSING)
        self.assertIsNone(c.releases("Unknown"))
        self.assertTrue(c.has_thumb("PunchPaw"))

    def test_bad_catalogs_are_refused(self):
        for bad in ("nope", "{}", json.dumps({"schema": 2, "products": {}, "generated_epoch": 1}),
                    json.dumps({"schema": 1, "products": {}}), json.dumps({"schema": 1, "products": [], "generated_epoch": 1})):
            with self.assertRaises(ValueError):
                CAT.parse_catalog(bad)

    def test_staleness_text(self):
        c = CAT.parse_catalog(_cat(gen=1000))
        self.assertFalse(c.stale(1000 + 3 * 3600))
        self.assertTrue(c.stale(1000 + 10 * 3600))
        txt, stale = CAT.describe(c, 1000 + 3600, local_time=time.gmtime)
        self.assertEqual((txt, stale), ("catalog updated at 00:16", False))
        txt, stale = CAT.describe(c, 1000 + 12 * 3600, local_time=time.gmtime)
        self.assertTrue(stale and "12 hours old" in txt)

    def test_catalog_answers_without_any_api_request(self):
        c = CAT.parse_catalog(_cat(PunchPaw=_entry("v0.2.0")))
        t = FakeTransport({})
        cl = GitHubClient(t, self.tmp(), now=lambda: 1000.0)
        p = M.Product(repo="PunchPaw", name="PunchPaw", kind="vst3", install={"linux": "vst3"}, detect={"vst3": "PunchPaw"})
        rows, notice = MD.build_rows(cl, [p], lambda p: I.InstalledInfo("installed", "0.1.0"), True, catalog=c)
        self.assertEqual(t.log, [], "no request of any kind")
        self.assertEqual((rows[0].status, rows[0].latest.tag), (MD.UPDATE, "v0.2.0"))

    def test_private_repo_in_catalog_is_never_shown(self):
        c = CAT.parse_catalog(_cat(Gone={"status": "missing"}))
        p = M.Product(repo="Gone", name="G", kind="vst3", install={"linux": "vst3"})
        rows, _ = MD.build_rows(GitHubClient(FakeTransport({}), self.tmp()), [p], lambda p: None, True, catalog=c)
        self.assertEqual(rows, [])

    def _svc(self, routes):
        h = self.tmp()
        t = FakeTransport(routes)
        return Service(system="linux", env={"XDG_DATA_HOME": str(h / "d"), "XDG_CACHE_HOME": str(h / "c")}, home=h, transport=t,
                       flatpak_probe=lambda: ("absent", set())), t

    def test_service_uses_catalog_then_falls_back_to_api(self):
        url = CAT.catalog_url("https://raw.githubusercontent.com", "SpeakingColors")
        svc, t = self._svc({url: (200, {"etag": "e1"}, _cat(gen=int(time.time()), PunchPaw=_entry()).encode())})
        rows, _ = svc.check()
        by = {r.product.repo: r for r in rows}
        self.assertEqual(by["PunchPaw"].latest.tag, "v0.2.0")
        api = [u for u, _h in t.log if u.startswith("https://api.github.com/repos/SpeakingColors/PunchPaw")]
        self.assertEqual(api, [], "PunchPaw came from the catalog")
        self.assertIn("catalog updated", svc.catalog_text()[0])
        # unreachable catalog: nothing parsed, the API is used as before
        svc2, t2 = self._svc({})
        svc2.check()
        self.assertIsNone(svc2.catalog)
        self.assertTrue([u for u, _h in t2.log if u.startswith("https://api.github.com/repos/")])
        self.assertEqual(svc2.catalog_text(), ("", False))

    def test_refresh_one_uses_the_api_directly(self):
        url = CAT.catalog_url("https://raw.githubusercontent.com", "SpeakingColors")
        api = "https://api.github.com/repos/SpeakingColors/PunchPaw/releases?per_page=6"
        svc, t = self._svc({url: (200, {}, _cat(PunchPaw=_entry("v0.2.0")).encode()),
                            api: (200, {}, json.dumps([_entry("v0.9.0")["releases"][0]]).encode())})
        svc.check()
        p = next(p for p in svc.products if p.repo == "PunchPaw")
        row = svc.refresh_one(p)
        self.assertEqual(row.latest.tag, "v0.9.0")


class ShotSkipTests(unittest.TestCase):
    def test_readme_logo_and_badge_images_are_skipped(self):
        txt = "![logo](docs/logo.png) ![b](https://raw.githubusercontent.com/o/r/HEAD/x/badge.png) ![real](docs/window.png)"
        self.assertTrue(SH.readme_image(txt, "o", "r").endswith("docs/window.png"))
        self.assertIsNone(SH.readme_image("![logo](docs/logo.png)", "o", "r"))
