"""Builds catalog.json and thumbs/ for the app. Run by .github/workflows/catalog.yml every 3 hours.
Reads PUBLIC data only (release lists, public repo names, docs/screenshot images). Usage:
  GH_TOKEN=... python3 tools/build_catalog.py OUT_DIR [PREVIOUS_catalog.json]
The token is the Actions built-in GITHUB_TOKEN; it is only used as an Authorization header for api.github.com."""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio87_updater import shots as S  # noqa: E402

API = "https://api.github.com"
KEEP = ("tag_name", "name", "body", "published_at", "created_at", "prerelease", "draft", "html_url")


def get(url, token=None, accept=None):
    h = {"User-Agent": "Studio87-GearUpdater-catalog"}
    if token and url.startswith(API):
        h["Authorization"] = "Bearer " + token
    if accept:
        h["Accept"] = accept
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, OSError):
        return 0, b""


def trim(rel):
    out = {k: rel.get(k) for k in KEEP}
    out["assets"] = [{"name": a.get("name"), "size": a.get("size"), "browser_download_url": a.get("browser_download_url"),
                      "digest": a.get("digest")} for a in rel.get("assets") or []]
    return out


def thumb_bytes(owner, repo):
    """Scaled once here, so every app download is small. Returns JPEG bytes or None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    urls = S.candidate_urls(owner, repo)
    st, body = get(S.readme_url(owner, repo))
    img = S.readme_image(body.decode("utf-8", "replace"), owner, repo) if st == 200 else None
    for u in urls + ([img] if img else []):
        st, data = get(u)
        if st == 200 and data:
            try:
                im = Image.open(io.BytesIO(data)).convert("RGB")
                im.thumbnail((620, 324))
                out = io.BytesIO()
                im.save(out, "JPEG", quality=82)
                return out.getvalue()
            except Exception:
                continue
    return None


def main():
    out = Path(sys.argv[1])
    prev = {}
    if len(sys.argv) > 2 and Path(sys.argv[2]).is_file():
        try:
            prev = json.loads(Path(sys.argv[2]).read_text()).get("products", {})
        except ValueError:
            prev = {}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    manifest = json.loads((ROOT / "studio87_updater" / "products.json").read_text())
    owner = manifest.get("owner") or "SpeakingColors"
    (out / "thumbs").mkdir(parents=True, exist_ok=True)
    products, failed = {}, 0
    for p in manifest["products"]:
        if p.get("kind") == "unknown" and not p.get("releases", True):
            continue
        repo = p["repo"]
        st, body = get("%s/repos/%s/%s/releases?per_page=6" % (API, owner, repo), token, "application/vnd.github+json")
        if st == 200:
            entry = {"status": "ok", "releases": [trim(r) for r in json.loads(body) if not r.get("draft")]}
        elif st == 404:
            entry = {"status": "missing"}        # private or gone: the app never shows it
        else:
            failed += 1
            entry = prev.get(repo) or {"status": "ok", "releases": []}      # keep the last good answer
            print("could not read %s (HTTP %s), kept the previous entry" % (repo, st))
        if entry["status"] == "ok":
            tb = thumb_bytes(owner, repo)
            if tb:
                (out / "thumbs" / (repo + ".jpg")).write_bytes(tb)
            entry["thumb"] = bool(tb) or bool((prev.get(repo) or {}).get("thumb") and (out / "thumbs" / (repo + ".jpg")).exists())
        products[repo] = entry
    st, body = get("%s/users/%s/repos?per_page=100&type=owner" % (API, owner), token, "application/vnd.github+json")
    public = [r["name"] for r in json.loads(body) if not r.get("private")] if st == 200 else None
    cat = {"schema": 1, "generated_epoch": int(time.time()), "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "owner": owner, "public_repos": public, "products": products}
    (out / "catalog.json").write_text(json.dumps(cat, separators=(",", ":")))
    print("catalog written: %d products, %d kept from the previous run" % (len(products), failed))
    return 0 if failed < len(products) else 1


if __name__ == "__main__":
    sys.exit(main())
