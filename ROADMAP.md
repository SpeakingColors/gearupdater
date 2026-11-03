# Roadmap

## Done in v0.1.0
- Core with tests (version compare, manifest, release parsing, SHA256 verify, installed-version detection, GitHub client with ETag and rate-limit handling, installer logic).
- Qt window with the scrolling list, search, category tabs, optional pages, changelog, settings, about, hover bubbles, three looks, aspect-locked resize, wood sides.
- Linux Flatpak, Windows installer and macOS package built by `release.yml`.

## Not verified yet (needs a real machine)
- [ ] Install a plugin with the updater on the author's Bazzite KDE machine (native `~/.vst3` route and the Flatpak DAW extension route).
- [ ] Flatpak of the updater: sandbox permissions, `flatpak-spawn --host flatpak install`, opening folders and links.
- [ ] Windows: installer, silent run of product installers, version after install.
- [ ] macOS: `.pkg`, uninstall app, Installer.app flow for product packages (the updater records nothing for a `.pkg`; the next check reads the bundle).
- [ ] Which products really put a version into their VST3 bundle (`moduleinfo.json`). Where none does, the updater only knows what it installed itself.

## Next
- [ ] Fill in `detect` hints for every product (bundle and Flatpak names) as each repo is read; classify kinds from each README.
- [ ] Windows: read the file version of the installed VST3 so detection does not depend on the installed-versions file.
- [ ] Parse each product's `INSTALL.txt` route instead of the fixed rules (logue units, apps with `install.sh`).
- [ ] Optional: read the public `releases.atom` feeds, which are not subject to the API limit, so the first check needs fewer API requests.
- [ ] Optional: let `products.json` update itself from the repo (still read-only public data).
- [ ] Code signing and notarisation if a certificate is ever worth paying for; until then the installers say they are unsigned.
- [ ] Linux fallback package for systems without Flatpak.
- [ ] Self-update of the updater through its own row, tested.
- [ ] Hardware firmware updates: see `docs/DESIGN.md`; each device protocol must be captured and verified first.
