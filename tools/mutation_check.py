#!/usr/bin/env python3
"""Proves the tests catch broken code: applies one deliberate bug at a time to the core, runs the
tests, and requires them to FAIL. Restores every file afterwards. Exit 1 if any bug slips through."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "studio87_updater"
MUTATIONS = [
    ("version.py", "return -1 if pa[0] < pb[0] else 1", "return 1 if pa[0] < pb[0] else -1"),
    ("version.py", "    if pa[1] is None:      # 1.0.0 is newer than 1.0.0-rc1\n        return 1", "    if pa[1] is None:\n        return -1"),
    ("version.py", "return None if c is None else c < 0", "return None if c is None else c <= 0"),
    ("checksum.py", "if got.lower() != str(expected_hex).lower():", "if False:"),
    ("checksum.py", "        if got != want:", "        if False:"),
    ("checksum.py", "        if not p.is_file():\n            raise ChecksumError", "        if False:\n            raise ChecksumError"),
    ("checksum.py", "def _inside(dest, name):\n", "def _inside(dest, name):\n    return True\n"),
    ("checksum.py", "if not (m.isfile() or m.isdir()):", "if False:"),
    ("checksum.py", "if len(tops) != 1 or not next(iter(tops)).endswith(top_suffix):", "if False:"),
    ("install.py", "    if not checked:\n        raise C.ChecksumError", "    if False:\n        raise C.ChecksumError"),
    ("install.py", "C.verify_tree(root, sums)", "pass"),
    ("install.py", "C.check_digest(zip_path, asset.sha256,", "(lambda *a: True)(zip_path, asset.sha256,"),
    ("install.py", "            self.record.set(p.repo, ver, rel.tag, plan.method, paths)", "            pass"),
    ("install.py", "    if r.returncode != 0:", "    if False:"),
    ("installed.py", "return InstalledInfo(\"not-installed\", None, \"scan\", \"\")", "return InstalledInfo(\"installed\", None, \"scan\", \"\")"),
    ("installed.py", "return InstalledInfo(\"unknown\", None, \"\", \"no way to detect this product yet\")", "return InstalledInfo(\"not-installed\", None, \"\", \"\")"),
    ("github.py", "headers[\"If-None-Match\"] = meta[\"etag\"]", "pass"),
    ("github.py", "raise RateLimited(self.reset)\n        headers", "pass\n        headers"),
    ("github.py", "h.get(\"x-ratelimit-remaining\") == \"0\"", "False"),
    ("model.py", "return UPDATE if upd else CURRENT", "return CURRENT if upd else UPDATE"),
    ("model.py", "        elif p.checks_releases:\n            try:", "        elif True:\n            try:"),
    ("model.py", "    return all(w in hay for w in words)", "    return any(w in hay for w in words)"),
    ("model.py", "    if tab == \"updates\":\n        return row.status == UPDATE", "    if tab == \"updates\":\n        return True"),
    ("model.py", "            if rels == MISSING:", "            if False:"),
    ("manifest.py", "        return {\"controller\": \"controller\", \"logue\": \"apps\"", "        return {\"controller\": \"fx\", \"logue\": \"apps\""),
    ("model.py", "    if upd:\n        return \"Update all (%d)\" % len(upd)", "    if ins:\n        return \"Update all (%d)\" % len(upd)"),
    ("model.py", "    return upd if upd else ins", "    return upd + ins"),
    ("model.py", "if upd and ins:\n        return \"Apply selected", "if upd or ins:\n        return \"Apply selected"),
    ("model.py", "return \"Installing\" if row.status in", "return \"Updating\" if row.status in"),
    ("model.py", "return row.status in (UPDATE, CURRENT)", "return row.status in (UPDATE,)"),
    ("catalog.py", "return self.age_seconds(now) > STALE_AFTER", "return self.age_seconds(now) < STALE_AFTER"),
    ("catalog.py", "d.get(\"schema\") != SCHEMA", "d.get(\"schema\") == SCHEMA"),
    ("model.py", "if p.checks_releases and cat_rels is not None:", "if False:"),
    ("mode.py", "return \"all-users\" if system in (\"windows\", \"macos\") else \"just-me\"", "return \"all-users\""),
    ("mode.py", "    if mode != \"all-users\":\n        return False", "    if False:\n        return False"),
    ("mode.py", "return {\"direct\": [m for m in methods if m not in elevated], \"elevated\": elevated, \"prompts\": 1}", "return {\"direct\": [m for m in methods if m not in elevated], \"elevated\": elevated, \"prompts\": len(elevated)}"),
    ("mode.py", "    if is_admin:\n        return {\"direct\": list(methods), \"elevated\": [], \"prompts\": 0}", "    if False:\n        return {\"direct\": list(methods), \"elevated\": [], \"prompts\": 0}"),
    ("installed.py", "if bundle is None and not found_ext and not win_hit and not pkg_hit:", "if bundle is None:"),
    ("installed.py", "for ch in (s or \"\").lower() if ch.isalnum()", "for ch in (s or \"\").lower() if ch.isalpha()"),
    ("installed.py", "    if rec_v:\n        return InstalledInfo(\"installed\", rec_v, \"install-record\", where)", "    if False:\n        return InstalledInfo(\"installed\", rec_v, \"install-record\", where)"),
    ("model.py", "self.installed is not None and self.installed.state == \"installed\"", "self.installed is not None and self.installed.state == \"unknown\""),
    ("shots.py", "any(w in url.lower() for w in SKIP_WORDS)", "False"),
    ("install.py", ", \"/SP-\", \"/CURRENTUSER\"]", ", \"/SP-\"]"),
    ("elevation.py", "if sha256_of(j.file) != j.sha256.lower():", "if False:"),
    ("elevation.py", "if kind not in KINDS or not isinstance(fname, str)", "if not isinstance(fname, str)"),
    ("elevation.py", "if fname != os.path.basename(fname) or fname in (\"\", \".\", \"..\") or \"/\" in fname or \"\\\\\" in fname:", "if False:"),
    ("elevation.py", "if len(sha) != 64 or any(", "if False and any("),
    ("elevation.py", "            if r.returncode != 0:\n                tail", "            if False:\n                tail"),
    ("install.py", "            if B.tree_hashes(target) != expected:", "            if False:"),
    ("install.py", "            if old_in_place:\n                os.replace(old, target)\n            if isinstance", "            if False:\n                os.replace(old, target)\n            if isinstance"),
    ("install.py", "        if old_in_place:\n            if keep is not None:", "        if False:\n            if keep is not None:"),
    ("backup.py", "if size > self.cap or others + size > self.cap:", "if False:"),
    ("github.py", "            headers[\"Range\"] = \"bytes=%d-\" % start", "            pass"),
    ("github.py", "            sleep(backoff * (2 ** (attempt - 1)))", "            pass"),
    ("github.py", "            if attempt > retries:\n                raise err", "            if False:\n                raise err"),
    ("auth.py", "                self._expire()        # expired refresh token", "                pass        # expired refresh token"),
    ("auth.py", "    if not hmac.compare_digest(", "    if False and not hmac.compare_digest("),
    ("auth.py", "        if self.keyring.available():\n            return \"keychain\"\n        return \"file\"", "        if False:\n            return \"keychain\"\n        return \"file\""),
    ("link.py", "if u.netloc.lower() != \"open\" or", "if False or"),
    ("link.py", "            if _REPO.match(v):", "            if True:"),
    ("link.py", "        product = by_lower.get(product.lower())", "        pass"),
    ("cache.py", "        if total <= self.cap:\n            return 0", "        if True:\n            return 0"),
    ("batch.py", "        except Exception as e:                       # one product", "        except KeyboardInterrupt as e:                       # one product"),
    ("selfupdate.py", "if r.zip_asset() is not None and V.is_update(current, r.tag):", "if r.zip_asset() is not None:"),
    ("releases.py", "if not d.get(\"draft\")", "if True"),
    ("manifest.py", "        if repo.lower() in seen:", "        if False:"),
    ("manifest.py", "        if low in known or low in manifest.ignore:", "        if low in known:"),
]


def run_tests():
    return subprocess.run([sys.executable, "-m", "unittest", "discover", "tests"], cwd=ROOT,
                          capture_output=True, text=True).returncode


def main():
    if run_tests() != 0:
        print("tests must pass on the real code first")
        return 2
    survivors = []
    for fname, old, new in MUTATIONS:
        path = PKG / fname
        src = path.read_text()
        if old not in src:
            print("STALE mutation (text not found): %s: %s" % (fname, old[:50]))
            survivors.append((fname, old))
            continue
        path.write_text(src.replace(old, new, 1))
        try:
            rc = run_tests()
        finally:
            path.write_text(src)
        print("%-9s %-60s %s" % ("caught" if rc != 0 else "SURVIVED", (fname + ": " + old.strip().splitlines()[0])[:60], ""))
        if rc == 0:
            survivors.append((fname, old))
    print("\n%d of %d deliberate bugs caught" % (len(MUTATIONS) - len(survivors), len(MUTATIONS)))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
