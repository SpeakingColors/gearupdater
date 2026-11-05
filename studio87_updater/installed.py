"""Find out what is really installed. Never guesses: 'not installed' and 'unknown' are shown honestly.

Presence is decided apart from the version. Version sources, in order: the installed-versions file this
updater writes after a successful install (accepted only while the thing is still found), the bundle's
moduleinfo.json, Info.plist, Inno DisplayVersion (Windows), pkgutil version (macOS), flatpak info.
When something is present but no version can be read the answer is 'installed, version unknown'.
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


def norm(s):
    """Letters and digits only, lower case: 'Stretch Cat', 'StretchCat' and 'stretch-cat' all match."""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def expected_names(product):
    """Every bundle / app / extension name this product may carry, normalised. Read from the product's CMake
    PRODUCT_NAME and release.yml (see products.json), plus its display name."""
    d = product.detect or {}
    raw = [d.get("vst3"), d.get("flatpak"), product.name] + list(d.get("names", []))
    return {norm(x) for x in raw if x}


def scan_vst3(dirs, names):
    """First *.vst3 in dirs whose name matches one of names (normalised). Handles folders and single files."""
    for d in dirs:
        try:
            entries = sorted(Path(d).iterdir())
        except OSError:
            continue
        for e in entries:
            if e.suffix.lower() == ".vst3" and norm(e.stem) in names:
                return e
    return None


def _lookup(table, names):
    """Entry of a {display name or id: version-or-None} table whose normalised key matches, else (False, None)."""
    for k, v in (table or {}).items():
        nk = norm(k)
        if nk in names or any(len(n) >= 6 and n in nk for n in names):
            return True, v
    return False, None


def read_inno_uninstall(winreg=None):
    """{DisplayName: DisplayVersion} from the Inno Setup uninstall keys (Windows only; returns {} elsewhere)."""
    out = {}
    try:
        if winreg is None:
            import winreg  # noqa
    except ImportError:
        return out
    roots = ((winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"))
    for hive, sub in roots:
        try:
            with winreg.OpenKey(hive, sub) as k:
                n = winreg.QueryInfoKey(k)[0]
                for i in range(n):
                    try:
                        name = winreg.EnumKey(k, i)
                        with winreg.OpenKey(k, name) as kk:
                            dn = winreg.QueryValueEx(kk, "DisplayName")[0]
                            try:
                                dv = winreg.QueryValueEx(kk, "DisplayVersion")[0]
                            except OSError:
                                dv = None
                            out[dn] = V.clean(str(dv)) if dv else None
                    except OSError:
                        continue
        except OSError:
            continue
    return out


def read_pkgutil(runner=subprocess.run):
    """{pkg id: version} from `pkgutil --pkgs` and `pkgutil --pkg-info` (macOS only). Only ids that look like ours are queried."""
    try:
        r = runner(["pkgutil", "--pkgs"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return {}
    if r.returncode != 0:
        return {}
    out = {}
    for pid in (l.strip() for l in r.stdout.splitlines()):
        if not pid or "studio87" not in pid.lower() and "speakingcolors" not in pid.lower():
            continue
        v = None
        try:
            ri = runner(["pkgutil", "--pkg-info", pid], capture_output=True, text=True, timeout=20)
            for line in ri.stdout.splitlines():
                if line.lower().startswith("version:"):
                    v = V.clean(line.split(":", 1)[1].strip())
        except (OSError, subprocess.SubprocessError):
            pass
        out[pid] = v
    return out


def flatpak_info_version(ext_id, runner=subprocess.run, in_sandbox=None):
    """Version line of `flatpak info <id>`, or None."""
    cmd = ["flatpak", "info", ext_id]
    if in_sandbox if in_sandbox is not None else os.path.exists("/.flatpak-info"):
        cmd = ["flatpak-spawn", "--host"] + cmd
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if line.strip().lower().startswith("version:"):
            return V.clean(line.split(":", 1)[1].strip()) or None
    return None


def detect(product, system, record, vst3_dirs, flatpak=("absent", set()), win_uninstall=None, mac_pkgs=None,
           flatpak_version=None):
    """InstalledInfo for one product. 'not-installed' only when nothing was found anywhere; presence is
    decided separately from the version. Version sources in order: this updater's install record (while the
    thing it installed is still there), moduleinfo.json, Info.plist, Inno DisplayVersion (Windows),
    pkgutil version (macOS), flatpak info version."""
    rec = record.get(product.repo) if record else None
    rec_v = V.clean(rec["version"]) if rec and rec.get("version") else None
    names = expected_names(product)
    want_ext = (product.detect or {}).get("flatpak")
    has_hint = bool(product.detect) or product.kind in ("vst3", "controller")
    if product.kind in ("logue",) and not product.detect:
        if rec_v:
            return InstalledInfo("installed", rec_v, "install-record", "installed by this updater (cannot be checked on disk)")
        return InstalledInfo("unknown", None, "", "no way to detect this product yet")

    bundle = scan_vst3(vst3_dirs, names)
    ext_state, ext_ids = flatpak
    ext_id = (EXT_PREFIX + want_ext) if want_ext else None
    found_ext = bool(ext_id and ext_id in ext_ids)
    win_hit, win_v = _lookup(win_uninstall, names) if system == "windows" else (False, None)
    pkg_hit, pkg_v = _lookup(mac_pkgs, names) if system == "macos" else (False, None)

    if bundle is None and not found_ext and not win_hit and not pkg_hit:
        if not has_hint:
            return InstalledInfo("unknown", None, "", "no way to detect this product yet")
        if want_ext and ext_state == "error":
            return InstalledInfo("unknown", None, "", "could not ask Flatpak what is installed")
        # a record whose files are gone is stale; never trusted
        return InstalledInfo("not-installed", None, "scan", "")

    where = str(bundle) if bundle else ("Flatpak extension" if found_ext else "installer registry")
    if rec_v:
        return InstalledInfo("installed", rec_v, "install-record", where)
    if bundle is not None:
        v = read_bundle_version(bundle)
        if v:
            return InstalledInfo("installed", v, "vst3-metadata", where)
    if win_hit and win_v:
        return InstalledInfo("installed", win_v, "inno-registry", where)
    if pkg_hit and pkg_v:
        return InstalledInfo("installed", pkg_v, "pkgutil", where)
    if found_ext:
        v = flatpak_version(ext_id) if flatpak_version else None
        if v:
            return InstalledInfo("installed", v, "flatpak-info", where)
    return InstalledInfo("installed", None, "present", "installed, version not readable")
