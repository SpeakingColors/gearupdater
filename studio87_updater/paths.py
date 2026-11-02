"""Where the updater keeps its own files. Never touches a product's preset or data folders."""
import os
import sys
from pathlib import Path

BRAND = "Studio 87"
PRODUCT = "Updater"


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


def vst3_dirs(system=None, env=None, home=None):
    """Folders where installed VST3 bundles are looked for."""
    system = system or system_name()
    env = os.environ if env is None else env
    home = Path(home) if home else Path.home()
    if system == "windows":
        common = env.get("COMMONPROGRAMFILES") or r"C:\Program Files\Common Files"
        return [Path(common) / "VST3"]
    if system == "macos":
        return [Path("/Library/Audio/Plug-Ins/VST3"), home / "Library" / "Audio" / "Plug-Ins" / "VST3"]
    return [home / ".vst3", Path("/usr/lib/vst3"), Path("/usr/local/lib/vst3")]


def user_vst3_dir(system=None, env=None, home=None):
    return vst3_dirs(system, env, home)[0 if (system or system_name()) != "macos" else 1]
