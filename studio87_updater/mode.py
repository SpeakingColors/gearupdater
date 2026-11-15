"""Install mode and elevation decisions. Pure functions, no side effects, easy to test.

Two modes:
  'all-users'  use the product's own installer (Windows Setup.exe, macOS .pkg). Needs administrator rights.
               The updater itself always starts unprivileged. When a batch holds installers that need administrator
               rights it starts ONE elevated helper for the whole batch (Windows: UAC prompt, macOS: osascript prompt),
               never one prompt per plugin, and none at all when the app is already running as administrator.
  'just-me'    no administrator rights, ever. The VST3 bundle goes into the per-user VST3 folder
               (Steinberg's official per-user locations), or the installer is asked for a per-user install.
Linux never needs administrator rights: the tarball goes to ~/.vst3 and Flatpak extensions use --user.
"""
from pathlib import Path

MODES = ("all-users", "just-me")
MODE_LABEL = {"all-users": "For all users (admin)", "just-me": "Just for me (no admin)"}

EXPLAIN = {
    "windows": "All users: the updater starts normally and asks for administrator rights (the Windows UAC prompt) only when you install, once for the whole batch, never once per plugin. "
               "Just for me: no administrator rights, no prompt; plugins go to your own VST3 folder.",
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


def batch_plan(system, mode, methods, is_admin=False):
    """Split queued install methods into the ones run directly and the ones that need ONE elevated helper.
    Returns {'direct': [...], 'elevated': [...], 'prompts': 0 or 1}. At most ONE prompt for the whole batch,
    and none when the app already runs as administrator (then everything runs directly) or nothing needs it."""
    elevated = [m for m in methods if method_needs_admin(system, mode, m)]
    if not elevated:
        return {"direct": list(methods), "elevated": [], "prompts": 0}
    if is_admin:
        return {"direct": list(methods), "elevated": [], "prompts": 0}
    return {"direct": [m for m in methods if m not in elevated], "elevated": elevated, "prompts": 1}
