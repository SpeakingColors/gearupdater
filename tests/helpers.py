import hashlib
import io
import json
import os
import tarfile
import tempfile
import zipfile

from studio87_updater.github import Offline, Response


class FakeTransport:
    """Stands in for the network. Records every request so tests can check what is sent."""

    def __init__(self, routes=None):
        self.routes = routes or {}      # url -> (status, headers, body) or callable(headers)
        self.log = []
        self.offline = False

    def request(self, url, headers=None):
        self.log.append((url, dict(headers or {})))
        if self.offline:
            raise Offline("no network")
        r = self.routes.get(url)
        if r is None:
            return Response(404, {}, b"")
        if callable(r):
            r = r(headers or {})
        return Response(r[0], {k.lower(): v for k, v in r[1].items()}, r[2])

    def open_stream(self, url, headers=None):
        self.log.append((url, dict(headers or {})))
        if self.offline:
            raise Offline("no network")
        r = self.routes.get(url)
        if r is None:
            return 404, {}, None
        return r[0], {"content-length": str(len(r[2]))}, io.BytesIO(r[2])


def release_json(tag="v0.2.0", assets=(), body="Notes", prerelease=True, draft=False, name=None):
    return {"tag_name": tag, "name": name or tag, "body": body, "prerelease": prerelease, "draft": draft,
            "published_at": "2026-11-02T00:00:00Z", "html_url": "https://github.com/x/y/releases/tag/" + tag,
            "assets": [{"name": n, "size": len(b), "browser_download_url": "https://dl.test/" + n,
                        "digest": "sha256:" + hashlib.sha256(b).hexdigest()} for n, b in assets]}


def make_vst3_tar(name="PunchPaw.vst3", payload=b"binary", version="0.2.0"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for path, data in ((name + "/Contents/x86_64-linux/" + name.replace(".vst3", ".so"), payload),
                           (name + "/Contents/Resources/moduleinfo.json", ('{"Version": "%s"}' % version).encode())):
            ti = tarfile.TarInfo(path)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def make_release_zip(top="PunchPaw-v0.2.0", files=None, sums=True, corrupt=None):
    """A zip shaped like the Studio 87 release zips: top/windows, top/linux, SHA256SUMS."""
    files = files or {"linux/PunchPaw-linux-vst3.tar.gz": make_vst3_tar(), "INSTALL.txt": b"install me",
                      "windows/PunchPaw-Setup.exe": b"MZ"}
    lines = []
    for p, b in sorted(files.items()):
        lines.append("%s  ./%s" % (hashlib.sha256(b).hexdigest(), p))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p, b in files.items():
            z.writestr("%s/%s" % (top, p), (b + b"!") if p == corrupt else b)
        if sums:
            z.writestr(top + "/SHA256SUMS", "\n".join(lines) + "\n")
    return buf.getvalue()
