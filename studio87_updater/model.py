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


MISSING = "missing-repo"     # GitHub answered 404: private or gone, so it is never shown


def check_product(client, product, use_network=True):
    """(releases or None when never checked, error text, from_cache). Raises Offline / RateLimited."""
    url = client.releases_url(product.owner, product.repo)
    try:
        data, src = client.get_json(url, use_network=use_network)
    except HttpError as e:
        return None, "GitHub answered %s" % e.status, False
    if data is None:
        if src == "missing":
            return MISSING, "", False
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
            if rels == MISSING:
                if on_progress:
                    on_progress(i + 1, len(products), row)
                continue
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


# ---- tabs, search, view -----------------------------------------------------
TABS = [("updates", "Updates"), ("all", "All"), ("fx", "VST and FX"), ("synth", "Synths"), ("controller", "Controllers"),
        ("apps", "Apps and logue"), ("installed", "Installed"), ("notinstalled", "Not installed")]
TAB_KEYS = [k for k, _ in TABS]
CAT_LABEL = {"fx": "VST plugins and FX", "synth": "Synths", "controller": "Hardware controllers", "apps": "Apps and logue units"}


def in_tab(row, tab):
    if tab == "all":
        return True
    if tab == "updates":
        return row.status == UPDATE
    if tab == "installed":
        return row.status in (UPDATE, CURRENT)
    if tab == "notinstalled":
        return row.status == NOT_INSTALLED
    return row.product.cat == tab


def matches(row, query):
    """Every word of the query must appear in the name, kind, category or status text (case-insensitive)."""
    words = (query or "").lower().split()
    if not words:
        return True
    hay = " ".join([row.product.name, row.product.kind_label, CAT_LABEL.get(row.product.cat, ""),
                    STATUS_TEXT[row.status], status_line(row), installed_text(row)]).lower()
    return all(w in hay for w in words)


def filter_rows(rows, tab="all", query=""):
    return [r for r in rows if in_tab(r, tab) and matches(r, query)]



# ---- contextual bulk buttons: only updates count as updates, fresh installs are installs ----

def split_actions(rows):
    """(updates, installs) among the rows that can actually be installed."""
    ok = [r for r in rows if r.can_install]
    return ([r for r in ok if r.status == UPDATE],
            [r for r in ok if r.status in (NOT_INSTALLED, UNKNOWN_INSTALL)])


def _n(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def all_targets(view_rows):
    """What 'all' acts on: the updates in view; if the view holds none, the installs in view."""
    upd, ins = split_actions(view_rows)
    return upd if upd else ins


def all_label(view_rows):
    upd, ins = split_actions(view_rows)
    if upd:
        return "Update all (%d)" % len(upd)
    if ins:
        return "Install all (%d)" % len(ins)
    return "Update all (0)"


def selected_label(rows):
    upd, ins = split_actions(rows)
    if upd and ins:
        return "Apply selected (%s, %s)" % (_n(len(upd), "update"), _n(len(ins), "install"))
    if upd:
        return "Update selected (%d)" % len(upd)
    if ins:
        return "Install selected (%d)" % len(ins)
    return "Update selected"


def confirm_title(rows):
    upd, ins = split_actions(rows)
    if upd and ins:
        return "Apply %s and %s?" % (_n(len(upd), "update"), _n(len(ins), "install"))
    if ins:
        return "Install %s?" % _n(len(ins), "product")
    return "Update %s?" % _n(len(upd), "product")


def confirm_button(rows):
    upd, ins = split_actions(rows)
    if upd and ins:
        return "Apply %d" % (len(upd) + len(ins))
    return ("Install %d" if ins else "Update %d") % (len(ins) or len(upd))


def progress_word(row):
    """Verb for one row while a queue runs."""
    return "Installing" if row.status in (NOT_INSTALLED, UNKNOWN_INSTALL) else "Updating"
