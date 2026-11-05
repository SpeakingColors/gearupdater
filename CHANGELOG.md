# Changelog

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
