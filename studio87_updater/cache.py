"""Offline mode: what is kept on disk, how big it may get, and how to clear it.

Scope (decided with the user): ONLY the catalog, the per-product release info and the thumbnails/screenshots are cached for
offline use (the GitHubClient already stores every answer by URL with its ETag, that is the cache). Plugin files are NOT
cached for offline use: the only plugin file kept is a zip that was fully downloaded but not yet installed (a failed or
declined install), so Retry or an offline install does not need the network again; it is removed once the install worked.

The cache is size capped (oldest answers go first, the catalog itself is kept as long as possible) and Settings can clear it.
"""
import json
import os
import time
from pathlib import Path

DEFAULT_CAP = 60 * 1024 * 1024            # bytes for saved answers and thumbnails
ZIP_MAX_AGE = 7 * 24 * 3600               # unfinished downloads and ready-but-uninstalled zips are dropped after a week
ZIP_CAP = 2 * 1024 * 1024 * 1024


def _entries(d):
    """{stem: [files]} for the client's cache folder (key.body, key.meta)."""
    out = {}
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        stem = n.split(".", 1)[0]
        out.setdefault(stem, []).append(Path(d) / n)
    return out


def _size(files):
    t = 0
    for f in files:
        try:
            t += f.stat().st_size
        except OSError:
            pass
    return t


class CacheManager:
    def __init__(self, github_dir, zip_dir=None, cap=DEFAULT_CAP, now=time.time):
        self.dir, self.zip_dir, self.cap, self.now = Path(github_dir), Path(zip_dir) if zip_dir else None, cap, now

    def size(self):
        return sum(_size(fs) for fs in _entries(self.dir).values())

    def _meta(self, files):
        for f in files:
            if f.name.endswith(".meta"):
                try:
                    return json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return {}
        return {}

    def prune(self):
        """Delete the oldest saved answers until the cache fits the cap. Returns bytes freed."""
        ents = _entries(self.dir)
        total = sum(_size(fs) for fs in ents.values())
        if total <= self.cap:
            return 0
        rank = []
        for stem, fs in ents.items():
            m = self._meta(fs)
            keep = "catalog.json" in str(m.get("url", ""))
            rank.append((1 if keep else 0, m.get("saved", 0), stem))
        rank.sort()
        freed = 0
        for _k, _saved, stem in rank:
            if total - freed <= self.cap:
                break
            for f in ents[stem]:
                try:
                    n = f.stat().st_size
                    f.unlink()
                    freed += n
                except OSError:
                    pass
        return freed

    def clear(self):
        """Remove every saved answer, catalog, release info and thumbnail. Returns bytes freed."""
        freed = 0
        for fs in _entries(self.dir).values():
            for f in fs:
                try:
                    n = f.stat().st_size
                    f.unlink()
                    freed += n
                except OSError:
                    pass
        return freed

    def prune_downloads(self):
        """Drop old unfinished downloads and zips that were never installed, and keep the folder under its cap."""
        if self.zip_dir is None or not self.zip_dir.is_dir():
            return 0
        files = []
        for dirpath, _d, names in os.walk(self.zip_dir):
            for n in names:
                p = Path(dirpath) / n
                try:
                    st = p.stat()
                    files.append((st.st_mtime, st.st_size, p))
                except OSError:
                    pass
        freed, total = 0, sum(s for _m, s, _p in files)
        for m, s, p in sorted(files):
            if self.now() - m > ZIP_MAX_AGE or total - freed > ZIP_CAP:
                try:
                    p.unlink()
                    freed += s
                except OSError:
                    pass
        for dirpath, _d, _n in os.walk(self.zip_dir, topdown=False):
            try:
                os.rmdir(dirpath) if Path(dirpath) != self.zip_dir else None
            except OSError:
                pass
        return freed
