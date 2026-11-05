"""Download, verify and install one release the user chose. Nothing here runs without a click.

Order is fixed: download -> verify SHA256 (refuse on any mismatch) -> pick the installer the
product's INSTALL.txt describes -> run it -> write the installed-versions record.
Only ever writes to: the updater's own cache/data folders, the user's VST3 folder (one bundle
folder named in the verified tarball) and whatever the product's own installer does. It never
touches preset or data folders.
"""
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import checksum as C
from . import version as V
from .github import HttpError


class InstallError(Exception):
    pass


@dataclass
class Plan:
    method: str          # 'vst3-tarball' | 'flatpak-ext' | 'flatpak-app' | 'exe' | 'pkg' | 'guided'
    file: Path = None
    folder: Path = None
    reason: str = ""


def _glob1(root, pattern):
    hits = sorted(Path(root).glob(pattern))
    return hits[0] if hits else None


def _find_bundle(root, system):
    """A Windows or macOS VST3 bundle shipped inside the verified zip: a .vst3 folder, or an archive holding one."""
    sub = "windows" if system == "windows" else "macos"
    d = _glob1(root, sub + "/*.vst3")
    if d is not None and d.is_dir():
        return "dir", d
    for pat in ("*vst3*.zip", "*vst3*.tar.gz"):
        a = _glob1(root, sub + "/" + pat)
        if a is not None:
            return "archive", a
    return None, None


def choose_plan(product, system, root, linux_target="auto", ext_installed=False, mode="all-users"):
    """Decide how to install from what the verified zip really contains. Pure; no side effects.
    mode 'just-me' (Windows/macOS) never needs administrator rights: the bundle from the zip goes into the
    per-user VST3 folder when the zip holds one, else the installer is asked for a per-user install."""
    root = Path(root)
    m = product.method(system)
    if mode == "just-me" and system in ("windows", "macos") and m in ("exe", "pkg"):
        kind, f = _find_bundle(root, system)
        if f is not None:
            return Plan("vst3-zip", f, reason=kind)
        if system == "windows":
            e = _glob1(root, "windows/*.exe")
            return Plan("exe-user", e) if e else Plan("guided", folder=root, reason="no Windows installer (.exe) in this release")
        k = _glob1(root, "macos/*.pkg")
        return Plan("pkg-user", k) if k else Plan("guided", folder=root, reason="no macOS installer (.pkg) in this release")
    if m == "none":
        return Plan("guided", folder=root, reason="this product has no installer for this system")
    if m == "guided":
        return Plan("guided", folder=root, reason="follow INSTALL.txt in the opened folder")
    if system == "windows" and m == "exe":
        f = _glob1(root, "windows/*.exe")
        return Plan("exe", f) if f else Plan("guided", folder=root, reason="no Windows installer (.exe) in this release")
    if system == "macos" and m == "pkg":
        f = _glob1(root, "macos/*.pkg")
        return Plan("pkg", f) if f else Plan("guided", folder=root, reason="no macOS installer (.pkg) in this release")
    if system == "linux" and m == "flatpak-app":
        f = _glob1(root, "linux/*.flatpak")
        return Plan("flatpak-app", f) if f else Plan("guided", folder=root, reason="no Flatpak in this release")
    if system == "linux" and m == "vst3":
        tar = _glob1(root, "linux/*-linux-vst3.tar.gz") or _glob1(root, "linux/*.tar.gz")
        fp = _glob1(root, "linux/*.flatpak")
        want_flatpak = linux_target == "flatpak" or (linux_target == "auto" and ext_installed)
        if want_flatpak and fp:
            return Plan("flatpak-ext", fp)
        if tar and linux_target != "flatpak":
            return Plan("vst3-tarball", tar)
        if fp and linux_target == "auto":
            return Plan("flatpak-ext", fp)
        return Plan("guided", folder=root, reason="the release has no file for the chosen Linux target")
    return Plan("guided", folder=root, reason="no automatic installer for this combination")


def install_vst3_tarball(tarball, vst3_dir):
    """Replace <Name>.vst3 in vst3_dir with the tarball's bundle. Keeps the old one until the new one is in place."""
    return _install_bundle(lambda tmp: C.safe_extract_tar(tarball, tmp), vst3_dir)


def install_vst3_zip(src, vst3_dir):
    """Per-user install: a .vst3 folder or an archive holding exactly one, from the verified zip."""
    src = Path(src)
    if src.is_dir():
        return _install_bundle(lambda tmp: Path(shutil.copytree(src, tmp / src.name)), vst3_dir)
    if src.name.endswith(".zip"):
        def get(tmp):
            root = Path(C.safe_extract_zip(src, tmp))
            hits = [p for p in root.rglob("*.vst3") if p.is_dir()]
            if len(hits) != 1:
                raise InstallError("the VST3 archive must hold exactly one .vst3 folder")
            return hits[0]
        return _install_bundle(get, vst3_dir)
    return _install_bundle(lambda tmp: C.safe_extract_tar(src, tmp), vst3_dir)


def bundle_files(target):
    """Every file of an installed bundle, for the install record (so exactly these can be removed or replaced)."""
    t = Path(target)
    return sorted(str(p) for p in t.rglob("*") if p.is_file()) if t.is_dir() else [str(t)]


def _install_bundle(extract, vst3_dir):
    vst3_dir = Path(vst3_dir)
    vst3_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".studio87-", dir=vst3_dir))
    try:
        new = extract(tmp)
        target = vst3_dir / new.name
        old = None
        if target.exists():
            old = vst3_dir / (new.name + ".studio87-old")
            if old.exists():
                shutil.rmtree(old)
            os.replace(target, old)
        try:
            os.replace(new, target)
        except OSError:
            if old is not None:
                os.replace(old, target)
            raise
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
        return target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def in_flatpak_sandbox():
    return os.path.exists("/.flatpak-info")


def _host(cmd):
    return ["flatpak-spawn", "--host"] + cmd if in_flatpak_sandbox() else cmd


def open_folder(path, system, runner=subprocess.run):
    if system == "windows":
        os.startfile(str(path))      # noqa: only reached on Windows
    elif system == "macos":
        runner(["open", str(path)])
    else:
        runner(_host(["xdg-open", str(path)]))


def run_plan(plan, system, runner=subprocess.run):
    """Run the chosen installer. Returns a short result text; raises InstallError on failure."""
    if plan.method == "flatpak-ext" or plan.method == "flatpak-app":
        cmd = _host(["flatpak", "install", "--user", "-y", "--noninteractive", "--reinstall", str(plan.file)])
    elif plan.method == "exe":
        cmd = [str(plan.file), "/SILENT", "/NORESTART", "/SP-"]
    elif plan.method == "exe-user":
        cmd = [str(plan.file), "/SILENT", "/NORESTART", "/SP-", "/CURRENTUSER"]
    elif plan.method == "pkg-user":
        cmd = ["installer", "-pkg", str(plan.file), "-target", "CurrentUserHomeDirectory"]
    elif plan.method == "pkg":
        cmd = ["open", "-W", str(plan.file)]
    else:
        raise InstallError("nothing to run for %s" % plan.method)
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as e:
        raise InstallError("could not start the installer: %s" % e)
    if r.returncode != 0:
        tail = ((r.stderr or r.stdout or "").strip().splitlines() or ["no message"])[-1]
        raise InstallError("installer failed (code %s): %s" % (r.returncode, tail[:200]))
    return "installer finished"


def verify_download(zip_path, release, asset, extract_to):
    """Check the zip and everything in it. Returns the extracted root. Raises ChecksumError / UnsafeArchive."""
    checked = []
    if asset.sha256:
        C.check_digest(zip_path, asset.sha256, "the download (GitHub's own digest)")
        checked.append("github-digest")
    sums_asset = release.sums_asset()
    if sums_asset is not None:
        # fetched by the caller and passed in via release.sums_text
        text = getattr(release, "sums_text", None)
        if text:
            outer = C.parse_sums(text)
            want = outer.get(asset.name)
            if want is None:
                raise C.ChecksumError("the release's SHA256SUMS does not list %s" % asset.name)
            C.check_digest(zip_path, want, "the download (release SHA256SUMS)")
            checked.append("release-sums")
    root = C.safe_extract_zip(zip_path, extract_to)
    inner = Path(root) / "SHA256SUMS"
    if inner.is_file():
        sums = C.parse_sums(inner.read_text(encoding="utf-8", errors="replace"))
        C.verify_tree(root, sums)
        checked.append("zip-sums")
    if not checked:
        raise C.ChecksumError("this release has no SHA256SUMS to check, so it is not installed")
    return Path(root), checked


def elevated_pkg_script(pkgs):
    """Shell script that installs every staged .pkg, run by ONE elevated helper for the whole batch."""
    lines = ["#!/bin/sh", "set -e"]
    for p in pkgs:
        q = "'" + str(p).replace("'", "'\\''") + "'"
        lines.append("/usr/sbin/installer -pkg %s -target /" % q)
    return "\n".join(lines) + "\n"


def elevation_command(script_path):
    """macOS: one administrator prompt for the whole script."""
    return ["osascript", "-e", 'do shell script "/bin/sh %s" with administrator privileges' % str(script_path).replace('"', '\\"')]


class Installer:
    """Everything the GUI needs for one product. Collaborators are injected so tests need no network."""

    def __init__(self, client, record, system, work_dir, vst3_dir, guided_dir, runner=subprocess.run,
                 linux_target="auto", opener=None, mode="all-users", stage_dir=None):
        self.mode = mode
        self.stage_dir = Path(stage_dir) if stage_dir else Path(guided_dir).parent / "staged"
        self.staged = []        # [(row, pkg path, version, tag)] waiting for the one elevated helper (macOS all-users)
        self.client, self.record, self.system = client, record, system
        self.work_dir, self.vst3_dir, self.guided_dir = Path(work_dir), Path(vst3_dir), Path(guided_dir)
        self.runner, self.linux_target = runner, linux_target
        self.opener = opener or (lambda p: open_folder(p, system, runner))

    def install(self, row, ext_installed=False, progress=None, cancel=lambda: False):
        """Returns a result dict {ok, message, method, version}. Raises on refusal (ChecksumError etc.)."""
        p, rel = row.product, row.latest
        if rel is None or rel.zip_asset() is None:
            raise InstallError("this release has no zip to install")
        asset = rel.zip_asset()
        say = progress or (lambda *a: None)
        work = self.work_dir / ("%s-%s" % (p.repo, rel.tag))
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        try:
            free = shutil.disk_usage(work).free
            if asset.size and free < asset.size * 3:
                raise InstallError("not enough free disk space for this download")
            zip_path = work / asset.name
            say("download", 0, asset.size)
            self.client.download(asset.url, zip_path, progress=lambda d, t: say("download", d, t or asset.size), cancel=cancel)
            sums = rel.sums_asset()
            if sums is not None:
                body, _ = self.client.fetch(sums.url)
                rel.sums_text = (body or b"").decode("utf-8", "replace")
            say("verify", 0, 0)
            root, checked = verify_download(zip_path, rel, asset, work / "x")
            plan = choose_plan(p, self.system, root, self.linux_target, ext_installed, self.mode)
            say("install", 0, 0)
            ver = rel.version
            if plan.method == "guided":
                dest = self.guided_dir / ("%s %s" % (p.name, rel.tag))
                shutil.rmtree(dest, ignore_errors=True)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(root, dest)
                self.opener(dest)
                return {"ok": True, "method": "guided", "version": ver, "checked": checked,
                        "message": "Downloaded and verified. Opened the folder; follow INSTALL.txt (%s)." % plan.reason}
            if plan.method == "vst3-tarball":
                target = install_vst3_tarball(plan.file, self.vst3_dir)
                paths = bundle_files(target)
            elif plan.method == "vst3-zip":
                target = install_vst3_zip(plan.file, self.vst3_dir)
                paths = bundle_files(target)
            elif plan.method == "pkg":
                # all-users on macOS: stage the verified pkg; ONE elevated helper installs the whole batch afterwards.
                self.stage_dir.mkdir(parents=True, exist_ok=True)
                keep = self.stage_dir / ("%s-%s.pkg" % (p.repo, rel.tag))
                shutil.copy2(plan.file, keep)
                self.staged.append((p.repo, p.name, keep, ver, rel.tag))
                return {"ok": True, "method": "pkg", "version": ver, "checked": checked, "staged": True,
                        "message": "Verified. Waiting to install with the rest of the batch (one administrator prompt)."}
            else:
                run_plan(plan, self.system, self.runner)
                paths = []
            self.record.set(p.repo, ver, rel.tag, plan.method, paths)
            return {"ok": True, "method": plan.method, "version": ver, "checked": checked,
                    "message": "Installed %s %s (%s). Checksums verified." % (p.name, ver, plan.method)}
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def finish_batch(self):
        """Run every staged .pkg through ONE elevated helper. Returns {repo: (ok, message)}."""
        out = {}
        if not self.staged:
            return out
        staged, self.staged = self.staged, []
        script = self.stage_dir / "install-batch.sh"
        script.write_text(elevated_pkg_script([s[2] for s in staged]))
        try:
            r = self.runner(elevation_command(script), capture_output=True, text=True, timeout=3600)
            ok = r.returncode == 0
            msg = "Installed (one administrator prompt for the batch)." if ok else \
                  "The administrator step failed or was cancelled: %s" % (((r.stderr or r.stdout or "").strip().splitlines() or ["no message"])[-1][:160])
        except (OSError, subprocess.SubprocessError) as e:
            ok, msg = False, "could not start the administrator helper: %s" % e
        for repo, name, pkg, ver, tag in staged:
            if ok:
                self.record.set(repo, ver, tag, "pkg", [])
            out[repo] = (ok, msg)
            try:
                Path(pkg).unlink()
            except OSError:
                pass
        try:
            script.unlink()
        except OSError:
            pass
        return out

    def uninstall_recorded(self, repo):
        """Remove exactly the files this updater recorded for a per-user install, then forget the record."""
        rec = self.record.get(repo)
        if not rec or rec.get("method") not in ("vst3-tarball", "vst3-zip"):
            return 0
        n = 0
        for f in rec.get("paths", []):
            fp = Path(f)
            try:
                if fp.is_file() or fp.is_symlink():
                    fp.unlink()
                    n += 1
            except OSError:
                continue
        roots = set()
        for f in rec.get("paths", []):
            for anc in Path(f).parents:
                if anc.suffix.lower() == ".vst3":
                    roots.add(anc)
                    break
        for r in roots:                      # only empty folders inside the recorded bundle go; anything else stays
            for dirpath, _dirs, _files in os.walk(r, topdown=False):
                try:
                    os.rmdir(dirpath)
                except OSError:
                    pass
        self.record.forget(repo)
        return n
