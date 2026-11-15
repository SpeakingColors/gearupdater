# Plugin link: open Studio 87 Gear Updater from a plugin

Every Studio 87 plugin can have an "Open Studio 87 Gear Updater" button in its About page. The button makes **no network call**
and sends nothing. It only asks the operating system to open a link of this form, and the updater (if it is installed) opens
and, optionally, jumps to that plugin's row.

## The contract

```
studio87://open
studio87://open?product=<repo>
```

- `studio87` is the scheme, `open` is the only action. There is no other action.
- `product` is optional: the GitHub repository name of the plugin, exactly as it appears under github.com/SpeakingColors
  (for example `PurrOne`, `catcrusher-vst`, `FatCat`). Case does not matter.
- Nothing else is read. Any other parameter, any path, port, user name or fragment is ignored. An unknown `product` is ignored too
  and the updater simply opens.
- A link can never run a command, open a file, download anything or use a path. The only effect is: the updater window comes
  to the front and, for a known product, shows that product's row (the All tab, search cleared, the row outlined).
- Only one updater window exists. If it is already open it is brought to the front and shows the product; a second window is not started.

## The snippet for plugins (JUCE)

```cpp
// In the About page, on the "Open Studio 87 Gear Updater" button:
const bool opened = juce::URL("studio87://open?product=NAME").launchInDefaultBrowser();

if (! opened)
    showMessage ("Install Studio 87 Gear Updater from github.com/SpeakingColors/gearupdater/releases");
```

Replace `NAME` with the plugin's repository name. Use `studio87://open` when the plugin has no repository row.

Fallback message, exactly: **Install Studio 87 Gear Updater from github.com/SpeakingColors/gearupdater/releases**

Show it when `launchInDefaultBrowser()` returns `false`. Honest limit: whether `launchInDefaultBrowser()` reports `false` when
no program handles a custom scheme can differ between Windows, macOS and Linux and has not been tested on all three, so also
put the same sentence in the button's hover bubble ("If nothing opens, install Studio 87 Gear Updater from
github.com/SpeakingColors/gearupdater/releases"). A plugin inside a sandboxed DAW (for example a Flatpak DAW) may not be allowed to
open links at all; the hover bubble covers that case too.

Do not put the plugin's version, the user's name, or anything else into the link. The button must not do anything else
(no update check, no network).

## How the updater registers the link (set up when you install it)

| System | How | Where |
| --- | --- | --- |
| Windows | Registry key `Software\Classes\studio87` with `URL Protocol`, command `"...\Studio87GearUpdater.exe" "%1"` | HKCU for a "just for me" install, HKLM for an all-users install (Inno Setup `HKA`), removed by the uninstaller |
| macOS | `CFBundleURLTypes` with scheme `studio87` in the app's `Info.plist`; the link arrives as an Apple Event (Qt `QFileOpenEvent`) | the app in /Applications; macOS learns the scheme when the app is first opened or moved |
| Linux | the Flatpak's `.desktop` file has `MimeType=x-scheme-handler/studio87;` and `Exec=studio87-gearupdater %u` | exported by the Flatpak; run from source it is not registered |

Status: tested here with unit tests (the link parser, the single instance hand-over, and checks that each installer declares the
scheme). **Not tested on a real Windows, macOS or Linux desktop** by the author: whether each system really launches the updater
from a link has not been confirmed.

## What the receiving side checks

`studio87_updater/link.py` is the only code that reads a link:

1. the scheme must be `studio87` and the host exactly `open`, with an empty path or `/`; otherwise the link is ignored;
2. the whole text is at most 500 characters with no control characters;
3. only the first `product` value is used, and only when it matches letters, digits, dot, dash and underscore (up to 100) and is
   one of the products in the catalog;
4. the result is a small object with one optional field (the product); nothing from the link is executed or opened.

## Test it by hand

- Windows (after installing): press Win+R and type `studio87://open?product=PurrOne`.
- macOS: `open "studio87://open?product=PurrOne"` in Terminal.
- Linux (Flatpak installed): `xdg-open "studio87://open?product=PurrOne"`.
- Any system, from source: `python3 -m studio87_updater "studio87://open?product=PurrOne"`.
