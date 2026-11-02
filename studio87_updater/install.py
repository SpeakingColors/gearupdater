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


def choose_plan(product, system, root, linux_target="auto", ext_installed=False):
    """Decide how to install from what the verified zip really contains. Pure; no side effects."""
    root = Path(root)
    m = product.method(system)
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
    vst3_dir = Path(vst3_dir)
    vst3_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".studio87-", dir=vst3_dir))
    try:
        new = C.safe_extract_tar(tarball, tmp)
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


class Installer:
    """Everything the GUI needs for one product. Collaborators are injected so tests need no network."""

    def __init__(self, client, record, system, work_dir, vst3_dir, guided_dir, runner=subprocess.run,
                 linux_target="auto", opener=None):
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
            plan = choose_plan(p, self.system, root, self.linux_target, ext_installed)
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
                paths = [target]
            elif plan.method == "pkg":
                # Installer.app reports no result to us, so nothing is recorded: the next check reads the bundle itself.
                run_plan(plan, self.system, self.runner)
                return {"ok": True, "method": "pkg", "version": ver, "checked": checked,
                        "message": "Installer closed. Run Check for updates to confirm the new version."}
            else:
                run_plan(plan, self.system, self.runner)
                paths = []
            self.record.set(p.repo, ver, rel.tag, plan.method, paths)
            return {"ok": True, "method": plan.method, "version": ver, "checked": checked,
                    "message": "Installed %s %s (%s). Checksums verified." % (p.name, ver, plan.method)}
        finally:
            shutil.rmtree(work, ignore_errors=True)
