"""Optional 'Sign in with GitHub' (OAuth device flow, no scope). The updater works without it; signing in only raises
the GitHub API limit from 60 to 5000 requests per hour. The token is never logged.

Where the token is kept, in this order (Settings shows which one is in use):
  1. the operating system keychain (keyring),
  2. when no keychain works (Flatpak without a secret service, headless): an encrypted-at-rest local file in the app data
     folder with 0600 permissions, keyed by a random per-install secret stored beside it. HONEST LIMIT: the key sits next
     to the file, so this only stops casual reading (a backup, a screenshot of a folder, someone glancing at the file);
     it does not protect against another program that runs as you. The token has no permissions at all (it only raises the
     rate limit), which is why this is acceptable.
  3. this session only (kept in memory, gone when the app closes), chosen by the user or used when the file cannot be written.
When a refresh fails (expired refresh token, or the OAuth app wants a client secret for refresh) the app signs out cleanly
and says 'please sign in again'. It never retries in a loop and keeps working unauthenticated through the catalog.
Pure logic with injected transport and stores, so it is testable offline."""
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLIENT_ID = "Ov23liDYwELf2bo6qyoG"
DEVICE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
SERVICE, ACCOUNT = "Studio 87 Gear Updater", "github"
SAFETY = 60        # refresh a minute before the token expires


class AuthError(Exception):
    pass


def http_post(url, data, timeout=20):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Accept": "application/json", "User-Agent": "Studio87-GearUpdater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:           # GitHub answered, just not with success: that is a reply, not "offline"
        try:
            d = json.loads(e.read().decode("utf-8"))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {"error": "http_%d" % e.code}


class KeyringStore:
    """The OS keychain. available() is False when no keyring backend works: then the local file is used instead."""
    kind = "keychain"

    def available(self):
        try:
            import keyring
            from keyring.backends import fail
            return not isinstance(keyring.get_keyring(), fail.Keyring)
        except Exception:
            return False

    def load(self):
        try:
            import keyring
            raw = keyring.get_password(SERVICE, ACCOUNT)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def save(self, d):
        import keyring
        keyring.set_password(SERVICE, ACCOUNT, json.dumps(d))

    def clear(self):
        try:
            import keyring
            keyring.delete_password(SERVICE, ACCOUNT)
        except Exception:
            pass


class MemoryStore:
    kind = "session"

    def __init__(self):
        self.d = None

    def available(self):
        return True

    def load(self):
        return self.d

    def save(self, d):
        self.d = dict(d)

    def clear(self):
        self.d = None


MAGIC = b"S87T1"


def _stream(key, nonce, n):
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def seal(secret, plain, urandom=os.urandom):
    """Encrypt-then-MAC with HMAC-SHA256 only (no third-party crypto module is needed). Casual-reading protection, see module text."""
    salt, nonce = urandom(16), urandom(16)
    ek = hmac.new(secret, b"enc" + salt, hashlib.sha256).digest()
    mk = hmac.new(secret, b"mac" + salt, hashlib.sha256).digest()
    ct = bytes(a ^ b for a, b in zip(plain, _stream(ek, nonce, len(plain))))
    body = MAGIC + salt + nonce + ct
    return body + hmac.new(mk, body, hashlib.sha256).digest()


def unseal(secret, blob):
    if len(blob) < len(MAGIC) + 32 + 32 or not blob.startswith(MAGIC):
        raise ValueError("not a sealed token")
    body, tag = blob[:-32], blob[-32:]
    salt, nonce, ct = body[5:21], body[21:37], body[37:]
    mk = hmac.new(secret, b"mac" + salt, hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(mk, body, hashlib.sha256).digest(), tag):
        raise ValueError("token file was changed or the key does not match")
    ek = hmac.new(secret, b"enc" + salt, hashlib.sha256).digest()
    return bytes(a ^ b for a, b in zip(ct, _stream(ek, nonce, len(ct))))


class FileStore:
    """Encrypted-at-rest token file in the app data folder, permissions 0600 (see the module text for the honest limit)."""
    kind = "file"

    def __init__(self, directory, urandom=os.urandom):
        self.dir = Path(directory)
        self.token_path = self.dir / "token.enc"
        self.key_path = self.dir / "install.key"
        self.urandom = urandom

    def _write(self, path, data):
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = str(path) + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)

    def _secret(self, create):
        try:
            k = self.key_path.read_bytes()
            if len(k) == 32:
                return k
        except OSError:
            pass
        if not create:
            return None
        k = self.urandom(32)
        self._write(self.key_path, k)
        return k

    def available(self):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            probe = self.dir / ".probe"
            probe.write_bytes(b"x")
            probe.unlink()
            return True
        except OSError:
            return False

    def load(self):
        try:
            secret = self._secret(False)
            if secret is None:
                return None
            d = json.loads(unseal(secret, self.token_path.read_bytes()).decode("utf-8"))
            return d if isinstance(d, dict) else None
        except Exception:
            return None

    def save(self, d):
        secret = self._secret(True)
        self._write(self.token_path, seal(secret, json.dumps(d).encode("utf-8"), self.urandom))

    def clear(self):
        for p in (self.token_path, self.key_path):
            try:
                p.unlink()
            except OSError:
                pass


class AutoStore:
    """keychain -> local file -> this session. `session_only` (the user's choice) skips the first two.
    `kind` says what the last load or save really used; `planned_kind()` what a new sign in would use."""

    def __init__(self, keyring_store, file_store, session_only=False):
        self.keyring, self.file, self.mem = keyring_store, file_store, MemoryStore()
        self.session_only = session_only
        self.kind = None

    def available(self):
        return True

    def planned_kind(self):
        if self.session_only:
            return "session"
        if self.keyring.available():
            return "keychain"
        return "file" if self.file.available() else "session"

    def load(self):
        if self.mem.d is not None:
            self.kind = "session"
            return self.mem.d
        if self.session_only:
            return None
        if self.keyring.available():
            d = self.keyring.load()
            if d:
                self.kind = "keychain"
                return d
        d = self.file.load()
        if d:
            self.kind = "file"
            return d
        return None

    def save(self, d):
        self.mem.d = None
        if not self.session_only:
            if self.keyring.available():
                try:
                    self.keyring.save(d)
                    self.kind = "keychain"
                    self.file.clear()
                    return
                except Exception:
                    pass
            try:
                self.file.save(d)
                self.kind = "file"
                return
            except Exception:
                pass
        self.mem.save(d)
        self.kind = "session"

    def clear(self):
        self.mem.clear()
        self.keyring.clear()
        self.file.clear()
        self.kind = None


KIND_TEXT = {"keychain": "OS keychain", "file": "local file", "session": "this session only"}


class Auth:
    RETRY_AFTER = 300      # seconds to leave a refresh alone after a network failure (no hammering while offline)

    def __init__(self, post=http_post, store=None, now=time.time, sleep=time.sleep):
        self.post, self.store, self.now, self.sleep = post, store or KeyringStore(), now, sleep
        self._tok = None
        self._loaded = False
        self.expired = False          # True after a sign in stopped working: the UI says "please sign in again"
        self._no_refresh_until = 0.0

    def __repr__(self):
        return "<Auth signed_in=%s>" % self.signed_in

    @property
    def available(self):
        return self.store.available()

    @property
    def store_kind(self):
        """'keychain' | 'file' | 'session' | None (nothing stored). For the Settings status line."""
        if hasattr(self.store, "planned_kind") and not self.signed_in:
            return self.store.planned_kind()
        return getattr(self.store, "kind", None)

    def status_line(self):
        if self.signed_in:
            return "Signed in, token stored in: %s" % KIND_TEXT.get(self.store_kind, "this session only")
        if self.expired:
            return "Your GitHub sign in expired. Please sign in again (the list works without it)."
        return "Not signed in (optional). A new sign in would be kept in: %s" % KIND_TEXT.get(self.store_kind, "this session only")

    def _load(self):
        if not self._loaded:
            self._tok, self._loaded = self.store.load(), True
        return self._tok

    @property
    def signed_in(self):
        return bool(self._load() and self._tok.get("access_token"))

    def start(self):
        d = self.post(DEVICE_URL, {"client_id": CLIENT_ID})
        if "device_code" not in d or "user_code" not in d:
            raise AuthError(d.get("error_description") or d.get("error") or "GitHub did not give a code")
        return d

    def _store_token(self, d):
        tok = {"access_token": d["access_token"]}
        if d.get("refresh_token"):
            tok["refresh_token"] = d["refresh_token"]
        if d.get("expires_in"):
            tok["expires_at"] = self.now() + float(d["expires_in"])
        self.store.save(tok)
        self._tok, self._loaded = tok, True
        self.expired = False
        self._no_refresh_until = 0.0

    def poll(self, dev, cancelled=lambda: False):
        """Wait until the user approves the code in the browser. Raises AuthError on denial, expiry or cancel."""
        interval = max(1, int(dev.get("interval", 5)))
        deadline = self.now() + float(dev.get("expires_in", 900))
        while self.now() < deadline:
            if cancelled():
                raise AuthError("cancelled")
            self.sleep(interval)
            d = self.post(TOKEN_URL, {"client_id": CLIENT_ID, "device_code": dev["device_code"],
                                      "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
            if d.get("access_token"):
                self._store_token(d)
                return True
            err = d.get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval = int(d.get("interval", interval + 5))
                continue
            raise AuthError({"expired_token": "the code expired", "access_denied": "sign in was declined"}.get(err, err or "sign in failed"))
        raise AuthError("the code expired")

    def _expire(self):
        """The sign in no longer works: forget it once, quietly. No error, no retry loop."""
        self.sign_out()
        self.expired = True

    def invalidate(self):
        """GitHub answered 401 to a request that carried the token."""
        if self._load() and self._tok.get("access_token"):
            self._expire()

    def token(self):
        """Access token for api.github.com, refreshed when it is about to expire; None when signed out or expired."""
        t = self._load()
        if not t or not t.get("access_token"):
            return None
        exp = t.get("expires_at")
        if exp and self.now() > exp - SAFETY:
            if self.now() < self._no_refresh_until:
                return None           # a recent refresh could not reach GitHub: do not try again on every request
            rt = t.get("refresh_token")
            if not rt:
                self._expire()
                return None
            try:
                d = self.post(TOKEN_URL, {"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": rt})
            except Exception:
                self._no_refresh_until = self.now() + self.RETRY_AFTER
                return None           # offline: stay signed in, ask without the token this time
            if isinstance(d, dict) and d.get("access_token"):
                self._store_token(d)
            else:
                self._expire()        # expired refresh token, or the OAuth app wants a client secret to refresh
                return None
        return self._tok["access_token"]

    def sign_out(self):
        self.store.clear()
        self._tok, self._loaded = None, True
        self.expired = False
