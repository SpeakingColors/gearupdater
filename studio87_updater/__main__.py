"""python3 -m studio87_updater          opens the window
   python3 -m studio87_updater --list  prints the list in the terminal (same checks, no GUI)"""
import sys

from . import APP_NAME, __version__
from .model import STATUS_TEXT, Row
from .service import Service


def cli_list():
    svc = Service()
    rows, notice = svc.check()
    for r in rows:
        inst = r.installed.version if r.installed and r.installed.version else (r.installed.state if r.installed else "?")
        print("%-28s %-18s installed=%-14s latest=%-8s %s" % (r.product.name, r.product.kind_label, inst,
              (r.latest.version if r.latest else "-"), STATUS_TEXT[r.status]))
    if notice:
        print("\n" + ("Offline: showing the saved list." if notice == "offline" else notice))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--version" in argv:
        print("%s %s" % (APP_NAME, __version__))
        return 0
    if "--list" in argv:
        return cli_list()
    from .gui.app import run
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
