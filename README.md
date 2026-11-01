# gear-updater

One Linux tool for updating the firmware of studio gear without a Windows machine, built so it never bricks a unit.
Part of the Studio 87 free and open source suite.

**Status: early.** It checks firmware files and lists MIDI ports. It does **not** flash anything yet: each device's update protocol must first be captured and verified (see `docs/DESIGN.md`).

```
python3 gear_updater/gear_updater.py ports            # list ALSA MIDI ports (needs amidi)
python3 gear_updater/gear_updater.py dry-run FW.syx   # check a file and print what a flash would involve
python3 -m unittest discover tests                    # run the tests
```

## Safety rules
Dry run first, back up settings, check power, verify after flashing, keep a log, and never redistribute vendor firmware: you download it yourself.

## Privacy
No telemetry, no network access. Licence: AGPL-3.0-or-later.
