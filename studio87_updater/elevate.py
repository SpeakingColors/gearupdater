"""Windows only: when the install mode is 'All users' the updater asks for administrator rights ONCE, at launch,
by relaunching itself with ShellExecute 'runas'. After that every installer runs silently inside that one session.
Chosen over an exe manifest because the manifest would also elevate 'Just for me' users, who must start normally.
The decision itself (mode.startup_elevation) is pure and tested; this thin wrapper is not testable off Windows."""
import sys

from . import mode as MODE
from .paths import data_dir, system_name
from .service import Settings

FLAG = "--elevation-tried"


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def maybe_relaunch_elevated(argv, system=None, admin=None):
    """True when an elevated copy was started and this process should exit."""
    system = system or system_name()
    if system != "windows":
        return False
    saved = Settings(data_dir(system) / "settings.json")["install_mode"]
    mode = MODE.effective_mode(system, saved)
    admin = is_admin() if admin is None else admin
    if MODE.startup_elevation(system, mode, admin, FLAG in argv) != "relaunch":
        return False
    try:
        import ctypes
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, " ".join(a for a in argv)
        else:
            exe, params = sys.executable, "-m studio87_updater " + " ".join(argv)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, (params + " " + FLAG).strip(), None, 1)
        return rc > 32           # <= 32 means the user declined the prompt: keep running normally
    except Exception:
        return False
