"""Optional 'Sign in with GitHub' (OAuth device flow, no scope). The updater works without it; signing in only raises
the GitHub API limit from 60 to 5000 requests per hour. The token is kept in the operating system keychain (keyring),
never in a file and never logged. Pure logic with injected transport and store, so it is testable offline."""
import json
import time
import urllib.parse
import urllib.request

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
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class KeyringStore:
    """The OS keychain. available() is False when no keyring backend works: then signing in is simply not offered."""

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


class Auth:
    def __init__(self, post=http_post, store=None, now=time.time, sleep=time.sleep):
        self.post, self.store, self.now, self.sleep = post, store or KeyringStore(), now, sleep
        self._tok = None
        self._loaded = False

    def __repr__(self):
        return "<Auth signed_in=%s>" % self.signed_in

    @property
    def available(self):
        return self.store.available()

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

    def token(self):
        """Access token for api.github.com, refreshed when it is about to expire; None when signed out."""
        t = self._load()
        if not t or not t.get("access_token"):
            return None
        exp = t.get("expires_at")
        if exp and self.now() > exp - SAFETY:
            rt = t.get("refresh_token")
            if not rt:
                self.sign_out()
                return None
            try:
                d = self.post(TOKEN_URL, {"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": rt})
            except Exception:
                return None           # offline: stay signed in, ask without the token this time
            if d.get("access_token"):
                self._store_token(d)
            else:
                self.sign_out()
                return None
        return self._tok["access_token"]

    def sign_out(self):
        self.store.clear()
        self._tok, self._loaded = None, True
