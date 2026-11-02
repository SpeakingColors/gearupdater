"""products.json: which GitHub repos are Studio 87 products, how they are named and installed."""
import json
from dataclasses import dataclass, field
from pathlib import Path

KINDS = {
    "vst3": "VST3 plugin",
    "app": "Standalone app",
    "controller": "Hardware controller",
    "logue": "logue unit",
    "unknown": "Not classified",
}
INSTALL_METHODS = {
    "linux": {"vst3", "flatpak-app", "guided", "none"},
    "windows": {"exe", "guided", "none"},
    "macos": {"pkg", "guided", "none"},
}


class ManifestError(ValueError):
    pass


@dataclass
class Product:
    repo: str
    name: str
    kind: str = "unknown"
    install: dict = field(default_factory=dict)      # os -> method
    detect: dict = field(default_factory=dict)       # vst3: bundle base name, flatpak: extension name
    branch: str = "main"
    discovered: bool = False                         # found on GitHub, not in products.json
    owner: str = "SpeakingColors"

    @property
    def kind_label(self):
        return KINDS.get(self.kind, KINDS["unknown"])

    def method(self, system):
        return self.install.get(system, "none")

    @property
    def checks_releases(self):
        """Unknown products are listed as 'view on GitHub' and never polled."""
        return self.kind != "unknown" and any(v != "none" for v in self.install.values())

    @property
    def github_url(self):
        return "https://github.com/%s/%s" % (self.owner, self.repo)


@dataclass
class Manifest:
    owner: str
    products: list
    ignore: list

    def by_repo(self):
        return {p.repo.lower(): p for p in self.products}


def _validate_install(repo, install):
    for system, method in install.items():
        if system not in INSTALL_METHODS:
            raise ManifestError("%s: unknown OS '%s'" % (repo, system))
        if method not in INSTALL_METHODS[system]:
            raise ManifestError("%s: unknown install method '%s' for %s" % (repo, method, system))


def parse_manifest(data):
    if not isinstance(data, dict) or not isinstance(data.get("products"), list):
        raise ManifestError("products.json needs a 'products' list")
    owner = data.get("owner") or "SpeakingColors"
    defaults = data.get("defaults", {})
    seen, products = set(), []
    for raw in data["products"]:
        repo, name = raw.get("repo"), raw.get("name")
        if not repo or not name:
            raise ManifestError("every product needs 'repo' and 'name': %r" % (raw,))
        if repo.lower() in seen:
            raise ManifestError("duplicate repo %s" % repo)
        seen.add(repo.lower())
        kind = raw.get("kind", "unknown")
        if kind not in KINDS:
            raise ManifestError("%s: unknown kind '%s'" % (repo, kind))
        install = dict(defaults.get(kind, {}))
        install.update(raw.get("install", {}))
        if kind == "unknown":
            install = {}
        _validate_install(repo, install)
        products.append(Product(repo=repo, name=name, kind=kind, install=install,
                                detect=dict(raw.get("detect", {})), branch=raw.get("branch", "main"), owner=owner))
    return Manifest(owner=owner, products=products, ignore=[r.lower() for r in data.get("ignore", [])])


def load_manifest(path=None):
    path = Path(path) if path else Path(__file__).with_name("products.json")
    with open(path, encoding="utf-8") as f:
        return parse_manifest(json.load(f))


def merge_discovered(manifest, repo_names):
    """Add repos found on GitHub but not in the manifest as 'view on GitHub' entries."""
    known = manifest.by_repo()
    out = list(manifest.products)
    for r in repo_names:
        low = r.lower()
        if low in known or low in manifest.ignore:
            continue
        out.append(Product(repo=r, name=r, kind="unknown", discovered=True, owner=manifest.owner))
    return out
