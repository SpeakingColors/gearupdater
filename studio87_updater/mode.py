"""Install mode and elevation decisions. Pure functions, no side effects, easy to test.

Two modes:
  'all-users'  use the product's own installer (Windows Setup.exe, macOS .pkg). Needs administrator rights.
               Windows: the updater itself starts elevated once (one UAC prompt), then every installer runs
               silently inside that session. macOS: one elevated helper runs every queued .pkg together.
  'just-me'    no administrator rights, ever. The VST3 bundle goes into the per-user VST3 folder
               (Steinberg's official per-user locations), or the installer is asked for a per-user install.
Linux never needs administrator rights: the tarball goes to ~/.vst3 and Flatpak extensions use --user.
"""
from pathlib import Path

MODES = ("all-users", "just-me")
MODE_LABEL = {"all-users": "For all users (admin)", "just-me": "Just for me (no admin)"}

EXPLAIN = {
    "windows": "All users: the updater asks for administrator rights once when it starts, then installs everything without asking again. "
               "Just for me: no administrator rights; plugins go to your own VST3 folder.",
    "macos": "All users: one administrator prompt per batch of installs. Just for me: no administrator rights; plugins go to ~/Library/Audio/Plug-Ins/VST3.",
    "linux": "Linux never needs administrator rights: plugins go to ~/.vst3 or a user-level Flatpak.",
}


def default_mode(system):
    return "all-users" if system in ("windows", "macos") else "just-me"


def effective_mode(system, saved):
    """The mode in force. Linux is always 'just-me'; an unknown saved value falls back to the system default."""
    if system == "linux":
        return "just-me"
    return saved if saved in MODES else default_mode(system)


def user_vst3_dir(system, env, home):
    """Steinberg's per-user VST3 location for this OS."""
    home = Path(home)
    if system == "windows":
        return Path((env or {}).get("LOCALAPPDATA") or home / "AppData" / "Local") / "Programs" / "Common" / "VST3"
    if system == "macos":
        return home / "Library" / "Audio" / "Plug-Ins" / "VST3"
    return home / ".vst3"


def method_needs_admin(system, mode, method):
    """Does installing with this method need administrator rights?"""
    if mode != "all-users":
        return False
    return (system == "windows" and method == "exe") or (system == "macos" and method == "pkg")


def startup_elevation(system, mode, is_admin, already_tried=False):
    """'relaunch' when the app should restart itself elevated (Windows, all-users, not admin yet, not tried), else 'none'."""
    if system == "windows" and mode == "all-users" and not is_admin and not already_tried:
        return "relaunch"
    return "none"


def batch_plan(system, mode, methods):
    """Split queued install methods into the ones run directly and the ones that need one elevated helper.
    Returns {'direct': [...], 'elevated': [...], 'prompts': 0 or 1}. At most ONE prompt for the whole batch."""
    elevated = [m for m in methods if method_needs_admin(system, mode, m)]
    # on Windows the whole app is already elevated, so nothing is prompted per batch
    prompts = 1 if (elevated and system == "macos") else 0
    return {"direct": [m for m in methods if m not in elevated], "elevated": elevated if system == "macos" else [], "prompts": prompts}
