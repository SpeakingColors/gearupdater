"""Update the updater itself, in the way that is safe for a program that is running.

On open the app compares its own version with the newest gearupdater release (the list already holds it, so this costs no
extra request). When a newer one exists the window shows 'Update the updater first' at the top. Updating it:
  1. downloads the release zip (retry and resume like any download) and verifies it exactly like any other update;
  2. copies the installer for THIS system out of the zip into the updater's own selfupdate folder (so cleaning the temporary
     folders cannot remove it), then hands over:
       Windows: starts the new Setup.exe detached (silent, closes this app, restarts it afterwards) and the app exits.
       macOS:   opens the .pkg in Installer; the app stays open until you finish the installer, then reopen it.
       Linux:   a running Flatpak cannot replace itself safely, and this copy is not on Flathub so `flatpak update` would not
                find it. The verified .flatpak is saved and the exact command to run is shown; nothing is run for you.
A failed download or a failed check changes nothing and the old version keeps working.
"""
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import install as INS
from . import version as V
from . import __version__

SELF_REPO = "gearupdater"


@dataclass
class SelfPlan:
    action: str          # 'launch' (Windows), 'open' (macOS), 'instruct' (Linux)
    file: Path
    version: str
    text: str = ""
    command: str = ""


def newer_release(releases, current=__version__):
    """The newest release that has a zip and is newer than `current`, or None."""
    for r in releases or []:
        if r.zip_asset() is not None and V.is_update(current, r.tag):
            return r
    return None


def prepare(client, release, system, folder, progress=None, cancel=lambda: False, sleep=None):
    """Download and verify the release, return a SelfPlan. Raises InstallError / ChecksumError on any problem."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    asset = release.zip_asset()
    if asset is None:
        raise INS.InstallError("this release has no zip")
    say = progress or (lambda *a: None)
    z = folder / asset.name
    work = folder / "x"
    shutil.rmtree(work, ignore_errors=True)
    say("download", 0, asset.size)
    kw = {"sleep": sleep} if sleep else {}
    try:
        client.download(asset.url, z, progress=lambda d, t: say("download", d, t or asset.size), cancel=cancel, **kw)
    except INS.Offline:
        raise INS.InstallError("could not reach GitHub to download the update; the old version keeps working")
    except INS.HttpError as e:
        raise INS.InstallError("the download failed (HTTP %s)" % e.status)
    except OSError as e:
        raise INS.InstallError("the download was interrupted: %s" % e)
    try:
        sums = release.sums_asset()
        if sums is not None:
            body, _ = client.fetch(sums.url)
            release.sums_text = (body or b"").decode("utf-8", "replace")
        say("verify", 0, 0)
        try:
            root, _checked = INS.verify_download(z, release, asset, work)
        except Exception:
            try:
                z.unlink()
            except OSError:
                pass
            raise
        ver = release.version or release.tag
        if system == "windows":
            src = next(iter(sorted(Path(root).glob("windows/*.exe"))), None)
            if src is None:
                raise INS.InstallError("this release has no Windows installer")
            dst = folder / ("Studio87-GearUpdater-Setup-%s.exe" % ver)
            shutil.copy2(src, dst)
            return SelfPlan("launch", dst, ver, "Verified. Starting the new installer; this window closes and the new version opens afterwards.")
        if system == "macos":
            src = next(iter(sorted(Path(root).glob("macos/*.pkg"))), None)
            if src is None:
                raise INS.InstallError("this release has no macOS installer")
            dst = folder / ("Studio87-GearUpdater-%s.pkg" % ver)
            shutil.copy2(src, dst)
            return SelfPlan("open", dst, ver, "Verified. Opened the installer; finish it, then open the updater again.")
        src = next(iter(sorted(Path(root).glob("linux/*.flatpak"))), None)
        if src is None:
            raise INS.InstallError("this release has no Flatpak")
        dst = folder / ("Studio87-GearUpdater-%s.flatpak" % ver)
        shutil.copy2(src, dst)
        cmd = 'flatpak install --user --reinstall "%s"' % dst
        return SelfPlan("instruct", dst, ver, "Verified and saved. A running Flatpak cannot replace itself: close this window, run the command below in a terminal, then start the updater again.", cmd)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        try:
            z.unlink()
        except OSError:
            pass


def launch(plan, system, popen=subprocess.Popen, runner=subprocess.run):
    """Hand over to the new installer. Returns True when the app should exit now (Windows only)."""
    if plan.action == "launch" and system == "windows":
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
        popen([str(plan.file), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"], creationflags=flags, close_fds=True)
        return True
    if plan.action == "open" and system == "macos":
        runner(["open", str(plan.file)])
        return False
    return False
