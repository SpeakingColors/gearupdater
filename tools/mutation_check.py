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
    ("model.py", "        if p.checks_releases:\n            try:", "        if True:\n            try:"),
    ("model.py", "    return all(w in hay for w in words)", "    return any(w in hay for w in words)"),
    ("model.py", "    if tab == \"updates\":\n        return row.status == UPDATE", "    if tab == \"updates\":\n        return True"),
    ("model.py", "            if rels == MISSING:", "            if False:"),
    ("manifest.py", "        return {\"controller\": \"controller\", \"logue\": \"apps\"", "        return {\"controller\": \"fx\", \"logue\": \"apps\""),
    ("model.py", "    if upd:\n        return \"Update all (%d)\" % len(upd)", "    if ins:\n        return \"Update all (%d)\" % len(upd)"),
    ("model.py", "    return upd if upd else ins", "    return upd + ins"),
    ("model.py", "if upd and ins:\n        return \"Apply selected", "if upd or ins:\n        return \"Apply selected"),
    ("model.py", "return \"Installing\" if row.status in", "return \"Updating\" if row.status in"),
    ("model.py", "return row.status in (UPDATE, CURRENT)", "return row.status in (UPDATE,)"),
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
