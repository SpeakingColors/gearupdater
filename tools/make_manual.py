#!/usr/bin/env python3
"""Builds the PDF manual from data: the text sections in docs/manual.txt, and the interface tour that tools/make_tour.py
reads out of the real window (docs/tour/tour.json, the PNGs and docs/tour/extra.json). Nothing about a control, a range, a
default or a hover bubble is typed here. Usage: python3 tools/make_manual.py out.pdf"""
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
from reportlab.platypus import CondPageBreak, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
TOUR = ROOT / "docs" / "tour"
ASSETS = ROOT / "studio87_updater" / "assets"
pdfmetrics.registerFont(TTFont("BC-Bold", str(ASSETS / "BarlowCondensed-Bold.ttf")))
pdfmetrics.registerFont(TTFont("BC", str(ASSETS / "BarlowCondensed-Medium.ttf")))
pdfmetrics.registerFont(TTFont("Mono", str(ASSETS / "JetBrainsMono-Regular.ttf")))

NAVY = colors.HexColor("#14183a")
H1 = ParagraphStyle("h1", fontName="BC-Bold", fontSize=26, leading=30, textColor=NAVY, spaceAfter=8)
H2 = ParagraphStyle("h2", fontName="BC-Bold", fontSize=17, leading=21, textColor=NAVY, spaceBefore=8, spaceAfter=4, keepWithNext=1)
H3 = ParagraphStyle("h3", fontName="BC-Bold", fontSize=13, leading=16, textColor=colors.HexColor("#3a3f6e"), spaceBefore=6, spaceAfter=3)
B = ParagraphStyle("b", fontName="BC", fontSize=11.5, leading=15, spaceAfter=5)
BL = ParagraphStyle("bl", parent=B, leftIndent=12, bulletIndent=2)
SM = ParagraphStyle("sm", fontName="BC", fontSize=10, leading=12.5)
SMB = ParagraphStyle("smb", parent=SM, fontName="BC-Bold")
CAP = ParagraphStyle("cap", fontName="BC", fontSize=9.5, leading=12, textColor=colors.HexColor("#555a80"), spaceAfter=6)
W = A4[0] - 36 * mm
PAGE_H = A4[1] - 34 * mm


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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


def controls_table(ctrls):
    rows = [[Paragraph(str(c["n"]), SMB), Paragraph(esc(c["name"]), SMB), Paragraph(esc(c.get("range", "")), SM), Paragraph(esc(c.get("default", "")), SM),
             Paragraph(esc(c["tip"] or "(no hover bubble)"), SM)] for c in ctrls]
    return table(rows, [8 * mm, 36 * mm, 30 * mm, 24 * mm, W - 98 * mm], ["#", "Control", "Range", "Default", "What it does (the full hover bubble text)"])


def displays_table(dsp):
    rows = [[Paragraph(d["letter"], SMB), Paragraph(esc(d["name"]), SMB), Paragraph(esc(d["text"]), SM)] for d in dsp]
    return table(rows, [8 * mm, 38 * mm, W - 46 * mm], ["", "Display", "What it shows"])


def with_head(title, tbl, n):
    """Heading kept with its table when the table is short; a long table may start right under its heading and run on."""
    if n <= 6:
        return [KeepTogether([Paragraph(title, H3), tbl])]
    return [CondPageBreak(40 * mm), Paragraph(title, H3), tbl]


def panel(story, tour, key, panels, maxh=100 * mm, extra_flow=(), keep=False):
    sc = tour["scenes"][key]
    title, text = panels[key]
    head = [Paragraph(title, H1 if key == "bars" else H2), Paragraph(esc(text), B), img(TOUR / sc["image"], W, maxh), Spacer(1, 2 * mm)]
    rest = []
    if sc["controls"]:
        rest += with_head("Controls", controls_table(sc["controls"]), len(sc["controls"]))
    if sc["displays"]:
        rest += with_head("Displays", displays_table(sc["displays"]), len(sc["displays"]))
    rest += list(extra_flow)
    rest.append(Spacer(1, 6 * mm))
    if keep:
        story.append(KeepTogether(head + rest))
    else:
        story.append(KeepTogether(head))
        story += rest


def hood_rows(h):
    p = h["paths"]
    caps = h["caps"]
    dl = h["downloads"]
    rows = [
        ("Where its own files live", "Data (settings, install list, backups, token file): Linux %s (inside the Flatpak: ~/.var/app/io.github.speakingcolors.Studio87GearUpdater/data/Studio 87/Gear Updater); Windows %s; macOS %s. "
         "Cache (saved GitHub answers, screenshots, downloads): Linux %s; Windows %s; macOS %s. Presets and plugin data folders are never in there and are never touched." % (
             p["linux"][0], p["windows"][0], p["macos"][0], p["linux"][1], p["windows"][1], p["macos"][1])),
        ("What is stored, and how big", "settings.json (your choices: look, bubbles, install mode, Linux target, where to keep the sign in; a few lines of text). installed-versions.json (what this updater installed, per product). "
         "backups/<repo>/ (the one previous version of each plugin the app copied itself, for Roll back; all together capped at %s; a bundle bigger than the cap is not kept and the update says so; Settings, Previous versions, Clear removes them). "
         "auth/token.enc and auth/install.key (only when the sign in is kept in a file). selfupdate/ (the new updater while it is being checked). "
         "In the cache folder: github/ (every saved GitHub answer and screenshot for offline mode, capped at %s, oldest first; Settings, Saved list, Clear empties it), "
         "zips/ (a release zip that finished downloading and waits for its install: deleted when the install worked; leftovers older than %d days are dropped and the folder is kept under %s at each check; Settings does not clear it), "
         "work/ (unpacked files during an install, deleted afterwards), staged/ (verified Setup.exe or .pkg files waiting for the one administrator step, deleted after it), and last_checked (the time of the last good check)." % (
             caps["backups"], caps["saved_list"], caps["zip_days"], caps["zips"])),
        ("Token storage chain", "Sign in is optional. The token is kept in the first place that works: (1) the OS keychain (service '%s', account '%s'); (2) when there is no keychain (a Flatpak without a secret service, a headless system) an encrypted file auth/token.enc in the data folder, permissions 0600, sealed with HMAC-SHA256 using a random key in auth/install.key beside it; "
         "(3) this session only, in memory. Settings says which one is in use. The file route is casual protection only: the key sits beside the file, so it hides the token from other accounts and from a glance, not from a program running as you. "
         "The token is sent only with requests to api.github.com, never to downloads, and is never logged. If GitHub answers 401 the token is forgotten once and the request is repeated without it; the list keeps working and Settings says 'please sign in again'." % (h["token"]["service"], h["token"]["account"])),
        ("The studio87:// link contract", "studio87://open or studio87://open?product=<repo>. Only the scheme studio87, the host open and the product parameter are read; the product must look like a repository name (letters, digits, dot, dash, underscore, up to 100) and be in the catalog. "
         "Any other parameter, path, port, user name or fragment is ignored, the whole text may be at most 500 characters with no control characters, and nothing in a link is ever executed, opened, downloaded or used as a file path. "
         "The only effect is that the window comes to the front and shows that product's row. Only one window exists. Registered by the Windows installer (registry), the macOS app (Info.plist) and the Linux Flatpak (.desktop file); not yet tried on a real desktop. Details: docs/plugin-link.md."),
        ("Install modes and when administrator rights are needed", "The app itself always starts as a normal user. Linux never needs administrator rights (~/.vst3 and user-level Flatpaks). On Windows and macOS the mode is %s (default on Windows and macOS) or %s. "
         "Only an All users install of a Windows Setup.exe or a macOS .pkg needs them, and then ONE elevated helper runs for the whole batch (one UAC prompt on Windows, one password prompt on macOS), none when the app already runs as administrator. "
         "The helper reads a job file (elevated-job.json) from the app's own staged folder, re-checks each installer's SHA256, and runs fixed command lines only: Setup.exe /SILENT /NORESTART /SP- and /usr/sbin/installer -pkg FILE -target /. It takes no commands or paths from the file. Just for me never prompts." % (
             h["modes"]["labels"]["all-users"], h["modes"]["labels"]["just-me"])),
        ("Verification (SHA256)", "At least one source must exist and all that exist must match: GitHub's own SHA-256 digest of the zip, a SHA256SUMS release asset that lists the zip, and the SHA256SUMS inside the zip for every file. The zip is unpacked only after the zip itself passes; paths outside the target and symbolic links are refused and a plugin tarball must hold exactly one .vst3 folder. "
         "A mismatch refuses that product before any installed file is touched. These checks prove the download is intact and is what the release published; they are not a signature and do not prove who made it."),
        ("Network and no telemetry", "Everything is a GET to public data: raw.githubusercontent.com (catalog.json and the thumbnails), api.github.com (release lists per product as a fallback and a list of repos; with the token if you signed in), and the release zip you chose (github.com). Headers: User-Agent Studio87-GearUpdater, Accept, and If-None-Match with an ETag GitHub gave. Timeout %d seconds. "
         "Nothing about you or your computer is sent. There is no telemetry, no account, no identifier, no timer, no background check and no auto-start; it checks GitHub only when you open it or click Check for updates." % dl["timeout"]),
        ("catalog.json and the rate limit", "A scheduled GitHub Action (catalog.yml, every 3 hours) reads the public releases of every product and publishes ONE small file, catalog.json, plus 620 x 324 thumbnails, as a single commit on the catalog branch of this repository. The app reads that one file (with an ETag, so an unchanged file costs nothing), so it normally makes no GitHub API request at all. "
         "If the file is older than 9 hours the status line turns amber and says so. If it cannot be read the app asks the API per product (about 50 requests; 60 per hour allowed without an account, 5000 if you sign in). It reads X-RateLimit-Remaining and X-RateLimit-Reset; at 0 it stops asking until the reset time, shows the saved list and says in how many minutes to try again. A missing screenshot is remembered for 24 hours."),
        ("Downloads", "A failed or cut-off download is retried up to %d times with growing pauses (%s seconds) and resumes where it stopped with an HTTP Range request (a server that ignores Range restarts that file); the part is kept when it gives up, so Retry failed continues it. A download needs three times its size free on disk. GitHub limits a release file to 2 GB." % (
            dl["retries"], ", ".join(("%g" % x) for x in dl["pauses"]))),
        ("Install routes", "Linux VST3 tarball: unpacked to a temporary folder inside ~/.vst3, then the plugin's .vst3 folder is swapped in and the old one kept for Roll back. Linux Flatpak: flatpak install --user -y --noninteractive --reinstall FILE (through flatpak-spawn --host when the updater itself runs in a Flatpak). "
         "Windows: the product's Setup.exe, silent; with Just for me the zip's plugin folder is copied into the per-user VST3 folder instead. macOS: the product's .pkg is opened in Installer; nothing is recorded, the next check reads the bundle. Anything else is guided: it downloads and verifies, opens the folder and shows you INSTALL.txt. It never runs scripts it does not know. A Setup.exe, .pkg or Flatpak cannot be taken back by the updater, so those rows have no Roll back."),
        ("Window", "The default design size is 1047 x 1150, fitted to your screen and never larger than it. A corner scales everything; a side changes only the width (960 to 1500) or the height (760 to 1500) and the rows, text wrapping and list length adapt while thumbnails keep their size. The only timer in the app is the one-second hover bubble. No animations."),
    ]
    return rows


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "Studio87-GearUpdater-manual.pdf"
    sec = sections(ROOT / "docs" / "manual.txt")
    tour = json.loads((TOUR / "tour.json").read_text())
    extra = json.loads((TOUR / "extra.json").read_text())
    panels = extra["panels"]
    sc = tour["scenes"]
    story = []
    # cover
    story += [Spacer(1, 6 * mm), Paragraph("Studio 87 Gear Updater", ParagraphStyle("t", fontName="BC-Bold", fontSize=44, leading=48, textColor=NAVY)),
              Paragraph("Manual, version %s (test build)" % version(), ParagraphStyle("s", fontName="BC", fontSize=16, textColor=colors.HexColor("#555a80"), spaceAfter=10)),
              img(ROOT / "docs" / "screenshot.png", W, 190 * mm),
              Spacer(1, 4 * mm),
              Paragraph("The window above was rendered offscreen from the real app with recorded GitHub data; the installed versions in it are staged so that every state shows. "
                        "Test build: version 0.1.0 worked on Windows; nothing in 0.1.2 has been tried on a real machine, and macOS and Linux have not been tested by anyone. Version 0.1.2 has no macOS package.", CAP),
              PageBreak()]
    for name in ("Intro", "Quick start"):
        story += [Paragraph(name, H1)] + body(sec[name])
    story += [Paragraph("What is in the zip", H2)] + body(sec["What is in the zip"])
    story += [Paragraph("Install and remove", H1)] + body(sec["Install and remove"])
    story += [Paragraph("Safety and privacy", H1)] + body(sec["Safety and privacy"])
    story.append(PageBreak())
    # tour: main window
    story += [Paragraph("Interface tour", H1),
              Paragraph("Numbered pink badges are controls you can click. Lettered teal badges are displays. The picture is the real window at 150 percent, rendered offscreen with recorded GitHub data; "
                        "every control name, range and hover bubble in the tables comes out of the app itself.", B),
              img(TOUR / sc["main"]["image"], W, 205 * mm),
              Paragraph("Signal flow in one line", H3), Paragraph(esc(extra["flow"]), B), PageBreak()]
    story += [Paragraph("Main window: controls", H1), controls_table(sc["main"]["controls"]), Spacer(1, 6 * mm)]
    story += [Paragraph("Main window: displays and the list row", H1),
              Paragraph("Each row of the list is one product. The picture is a real crop of one row, with the Roll back button showing because a previous version is kept for it.", B), img(TOUR / "row.png", W, 70 * mm),
              Spacer(1, 3 * mm), displays_table(sc["main"]["displays"]), Paragraph("Status words", H2)]
    status = [("Update available", "The installed version is older than the newest release."), ("Up to date", "The installed version is the newest release or newer."),
              ("Not installed", "The updater looked where the plugin lives and found nothing."),
              ("Installed version unknown", "Something is there (or the updater cannot tell) but no version can be read, and this updater did not install it."),
              ("No release yet", "The repository has no published release. The row shows only a GitHub button."), ("Could not check", "GitHub gave an error for this product; the reason is shown."),
              ("View on GitHub", "Not set up for updates yet. Only a link to the project page.")]
    story.append(table([[Paragraph(esc(a), SMB), Paragraph(esc(b), SM)] for a, b in status], [45 * mm, W - 45 * mm], ["Status", "Meaning"]))
    story.append(Spacer(1, 6 * mm))
    # panels
    story += [Paragraph("Bars, batches and pop-up panels", H1), Paragraph("One section per panel: the real picture with numbered controls and lettered displays, then the control table and the display table.", B)]
    panel(story, tour, "bars", panels, 75 * mm)
    panel(story, tour, "working", panels, 42 * mm)
    panel(story, tour, "confirm", panels, 62 * mm)
    panel(story, tour, "results", panels, 58 * mm)
    panel(story, tour, "changelog", panels, 58 * mm)
    panel(story, tour, "signin", panels, 52 * mm)
    panel(story, tour, "about", panels, 68 * mm)
    panel(story, tour, "firstrun", panels, 50 * mm)
    panel(story, tour, "settings", panels, 80 * mm, keep=False)
    st = tour["hood"]["status_lines"]
    story += [Paragraph("Sign in status line (under the GitHub account button)", H3),
              table([[Paragraph(esc(x), SM)] for x in st["signed_in"] + [st["expired"], st["out"]]], [W], ["Text shown"]), Paragraph("Settings in words", H3)] + body(sec["Settings"])
    story += [Paragraph("Troubleshooting", H1)] + body(sec["Troubleshooting"])
    # under the hood
    story += [CondPageBreak(60 * mm), Paragraph("Under the hood", H1), Paragraph("Facts taken from the source code (studio87_updater) and the repository's workflows, not guesses. Sizes and limits are the real constants.", B)]
    hood = hood_rows(tour["hood"])
    story.append(table([[Paragraph(esc(a), SMB), Paragraph(esc(b), SM)] for a, b in hood], [34 * mm, W - 34 * mm], ["Topic", "Detail"]))
    story += [Spacer(1, 4 * mm), Paragraph("Honest status", H2),
              Paragraph("Tested: the pure core, the Qt window offscreen with a stub GitHub, the deliberate bugs that the tests must catch, and CI runs. Version 0.1.0 was tried on Windows by the author. "
                        "Not yet tested on a real machine: any real plugin install by this version, the Flatpak (permissions, flatpak-spawn --host), the Windows and macOS builds and installers, the administrator helper, Roll back, the studio87:// registrations, self update and the file token store. "
                        "macOS and Linux have not been tested by anyone, and the macOS package is missing from v0.1.2. See ROADMAP.md.", B)]
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title="Studio 87 Gear Updater manual", author="Studio 87")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("wrote", out)


if __name__ == "__main__":
    main()
