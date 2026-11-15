Studio 87 Gear Updater 0.1.2 (test build). A free, open source window that lists every Studio 87 plugin and app, shows which have a newer version on GitHub, and updates them one by one, several at once or all together.

One zip: the Linux Flatpak, the Windows installer (.exe), the PDF manual with an interface tour, INSTALL.txt and SHA256SUMS. There is NO macOS package in this release: the macOS build queue was stuck, so macOS was skipped (the zip holds NO-MACOS.txt instead of a macos folder). It comes back with the next release. A separate SHA256SUMS asset lists the zip itself. The updater checks GitHub only when you open it or click Check for updates, collects nothing, verifies SHA256 before installing, and never touches your presets.

New in 0.1.2:
- No administrator prompt when the app starts. It asks once per batch, and only for All users installs. Just for me never asks.
- The version you had is kept and Roll back puts it back; a failed update restores the old version by itself.
- Downloads retry and resume. In Update all one failure does not stop the others; you get a result list and Retry failed.
- Sign in keeps its token in the keychain, else an encrypted local file (casual protection only), else this session only. Settings says which.
- Offline mode shows the saved list, product info and screenshots. Install and Update wait until you are online.
- "Update the updater first" when a newer version exists.
- Plugins can open the updater with studio87://open?product=NAME.
- Product list: 52 public products. Synth Cook Book (SynthCookBook) replaces catpro1, td3mo-vst was removed, and Purrr Voice Channel (a design mockup, no release yet) is listed with only a GitHub button.
- The PDF manual is a visual tour of the real window: numbered controls, every hover bubble, one section per pop-up, and an Under the hood page.

The installers are not code-signed or notarised. Windows may say "unknown publisher" (More info, Run anyway); macOS may need Privacy and Security, Open Anyway. This is not a sign of harm: the code is open and the checksums are in the zip.

This is a test build. Version 0.1.0 was tested on Windows and worked. Nothing in 0.1.2 has been tried on a real machine yet, and macOS and Linux have not been tested by anyone (and this release has no macOS package). See ROADMAP.md.
