"""Find out what is really installed. Never guesses: 'not installed' and 'unknown' are shown honestly.

Sources, in order of trust:
  1. the VST3 bundle's own metadata (Contents/Resources/moduleinfo.json, or Info.plist on macOS)
  2. the installed-versions file this updater writes after a successful install, accepted only
     while the thing it installed is still there
  3. the Flatpak list (tells installed or not, but a Flatpak extension carries no version here)
"""
import json
import os
import plistlib
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import version as V

EXT_PREFIX = "org.freedesktop.LinuxAudio.Plugins."


@dataclass
class InstalledInfo:
    state: str            # 'installed' | 'not-installed' | 'unknown'
    version: str = None   # clean version string or None
    source: str = ""      # where the answer came from
    detail: str = ""      # short human text

    @property
    def known_version(self):
        return self.state == "installed" and self.version is not None


class Record:
    """installed-versions.json, written only after the user clicked Update and it succeeded."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("products"), dict):
                self.data = d["products"]
        except (OSError, ValueError):
            pass

    def get(self, repo):
        return self.data.get(repo)

    def set(self, repo, version, tag, method, paths=(), when=None):
        self.data[repo] = {"version": version, "tag": tag, "method": method, "paths": [str(p) for p in paths],
                           "installed_at": when or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self.save()

    def forget(self, repo):
        if self.data.pop(repo, None) is not None:
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self.path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "products": self.data}, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)


def read_bundle_version(bundle):
    """Version from a .vst3 bundle's metadata, or None when it carries none."""
    bundle = Path(bundle)
    mi = bundle / "Contents" / "Resources" / "moduleinfo.json"
    try:
        with open(mi, encoding="utf-8-sig") as f:
            v = V.clean(str(json.load(f).get("Version", "")))
        if v:
            return v
    except (OSError, ValueError, AttributeError):
        pass
    plist = bundle / "Contents" / "Info.plist"
    try:
        with open(plist, "rb") as f:
            d = plistlib.load(f)
        return V.clean(str(d.get("CFBundleShortVersionString") or d.get("CFBundleVersion") or ""))
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def probe_flatpak(runner=subprocess.run, in_sandbox=None):
    """('ok', set of installed ids) | ('absent', set()) | ('error', set())."""
    if in_sandbox is None:
        in_sandbox = os.path.exists("/.flatpak-info")
    cmd = ["flatpak", "list", "--columns=application"]
    if in_sandbox:
        cmd = ["flatpak-spawn", "--host"] + cmd
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        return ("error" if in_sandbox else "absent"), set()
    except (subprocess.SubprocessError, OSError):
        return "error", set()
    if r.returncode != 0:
        return "error", set()
    return "ok", {l.strip() for l in r.stdout.splitlines() if l.strip()}


def detect(product, system, record, vst3_dirs, flatpak=("absent", set())):
    """InstalledInfo for one product."""
    rec = record.get(product.repo) if record else None
    want_bundle = product.detect.get("vst3")
    want_ext = product.detect.get("flatpak")
    if not want_bundle and not want_ext:
        # We cannot look for it, so we only know what this updater installed itself.
        if rec and rec.get("version"):
            return InstalledInfo("installed", V.clean(rec["version"]), "install-record",
                                 "installed by this updater (cannot be checked on disk)")
        return InstalledInfo("unknown", None, "", "no way to detect this product yet")

    found_bundle = None
    if want_bundle:
        for d in vst3_dirs:
            b = Path(d) / (want_bundle + ".vst3")
            if b.exists():
                found_bundle = b
                break
    ext_state, ext_ids = flatpak
    found_ext = bool(want_ext and (EXT_PREFIX + want_ext) in ext_ids)

    if found_bundle is not None:
        v = read_bundle_version(found_bundle)
        if v:
            return InstalledInfo("installed", v, "vst3-metadata", str(found_bundle))
        if rec and rec.get("version") and rec.get("method") in ("vst3-tarball", "exe", "pkg"):
            return InstalledInfo("installed", V.clean(rec["version"]), "install-record", str(found_bundle))
        return InstalledInfo("installed", None, "vst3-bundle", "installed, version not readable")
    if found_ext:
        if rec and rec.get("version") and rec.get("method") == "flatpak-ext":
            return InstalledInfo("installed", V.clean(rec["version"]), "install-record", "Flatpak extension")
        return InstalledInfo("installed", None, "flatpak", "Flatpak extension, version not readable")
    # Not found where we looked.
    if want_ext and ext_state == "error":
        return InstalledInfo("unknown", None, "", "could not ask Flatpak what is installed")
    return InstalledInfo("not-installed", None, "scan", "")
