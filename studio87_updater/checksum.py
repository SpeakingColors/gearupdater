"""SHA256 checks and safe archive handling. Refuses on any mismatch."""
import hashlib
import os
import re
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


class ChecksumError(Exception):
    pass


class UnsafeArchive(Exception):
    pass


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


_LINE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")


def parse_sums(text):
    """Parse sha256sum output into {normalised path: lowercase hex}."""
    out = {}
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if m:
            out[norm_path(m.group(2))] = m.group(1).lower()
    return out


def norm_path(p):
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def check_digest(path, expected_hex, label="file"):
    got = sha256_file(path)
    if got.lower() != str(expected_hex).lower():
        raise ChecksumError("%s does not match its SHA256 (expected %s, got %s)" % (label, expected_hex, got))
    return True


def verify_tree(root, sums, required=()):
    """Every file listed in sums must exist under root and match; every required file must be listed."""
    root = Path(root)
    if not sums:
        raise ChecksumError("SHA256SUMS is empty")
    for rel in required:
        if norm_path(rel) not in sums:
            raise ChecksumError("%s is not listed in SHA256SUMS" % rel)
    for rel, want in sums.items():
        p = (root / rel)
        if not p.is_file():
            raise ChecksumError("%s is listed in SHA256SUMS but missing from the download" % rel)
        got = sha256_file(p)
        if got != want:
            raise ChecksumError("%s does not match SHA256SUMS (expected %s, got %s)" % (rel, want, got))
    return True


def _inside(dest, name):
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or (p.parts and p.parts[0].endswith(":")):
        return False
    target = os.path.realpath(os.path.join(dest, *p.parts))
    return target == os.path.realpath(dest) or target.startswith(os.path.realpath(dest) + os.sep)


def safe_extract_zip(zip_path, dest):
    """Extract a zip without path traversal. Returns the single top-level folder, or dest."""
    dest = str(dest)
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if not _inside(dest, info.filename):
                raise UnsafeArchive("unsafe path in zip: %s" % info.filename)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UnsafeArchive("symlink in zip: %s" % info.filename)
        z.extractall(dest)
    tops = [p for p in Path(dest).iterdir()]
    if len(tops) == 1 and tops[0].is_dir():
        return tops[0]
    return Path(dest)


def safe_extract_tar(tar_path, dest, top_suffix=".vst3"):
    """Extract a tarball whose members all live under one `<name>.vst3` folder. No links, no traversal."""
    dest = str(dest)
    os.makedirs(dest, exist_ok=True)
    tops = set()
    with tarfile.open(tar_path, "r:*") as t:
        members = t.getmembers()
        for m in members:
            if not _inside(dest, m.name):
                raise UnsafeArchive("unsafe path in tarball: %s" % m.name)
            if not (m.isfile() or m.isdir()):
                raise UnsafeArchive("tarball member is not a plain file or folder: %s" % m.name)
            parts = PurePosixPath(m.name).parts
            if not parts:
                continue
            tops.add(parts[0] if parts[0] != "." else (parts[1] if len(parts) > 1 else "."))
        tops.discard(".")
        if len(tops) != 1 or not next(iter(tops)).endswith(top_suffix):
            raise UnsafeArchive("tarball must contain exactly one %s folder, found: %s" % (top_suffix, sorted(tops)))
        for m in members:
            m.mode = (m.mode & 0o755) | 0o600 | (0o100 if m.isdir() else 0)
        try:
            t.extractall(dest, members=members, filter="data")
        except TypeError:   # Python before 3.12 has no extraction filters; the checks above already ran
            t.extractall(dest, members=members)
    return Path(dest) / next(iter(tops))
