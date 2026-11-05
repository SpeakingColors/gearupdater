"""Read-only GitHub client. Only public data; no identifiers; generic User-Agent.

Uses conditional requests (ETag): a 304 answer costs nothing against the unauthenticated limit
(about 60 API requests per hour) and the cached copy is used. Everything is cached on disk so the
list still shows when offline.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import USER_AGENT

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"


class Offline(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, reset_epoch=None):
        self.reset_epoch = reset_epoch
        super().__init__("GitHub rate limit reached")

    def message(self, now=None):
        if not self.reset_epoch:
            return "GitHub says too many requests were made. Try again later."
        mins = max(1, int((self.reset_epoch - (now or time.time())) / 60 + 0.999))
        return "GitHub rate limit reached (about 60 checks per hour without an account). Try again in about %d min." % mins


class HttpError(Exception):
    def __init__(self, status, url):
        self.status = status
        super().__init__("HTTP %s for %s" % (status, url))


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes = b""


class UrlLibTransport:
    """The only code that touches the network. Sends nothing about the user or the machine."""

    def __init__(self, user_agent=USER_AGENT, timeout=20):
        self.user_agent = user_agent
        self.timeout = timeout

    def _req(self, url, headers):
        h = {"User-Agent": self.user_agent}
        h.update(headers or {})
        return urllib.request.Request(url, headers=h, method="GET")

    def request(self, url, headers=None):
        try:
            with urllib.request.urlopen(self._req(url, headers), timeout=self.timeout) as r:
                return Response(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
        except urllib.error.HTTPError as e:
            return Response(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read() if e.fp else b"")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise Offline(str(e))

    def open_stream(self, url, headers=None):
        try:
            r = urllib.request.urlopen(self._req(url, headers), timeout=self.timeout)
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise Offline(str(e))


class GitHubClient:
    NEGATIVE_TTL = 24 * 3600

    def __init__(self, transport, cache_dir, now=time.time):
        self.t = transport
        self.cache_dir = str(cache_dir)
        self.now = now
        self.remaining = None
        self.reset = None
        self.requests_made = 0
        self.went_offline = False
        self.token_provider = None     # optional: returns an OAuth token string or None (never logged)
        os.makedirs(self.cache_dir, exist_ok=True)

    # -- cache -------------------------------------------------------------
    def _key(self, url):
        return os.path.join(self.cache_dir, hashlib.sha1(url.encode()).hexdigest())

    def _load_meta(self, url):
        try:
            with open(self._key(url) + ".meta", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _load_body(self, url):
        try:
            with open(self._key(url) + ".body", "rb") as f:
                return f.read()
        except OSError:
            return None

    def _save(self, url, etag, body, status=200):
        k = self._key(url)
        with open(k + ".body.tmp", "wb") as f:
            f.write(body)
        os.replace(k + ".body.tmp", k + ".body")
        with open(k + ".meta", "w", encoding="utf-8") as f:
            json.dump({"url": url, "etag": etag, "saved": self.now(), "status": status}, f)

    def cached_age(self, url):
        m = self._load_meta(url)
        return None if not m else self.now() - m.get("saved", 0)

    def cached_bytes(self, url):
        m = self._load_meta(url)
        if not m or m.get("status") != 200:
            return None
        return self._load_body(url)

    def cached_json(self, url):
        b = self.cached_bytes(url)
        if b is None:
            return None
        try:
            return json.loads(b.decode("utf-8"))
        except ValueError:
            return None

    # -- requests ----------------------------------------------------------
    def _note_rate(self, headers):
        try:
            if "x-ratelimit-remaining" in headers:
                self.remaining = int(headers["x-ratelimit-remaining"])
            if "x-ratelimit-reset" in headers:
                self.reset = int(headers["x-ratelimit-reset"])
        except ValueError:
            pass

    def _is_limited(self, resp):
        if resp.status == 429:
            return True
        if resp.status == 403:
            h = resp.headers
            return h.get("x-ratelimit-remaining") == "0" or "retry-after" in h or b"rate limit" in resp.body[:400].lower()
        return False

    def fetch(self, url, accept=None, use_network=True):
        """Return (bytes or None, source). source: 'network', 'not-modified', 'cache', 'missing'.
        Raises Offline (no cache to fall back on), RateLimited, HttpError."""
        meta = self._load_meta(url)
        cached = self._load_body(url) if meta and meta.get("status") == 200 else None
        if meta and meta.get("status") == 404 and self.now() - meta.get("saved", 0) < self.NEGATIVE_TTL:
            return None, "missing"
        if not use_network:
            return cached, "cache"
        if self.remaining is not None and self.remaining <= 0 and self.reset and self.now() < self.reset and url.startswith(API):
            raise RateLimited(self.reset)
        headers = {}
        if accept:
            headers["Accept"] = accept
        if meta and meta.get("etag") and cached is not None:
            headers["If-None-Match"] = meta["etag"]
        tok = self.token_provider() if (self.token_provider and url.startswith(API)) else None
        if tok:
            headers["Authorization"] = "Bearer " + tok
        try:
            resp = self.t.request(url, headers)
        except Offline:
            self.went_offline = True
            if cached is not None:
                return cached, "cache"
            raise
        self.requests_made += 1
        self._note_rate(resp.headers)
        if resp.status == 304 and cached is not None:
            return cached, "not-modified"
        if resp.status == 200:
            self._save(url, resp.headers.get("etag"), resp.body)
            return resp.body, "network"
        if resp.status == 404:
            self._save(url, None, b"", status=404)
            return None, "missing"
        if self._is_limited(resp):
            raise RateLimited(self.reset)
        raise HttpError(resp.status, url)

    def get_json(self, url, use_network=True):
        body, src = self.fetch(url, accept="application/vnd.github+json", use_network=use_network)
        if body is None:
            return None, src
        try:
            return json.loads(body.decode("utf-8")), src
        except ValueError:
            raise HttpError(200, url + " (not JSON)")

    # -- convenience -------------------------------------------------------
    def releases_url(self, owner, repo, n=6):
        return "%s/repos/%s/%s/releases?per_page=%d" % (API, owner, repo, n)

    def repos_url(self, owner):
        return "%s/users/%s/repos?per_page=100&type=owner" % (API, owner)

    def screenshot_url(self, owner, repo, branch="main"):
        return "%s/%s/%s/%s/docs/screenshot.png" % (RAW, owner, repo, branch)

    def download(self, url, dest, progress=None, cancel=lambda: False):
        """Stream a release asset to dest (via dest.part). Returns bytes written."""
        status, headers, stream = self.t.open_stream(url, {"Accept": "application/octet-stream"})
        if status != 200 or stream is None:
            raise HttpError(status, url)
        total = int(headers.get("content-length") or 0)
        done = 0
        part = str(dest) + ".part"
        try:
            with open(part, "wb") as f:
                while True:
                    if cancel():
                        raise InterruptedError("cancelled")
                    b = stream.read(1 << 18)
                    if not b:
                        break
                    f.write(b)
                    done += len(b)
                    if progress:
                        progress(done, total)
            os.replace(part, dest)
        except BaseException:
            try:
                os.remove(part)
            except OSError:
                pass
            raise
        finally:
            stream.close()
        return done
