# Changelog

## v0.1.2 (test build)
- No administrator prompt at start any more: the manifest and installer no longer ask. The app asks once per batch, only for All users installs of a Setup.exe or .pkg, through one elevated helper that re-checks each installer's SHA256 and runs fixed command lines. Just for me never asks.
- Safe updates: the previous plugin folder is kept (last version, 600 MB cap, cleared in Settings), Roll back puts it back, a failed copy or check restores it by itself, the SHA256 is verified before installed files are touched. Downloads retry with backoff and resume with HTTP Range.
- Update all keeps going after a failure and shows a result list with Retry failed.
- Sign in keeps its token in the keychain, else an encrypted local file (casual protection only, said plainly), else this session only; Settings says which. An expired refresh token falls back to "please sign in again".
- Offline mode for the catalog, product info and screenshots (60 MB cap, Clear in Settings); Install and Update are off with a reason, unless the installer is already downloaded.
- Self update: "Update the updater first" when a newer release exists; the footer shows the version everywhere.
- Plugin link `studio87://open[?product=<repo>]`, registered by the Windows installer, the macOS app and the Linux `.desktop` file; see `docs/plugin-link.md`.
- Product list: `catpro1` is now `SynthCookBook` (Synth Cook Book; an install record under the old name still counts), `td3mo-vst` was removed (its book lives in Synth Cook Book).
- Mockup is now `updater-v11.html` (v9 and v10 are kept in `docs/mockup/versions`).
- Same zip layout and a separate `SHA256SUMS` asset, so v0.1.1 can update to it. Not tested on real machines.

## v0.1.1 (test build)
- Renamed everywhere to Studio 87 Gear Updater. The release zip is now `Studio87-Gear-Updater-v0.1.1.zip` (v0.1.0 used `Studio87-Updater-v0.1.0.zip`); the zip still holds `windows`, `macos` and `linux` folders, a manual, `INSTALL.txt` and `SHA256SUMS`, and a separate `SHA256SUMS` asset lists the zip, so v0.1.0 can update to it.
- New window from the approved mockup: portrait 1047 x 1150, fitted to your screen; corners scale everything, sides change only width or height (960 to 1500 wide, 760 to 1500 high); 310 x 162 thumbnails, two-line descriptions, at most six lines per row, a scrolling list with search and category tabs, Installed and Not installed filters, opens on Updates with an "Everything is up to date" screen.
- All tab: products with an update first, then by name. Buttons say Update, Install, Update all, Install all (never Update all on the Not installed tab).
- Catalog: public Studio 87 repos only, from a `catalog.json` built every 3 hours by a GitHub Action (ETag requests), so the 60 per hour limit is not hit. Private or missing repos are never shown.
- Optional Sign in with GitHub (device flow, no permissions, token in the system keychain).
- Installed-version detection from VST3 `moduleinfo.json` or `Info.plist`, Inno uninstall registry, macOS pkg receipts and `flatpak info`.
- Screenshots from each repo's `docs/screenshot.png`, cached; tinted "no screenshot yet" tile otherwise.
- Install modes All users and Just for me; Windows build starts with an administrator manifest; macOS one prompt per batch; SHA256 checks of GitHub digest, `SHA256SUMS` asset and inner `SHA256SUMS`.

## v0.1.0 (test build)
First release: list, update, changelog, SHA256 verification, Flatpak, Windows installer and macOS package.
