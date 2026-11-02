"""Turns manifest + releases + installed info into the rows the list shows."""
from dataclasses import dataclass, field

from . import releases as R
from . import version as V
from .github import HttpError, Offline, RateLimited

# status codes
UPDATE, CURRENT, NOT_INSTALLED, UNKNOWN_INSTALL, NO_RELEASE, GITHUB_ONLY, ERROR, UNCHECKED = (
    "update", "current", "not-installed", "unknown-install", "no-release", "github-only", "error", "unchecked")

STATUS_TEXT = {
    UPDATE: "Update available",
    CURRENT: "Up to date",
    NOT_INSTALLED: "Not installed",
    UNKNOWN_INSTALL: "Installed version unknown",
    NO_RELEASE: "No release yet",
    GITHUB_ONLY: "View on GitHub",
    ERROR: "Could not check",
    UNCHECKED: "Not checked yet",
}


@dataclass
class Row:
    product: object
    releases: list = field(default_factory=list)
    installed: object = None
    status: str = UNCHECKED
    error: str = ""
    from_cache: bool = False

    @property
    def latest(self):
        return self.releases[0] if self.releases else None

    @property
    def can_install(self):
        p = self.product
        return bool(self.latest and self.latest.zip_asset() and p.checks_releases)

    @property
    def action_label(self):
        return {UPDATE: "Update", NOT_INSTALLED: "Install", UNKNOWN_INSTALL: "Install"}.get(self.status, "Update")

    @property
    def changelog_line(self):
        return R.changelog_line(self.latest.body) if self.latest else ""

    def notes(self):
        iv = self.installed.version if self.installed else None
        return R.notes_since(self.releases, iv)


def compute_status(product, releases, installed, error=None):
    if not product.checks_releases:
        return GITHUB_ONLY
    if error:
        return ERROR
    if releases is None:
        return UNCHECKED
    if not releases:
        return NO_RELEASE
    latest = releases[0]
    if installed is None or installed.state == "unknown":
        return UNKNOWN_INSTALL
    if installed.state == "not-installed":
        return NOT_INSTALLED
    if installed.version is None:
        return UNKNOWN_INSTALL
    upd = V.is_update(installed.version, latest.tag)
    if upd is None:
        return UNKNOWN_INSTALL
    return UPDATE if upd else CURRENT


def sort_key(row):
    order = {UPDATE: 0, UNKNOWN_INSTALL: 1, NOT_INSTALLED: 2, CURRENT: 3, ERROR: 4, NO_RELEASE: 5, UNCHECKED: 5, GITHUB_ONLY: 6}
    return (order.get(row.status, 9), row.product.name.lower())


def check_product(client, product, use_network=True):
    """(releases or None when never checked, error text, from_cache). Raises Offline / RateLimited."""
    url = client.releases_url(product.owner, product.repo)
    try:
        data, src = client.get_json(url, use_network=use_network)
    except HttpError as e:
        return None, "GitHub answered %s" % e.status, False
    if data is None:
        return (None if src == "cache" else []), "", src == "cache"
    return R.parse_releases(data), "", src == "cache"


def build_rows(client, products, installed_for, use_network=True, on_progress=None):
    """Check every product. Returns (rows, notice); notice is '' or a user-facing message.
    Stops using the network on the first offline or rate-limit answer and fills the rest from the cache."""
    rows, notice, net = [], "", use_network
    client.went_offline = False
    for i, p in enumerate(products):
        row = Row(product=p, installed=installed_for(p))
        if p.checks_releases:
            try:
                rels, err, cached = check_product(client, p, use_network=net)
            except Offline:
                net, notice = False, notice or "offline"
                rels, err, cached = check_product(client, p, use_network=False)
            except RateLimited as e:
                net, notice = False, e.message(client.now())
                rels, err, cached = check_product(client, p, use_network=False)
            if client.went_offline:
                net, notice = False, notice or "offline"
            row.releases, row.error, row.from_cache = rels or [], err, cached
            row.status = UNCHECKED if (rels is None and not err) else compute_status(p, rels, row.installed, err or None)
        else:
            row.status = GITHUB_ONLY
        rows.append(row)
        if on_progress:
            on_progress(i + 1, len(products), row)
    return rows, notice


def installed_text(row):
    i = row.installed
    if i is None or i.state == "unknown":
        return "unknown"
    if i.state == "not-installed":
        return "not installed"
    return i.version or "installed, version not readable"


def status_line(row):
    s = row.status
    if s == ERROR:
        return row.error or STATUS_TEXT[ERROR]
    if s == UNKNOWN_INSTALL:
        i = row.installed
        if i is not None and i.state == "installed":
            return "Installed, version not readable"
        return "Cannot tell if it is installed"
    if s == GITHUB_ONLY:
        return "Not set up for updates yet: view on GitHub"
    if s == UNCHECKED:
        return "Not checked (offline or rate limited)"
    return STATUS_TEXT[s]


METHOD_TEXT = {"vst3": "VST3 (native or Flatpak)", "exe": "Windows installer", "pkg": "macOS installer",
               "flatpak-app": "Flatpak", "guided": "guided: opens the folder", "none": "no installer"}


def method_text(row, system):
    return METHOD_TEXT.get(row.product.method(system), "no installer")
