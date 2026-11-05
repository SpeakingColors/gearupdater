"""The catalog: ONE small file that a scheduled GitHub Action builds every 3 hours with GitHub's built-in
token (see .github/workflows/catalog.yml). The app reads it with a single request to raw.githubusercontent.com,
which is not subject to the 60-per-hour API limit, instead of one API call per product.
Pure parsing and decisions only; the fetching lives in service.py. Contains public data only."""
import json
import time

from . import releases as R

SCHEMA = 1
STALE_AFTER = 9 * 3600       # three missed 3-hour runs: say so and keep the per-product refresh in view
MISSING = "missing-repo"


def catalog_url(raw, owner, repo="gearupdater", branch="catalog"):
    return "%s/%s/%s/%s/catalog.json" % (raw, owner, repo, branch)


def thumb_url(raw, owner, product_repo, repo="gearupdater", branch="catalog"):
    return "%s/%s/%s/%s/thumbs/%s.jpg" % (raw, owner, repo, branch, product_repo)


class Catalog:
    def __init__(self, generated, products, public_repos=None):
        self.generated = generated            # epoch seconds
        self.products = products              # repo -> {"status": "ok"|"missing", "releases": [...], "thumb": bool}
        self.public_repos = public_repos

    def has(self, repo):
        return repo in self.products

    def releases(self, repo):
        """list of Release, MISSING (private or gone), or None when the catalog does not know this repo."""
        e = self.products.get(repo)
        if e is None:
            return None
        if e.get("status") == "missing":
            return MISSING
        return R.parse_releases(e.get("releases") or [])

    def has_thumb(self, repo):
        return bool((self.products.get(repo) or {}).get("thumb"))

    def age_seconds(self, now=None):
        return max(0.0, (now if now is not None else time.time()) - self.generated)

    def stale(self, now=None):
        return self.age_seconds(now) > STALE_AFTER


def parse_catalog(body):
    """bytes/str -> Catalog. Raises ValueError for anything that is not a usable catalog."""
    try:
        d = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("catalog is not JSON")
    if not isinstance(d, dict) or d.get("schema") != SCHEMA or not isinstance(d.get("products"), dict):
        raise ValueError("catalog has an unknown format")
    gen = d.get("generated_epoch")
    if not isinstance(gen, (int, float)):
        raise ValueError("catalog has no time stamp")
    pub = d.get("public_repos")
    return Catalog(float(gen), d["products"], pub if isinstance(pub, list) else None)


def describe(cat, now=None, local_time=time.localtime):
    """(text, stale) for the status line: 'catalog updated at 14:05' or the same plus an age warning."""
    when = time.strftime("%H:%M", local_time(cat.generated))
    if cat.stale(now):
        hours = int(cat.age_seconds(now) // 3600)
        return "catalog updated at %s (%d hours old, use Refresh on a product for the newest)" % (when, hours), True
    return "catalog updated at %s" % when, False
