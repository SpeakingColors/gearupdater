"""Stub transport that replays recorded public GitHub data (tools/screenshot_data). Used by the screenshot
tool and the GUI smoke test, so neither needs the network."""
import io
from pathlib import Path

from studio87_updater.github import Response

DATA = Path(__file__).resolve().parent / "screenshot_data"


class ReplayTransport:
    def __init__(self, files=None):
        self.files = files or {}       # url -> bytes, for downloads
        self.log = []

    def request(self, url, headers=None):
        self.log.append(url)
        if "/releases?per_page" in url:
            repo = url.split("/repos/SpeakingColors/")[1].split("/")[0]
            f = DATA / "releases" / (repo + ".json")
            if f.exists():
                return Response(200, {"etag": '"%s"' % repo, "x-ratelimit-remaining": "55"}, f.read_bytes())
            return Response(500, {}, b"{}")
        if url.startswith("https://raw.githubusercontent.com/"):
            repo = url.split("/")[4]
            f = DATA / "shots" / (repo + ".jpg")
            return Response(200, {"etag": '"s"'}, f.read_bytes()) if f.exists() else Response(404, {}, b"")
        if url in self.files:
            return Response(200, {}, self.files[url])
        return Response(404, {}, b"")

    def open_stream(self, url, headers=None):
        self.log.append(url)
        if url in self.files:
            b = self.files[url]
            return 200, {"content-length": str(len(b))}, io.BytesIO(b)
        return 404, {}, None
