"""Studio 87 Gear Updater: lists every Studio 87 plugin and app with an update available.

Pure core (no GUI): version compare, manifest, release parsing, checksums,
installed-version detection, GitHub client, installer logic. The Qt GUI lives in
`studio87_updater.gui` and is the only part that needs PySide6.

No telemetry. The only network use is read-only requests for public GitHub data and
the download of a release zip the user chose to install.
"""
__version__ = "0.1.1"
APP_NAME = "Studio 87 Gear Updater"
USER_AGENT = "Studio87-GearUpdater"
GITHUB_OWNER = "SpeakingColors"
