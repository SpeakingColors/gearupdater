"""Where a product's picture comes from. Pure helpers; the network part lives in service.py.

Order: docs/screenshot.png, docs/screenshot.jpg, then the first usable image in the repo's README.
The default branch is reached through the raw 'HEAD' ref, so master/main/anything works.
Only images hosted by GitHub itself are used (this app talks to GitHub and nobody else)."""
import re
from urllib.parse import urljoin, urlparse

RAW = "https://raw.githubusercontent.com"
GOOD_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
SKIP_WORDS = ("icon", "logo", "badge", "shields.io", "banner-bg")
GITHUB_HOSTS = ("raw.githubusercontent.com", "github.com", "user-images.githubusercontent.com", "private-user-images.githubusercontent.com",
                "camo.githubusercontent.com", "objects.githubusercontent.com")


def candidate_urls(owner, repo):
    base = "%s/%s/%s/HEAD" % (RAW, owner, repo)
    return [base + "/docs/screenshot.png", base + "/docs/screenshot.jpg"]


def readme_url(owner, repo):
    return "%s/%s/%s/HEAD/README.md" % (RAW, owner, repo)


def readme_image(text, owner, repo):
    """First screenshot-like image URL in a README, or None. Icons, logos, badges and SVGs are skipped."""
    base = readme_url(owner, repo)
    found = re.findall(r'!\[[^\]]*\]\(\s*<?([^)\s>]+)', text or "") + re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', text or "")
    for raw in found:
        url = urljoin(base, raw)
        u = urlparse(url)
        path = u.path.lower()
        if u.scheme != "https" or u.hostname not in GITHUB_HOSTS:
            continue
        if not path.endswith(GOOD_EXT) or any(w in url.lower() for w in SKIP_WORDS):
            continue
        return url
    return None
