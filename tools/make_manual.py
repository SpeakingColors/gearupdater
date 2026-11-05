#!/usr/bin/env python3
"""Builds the PDF manual: text sections from docs/manual.txt plus an interface tour built from docs/tour (made from the real
window by tools/make_tour.py). Usage: python3 tools/make_manual.py out.pdf"""
import json
import sys
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as RLImage
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
TOUR = ROOT / "docs" / "tour"
ASSETS = ROOT / "studio87_updater" / "assets"
pdfmetrics.registerFont(TTFont("BC-Bold", str(ASSETS / "BarlowCondensed-Bold.ttf")))
pdfmetrics.registerFont(TTFont("BC", str(ASSETS / "BarlowCondensed-Medium.ttf")))
pdfmetrics.registerFont(TTFont("Mono", str(ASSETS / "JetBrainsMono-Regular.ttf")))

NAVY = colors.HexColor("#14183a")
PINK = colors.HexColor("#FF7BB1")
TEAL = colors.HexColor("#02EBBA")
H1 = ParagraphStyle("h1", fontName="BC-Bold", fontSize=26, leading=30, textColor=NAVY, spaceAfter=8)
H2 = ParagraphStyle("h2", fontName="BC-Bold", fontSize=17, leading=21, textColor=NAVY, spaceBefore=8, spaceAfter=4)
B = ParagraphStyle("b", fontName="BC", fontSize=11.5, leading=15, spaceAfter=5)
BL = ParagraphStyle("bl", parent=B, leftIndent=12, bulletIndent=2)
SM = ParagraphStyle("sm", fontName="BC", fontSize=10, leading=12.5)
SMB = ParagraphStyle("smb", parent=SM, fontName="BC-Bold")
MONO = ParagraphStyle("mono", fontName="Mono", fontSize=8.5, leading=11)
W = A4[0] - 36 * mm


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def sections(path):
    out, cur = {}, None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return out


def body(lines):
    fl = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("- "):
            fl.append(Paragraph(esc(ln[2:]), BL, bulletText="•"))
        else:
            fl.append(Paragraph(esc(ln), B))
    return fl


def img(path, width=W, maxh=None):
    w, h = Image.open(path).size
    hh = width * h / w
    if maxh and hh > maxh:
        width, hh = width * maxh / hh, maxh
    return RLImage(str(path), width=width, height=hh)


def table(rows, widths, head):
    t = Table([head] + rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, 0), "BC-Bold"), ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9cbe0")),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f3fa")]),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def footer(canv, doc):
    canv.saveState()
    canv.setFont("BC", 9)
    canv.setFillColor(colors.HexColor("#666a88"))
    canv.drawString(18 * mm, 10 * mm, "Studio 87 Gear Updater - free and open source (AGPL-3.0-or-later) - collects nothing")
    canv.drawRightString(A4[0] - 18 * mm, 10 * mm, "page %d" % doc.page)
    canv.restoreState()


def version():
    for ln in (ROOT / "studio87_updater" / "__init__.py").read_text().splitlines():
        if ln.startswith("__version__"):
            return ln.split('"')[1]
    return "0"


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "Studio87-GearUpdater-manual.pdf"
    sec = sections(ROOT / "docs" / "manual.txt")
    tour = json.loads((TOUR / "tour.json").read_text())
    story = []
    # cover
    story += [Spacer(1, 6 * mm), Paragraph("Studio 87 Gear Updater", ParagraphStyle("t", fontName="BC-Bold", fontSize=44, leading=48, textColor=NAVY)),
              Paragraph("Manual, version %s (test build)" % version(), ParagraphStyle("s", fontName="BC", fontSize=16, textColor=colors.HexColor("#555a80"), spaceAfter=10)),
              img(ROOT / "docs" / "screenshot.png", W),
              Spacer(1, 4 * mm),
              Paragraph("The window above was rendered offscreen from the real app with recorded GitHub data; the installed versions in it are staged so that every state shows.", SM),
              PageBreak()]
    for name in ("Intro", "Quick start"):
        story += [Paragraph(name, H1)] + body(sec[name])
    story.append(PageBreak())
    story += [Paragraph("Install and remove", H1)] + body(sec["Install and remove"]) + [Paragraph("Settings", H1)] + body(sec["Settings"]) + [PageBreak()]
    # tour
    story += [Paragraph("Interface tour", H1),
              Paragraph("Numbered pink badges are controls you can click. Lettered teal badges are displays. The picture is the real window at 150 percent.", B),
              img(TOUR / "window-badges.png", W),
              Paragraph("Signal flow in one line", H2),
              Paragraph("You open it or click Check for updates, then GitHub public release data (read only, saved with ETags), then the list with the installed version read from your computer, then your click on Update, then download, SHA256 check (refuse on mismatch), install by the product's own route, and a note of the installed version.", B),
              PageBreak()]
    story += [Paragraph("Controls", H1)]
    rows = [[Paragraph(str(c["n"]), SMB), Paragraph(esc(c["name"]), SMB), Paragraph(esc(c["tip"]), SM)] for c in tour["controls"]]
    story.append(table(rows, [10 * mm, 38 * mm, W - 48 * mm], ["#", "Control", "What it does (the hover bubble text)"]))
    story += [PageBreak(), Paragraph("Displays and the list row", H1),
              Paragraph("Each row of the list is one product. The picture is a real crop of one row.", B), img(TOUR / "row.png", W), Spacer(1, 3 * mm)]
    rows = [[Paragraph(d["letter"], SMB), Paragraph(esc(d["name"]), SMB), Paragraph(esc(d["text"]), SM)] for d in tour["displays"]]
    story.append(table(rows, [10 * mm, 42 * mm, W - 52 * mm], ["", "Display", "What it shows"]))
    story += [Paragraph("Status words", H2)]
    status = [("Update available", "The installed version is older than the newest release."), ("Up to date", "The installed version is the newest release or newer."),
              ("Not installed", "The updater looked where the plugin lives and found nothing."),
              ("Installed version unknown", "Something is there (or the updater cannot tell) but no version can be read, and this updater did not install it."),
              ("No release yet", "The repository has no published release."), ("Could not check", "GitHub gave an error for this product; the reason is shown."),
              ("View on GitHub", "Not set up for updates yet. Only a link to the project page.")]
    story.append(table([[Paragraph(esc(a), SMB), Paragraph(esc(b), SM)] for a, b in status], [45 * mm, W - 45 * mm], ["Status", "Meaning"]))
    story.append(PageBreak())
    # panels
    story += [Paragraph("The pop-up panels", H1)]
    for key, title, text in (("changelog", "Changelog", "Shows the release notes of every version newer than the installed one (or the newest one if the installed version is unknown). Page up and Page down move through long notes; there are no scrollbars."),
                             ("confirm", "Update several", "Update selected, Install selected, Apply selected, Update all and Install all show this list first, worded to match (for example: Apply 1 update and 2 installs?). It says the installers are not code-signed, and that your presets are never touched."),
                             ("settings", "Settings", "Look, hover bubbles and, on Linux, where plugins go. Saved on this computer only."),
                             ("about", "About", "What the app is, what it collects (nothing), where its own files are and how to remove it. The Ko-fi button only opens the page in your browser when you click it.")):
        story.append(KeepTogether([Paragraph(title, H2), Paragraph(text, B), img(TOUR / (key + ".png"), W * 0.78)]))
    story.append(PageBreak())
    story += [Paragraph("Safety and privacy", H1)] + body(sec["Safety and privacy"]) + [Paragraph("Troubleshooting", H1)] + body(sec["Troubleshooting"]) + [PageBreak()]
    # under the hood
    story += [Paragraph("Under the hood", H1), Paragraph("Facts taken from the source code (studio87_updater), not guesses.", B)]
    hood = [
        ("Network", "Only these requests, all GET: api.github.com/repos/OWNER/REPO/releases?per_page=6 (once per product per check), api.github.com/users/OWNER/repos?per_page=100&type=owner (once per check, to list repos that are not in products.json), raw.githubusercontent.com/OWNER/REPO/main/docs/screenshot.png (the row picture), and the release zip you chose to install. Headers: User-Agent Studio87-GearUpdater, Accept, and If-None-Match with an ETag GitHub gave. Timeout 20 seconds."),
        ("Rate limit", "The app reads X-RateLimit-Remaining and X-RateLimit-Reset. At 0 it makes no more API requests until the reset time and shows how many minutes are left. A saved answer is used instead. A missing screenshot is remembered for 24 hours."),
        ("Saved files", "Settings (settings.json) and the installed-versions list (installed-versions.json) live in the data folder Studio 87/Gear Updater. Saved GitHub answers, screenshots and the time of the last check live in the cache folder. A download is kept in a work folder only while it is being installed and is deleted afterwards."),
        ("Installed version", "In order: the VST3 bundle's moduleinfo.json (Version) or, on macOS, Info.plist (CFBundleShortVersionString); then installed-versions.json, but only while the bundle or Flatpak extension it installed is still there; the Flatpak list tells installed or not. A Flatpak extension carries no readable version here. Products without bundle or extension names in products.json show unknown until the updater installs them once."),
        ("Verification order", "Zip against GitHub's digest, then against the SHA256SUMS release asset if there is one, then every file inside against the zip's own SHA256SUMS. At least one must exist. The zip is unpacked only after the zip itself passes."),
        ("Install routes", "Linux VST3 tarball: unpacked to a temporary folder inside ~/.vst3, then the plugin's .vst3 folder is swapped in and the old one removed. Linux Flatpak: flatpak install --user -y --noninteractive --reinstall FILE (through flatpak-spawn --host when the updater itself runs in a Flatpak). Windows: the product's Setup.exe with /SILENT /NORESTART /SP-. macOS: open -W on the .pkg; nothing is recorded, the next check reads the bundle. Anything else: guided."),
        ("Limits", "The list scrolls (no pages, no scrollbars). The product's installer may run for up to 30 minutes. A download needs three times its size free on disk. Release zips are limited by GitHub to 2 GB per file."),
        ("Window", "The default design size is 1047 x 1150, fitted to your screen. A corner scales everything; a side changes only the width (960 to 1500) or the height (760 to 1500) and the rows, text wrapping and list length adapt while thumbnails keep their size. The only timer in the app is the one-second hover bubble."),
    ]
    story.append(table([[Paragraph(esc(a), SMB), Paragraph(esc(b), SM)] for a, b in hood], [30 * mm, W - 30 * mm], ["Topic", "Detail"]))
    story += [Spacer(1, 4 * mm), Paragraph("Honest status", H2),
              Paragraph("Tested: the pure core, the Qt window offscreen with a stub GitHub, and the deliberate bugs that the tests must catch. Not yet tested: a real plugin install on a real machine, the Flatpak, and the Windows and macOS builds. See ROADMAP.md.", B)]
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title="Studio 87 Gear Updater manual", author="Studio 87")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("wrote", out)


if __name__ == "__main__":
    main()
