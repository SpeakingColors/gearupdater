Studio 87 Gear Updater 0.1.1 (test build). A free, open source window that lists every Studio 87 plugin and app, shows which have a newer version on GitHub, and updates them one by one, several at once or all together.

One zip: the Linux Flatpak, the Windows installer (.exe), the macOS installer (.pkg) if the macOS build was available, the PDF manual with an interface tour, INSTALL.txt and SHA256SUMS. A separate SHA256SUMS asset lists the zip itself. The updater checks GitHub only when you open it or click Check for updates, collects nothing, verifies SHA256 before installing, and never touches your presets.

The installers are not code-signed or notarised. Windows may say "unknown publisher" (More info, Run anyway); macOS may need Privacy and Security, Open Anyway. This is not a sign of harm: the code is open and the checksums are in the zip.

This is a test build: the automated tests, the deliberate-bug check and an offscreen render of the real window pass in CI, but it has not yet been used to install a plugin on a real machine, and the Flatpak, Windows and macOS installers have not been tried on real systems. See ROADMAP.md.


New in 0.1.1: a bigger portrait window ported from the approved mockup (resizable, fits your screen), the full public Studio 87 catalog from one small file that GitHub rebuilds every 3 hours, Install and Update buttons that say what they do, optional Sign in with GitHub (keychain, no permissions), install modes All users or Just for me, better installed-version detection. The zip is now called Studio87-Gear-Updater-v0.1.1.zip (v0.1.0 used Studio87-Updater-v0.1.0.zip); its layout is the same, so v0.1.0 can update to it.
Not tested by the author on real Windows, macOS or Linux installs yet; the OAuth token refresh is unverified.
