"""Download, verify and install one release the user chose. Nothing here runs without a click.

Order is fixed: download (retry with backoff, resume an interrupted download) -> verify SHA256 (refuse on any
mismatch, before anything installed is touched) -> pick the installer the product's INSTALL.txt describes -> run it
-> write the installed-versions record. A plugin bundle replaces the old one only after it was copied and checked;
the old one is kept as the one backup for Roll back, and restored automatically if the new copy fails.
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

from . import backup as B
from . import checksum as C
from . import elevation as EL
from . import installed as I
from . import version as V
from .github import HttpError, Offline


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


def install_vst3_tarball(tarball, vst3_dir, keep=None, verify=None):
    """Replace <Name>.vst3 in vst3_dir with the tarball's bundle. Keeps the old one until the new one is in place and checked."""
    return _install_bundle(lambda tmp: C.safe_extract_tar(tarball, tmp), vst3_dir, keep, verify)


def install_vst3_zip(src, vst3_dir, keep=None, verify=None):
    """Per-user install: a .vst3 folder or an archive holding exactly one, from the verified zip."""
    src = Path(src)
    if src.is_dir():
        return _install_bundle(lambda tmp: Path(shutil.copytree(src, tmp / src.name)), vst3_dir, keep, verify)
    if src.name.endswith(".zip"):
        def get(tmp):
            root = Path(C.safe_extract_zip(src, tmp))
            hits = [p for p in root.rglob("*.vst3") if p.is_dir()]
            if len(hits) != 1:
                raise InstallError("the VST3 archive must hold exactly one .vst3 folder")
            return hits[0]
        return _install_bundle(get, vst3_dir, keep, verify)
    return _install_bundle(lambda tmp: C.safe_extract_tar(src, tmp), vst3_dir, keep, verify)


def bundle_files(target):
    """Every file of an installed bundle, for the install record (so exactly these can be removed or replaced)."""
    t = Path(target)
    return sorted(str(p) for p in t.rglob("*") if p.is_file()) if t.is_dir() else [str(t)]


def _install_bundle(extract, vst3_dir, keep=None, verify=None):
    """Swap one bundle folder in, safely:
       1. extract the verified archive next to the target (same disk), hash every file;
       2. move the old bundle aside, move the new one in, hash the installed copy and compare (and run `verify`);
       3. on ANY failure put the old bundle back (the installed plugin is never left half replaced);
       4. only then hand the old bundle to `keep` (the backup) and delete it."""
    vst3_dir = Path(vst3_dir)
    vst3_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".studio87-", dir=vst3_dir))
    try:
        new = extract(tmp)
        expected = B.tree_hashes(new)
        if not expected:
            raise InstallError("the new bundle is empty; nothing was changed")
        target = vst3_dir / new.name
        old = vst3_dir / (new.name + ".studio87-old")
        if old.exists() and not target.exists():           # an earlier run was interrupted between the two moves: put it back first
            os.replace(old, target)
        old_in_place = False
        try:
            if target.exists():
                if old.exists():
                    shutil.rmtree(old)
                os.replace(target, old)
                old_in_place = True
        except OSError as e:
            raise InstallError("could not replace the installed plugin (is your DAW still open?): %s" % e)
        try:
            os.replace(new, target)
            if B.tree_hashes(target) != expected:
                raise InstallError("the installed files do not match the verified download")
            if verify is not None:
                verify(target)
        except BaseException as e:
            shutil.rmtree(target, ignore_errors=True)
            if old_in_place:
                os.replace(old, target)
            if isinstance(e, (InstallError, KeyboardInterrupt)):
                raise
            raise InstallError("the new copy failed its check and the previous version was restored: %s" % e)
        if old_in_place:
            if keep is not None:
                try:
                    keep(old)
                except Exception:
                    pass
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




@dataclass
class Staged:
    """A verified installer that waits for the ONE elevated helper of the batch."""
    repo: str
    name: str
    file: Path
    version: str
    tag: str
    kind: str                 # 'exe' | 'pkg'
    sha256: str
    zip_path: Path = None


class Installer:
    """Everything the GUI needs for one product. Collaborators are injected so tests need no network."""

    def __init__(self, client, record, system, work_dir, vst3_dir, guided_dir, runner=subprocess.run,
                 linux_target="auto", opener=None, mode="all-users", stage_dir=None, backend=None, backups=None,
                 zip_dir=None, sleep=None):
        self.mode = mode
        self.stage_dir = Path(stage_dir) if stage_dir else Path(guided_dir).parent / "staged"
        self.staged = []        # [Staged] waiting for the one elevated helper (Windows and macOS, 'All users')
        self.client, self.record, self.system = client, record, system
        self.work_dir, self.vst3_dir, self.guided_dir = Path(work_dir), Path(vst3_dir), Path(guided_dir)
        self.runner, self.linux_target = runner, linux_target
        self.opener = opener or (lambda p: open_folder(p, system, runner))
        self.backend = backend if backend is not None else EL.default_backend(system, runner)
        self.backups = backups
        self.zip_dir = Path(zip_dir) if zip_dir else self.work_dir.parent / "zips"
        self.sleep = sleep

    # -- downloads that survive a bad connection ------------------------------
    def zip_path_for(self, product, release, asset):
        return self.zip_dir / ("%s-%s" % (product.repo, release.tag)) / asset.name

    def zip_ready(self, product, release):
        """True when this release's zip is already completely on disk (used offline: install without the network)."""
        a = release.zip_asset() if release else None
        if a is None:
            return False
        z = self.zip_path_for(product, release, a)
        try:
            return z.is_file() and (not a.size or z.stat().st_size == a.size)
        except OSError:
            return False

    def _fetch_zip(self, product, release, asset, say, cancel):
        z = self.zip_path_for(product, release, asset)
        z.parent.mkdir(parents=True, exist_ok=True)
        if self.zip_ready(product, release):
            say("download", asset.size, asset.size)
            return z
        say("download", 0, asset.size)
        kw = {"sleep": self.sleep} if self.sleep else {}
        try:
            self.client.download(asset.url, z, progress=lambda d, t: say("download", d, t or asset.size), cancel=cancel, **kw)
        except Offline:
            raise InstallError("could not reach GitHub to download this. The part that was downloaded is kept; use Retry failed when the connection is back")
        except HttpError as e:
            raise InstallError("the download failed (HTTP %s)" % e.status)
        except OSError as e:
            raise InstallError("the download was interrupted: %s. The part that was downloaded is kept; use Retry failed" % e)
        return z

    def _prev_version(self, repo, old_bundle):
        v = I.read_bundle_version(old_bundle)
        if v:
            return v
        rec = self.record.get(repo)
        return rec.get("version") if rec else None

    def _keeper(self, p, plan_method, target_dir):
        """Callback that stores the replaced bundle as the one backup. Failure to back up never fails the update."""
        if self.backups is None:
            return None
        rec = self.record.get(p.repo) or {}

        def keep(old):
            real = Path(old).name.replace(".studio87-old", "")
            self.backups.put(p.repo, old, self._prev_version(p.repo, old), rec.get("tag"), plan_method, Path(target_dir) / real, name=real)
        return keep

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
        zip_path = None
        try:
            free = shutil.disk_usage(work).free
            if asset.size and free < asset.size * 3:
                raise InstallError("not enough free disk space for this download")
            zip_path = self._fetch_zip(p, rel, asset, say, cancel)
            sums = rel.sums_asset()
            if sums is not None:
                try:
                    body, _ = self.client.fetch(sums.url)
                except Offline:
                    raise InstallError("could not reach GitHub to read SHA256SUMS; use Retry failed when the connection is back")
                rel.sums_text = (body or b"").decode("utf-8", "replace")
            say("verify", 0, 0)
            try:
                root, checked = verify_download(zip_path, rel, asset, work / "x")
            except (C.ChecksumError, C.UnsafeArchive):
                try:
                    zip_path.unlink()        # a damaged or tampered copy is never reused
                except OSError:
                    pass
                raise
            plan = choose_plan(p, self.system, root, self.linux_target, ext_installed, self.mode)
            say("install", 0, 0)
            ver = rel.version
            if plan.method == "guided":
                dest = self.guided_dir / ("%s %s" % (p.name, rel.tag))
                shutil.rmtree(dest, ignore_errors=True)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(root, dest)
                self.opener(dest)
                self._drop_zip(zip_path)
                return {"ok": True, "method": "guided", "version": ver, "checked": checked,
                        "message": "Downloaded and verified. Opened the folder; follow INSTALL.txt (%s)." % plan.reason}
            if plan.method in ("vst3-tarball", "vst3-zip"):
                keep = self._keeper(p, plan.method, self.vst3_dir)
                fn = install_vst3_tarball if plan.method == "vst3-tarball" else install_vst3_zip
                target = fn(plan.file, self.vst3_dir, keep=keep)
                paths = bundle_files(target)
                pass
                self._drop_zip(zip_path)
                kept = self.backups is not None and self.backups.has(p.repo)
                msg = "Installed %s %s (%s). Checksums verified." % (p.name, ver, plan.method)
                if kept:
                    msg += " The previous version is kept; Roll back puts it back."
                return {"ok": True, "method": plan.method, "version": ver, "checked": checked, "message": msg, "backup": kept}
            if plan.method == "pkg" or (plan.method == "exe" and not self.backend.is_admin()):
                # All users: stage the verified installer; ONE elevated helper installs the whole batch afterwards.
                self.stage_dir.mkdir(parents=True, exist_ok=True)
                kind = "pkg" if plan.method == "pkg" else "exe"
                keepf = self.stage_dir / ("%s-%s.%s" % (p.repo, rel.tag, kind))
                shutil.copy2(plan.file, keepf)
                self.staged.append(Staged(p.repo, p.name, keepf, ver, rel.tag, kind, EL.sha256_of(keepf), zip_path))
                return {"ok": True, "method": plan.method, "version": ver, "checked": checked, "staged": True,
                        "message": "Verified. Waiting to install with the rest of the batch (one administrator prompt)."}
            run_plan(plan, self.system, self.runner)
            self.record.set(p.repo, ver, rel.tag, plan.method, [])
            self._drop_zip(zip_path)
            return {"ok": True, "method": plan.method, "version": ver, "checked": checked,
                    "message": "Installed %s %s (%s). Checksums verified." % (p.name, ver, plan.method)}
        finally:
            shutil.rmtree(work, ignore_errors=True)       # a finished zip stays in the zip folder until the install worked (Retry, offline)

    def finish_batch(self):
        """Run every staged installer through ONE elevated helper. Returns {repo: (ok, message)}."""
        out = {}
        if not self.staged:
            return out
        staged, self.staged = self.staged, []
        jobs = [EL.Job(s.repo, s.name, s.kind, str(s.file), s.sha256, s.version, s.tag) for s in staged]
        try:
            results = self.backend.run_batch(jobs, self.stage_dir)
        except Exception as e:
            results = {s.repo: (False, "could not start the administrator helper: %s" % e) for s in staged}
        for s in staged:
            ok, msg = results.get(s.repo, (False, "no result from the administrator step"))
            if ok:
                self.record.set(s.repo, s.version, s.tag, s.kind if s.kind == "pkg" else "exe", [])
                self._drop_zip(s.zip_path)
            out[s.repo] = (ok, msg)
            try:
                Path(s.file).unlink()
            except OSError:
                pass
        return out

    def _drop_zip(self, z):
        if z is None:
            return
        try:
            Path(z).unlink()
            Path(z).parent.rmdir()
        except OSError:
            pass

    def can_rollback(self, repo):
        return self.backups is not None and self.backups.has(repo)

    def rollback(self, repo):
        """Put the saved previous version of a plugin bundle back. Returns a message; raises InstallError when it cannot."""
        if self.backups is None:
            raise InstallError("no backups are kept here")
        bundle, meta = self.backups.take(repo)
        if bundle is None:
            raise InstallError("there is no saved previous version of this product")
        name = meta.get("name") or Path(bundle).name
        if not str(name).endswith(".vst3") or "/" in str(name) or "\\" in str(name):
            raise InstallError("the saved backup is not usable")
        src = Path(bundle)
        if src.name != name:                       # the backup folder is called 'bundle': give it its real name for the swap
            stage = Path(tempfile.mkdtemp(prefix=".studio87-rb-", dir=self.vst3_dir if self.vst3_dir.is_dir() else None))
            try:
                shutil.copytree(src, stage / name)
                target = install_vst3_zip(stage / name, self.vst3_dir)
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        else:
            target = install_vst3_zip(src, self.vst3_dir)
        ver, tag = meta.get("version"), meta.get("tag")
        if ver:
            self.record.set(repo, ver, tag or ("v" + ver), meta.get("method") or "vst3-zip", bundle_files(target))
        else:
            self.record.forget(repo)
        self.backups.drop(repo)
        return "Rolled back to %s." % (("version " + ver) if ver else "the previous version")

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
