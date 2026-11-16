# Studio 87 Gear Updater

<p align="center"><a href="https://ko-fi.com/studio87"><img src="https://raw.githubusercontent.com/SpeakingColors/.github/main/assets/kofi-banner.svg" alt="Support Studio 87 on Ko-fi" width="440"></a></p>

One window that lists every Studio 87 plugin, VST, FX and app, shows which ones have a newer version on GitHub, and updates them one by one, several at once, or all together. Free and open source, made mainly for the author, so it is built to be quick.

![Studio 87 Gear Updater](docs/screenshot.png)

*The screenshot is the real window rendered offscreen with recorded GitHub data for the products that were recorded; the "installed" versions are staged on purpose so every state shows (see Honest status).*

**TLDR**
- **Product list (v0.1.2):** 52 public products. `SynthCookBook` (Synth Cook Book) replaces `catpro1`, `td3mo-vst` was removed (its book lives in Synth Cook Book), and `purrrvoicechannel` (a design mockup) is listed with no release yet, so its row has only a GitHub button.
- A list: a 310 x 162 screenshot on the left, at most six lines on the right (name and kind, installed and latest version, status, a two-line description, date, size and install route). Buttons: Update or Install, Changelog, GitHub.
- The full public Studio 87 catalog in one scrolling list (mouse wheel, drag or keys; no scrollbars). It opens on Updates, with an "Everything is up to date" screen when there is nothing to do. Search filters as you type. Tabs: Updates, All (updates first, then by name), VST and FX, Synths, Controllers, Apps and logue, Installed, Not installed. Private and unavailable repos are never shown.
- Buttons say what they will do: Update all / Update selected only count real updates; on the Not installed tab it says Install all, and a row says Install; a mixed selection says Apply selected (N updates, M installs).
- It checks GitHub **only when you open it or click "Check for updates"**. No timers, no background polling, no auto-start.
- The only network use is read-only requests for public GitHub data and the download of a release zip you chose. The User-Agent is the generic `Studio87-GearUpdater`.
- Nothing is installed without a click. Every download is checked against `SHA256SUMS` first and **refused on a mismatch**, before any installed file is touched.
- Your presets and data folders are never touched.
- **New in 0.1.2:** the app always starts as a normal user (no administrator prompt at start; it asks once per batch, only for "All users" installs); the version before an update is kept and Roll back puts it back; a failed copy restores the old version by itself; downloads retry (up to four times) and resume; one failed product never stops Update all (a result list with Retry failed); sign in falls back from the keychain to a local file to this session only; offline mode shows the saved list; the updater tells you when a newer updater exists; plugins can open it with a `studio87://` link.
- The installers are **not code-signed**; the app says so where it matters.

## Install (double click, no terminal)
Get `Studio87-Gear-Updater-vX.Y.Z.zip` from the [Releases page](https://github.com/SpeakingColors/gearupdater/releases) (v0.1.0 was called `Studio87-Updater-v0.1.0.zip`; the layout of the zip is the same since then, so the updater can update itself) and follow `INSTALL.txt` inside it. The PDF manual is inside too, and [here](https://github.com/SpeakingColors/gearupdater/blob/main/docs/Studio87-GearUpdater-manual.pdf) (an interface tour of the real window, every hover bubble, and an Under the hood page):
- **Linux (Bazzite KDE and others):** double click `linux/Studio87-GearUpdater.flatpak`, then Install in the software centre.
- **Windows:** run `windows/Studio87-GearUpdater-Setup.exe` (unknown-publisher warning: More info, Run anyway).
- **macOS:** open `macos/Studio87-GearUpdater-macOS.pkg` (Privacy and Security, Open Anyway if blocked). **Version 0.1.2 has no macOS package:** the macOS build queue was stuck, so that release was built without it (the zip holds `NO-MACOS.txt` instead of a `macos` folder). The next release brings it back.

Each installer comes with an uninstaller that removes everything it installed; the updater's own settings stay unless you choose to delete them.

## How it works
1. On open it shows the list saved last time at once, then asks GitHub for the releases of every product in `studio87_updater/products.json` (one small read-only request per product, using ETags so unchanged answers cost nothing).
2. **Installed version** is read from what is really on the computer, never guessed: the VST3 bundle's own metadata (`moduleinfo.json`, or `Info.plist` on macOS), the Flatpak list, and the `installed-versions.json` this updater writes after it installs something (trusted only while the thing it installed is still there). Otherwise the row says *Not installed* or *Installed version unknown*.
3. **Update** downloads the release zip, verifies it, then follows the product's own `INSTALL.txt` route:
   - Linux: the VST3 tarball into `~/.vst3`, or the Flatpak extension if that product's extension is already installed (Settings can force either). Standalone apps: their Flatpak.
   - Windows: runs the release's `Setup.exe` silently. macOS: opens the `.pkg` in Installer.
   - Anything without a known installer (logue units, apps that ship an `install.sh`, a zip without the expected files): **guided**. It downloads and verifies, opens the folder, and shows you `INSTALL.txt`. It never runs scripts it does not know.
4. Verification (at least one source is required, all that exist must match): GitHub's own SHA-256 digest of the zip, a `SHA256SUMS` release asset that lists the zip, and the `SHA256SUMS` inside the zip for every file. The zip is unpacked safely (no path tricks, no symlinks, a plugin tarball must hold exactly one `.vst3` folder). These checks prove the download is intact and is what the release published; they are not a signature and do not prove who made it.

## Decisions (kept simple on purpose)
- **GUI toolkit: Qt 6 through PySide6 (Python).** Native on KDE, ships as a Flatpak on the KDE runtime and the PySide base app (no Qt bundled twice), as a PyInstaller build for Windows and macOS, and renders offscreen in CI for the screenshot and tests.
- **Layout:** ported from the approved mockup (`docs/mockup/updater-v11.html`, older versions in `docs/mockup/versions`). Default design size 1047 x 1150 (portrait), scaled down to fit your screen, never larger than it. Dragging a corner scales everything; a side changes only the width (960 to 1500) and the layout adapts; top or bottom changes only the height (760 to 1500) and shows more rows, text re-wraps and thumbnails keep their size. Double click on a wood side or Fit resets the size; 1:1 shows the design size. PurrOne wood sides, hover bubbles after one second, three looks in Settings (Neon Navy, Purple Soda Pop, PurrOne; PurrOne is the default).
- **Light:** no animation timers; the only timer is the one-second hover bubble. Network work runs on a thread pool; thumbnails are decoded as rows are shown.
- **Manifest:** `studio87_updater/products.json` maps repo to display name, kind (`vst3`, `controller`, `logue`, `app`, `unknown`), install method per OS, and where to look for the installed copy. Kinds and display names come from the repo names; `detect` hints (bundle and Flatpak names) were read from each product's own `release.yml` and are only filled in where that was done. Repos found on GitHub that are not in the file are listed as **view on GitHub**.
- **Catalog:** a scheduled workflow (`.github/workflows/catalog.yml`, every 3 hours) builds one `catalog.json` plus small thumbnails from the public API and publishes them on the `catalog` branch. The app fetches that single file by default (with ETag conditional requests), so it normally makes no API request per product and cannot hit the 60 per hour limit. If the catalog cannot be read it falls back to the API, one request per product, and stops asking when the limit is reached.
- **Optional sign in:** Settings, Sign in with GitHub (OAuth device flow, no permissions requested) raises the API limit to 5000 per hour. The token is kept in your system keychain when there is one; if not, in an encrypted file in the app's own folder (permissions 0600, key from a random secret stored next to it); if that is not possible, only for this session. Settings says which: "Signed in, token stored in: OS keychain / local file / this session only". **Honest limit:** the file route is casual protection only. The key sits beside the file, so it keeps the token out of plain sight and from other accounts, but not from a program running as you. The token is never logged. An expired refresh token falls back to "please sign in again"; the catalog keeps working without sign in.
- **Install modes:** All users (default on Windows and macOS) or Just for me (Windows `%LOCALAPPDATA%\Programs\Common\VST3`, macOS `~/Library/Audio/Plug-Ins/VST3`, Linux `~/.vst3`). **The app itself never needs administrator rights and starts without a prompt (v0.1.2; v0.1.1 asked at start).** Only "All users" installs of a Windows Setup.exe or a macOS .pkg need them: the app then starts one elevated helper for the whole batch (one UAC prompt on Windows, one password prompt on macOS). The helper reads a job file from the app's staging folder, re-checks each installer's SHA256, and runs fixed command lines; it takes no commands or paths from the file. "Just for me" never prompts.
- **Safe updates:** for plugin folders the app copies itself (Linux tarball and "Just for me" zip route) the previous version is kept under `Studio 87/Gear Updater/backups` (last version per product, 600 MB cap, Settings clears it) and Roll back puts it back in one click. If the new copy fails its check, the old one is restored automatically. A Setup.exe, .pkg or Flatpak is run as it is and cannot be taken back by the updater, so those rows have no Roll back. Downloads retry up to four times with backoff (1.5, 3, 6 and 12 seconds) and resume with an HTTP Range request.
- **Offline mode:** only the catalog, product info and screenshots are cached (60 MB cap, Settings clears it); never plugin files. Offline shows "Offline, showing saved list from <date>", Install and Update are off with a tooltip unless the installer zip was already downloaded.
- **Self update:** on open it compares its version with the newest gearupdater release; if newer, "Update the updater first" appears at the top. Windows runs the new Setup and exits; macOS opens the .pkg; the Linux Flatpak tells you the command to run. The footer shows "Studio 87 Gear Updater v0.1.2".
- **Plugin link:** `studio87://open[?product=<repo>]` (see `docs/plugin-link.md`). Only `open` and `product` are read, the product must exist in the catalog, nothing is executed, only one window exists.
- **Screenshots:** each repo's `docs/screenshot.png`, cached locally. Products without one show a tinted "no screenshot yet" tile; nothing is faked.

## Develop
```
python3 -m unittest discover tests          # pure core + firmware checker + GUI smoke tests (GUI ones skip without PySide6)
python3 tools/mutation_check.py             # applies deliberate bugs one at a time; the tests must catch every one
python3 -m studio87_updater --list          # same checks in the terminal, no GUI
python3 -m studio87_updater                 # the window (needs PySide6)
QT_QPA_PLATFORM=offscreen python3 tools/make_screenshot.py    # renders the real window with recorded data
QT_QPA_PLATFORM=offscreen python3 tools/make_tour.py          # re-shoots docs/tour (controls, badges, hover bubbles read from the real window)
python3 tools/make_manual.py Studio87-GearUpdater-manual.pdf  # builds the PDF manual from docs/manual.txt and docs/tour
```
Releases: run the `release` workflow by hand with a tag (`inputs[tag]=v0.1.2`). It builds the Flatpak, the Windows installer, the macOS package and the PDF manual, and publishes one zip plus a separate `SHA256SUMS` asset as a pre-release.

## Honest status
Verified: the unit and GUI smoke tests, the deliberate-bug check, CI runs, and the offscreen render of the real window. Real GitHub data was read for the repos this development session could reach (15 products); a real network check works from the command line.
**v0.1.0 was tested on Windows by the author and worked. Nothing in 0.1.2 has been tried on a real machine by anyone yet, and macOS and Linux have not been tested by anyone.** The new administrator helper, roll back, the `studio87://` registrations (registry, Info.plist, `.desktop`), self update and the file token store are covered by unit tests with fake backends only.
**Not verified:** a real install of a plugin on a real machine, anything on macOS (and the v0.1.2 release has no macOS package), the Flatpak (permissions, `flatpak-spawn --host`), Windows and macOS builds and installers, the macOS `.pkg` and uninstaller, and the Linux "Flatpak DAW" route. The `docs/screenshot.png` shows staged installed versions (a temporary fake VST3 folder with older version numbers) because the build machine has no real plugins installed. See `ROADMAP.md`.

## Also in this repo: firmware file checker (early)
`gear_updater/` is the earlier tool that checks firmware files and lists MIDI ports. It does not flash anything; each device's update protocol must first be captured and verified (see `docs/DESIGN.md`).
```
python3 gear_updater/gear_updater.py ports            # list ALSA MIDI ports (needs amidi)
python3 gear_updater/gear_updater.py dry-run FW.syx   # check a file and print what a flash would involve
```

## Fonts and licence
Fonts: Barlow Condensed and JetBrains Mono (SIL OFL, see `studio87_updater/assets`). Licence: AGPL-3.0-or-later. Support is optional: ko-fi.com/studio87.
