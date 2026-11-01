# Gear updater: design

Goal: one Linux tool that updates firmware for the studio gear without a Windows machine, and never bricks a unit. First target the FM-1; the same shell later covers other gear. This is that repo.

## Why per-device backends
Vendors do it differently. Facts from our folder:
- Ferrofish A32 / Pulse16: main firmware by the PC updater app (Windows exe, PulseUpdate) over USB or a MIDI port. Pulse16 has no USB, MIDI only. Ferrofish advises a good MIDI interface with its own driver because cheap class-compliant ones may lack buffer memory and the update fails. Dante boards (A32 Dante, Pulse16 DX) have a second firmware, updated over ethernet with Audinate's Dante Firmware Update Manager. Source: Ferrofish "Firmware Update Manual" and "P16 Dante FW Upgrade Procedure".
- FM-1: SysEx over USB MIDI only (community notes).
- Behringer: updates via the vendor app (SynthTribe), Windows and Mac. The Pro-1 guide says its updater is downloaded from musictribe.com with a notes file.
- Modal: MODALapp (Windows and Mac installers in our folder).
Nothing above says any of these protocols is documented by the vendor, so a native Linux backend is only built where we can capture and verify the protocol ourselves.

## Levels
1. Native backend: we speak the update protocol (FM-1 first, after a USBPcap capture of M-UPGRADE).
2. Guided: the tool checks version, power, cables, and explains the vendor route (Wine or a VM is not promised to work; test per device and write the result into the device page).
3. Info only: version lookup and links.

## Safety rules (apply to every backend)
- Dry run first: parse the file, verify size and checksum, print what will happen.
- Refuse unknown or unsigned-looking files unless the user confirms, and never flash a firmware without a documented way back.
- Back up settings and presets first.
- Check power (battery or USB), block sleep, never over Bluetooth.
- Verify after flashing; keep a log file.
- Never redistribute vendor firmware: the user downloads it or picks the file.

## Roadmap
- [ ] Capture M-UPGRADE with USBPcap and document the FM-1 SysEx update framing
- [ ] CLI: detect, dry-run, flash, rollback for the FM-1
- [ ] JUCE or CLI front end on cat-ui
- [ ] Ferrofish, Behringer, Modal guided pages
