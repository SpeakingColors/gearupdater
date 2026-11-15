"""Glue between the pure core and the GUI/CLI. No Qt in here."""
import json
import os
import time
from pathlib import Path

from . import backup as BK
from . import cache as CA
from . import installed as I
from . import mode as MODE
from . import selfupdate as SU
from . import manifest as M
from . import model as MD
from . import paths as P
from . import shots as S
from . import catalog as CAT
from .github import GitHubClient, Offline, RateLimited, UrlLibTransport, RAW
from .install import Installer
from .auth import Auth, AutoStore, FileStore, KeyringStore

DEFAULT_SETTINGS = {"theme": "purr", "bubbles": True, "linux_target": "auto", "zoom_note_seen": False, "view": "scroll", "tab": "all", "install_mode": "", "mode_seen": False, "token_storage": "auto"}
THEMES = ("navy", "soda", "purr")


class Settings:
    def __init__(self, path):
        self.path = Path(path)
        self.data = dict(DEFAULT_SETTINGS)
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                for k in DEFAULT_SETTINGS:
                    if k in d:
                        self.data[k] = d[k]
        except (OSError, ValueError):
            pass
        if self.data["view"] not in ("pages", "scroll"):
            self.data["view"] = "scroll"
        if self.data["tab"] not in ("all", "fx", "synth", "controller", "apps", "installed", "notinstalled", "updates"):
            self.data["tab"] = "all"
        if self.data["theme"] not in THEMES:
            self.data["theme"] = "purr"
        if self.data["install_mode"] not in ("", "all-users", "just-me"):
            self.data["install_mode"] = ""
        if self.data["token_storage"] not in ("auto", "session"):
            self.data["token_storage"] = "auto"
        if self.data["linux_target"] not in ("auto", "native", "flatpak"):
            self.data["linux_target"] = "auto"

    def __getitem__(self, k):
        return self.data[k]

    def set(self, k, v):
        self.data[k] = v
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1)


class Service:
    def __init__(self, system=None, env=None, home=None, transport=None, manifest=None, vst3_dirs=None,
                 flatpak_probe=None, runner=None, auth=None):
        self.system = system or P.system_name()
        self._env, self._home = env, home
        P.migrate_old_data(self.system, env, home)
        self.data_dir = P.data_dir(self.system, env, home)
        self.cache_dir = P.cache_dir(self.system, env, home)
        self.manifest = manifest or M.load_manifest()
        self.client = GitHubClient(transport or UrlLibTransport(), self.cache_dir / "github")
        self.settings = Settings(self.data_dir / "settings.json")
        self.auth = auth or Auth(store=AutoStore(KeyringStore(), FileStore(self.data_dir / "auth"),
                                                 session_only=self.settings["token_storage"] == "session"))
        self.client.token_provider = self.auth.token
        self.client.on_unauthorized = self.auth.invalidate
        self.record = I.Record(self.data_dir / "installed-versions.json")
        self.backups = BK.BackupStore(self.data_dir / "backups")
        self.caches = CA.CacheManager(self.cache_dir / "github", self.cache_dir / "zips")
        self.offline = False
        self._vst3_dirs = vst3_dirs if vst3_dirs is not None else P.vst3_dirs(self.system, env, home)
        self._probe = flatpak_probe or (lambda: I.probe_flatpak() if self.system == "linux" else ("absent", set()))
        self._flatpak = ("absent", set())
        self._win, self._pkgs, self._fpv = {}, {}, {}
        self.no_shot = set()
        self.catalog = None
        self.runner = runner
        self.last_checked = self._load_last()
        self.products = list(self.manifest.products)

    # -- state -------------------------------------------------------------
    def _load_last(self):
        try:
            return float((self.cache_dir / "last_checked").read_text())
        except (OSError, ValueError):
            return None

    def _save_last(self):
        self.last_checked = time.time()
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / "last_checked").write_text(str(self.last_checked))
        except OSError:
            pass

    def refresh_local(self):
        """Re-read what is installed (local only, no network)."""
        self._flatpak = self._probe()
        self._fpv = {}
        if self.system == "windows":
            self._win = I.read_inno_uninstall()
        elif self.system == "macos":
            self._pkgs = I.read_pkgutil(self.runner or __import__("subprocess").run)

    @property
    def mode(self):
        return MODE.effective_mode(self.system, self.settings["install_mode"])

    def _flatpak_version(self, ext_id):
        if ext_id not in self._fpv:
            self._fpv[ext_id] = I.flatpak_info_version(ext_id, self.runner or __import__("subprocess").run)
        return self._fpv[ext_id]

    def installed_for(self, product):
        return I.detect(product, self.system, self.record, self._vst3_dirs, self._flatpak, self._win, self._pkgs,
                        self._flatpak_version)

    def ext_installed(self, product):
        want = product.detect.get("flatpak")
        return bool(want and (I.EXT_PREFIX + want) in self._flatpak[1])

    # -- checking ----------------------------------------------------------
    def _load_catalog(self, use_network):
        """The one-file catalog (see catalog.py). None when unreachable: the caller then asks the API as before."""
        url = CAT.catalog_url(RAW, self.manifest.owner)
        try:
            body, _ = self.client.fetch(url, use_network=use_network)
        except Exception:
            body = self.client.cached_bytes(url)
        try:
            return CAT.parse_catalog(body) if body else None
        except ValueError:
            return None

    def catalog_text(self):
        """('catalog updated at HH:MM', stale) or ('', False) when no catalog is in use."""
        return CAT.describe(self.catalog) if self.catalog is not None else ("", False)

    def refresh_one(self, product):
        """Ask the API directly for one product (counts against the hourly limit). Returns a Row."""
        rels, err, cached = MD.check_product(self.client, product, use_network=True)
        row = MD.Row(product=product, installed=self.installed_for(product))
        if rels == MD.MISSING:
            return None
        row.releases, row.error, row.from_cache = rels or [], err, cached
        row.status = MD.UNCHECKED if (rels is None and not err) else MD.compute_status(product, rels, row.installed, err or None)
        return row

    def _discover(self, use_network):
        if self.catalog is not None and self.catalog.public_repos:
            self.products = M.merge_discovered(self.manifest, [n for n in self.catalog.public_repos])
            return
        url = self.client.repos_url(self.manifest.owner)
        try:
            data, _ = self.client.get_json(url, use_network=use_network)
        except (Offline, RateLimited):
            data = self.client.cached_json(url)
        except Exception:
            data = None
        if not isinstance(data, list):
            return
        names = [d.get("name") for d in data if isinstance(d, dict) and d.get("name") and not d.get("private")]
        self.products = M.merge_discovered(self.manifest, names)

    def saved_date(self):
        """Epoch seconds of the list being shown from the saved copy (the catalog's time, else the last good check), or None."""
        if self.catalog is not None:
            return self.catalog.generated
        return self.last_checked

    def offline_text(self):
        """'Offline, showing saved list from 2026-11-15 14:05' (empty when online)."""
        if not self.offline:
            return ""
        t = self.saved_date()
        return "Offline, showing saved list from %s" % (time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "an earlier visit (date unknown)")

    def install_disabled_reason(self, row):
        """Why Install/Update cannot run right now, or '' when it can. Offline: only a zip that is already downloaded works."""
        if not self.offline:
            return ""
        try:
            if row.latest is not None and self.installer().zip_ready(row.product, row.latest):
                return ""
        except Exception:
            pass
        return "Offline. Install and Update need the internet to download the plugin, unless its installer is already downloaded."

    def self_update_release(self, rows):
        """The newer gearupdater release to offer, or None."""
        r = next((x for x in rows if x.product.repo == SU.SELF_REPO), None)
        return SU.newer_release(r.releases) if r is not None else None

    def cached_rows(self):
        self.refresh_local()
        self.catalog = self._load_catalog(False)
        self._discover(False)
        rows, _ = MD.build_rows(self.client, self.products, self.installed_for, use_network=False, catalog=self.catalog)
        return sorted(rows, key=MD.sort_key)

    def check(self, on_progress=None):
        """The only place that polls GitHub. Called when the app opens and on 'Check for updates'."""
        self.refresh_local()
        self.catalog = self._load_catalog(True)
        self._discover(True)
        rows, notice = MD.build_rows(self.client, self.products, self.installed_for, True, on_progress, catalog=self.catalog)
        self.offline = notice == "offline"
        if notice != "offline":
            self._save_last()
        try:
            self.caches.prune()
            self.caches.prune_downloads()
        except OSError:
            pass
        return sorted(rows, key=MD.sort_key), notice

    def _get(self, url, use_network):
        try:
            body, _ = self.client.fetch(url, use_network=use_network)
        except Exception:
            body = self.client.cached_bytes(url)
        return body or None

    def screenshot(self, product, use_network=True):
        """Image bytes for the list, or None. Cached on disk with ETag; 404s are remembered for a while."""
        if self.catalog is not None and self.catalog.has_thumb(product.repo):
            body = self._get(CAT.thumb_url(RAW, product.owner, product.repo), use_network)
            if body:
                self.no_shot.discard(product.repo)
                return body
        for url in S.candidate_urls(product.owner, product.repo):
            body = self._get(url, use_network)
            if body:
                self.no_shot.discard(product.repo)
                return body
        text = self._get(S.readme_url(product.owner, product.repo), use_network)
        img = S.readme_image(text.decode("utf-8", "replace") if text else "", product.owner, product.repo)
        body = self._get(img, use_network) if img else None
        if body:
            self.no_shot.discard(product.repo)
            return body
        if use_network:
            self.no_shot.add(product.repo)
        return None

    def installer(self):
        kw = {"runner": self.runner} if self.runner else {}
        return Installer(self.client, self.record, self.system, self.cache_dir / "work", P.user_vst3_dir(self.system, self._env, self._home),
                         self.data_dir / "downloads", linux_target=self.settings["linux_target"], mode=self.mode,
                         stage_dir=self.cache_dir / "staged", backups=self.backups, zip_dir=self.cache_dir / "zips", **kw)

    def self_update_folder(self):
        return self.data_dir / "selfupdate"
