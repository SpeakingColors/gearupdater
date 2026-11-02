"""Glue between the pure core and the GUI/CLI. No Qt in here."""
import json
import os
import time
from pathlib import Path

from . import installed as I
from . import manifest as M
from . import model as MD
from . import paths as P
from .github import GitHubClient, Offline, RateLimited, UrlLibTransport
from .install import Installer

DEFAULT_SETTINGS = {"theme": "purr", "bubbles": True, "linux_target": "auto", "zoom_note_seen": False}
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
        if self.data["theme"] not in THEMES:
            self.data["theme"] = "purr"
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
                 flatpak_probe=None, runner=None):
        self.system = system or P.system_name()
        self._env, self._home = env, home
        self.data_dir = P.data_dir(self.system, env, home)
        self.cache_dir = P.cache_dir(self.system, env, home)
        self.manifest = manifest or M.load_manifest()
        self.client = GitHubClient(transport or UrlLibTransport(), self.cache_dir / "github")
        self.record = I.Record(self.data_dir / "installed-versions.json")
        self.settings = Settings(self.data_dir / "settings.json")
        self._vst3_dirs = vst3_dirs if vst3_dirs is not None else P.vst3_dirs(self.system, env, home)
        self._probe = flatpak_probe or (lambda: I.probe_flatpak() if self.system == "linux" else ("absent", set()))
        self._flatpak = ("absent", set())
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

    def installed_for(self, product):
        return I.detect(product, self.system, self.record, self._vst3_dirs, self._flatpak)

    def ext_installed(self, product):
        want = product.detect.get("flatpak")
        return bool(want and (I.EXT_PREFIX + want) in self._flatpak[1])

    # -- checking ----------------------------------------------------------
    def _discover(self, use_network):
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

    def cached_rows(self):
        self.refresh_local()
        self._discover(False)
        rows, _ = MD.build_rows(self.client, self.products, self.installed_for, use_network=False)
        return sorted(rows, key=MD.sort_key)

    def check(self, on_progress=None):
        """The only place that polls GitHub. Called when the app opens and on 'Check for updates'."""
        self.refresh_local()
        self._discover(True)
        rows, notice = MD.build_rows(self.client, self.products, self.installed_for, True, on_progress)
        if notice != "offline":
            self._save_last()
        return sorted(rows, key=MD.sort_key), notice

    def screenshot(self, product, use_network=True):
        url = self.client.screenshot_url(product.owner, product.repo, product.branch)
        try:
            body, _ = self.client.fetch(url, use_network=use_network)
        except Exception:
            body = self.client.cached_bytes(url)
        return body

    def installer(self):
        kw = {"runner": self.runner} if self.runner else {}
        return Installer(self.client, self.record, self.system, self.cache_dir / "work", P.user_vst3_dir(self.system, self._env, self._home),
                         self.data_dir / "downloads", linux_target=self.settings["linux_target"], **kw)
