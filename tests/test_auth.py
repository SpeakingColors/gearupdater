import unittest

from studio87_updater import auth as A


class Clock:
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class AuthTests(unittest.TestCase):
    def mk(self, replies):
        self.calls = []
        it = iter(replies)

        def post(url, data):
            self.calls.append((url, dict(data)))
            return next(it)
        c = Clock()
        self.store = A.MemoryStore()
        return A.Auth(post=post, store=self.store, now=c.now, sleep=c.sleep), c

    def test_device_flow_sends_client_id_and_no_scope_and_stores_token(self):
        au, _ = self.mk([{"device_code": "dc", "user_code": "ABCD-1234", "verification_uri": "https://github.com/login/device", "interval": 5, "expires_in": 900},
                         {"error": "authorization_pending"}, {"error": "slow_down", "interval": 10},
                         {"access_token": "tok1", "refresh_token": "ref1", "expires_in": 28800}])
        dev = au.start()
        self.assertEqual(dev["user_code"], "ABCD-1234")
        self.assertEqual(self.calls[0][1], {"client_id": "Ov23liDYwELf2bo6qyoG"})
        self.assertNotIn("scope", self.calls[0][1])
        self.assertTrue(au.poll(dev))
        self.assertTrue(au.signed_in)
        self.assertEqual(self.store.d["refresh_token"], "ref1")
        self.assertEqual(au.token(), "tok1")

    def test_denied_expired_and_cancel(self):
        au, _ = self.mk([{"error": "access_denied"}])
        with self.assertRaises(A.AuthError):
            au.poll({"device_code": "x", "interval": 1, "expires_in": 60})
        self.assertFalse(au.signed_in)
        au, _ = self.mk([])
        with self.assertRaises(A.AuthError):
            au.poll({"device_code": "x", "interval": 1, "expires_in": 60}, cancelled=lambda: True)

    def test_expired_token_is_refreshed_and_failed_refresh_signs_out(self):
        au, c = self.mk([{"access_token": "new", "refresh_token": "r2", "expires_in": 28800}])
        self.store.save({"access_token": "old", "refresh_token": "r1", "expires_at": c.t - 5})
        self.assertEqual(au.token(), "new")
        self.assertEqual(self.calls[0][1]["grant_type"], "refresh_token")
        au, c = self.mk([{"error": "bad_refresh_token"}])
        self.store.save({"access_token": "old", "refresh_token": "r1", "expires_at": c.t - 5})
        self.assertIsNone(au.token())
        self.assertFalse(au.signed_in)
        self.assertIsNone(self.store.d)

    def test_token_never_in_repr_and_signed_out_sends_no_header(self):
        au, _ = self.mk([])
        self.store.save({"access_token": "SECRETTOKEN"})
        self.assertNotIn("SECRETTOKEN", repr(au))
        au.sign_out()
        self.assertIsNone(au.token())

    def test_client_sends_bearer_only_to_api(self):
        import tempfile
        from helpers import FakeTransport
        from studio87_updater.github import GitHubClient
        t = FakeTransport({"https://api.github.com/x": (200, {}, b"[]"), "https://raw.githubusercontent.com/y": (200, {}, b"[]")})
        c = GitHubClient(t, tempfile.mkdtemp())
        c.token_provider = lambda: "TOK"
        c.fetch("https://api.github.com/x")
        c.fetch("https://raw.githubusercontent.com/y")
        hdrs = [h for _u, h in t.log]
        self.assertIsNotNone(hdrs)
        self.assertEqual(hdrs[0].get("Authorization"), "Bearer TOK")
        self.assertNotIn("Authorization", hdrs[1])


if __name__ == "__main__":
    unittest.main()
