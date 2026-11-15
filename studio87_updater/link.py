"""The plugin link: `studio87://open` and `studio87://open?product=<repo>`.

A plugin's About page can open this updater (and jump to that plugin's row) without any network call. The contract is
documented for plugin authors in docs/plugin-link.md. This module is the receiving side and is deliberately strict:

  - the scheme must be studio87 and the host exactly `open`; anything else is ignored;
  - only the `product` parameter is read, and only when it looks like a repository name (letters, digits, dot, dash,
    underscore, up to 100 characters) AND, when the catalog is known, is one of the catalog's products;
  - every other parameter, any path, any port, user name or fragment is ignored;
  - nothing in a link is ever executed, opened, downloaded or used as a file path. The only effect is: bring the window
    to the front and, for a valid product, show that product's row.
"""
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

SCHEME = "studio87"
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
MAX_LEN = 500


@dataclass(frozen=True)
class LinkAction:
    product: str = None          # a catalog repo name, or None (just open the updater)


def parse(text, known=None):
    """-> LinkAction for a valid `studio87://open[?product=...]`, else None (ignore the link).
    `known` is an optional iterable of catalog repo names; a product not in it is dropped (the app still opens)."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text or len(text) > MAX_LEN or any(ord(c) < 32 or ord(c) == 127 for c in text):
        return None
    try:
        u = urlsplit(text)
    except ValueError:
        return None
    if u.scheme.lower() != SCHEME:
        return None
    if u.netloc.lower() != "open" or u.path not in ("", "/"):
        return None
    product = None
    for k, v in parse_qsl(u.query, keep_blank_values=False, max_num_fields=20):
        if k == "product":
            if _REPO.match(v):
                product = v
            break                  # only the first `product` counts
    if product is not None and known is not None:
        by_lower = {str(n).lower(): n for n in known}
        product = by_lower.get(product.lower())
    return LinkAction(product)


def find_in_argv(argv):
    """The first command line argument that starts with `studio87:`, else None."""
    for a in argv or []:
        if isinstance(a, str) and a.lower().startswith(SCHEME + ":"):
            return a
    return None
