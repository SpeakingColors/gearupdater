"""Parse GitHub release JSON (read-only public data)."""
import re
from dataclasses import dataclass, field

from . import version as V


@dataclass
class Asset:
    name: str
    size: int
    url: str
    sha256: str = None     # from GitHub's own digest field, when present


@dataclass
class Release:
    tag: str
    name: str
    body: str
    published: str
    prerelease: bool
    html_url: str
    assets: list = field(default_factory=list)

    @property
    def version(self):
        return V.clean(self.tag)

    @property
    def is_test_build(self):
        return self.prerelease or "test build" in (self.name or "").lower()

    def asset(self, name):
        for a in self.assets:
            if a.name == name:
                return a
        return None

    def zip_asset(self):
        zips = [a for a in self.assets if a.name.lower().endswith(".zip")]
        if not zips:
            return None
        tagged = [a for a in zips if self.tag and self.tag in a.name]
        return (tagged or zips)[0]

    def sums_asset(self):
        return self.asset("SHA256SUMS")


def parse_release(d):
    assets = []
    for a in d.get("assets") or []:
        dig = a.get("digest") or ""
        sha = dig.split(":", 1)[1].lower() if dig.lower().startswith("sha256:") else None
        assets.append(Asset(name=a.get("name", ""), size=int(a.get("size") or 0),
                            url=a.get("browser_download_url", ""), sha256=sha))
    return Release(tag=d.get("tag_name", ""), name=d.get("name") or d.get("tag_name", ""),
                   body=d.get("body") or "", published=(d.get("published_at") or d.get("created_at") or ""),
                   prerelease=bool(d.get("prerelease")), html_url=d.get("html_url", ""), assets=assets)


def parse_releases(items):
    """All non-draft releases, newest version first. Test builds count: every Studio 87 release is one."""
    rels = [parse_release(d) for d in (items or []) if not d.get("draft")]

    def key(r):
        p = V.parse(r.tag)
        return (1, p[0], 1 if p[1] is None else 0, r.published) if p else (0, (), 0, r.published)
    return sorted(rels, key=key, reverse=True)


_MD = [(re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""), (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
       (re.compile(r"[`*_>]+"), ""), (re.compile(r"^#+\s*"), "")]


def changelog_line(body, maxlen=100):
    """One short line for the list: the first real line of the release notes, markdown stripped."""
    for line in (body or "").splitlines():
        t = line.strip()
        for rx, rep in _MD:
            t = rx.sub(rep, t)
        t = t.strip(" -\t")
        if t:
            if len(t) > maxlen:
                t = t[:maxlen].rsplit(" ", 1)[0].rstrip(",.;: ") + "..."
            return t
    return ""


def notes_since(releases, installed_version, limit=5):
    """Releases newer than the installed version (all up to `limit` if the installed version is unknown)."""
    out = []
    for r in releases:
        if installed_version is None or V.is_update(installed_version, r.tag):
            out.append(r)
    return out[:limit]
