"""The documentation must match the app: web page, tour data (made from the real window) and the manual's inputs."""
import json
import unittest
from pathlib import Path

from studio87_updater import __version__

ROOT = Path(__file__).resolve().parents[1]


class DocsTest(unittest.TestCase):
    def test_web_page(self):
        html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertIn("v" + __version__, html)
        for ref in ("screenshot.png", "Studio87-GearUpdater-manual.pdf", "mockup/updater-v11.html"):
            self.assertIn(ref, html)
            self.assertTrue((ROOT / "docs" / ref).exists(), ref)

    def test_tour_matches_version_and_has_bubbles(self):
        tour = json.loads((ROOT / "docs" / "tour" / "tour.json").read_text())
        self.assertEqual(tour["version"], __version__)
        for key in ("main", "working", "bars", "changelog", "confirm", "results", "settings", "signin", "about", "firstrun"):
            self.assertIn(key, tour["scenes"])
            self.assertTrue((ROOT / "docs" / "tour" / tour["scenes"][key]["image"]).exists())
            for c in tour["scenes"][key]["controls"]:
                self.assertTrue(c["tip"], "%s: %s has no hover bubble" % (key, c["name"]))

    def test_no_long_dashes_in_docs(self):
        for f in ("README.md", "INSTALL.txt", "CHANGELOG.md", "ROADMAP.md", "release/NOTES.md", "docs/manual.txt", "docs/index.html", "docs/tour/extra.json"):
            t = (ROOT / f).read_text(encoding="utf-8")
            self.assertNotIn("—", t, f)
            self.assertNotIn("–", t, f)

    def test_docs_agree(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        notes = (ROOT / "release" / "NOTES.md").read_text(encoding="utf-8")
        install = (ROOT / "INSTALL.txt").read_text(encoding="utf-8")
        for t in (readme, notes):
            self.assertIn("52", t)
            self.assertIn("catpro1", t)
        self.assertIn("NO-MACOS", install)
        self.assertNotIn("unzip", readme.lower() + install.lower() + (ROOT / "docs" / "manual.txt").read_text().lower())


if __name__ == "__main__":
    unittest.main()
