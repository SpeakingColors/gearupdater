"""Where the updater keeps its own files. Never touches a product's preset or data folders."""
import os
import sys
from pathlib import Path

BRAND = "Studio 87"
PRODUCT = "Gear Updater"
OLD_PRODUCT = "Updater"      # v0.1.0 folder name; migrated on first start


def system_name(platform=None):
    p = platform or sys.platform
    if p.startswith("win"):
        return "windows"
    if p == "darwin":
        return "macos"
    return "linux"


def data_dir(system=None, env=None, home=None):
    system = system or system_name()
    env = os.environ if env is None else env
    home = Path(home) if home else Path.home()
    if system == "windows":
        base = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
    elif system == "macos":
        base = home / "Library" / "Application Support"
    else:
        base = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
    return base / BRAND / PRODUCT


def cache_dir(system=None, env=None, home=None):
    system = system or system_name()
    env = os.environ if env is None else env
    home = Path(home) if home else Path.home()
    if system == "windows":
        base = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif system == "macos":
        base = home / "Library" / "Caches"
    else:
        base = Path(env.get("XDG_CACHE_HOME") or home / ".cache")
    return base / BRAND / PRODUCT


def migrate_old_data(system=None, env=None, home=None):
    """v0.1.0 kept its files in '.../Studio 87/Updater'. Copy them to the new folder once; the old one is left in place."""
    import shutil
    new = data_dir(system, env, home)
    old = new.parent / OLD_PRODUCT
    if old.is_dir() and not new.exists():
        try:
            shutil.copytree(old, new)
        except OSError:
            pass
    newc = cache_dir(system, env, home)
    oldc = newc.parent / OLD_PRODUCT
    if oldc.is_dir() and not newc.exists():
        try:
            shutil.copytree(oldc, newc)
        except OSError:
            pass


def vst3_dirs(system=None, env=None, home=None):
    """Folders where installed VST3 bundles are looked for."""
    system = system or system_name()
    env = os.environ if env is None else env
    home = Path(home) if home else Path.home()
    if system == "windows":
        common = env.get("COMMONPROGRAMFILES") or r"C:\Program Files\Common Files"
        local = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local") / "Programs" / "Common" / "VST3"
        return [Path(common) / "VST3", local]
    if system == "macos":
        return [Path("/Library/Audio/Plug-Ins/VST3"), home / "Library" / "Audio" / "Plug-Ins" / "VST3"]
    return [home / ".vst3", Path("/usr/lib/vst3"), Path("/usr/lib64/vst3"), Path("/usr/local/lib/vst3"), Path("/usr/local/lib64/vst3")]


def user_vst3_dir(system=None, env=None, home=None):
    """The per-user VST3 folder (Steinberg's 'User' location)."""
    from . import mode as MODE
    system = system or system_name()
    env = os.environ if env is None else env
    return MODE.user_vst3_dir(system, env, Path(home) if home else Path.home())
