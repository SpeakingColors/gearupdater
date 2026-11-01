#!/usr/bin/env python3
"""gear-updater (early): checks firmware files and lists MIDI ports. It does NOT flash anything yet.

  gear_updater.py ports               list the ALSA MIDI ports (needs `amidi`)
  gear_updater.py dry-run FILE.syx    check the file and print what a flash would involve

Flashing is not implemented on purpose: the update protocol of each device must first be captured and
verified (see docs/UPDATER-DESIGN.md). Never redistribute vendor firmware; use your own file."""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sysex  # noqa: E402

CHECKLIST = [
    "Power: use mains power or a full battery, and block computer sleep.",
    "Cable: USB only, never Bluetooth.",
    "Backup: save the device's presets and settings first.",
    "Way back: only flash a firmware that keeps a way into the bootloader, and know the route back to the official firmware.",
    "Source: only a file you downloaded yourself from the vendor or the project that made it.",
]


def parse_amidi(text: str):
    ports = []
    for line in text.splitlines():
        m = re.match(r"^\s*([IO]{1,2})\s+(hw:\d+,\d+(?:,\d+)?)\s+(.*?)\s*$", line)
        if m:
            ports.append({"dir": m.group(1), "id": m.group(2), "name": m.group(3)})
    return ports


def cmd_ports(_):
    try:
        out = subprocess.run(["amidi", "-l"], capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError) as e:
        print(f"Could not run amidi ({e}). Install alsa-utils.", file=sys.stderr)
        return 1
    for p in parse_amidi(out):
        print(f"{p['id']:10} {p['dir']:3} {p['name']}")
    return 0


def cmd_dry_run(a):
    p = Path(a.file)
    if not p.is_file():
        print(f"No such file: {p}", file=sys.stderr)
        return 1
    rep = sysex.check(p.read_bytes())
    print(f"File: {p.name}\nSize: {rep.size} bytes\nSHA-256: {rep.sha256}\nSysEx messages: {rep.messages} (largest {rep.largest} bytes)")
    if a.sha256 and a.sha256.lower() != rep.sha256:
        rep.problems.append("SHA-256 does not match the value you gave")
    for pr in rep.problems:
        print(f"PROBLEM: {pr}")
    print("\nBefore any flash:")
    for c in CHECKLIST:
        print(f"  - {c}")
    print("\nResult:", "file looks well formed (this does not prove it is the right firmware)" if rep.ok else "NOT OK, do not flash")
    print("Nothing was sent to any device.")
    return 0 if rep.ok else 2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports").set_defaults(fn=cmd_ports)
    d = sub.add_parser("dry-run"); d.add_argument("file"); d.add_argument("--sha256", help="expected SHA-256 from the source"); d.set_defaults(fn=cmd_dry_run)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
