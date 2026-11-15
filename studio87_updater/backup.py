"""Safe updates: keep the version that was installed before an update, so one click can put it back.

Scope, said plainly: this covers plugin bundles (a .vst3 folder) that the updater itself copies into a VST3 folder
(the Linux tarball route and the 'Just for me' zip route). A product's own Setup.exe, .pkg or Flatpak is run as it is;
the updater cannot take that back, so those rows have no Roll back button (a failed installer leaves the record untouched).

Rules: the last ONE version per product is kept, the whole backup folder is size capped (a bundle bigger than the cap
is simply not backed up, and the update says so), and Settings can clear it. Backups live in the updater's own data
folder, Studio 87/Gear Updater/backups/<repo>/, and never touch preset or data folders.
"""
import json
import os
import shutil
import time
from pathlib import Path

DEFAULT_CAP = 600 * 1024 * 1024      # bytes for all backups together


def tree_size(path):
    p = Path(path)
    if p.is_file():
        return p.stat().st_size
    total = 0
    for dirpath, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def tree_hashes(root):
    """{relative path: sha256} of every file under root, to prove a copied bundle equals the verified one."""
    from .checksum import sha256_file
    root = Path(root)
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            fp = Path(dirpath) / f
            out[fp.relative_to(root).as_posix()] = sha256_file(fp)
    return out


class BackupStore:
    def __init__(self, base, cap=DEFAULT_CAP):
        self.base = Path(base)
        self.cap = cap

    def _dir(self, repo):
        return self.base / repo

    def meta(self, repo):
        try:
            d = json.loads((self._dir(repo) / "meta.json").read_text(encoding="utf-8"))
            if isinstance(d, dict) and (self._dir(repo) / "bundle").is_dir():
                return d
        except (OSError, ValueError):
            pass
        return None

    def has(self, repo):
        return self.meta(repo) is not None

    def total_size(self):
        return tree_size(self.base) if self.base.is_dir() else 0

    def put(self, repo, bundle, version, tag, method, target, name=None):
        """Keep `bundle` (the folder that was installed before) as the single backup for repo, replacing an older backup.
        Returns True when kept, False when it did not fit the size cap (the old backup is left alone then)."""
        bundle = Path(bundle)
        size = tree_size(bundle)
        others = self.total_size() - (tree_size(self._dir(repo)) if self._dir(repo).is_dir() else 0)
        if size > self.cap or others + size > self.cap:
            return False
        d = self._dir(repo)
        new = self.base / (repo + ".new")
        shutil.rmtree(new, ignore_errors=True)
        try:
            new.mkdir(parents=True)
            shutil.copytree(bundle, new / "bundle")
            (new / "meta.json").write_text(json.dumps({"version": version, "tag": tag, "method": method, "target": str(target),
                                                        "name": name or bundle.name, "saved": time.time(), "size": size}), encoding="utf-8")
            shutil.rmtree(d, ignore_errors=True)
            os.replace(new, d)
        except OSError:
            shutil.rmtree(new, ignore_errors=True)
            return False
        return True

    def take(self, repo):
        """(bundle path, meta) of the backup, or (None, None). The caller restores from it, then calls drop."""
        m = self.meta(repo)
        return (self._dir(repo) / "bundle", m) if m else (None, None)

    def drop(self, repo):
        shutil.rmtree(self._dir(repo), ignore_errors=True)

    def clear(self):
        """Remove every backup. Returns the number of bytes freed."""
        n = self.total_size()
        shutil.rmtree(self.base, ignore_errors=True)
        return n

    def describe(self, repo):
        m = self.meta(repo)
        return "version %s" % m.get("version") if m and m.get("version") else ("the previous version" if m else "")
