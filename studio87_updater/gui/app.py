"""The Qt window, ported from the approved mockup (docs/mockup/updater-v9.html): design size 1047 x 1150, scaled to the window."""
import os
import sys
import time
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QFontMetrics, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QApplication, QLineEdit, QScrollArea, QGraphicsScene, QGraphicsView, QMainWindow, QTextBrowser, QWidget)

from .. import APP_NAME, __version__
from .. import model as MD
from .. import mode as MODE
from ..service import THEMES, Service
from .theme import LOOKS, THEME
from .widgets import MONO, BubbleManager, Btn, Check, font, paint_cat, wood_pixmap

DW, DH = 1047, 1150
MINW, MINH, MAXW, MAXH = 960, 760, 1500, 1500
S_MIN, S_MAX = 0.3, 2.0
CHEEK = 34
ROW_H = 172
ROW_GAP = 4
THUMB_W, THUMB_H = 310, 162
LIST_Y = 140
KOFI = "https://ko-fi.com/studio87"
ASSETS = Path(__file__).resolve().parents[1] / "assets"


def load_fonts():
    for f in ASSETS.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(f))


def human_size(n):
    return "%.0f MB" % (n / 1048576) if n >= 1048576 else "%.0f KB" % (n / 1024)


class Bridge(QObject):
    progress = Signal(int, int)
    checked = Signal(object, str)
    shot = Signal(str, object)
    refreshed = Signal(str, object)
    inst_progress = Signal(str, str, int, int)
    inst_done = Signal(str, bool, str, object)
    queue_done = Signal()
    signin = Signal(str, str, str)


class Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.fn()
        except Exception as e:      # never let a worker die silently
            print("worker error:", e, file=sys.stderr)


def paint_no_shot(p, tr, kind, T, confirmed):
    """Tinted card with the product's kind icon; says 'no screenshot yet' once we know there is none."""
    inner = tr.adjusted(1, 1, -1, -1)
    tint = QColor(T.c("accent"))
    tint.setAlpha(34)
    p.setBrush(tint)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(inner, 4, 4)
    p.setPen(QPen(T.c("dim"), 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = inner.center().x(), inner.center().y() - 8
    if kind == "controller":
        for i in range(4):
            p.drawEllipse(QRect(cx - 38 + i * 20, cy - 8, 14, 14))
        p.drawRect(QRect(cx - 38, cy + 12, 74, 6))
    elif kind == "logue":
        for i in range(7):
            p.drawRect(QRect(cx - 35 + i * 10, cy - 10, 10, 30))
    elif kind == "app":
        p.drawRoundedRect(QRect(cx - 32, cy - 14, 64, 40), 4, 4)
        p.drawLine(cx - 32, cy - 4, cx + 32, cy - 4)
    else:
        p.drawRoundedRect(QRect(cx - 34, cy - 14, 68, 40), 4, 4)
        for i in range(3):
            p.drawEllipse(QRect(cx - 24 + i * 20, cy - 2, 12, 12))
    if confirmed:
        p.setPen(T.c("dim"))
        p.setFont(font(px=12, weight=QFont.Weight.Medium, spacing=1))
        p.drawText(QRect(inner.x(), inner.bottom() - 22, inner.width(), 18), Qt.AlignmentFlag.AlignCenter, "no screenshot yet")



def wrap_lines(text, fm, width, max_lines=2):
    """Greedy word wrap; the last allowed line ends in '...' when the text is longer."""
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if fm.horizontalAdvance(t) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        rest = " ".join(lines[max_lines - 1:])
        lines = lines[:max_lines - 1] + [fm.elidedText(rest, Qt.TextElideMode.ElideRight, width)]
    return [fm.elidedText(l, Qt.TextElideMode.ElideRight, width) for l in lines]


class RowWidget(QWidget):
    H = ROW_H

    def __init__(self, ui, parent):
        super().__init__(parent)
        self.ui = ui
        self.row = None
        self.busy = None            # (text, fraction or None)
        self.message = ""
        self.W = 900
        self.resize(self.W, self.H)
        self.check = Check(self)
        self.check.move(8, self.H // 2 - 10)
        self.b_main = Btn("Update", self, "primary", 16)
        self.b_log = Btn("Changelog", self, "normal", 16)
        self.b_git = Btn("GitHub", self, "normal", 16)
        self.check.toggled.connect(lambda on: ui.toggle_select(self.row, on))
        self.b_main.clicked.connect(lambda: ui.update_rows([self.row]))
        self.b_log.clicked.connect(lambda: ui.show_changelog(self.row))
        self.b_git.clicked.connect(lambda: ui.open_url(self.row.product.github_url))
        ui.bubbles.attach(self.check, "Tick to include this product in the batch button above the list.")
        ui.bubbles.attach(self.b_log, "Read the release notes for every version newer than the one you have.")
        ui.bubbles.attach(self.b_git, "Open the project page in your browser.")
        ui.bubbles.attach(self.b_main, lambda: self.main_tip())
        self.set_width(self.W)

    def set_width(self, w):
        self.W = w
        self.resize(w, self.H)
        for b, y in ((self.b_main, 14), (self.b_log, 49), (self.b_git, 84)):
            b.setGeometry(w - 124, y, 112, 28)

    def main_tip(self):
        r = self.row
        if r is None:
            return ""
        if r.status == MD.CURRENT:
            return "You have the newest version."
        if not r.can_install:
            return "No download for this one yet, or it is not set up for updates."
        return ("Download, verify the SHA256 checksums, then install %s. Installers are not code-signed: Windows or macOS may show a warning. "
                "Nothing is installed until you click." % (r.latest.version or r.latest.tag))

    def bind(self, row):
        self.row = row
        self.busy = None
        self.message = ""
        self.refresh_buttons()
        self.check.blockSignals(True)
        self.check.setChecked(row.product.repo in self.ui.selected)
        self.check.blockSignals(False)
        self.update()

    def refresh_buttons(self):
        r = self.row
        if r is None:
            return
        busy = self.busy is not None
        if r.status == MD.CURRENT:
            label = "Up to date"
        elif r.status in (MD.UPDATE, MD.NOT_INSTALLED, MD.UNKNOWN_INSTALL):
            label = r.action_label
        else:
            label = "Unavailable"
        self.b_main.setText(label)
        self.b_main.kind = "primary" if r.status in (MD.UPDATE, MD.NOT_INSTALLED) else "normal"
        self.b_main.setEnabled(r.can_install and r.status != MD.CURRENT and not busy and not self.ui.installing)
        self.b_main.setVisible(r.status != MD.GITHUB_ONLY)
        self.b_log.setVisible(r.status != MD.GITHUB_ONLY)
        self.b_log.setEnabled(bool(r.releases))
        self.check.setVisible(r.status != MD.GITHUB_ONLY)
        self.check.setEnabled(r.can_install and r.status != MD.CURRENT and not busy)
        self.b_main.update()

    def set_busy(self, text, frac=None):
        self.busy = (text, frac)
        self.refresh_buttons()
        self.update()

    def paintEvent(self, e):
        r = self.row
        if r is None:
            return
        T = THEME
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setBrush(T.c("panel"))
        p.setPen(QPen(T.c("line"), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.W - 1, self.H - 1), 4, 4)
        tr = QRect(36, 4, THUMB_W, THUMB_H)
        p.setBrush(T.c("display"))
        p.setPen(QPen(T.c("line"), 1))
        p.drawRoundedRect(tr, 2, 2)
        pm = self.ui.thumb(r.product.repo)
        if pm is not None:
            inner = tr.adjusted(1, 1, -1, -1)
            p.save()
            p.setClipRect(inner)
            sc = min(inner.width() / pm.width(), inner.height() / pm.height())
            tw, th = round(pm.width() * sc), round(pm.height() * sc)
            p.drawPixmap(QRect(inner.x() + (inner.width() - tw) // 2, inner.y() + (inner.height() - th) // 2, tw, th), pm)
            p.restore()
        else:
            paint_no_shot(p, tr, r.product.kind, T, r.product.repo in self.ui.noshot)
        x = 36 + THUMB_W + 10
        w = max(120, self.W - x - 132)
        p.setPen(T.c("title") if T.name != "purr" else T.c("text"))
        p.setFont(font(px=25, weight=QFont.Weight.Bold))
        p.drawText(x, 6, w, 28, Qt.AlignmentFlag.AlignVCenter, r.product.name)
        nw = QFontMetrics(p.font()).horizontalAdvance(r.product.name) + 10
        p.setFont(font(px=12, weight=QFont.Weight.DemiBold, spacing=1.6))
        p.setPen(T.c("info"))
        label = r.product.kind_label.upper()
        p.drawText(x + nw, 6, 220, 28, Qt.AlignmentFlag.AlignVCenter, label)
        if r.latest and r.latest.is_test_build:
            lw = QFontMetrics(p.font()).horizontalAdvance(label) + 14
            p.setPen(T.c("dim"))
            p.drawText(x + nw + lw, 6, 200, 28, Qt.AlignmentFlag.AlignVCenter, "TEST BUILD")
        p.setFont(font(MONO, 15, QFont.Weight.Normal))
        p.setPen(T.c("text"))
        if r.status == MD.GITHUB_ONLY:
            l2 = "Not checked for updates yet"
        else:
            l2 = "Installed %s    >    Latest %s" % (MD.installed_text(r), r.latest.version if r.latest else "none")
        p.drawText(x, 36, w, 20, Qt.AlignmentFlag.AlignVCenter, l2)
        col = {MD.UPDATE: "accent", MD.CURRENT: "good", MD.ERROR: "bad", MD.UNKNOWN_INSTALL: "info"}.get(r.status, "dim")
        p.setFont(font(px=18, weight=QFont.Weight.DemiBold, spacing=0.3))
        if self.busy:
            text, frac = self.busy
            p.setPen(T.c("accent"))
            p.drawText(x, 60, 160, 22, Qt.AlignmentFlag.AlignVCenter, text)
            if frac is not None:
                bar = QRectF(x + 170, 65, min(300, w - 170), 11)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(T.c("display"))
                p.drawRoundedRect(bar, 3, 3)
                p.setBrush(T.c("info"))
                p.drawRoundedRect(QRectF(bar.x(), bar.y(), max(6, bar.width() * frac), bar.height()), 3, 3)
        else:
            p.setBrush(T.c(col))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(x, 66, 10, 10)
            p.setPen(T.c(col))
            msg = self.message or MD.status_line(r)
            p.drawText(x + 17, 60, w - 17, 22, Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(p.font()).elidedText(msg, Qt.TextElideMode.ElideRight, w - 17))
        p.setFont(font(px=17, weight=QFont.Weight.Medium))
        p.setPen(T.c("text"))
        cl = r.changelog_text if r.status != MD.GITHUB_ONLY else "Open the project page to see what it is and how to get it."
        for i, ln in enumerate(wrap_lines(cl, QFontMetrics(p.font()), w, 2)):
            p.drawText(x, 86 + i * 22, w, 22, Qt.AlignmentFlag.AlignVCenter, ln)
        p.setFont(font(px=14, weight=QFont.Weight.Medium))
        p.setPen(T.c("dim"))
        if r.latest:
            a = r.latest.zip_asset()
            bits = [r.latest.published[:10], human_size(a.size) if a else "no zip", MD.method_text(r, self.ui.svc.system)]
            if r.from_cache:
                bits.append("saved list")
            p.drawText(x, 136, w, 18, Qt.AlignmentFlag.AlignVCenter, "   ".join(b for b in bits if b))
        p.end()


class StudioRoot(QWidget):
    """The whole window content, laid out for the current design size W x H (default 1047 x 1150) and scaled by the window."""

    def __init__(self, svc, window=None):
        super().__init__()
        self.svc, self.win = svc, window
        THEME.set(svc.settings["theme"])
        self.W, self.H = DW, DH
        self.resize(DW, DH)
        self.rows, self.view_rows, self.tab = [], [], "updates"      # always opens on Updates
        self.selected, self.installing, self.checking = set(), False, False
        self.thumbs, self.status, self.notice = {}, "", ""
        self.noshot = set()
        self.catalog_line, self.catalog_stale = "", False
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(3)
        self.install_pool = QThreadPool()
        self.install_pool.setMaxThreadCount(1)
        self.br = Bridge()
        self.br.progress.connect(self.on_progress)
        self.br.checked.connect(self.on_checked)
        self.br.refreshed.connect(self.on_refreshed)
        self.br.shot.connect(self.on_shot)
        self.br.inst_progress.connect(self.on_inst_progress)
        self.br.inst_done.connect(self.on_inst_done)
        self.br.queue_done.connect(self.on_queue_done)
        self.br.signin.connect(self.on_signin)
        self.bubbles = BubbleManager(self, lambda: bool(self.svc.settings["bubbles"]))
        self.cancel_flag = False
        self.signin_cancel = False
        self.queue = []
        self.overlay = None
        self._build()
        self.apply_look()
        self.relayout(DW, DH)

    # ---- construction ---------------------------------------------------
    def _build(self):
        self.b_check = Btn("Check for updates", self, "primary", 18)
        self.b_set = Btn("Settings", self, "normal", 18)
        self.b_about = Btn("About", self, "normal", 18)
        self.tabs = {}
        for key, label in MD.TABS:
            b = Btn(label, self, "tab", 16)
            b.clicked.connect(lambda _, k=key: self.set_tab(k))
            self.tabs[key] = b
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search products")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.on_search)
        self.b_all = Btn("Update all", self, "primary", 16)
        self.b_sel = Btn("Update selected", self, "normal", 16)
        self.b_stop = Btn("Stop after this one", self, "normal", 15)
        self.b_stop.hide()
        self.b_browse = Btn("Browse all products", self, "primary", 19)
        self.b_browse.hide()
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # no scrollbars: wheel, drag or keys
        self.scroll.setWidgetResizable(False)
        self.inner = QWidget()
        self.scroll.setWidget(self.inner)
        self.allrows = []
        self.b_zoom_out = Btn("-", self, "normal", 16)
        self.b_zoom_in = Btn("+", self, "normal", 16)
        self.b_zoom_fit = Btn("Fit", self, "normal", 16)
        self.b_zoom_100 = Btn("1:1", self, "normal", 16)
        self.b_check.clicked.connect(self.start_check)
        self.b_set.clicked.connect(self.show_settings)
        self.b_about.clicked.connect(self.show_about)
        self.b_all.clicked.connect(lambda: self.update_rows(MD.all_targets(self.view_rows)))
        self.b_sel.clicked.connect(lambda: self.update_rows([r for r in self.rows if r.product.repo in self.selected and r.can_install]))
        self.b_stop.clicked.connect(self.stop_queue)
        self.b_browse.clicked.connect(lambda: self.set_tab("all"))
        self.b_zoom_out.clicked.connect(lambda: self.win and self.win.zoom(-0.1))
        self.b_zoom_in.clicked.connect(lambda: self.win and self.win.zoom(0.1))
        self.b_zoom_fit.clicked.connect(lambda: self.win and self.win.reset_100())
        self.b_zoom_100.clicked.connect(lambda: self.win and self.win.one_to_one())
        B = self.bubbles.attach
        B(self.b_check, "Ask GitHub about every product now. It only reads public release data; nothing is sent about you or this computer.")
        B(self.b_set, "Look, hover bubbles, install mode and the optional GitHub sign in.")
        B(self.b_about, "What this is, what it collects (nothing), and how to remove it.")
        B(self.search, "Type to filter the list by name, kind (for example controller) or status (for example update).")
        B(self.b_all, lambda: "Install every product shown that is not installed yet." if self.b_all.text().startswith("Install") else
          "Update every product that has a newer version. Products with an unknown installed version are left alone.")
        B(self.b_sel, "Update or install the products you ticked, one after another.")
        B(self.b_stop, "Finish the current product, then stop the rest.")
        B(self.b_zoom_out, "Smaller. Drag a corner to scale everything; drag a side to change only the width or the height.")
        B(self.b_zoom_in, "Bigger.")
        B(self.b_zoom_fit, "Back to the normal size for this screen. Double click on either wood side does the same.")
        B(self.b_zoom_100, "Show everything at its design size (1:1).")
        tips = {"updates": "Products that have a newer version than the one installed.", "all": "Every public Studio 87 product. Updates come first.",
                "fx": "VST3 effects, analysers, editors and tools.", "synth": "Synths and instruments.",
                "controller": "Plugins that control a hardware synth or effect unit.", "apps": "Standalone apps and logue units (minilogue xd, drumlogue).",
                "installed": "Products found on this computer.", "notinstalled": "Products not installed yet. Pick Install on a row."}
        for k, b in self.tabs.items():
            B(b, tips[k])

    def relayout(self, W, H):
        """Place everything for a W x H design size. Thumbnails keep their size; text re-wraps; the list gets more or fewer rows."""
        self.W, self.H = W, H
        self.resize(W, H)
        x0, rw = CHEEK + 10, W - 2 * CHEEK - 20
        right = W - CHEEK - 10
        self.b_about.setGeometry(right - 84, 13, 84, 34)
        self.b_set.setGeometry(right - 84 - 8 - 96, 13, 96, 34)
        self.b_check.setGeometry(right - 84 - 8 - 96 - 8 - 170, 13, 170, 34)
        x = x0
        widths = {"updates": 100, "all": 66, "fx": 118, "synth": 92, "controller": 112, "apps": 144}
        for key in ("updates", "all", "fx", "synth", "controller", "apps"):
            self.tabs[key].setGeometry(x, 64, widths[key], 30)
            x += widths[key] + 4
        self.search.setGeometry(x0, 100, 176, 30)
        sx = x0 + 176 + 8
        for key, wd in (("installed", 104), ("notinstalled", 124)):
            self.tabs[key].setGeometry(sx, 100, wd, 30)
            sx += wd + 4
        self.b_all.setGeometry(right - 140, 100, 140, 30)
        self.b_sel.setGeometry(right - 140 - 8 - 164, 100, 164, 30)
        self.b_stop.setGeometry(right - 140 - 8 - 164 - 8 - 160, 100, 160, 30)
        self.scroll.setGeometry(x0, LIST_Y, rw, max(100, H - 240))
        self.row_w = rw - 14
        for rwid in self.allrows:
            rwid.set_width(self.row_w)
            if rwid.row is not None:
                rwid.update()
        self.inner.resize(self.row_w, max(1, len(self.view_rows)) * (ROW_H + ROW_GAP))
        for i, rwid in enumerate(self.allrows):
            rwid.move(0, i * (ROW_H + ROW_GAP))
        self.b_browse.setGeometry(W // 2 - 110, LIST_Y + 130, 220, 38)
        fx = W - CHEEK - 14 - 4 * 56 - 3 * 6
        for i, b in enumerate((self.b_zoom_out, self.b_zoom_in, self.b_zoom_fit, self.b_zoom_100)):
            b.setGeometry(fx + i * 62, H - 36, 56, 28)
        if self.overlay is not None:
            self.overlay.relayout()
        self.update()

    def apply_look(self):
        THEME.set(self.svc.settings["theme"])
        T = THEME
        self.search.setFont(font("Barlow Condensed", 16, QFont.Weight.Medium))
        self.search.setStyleSheet("QLineEdit{background:%s;color:%s;border:1px solid %s;border-radius:3px;padding:2px 8px;}QLineEdit:focus{border:1px solid %s;}" % (
            T.s("display"), T.s("text"), T.s("line"), T.s("accent")))
        self.scroll.setStyleSheet("QScrollArea{background:transparent;}")
        self.inner.setStyleSheet("background:transparent;")
        self.update()
        for w in self.findChildren(QWidget):
            w.update()

    # ---- painting -------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        T = THEME
        W, H = self.W, self.H
        p.fillRect(self.rect(), T.c("bg"))
        p.fillRect(CHEEK, 0, W - 2 * CHEEK, 60, T.c("panel"))
        p.setPen(QPen(T.c("line"), 1))
        p.drawLine(CHEEK, 60, W - CHEEK, 60)
        paint_cat(p, QRect(CHEEK + 12, 9, 42, 42))
        p.setPen(T.c("text"))
        p.setFont(font(px=34, weight=QFont.Weight.Bold, italic=True))
        p.drawText(CHEEK + 64, 8, 260, 40, Qt.AlignmentFlag.AlignVCenter, "Gear Updater")
        p.setPen(T.c("dim"))
        p.setFont(font(MONO, 12, QFont.Weight.Normal, spacing=2.6))
        p.drawText(CHEEK + 64 + 214, 8, 200, 40, Qt.AlignmentFlag.AlignVCenter, "STUDIO 87")
        # pager row: status left, count right
        sy = H - 92
        p.setPen(T.c("dim"))
        p.setFont(font(px=16, weight=QFont.Weight.Medium))
        two = bool(self.catalog_line)
        sw = W // 2 + 40 - CHEEK
        p.drawText(CHEEK + 10, sy - (8 if two else 0), sw, 30, Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(p.font()).elidedText(self.status, Qt.TextElideMode.ElideRight, sw))
        if two:
            p.setFont(font(px=13, weight=QFont.Weight.Medium))
            p.setPen(T.c("accent") if self.catalog_stale else T.c("dim"))
            p.drawText(CHEEK + 10, sy + 14, sw, 18, Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(p.font()).elidedText(self.catalog_line, Qt.TextElideMode.ElideRight, sw))
        p.setPen(T.c("dim"))
        p.setFont(font(px=15, weight=QFont.Weight.Medium))
        right_txt = ("%d of %d shown" % (len(self.view_rows), len(self.rows))) if self.rows else ""
        p.drawText(W // 2 + 60, sy, W // 2 - 60 - CHEEK - 14, 30, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, right_txt)
        if self.notice:
            p.setPen(T.c("bad"))
            p.setFont(font(px=15, weight=QFont.Weight.DemiBold))
            p.drawText(W // 2 + 60, sy + 20, W // 2 - 60 - CHEEK - 14, 22, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       QFontMetrics(p.font()).elidedText(self.notice, Qt.TextElideMode.ElideLeft, W // 2 - 60 - CHEEK - 14))
        # footer
        p.fillRect(CHEEK, H - 44, W - 2 * CHEEK, 44, T.c("panel"))
        p.setPen(QPen(T.c("line"), 1))
        p.drawLine(CHEEK, H - 44, W - CHEEK, H - 44)
        p.setPen(T.c("dim"))
        p.setFont(font(px=16, weight=QFont.Weight.Medium))
        p.drawText(CHEEK + 26, H - 44, 420, 44, Qt.AlignmentFlag.AlignVCenter, "Studio 87  ·  Gear Updater v%s" % __version__)
        sz = self.win.logical_size() if self.win else (W, H)
        p.setFont(font(MONO, 13, QFont.Weight.Normal))
        p.drawText(W // 2 - 60, H - 44, 200, 44, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter,
                   "%d x %d  %d%%" % (sz[0], sz[1], sz[2]))
        if not self.view_rows:
            p.setPen(T.c("dim"))
            p.setFont(font(px=24, weight=QFont.Weight.Medium))
            p.drawText(CHEEK, LIST_Y + 60, W - 2 * CHEEK, 60, Qt.AlignmentFlag.AlignCenter, self.empty_text())
        if not hasattr(self, "_wood") or self._wood[0] != H:
            self._wood = (H, wood_pixmap(CHEEK, H, True), wood_pixmap(CHEEK, H, False))
        p.drawPixmap(0, 0, self._wood[1])
        p.drawPixmap(W - CHEEK, 0, self._wood[2])
        p.end()

    def empty_text(self):
        if self.checking and not self.rows:
            return "Checking GitHub..."
        if not self.rows:
            return "Nothing to show yet. Click 'Check for updates'."
        if self.search.text().strip():
            return "Nothing matches your search."
        return {"updates": "Everything is up to date.", "installed": "Nothing is installed yet.",
                "notinstalled": "Everything is installed."}.get(self.tab, "Nothing here.")

    def mouseDoubleClickEvent(self, e):
        x = e.position().x()
        if (x < CHEEK or x > self.W - CHEEK) and self.win:
            self.win.reset_100()
        else:
            super().mouseDoubleClickEvent(e)

    # ---- list -----------------------------------------------------------
    def filtered(self):
        return MD.filter_rows(self.rows, self.tab, self.search.text())

    def set_tab(self, key):
        self.tab = key
        self.refresh_list()

    def on_search(self, _text):
        self.refresh_list()

    def all_row_widgets(self):
        return self.allrows

    def refresh_list(self):
        self.view_rows = self.filtered()
        chunk, pool = self.view_rows, self.allrows
        while len(pool) < len(chunk):
            pool.append(RowWidget(self, self.inner))
            pool[-1].set_width(getattr(self, "row_w", 900))
        for i, rw in enumerate(pool):
            if i < len(chunk):
                rw.move(0, i * (ROW_H + ROW_GAP))
                rw.bind(chunk[i])
                if chunk[i].product.repo in self.busy_text:
                    rw.set_busy(*self.busy_text[chunk[i].product.repo])
                rw.show()
            else:
                rw.row = None
                rw.hide()
        self.inner.resize(self.row_w if hasattr(self, "row_w") else 900, max(1, len(chunk)) * (ROW_H + ROW_GAP))
        self.scroll.setVisible(bool(chunk))
        self.b_browse.setVisible(not chunk and self.tab == "updates" and bool(self.rows) and not self.search.text().strip())
        for k, label in MD.TABS:
            n = len(MD.filter_rows(self.rows, k, ""))
            b = self.tabs[k]
            b.setText("%s (%d)" % (label, n) if self.rows else label)
            b.setChecked(k == self.tab)
        n_all = len(MD.all_targets(self.view_rows))
        self.b_all.setText(MD.all_label(self.view_rows))
        self.b_all.setEnabled(n_all > 0 and not self.installing)
        sel = [r for r in self.rows if r.product.repo in self.selected and r.can_install]
        self.b_sel.setText(MD.selected_label(sel))
        self.b_sel.setEnabled(bool(sel) and not self.installing)
        self.b_check.setEnabled(not self.checking and not self.installing)
        self.b_stop.setVisible(self.installing)
        self.update()
        self.load_visible_thumbs()

    busy_text = {}

    def toggle_select(self, row, on):
        if row is None:
            return
        (self.selected.add if on else self.selected.discard)(row.product.repo)
        self.refresh_list()

    # ---- thumbnails -----------------------------------------------------
    def thumb(self, repo):
        return self.thumbs.get(repo)

    def _make_thumb(self, data):
        img = QImage()
        if not data or not img.loadFromData(bytes(data)):
            return None
        return QPixmap.fromImage(img.scaled(QSize(THUMB_W * 2, THUMB_H * 2), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def load_visible_thumbs(self):
        for r in self.view_rows:
            repo = r.product.repo
            if repo not in self.thumbs and r.product.checks_releases:
                pm = self._make_thumb(self.svc.screenshot(r.product, use_network=False))
                if pm is not None:
                    self.thumbs[repo] = pm



    def on_shot(self, repo, data):
        pm = self._make_thumb(data) if data else None
        if pm is not None:
            self.thumbs[repo] = pm
            self.noshot.discard(repo)
        else:
            self.noshot.add(repo)
        for rw in self.all_row_widgets():
            if rw.row is not None and rw.row.product.repo == repo:
                rw.update()


    # ---- checking -------------------------------------------------------
    def start_open_check(self):
        """On open: show the saved list at once, then check GitHub (the only automatic check)."""
        self.rows = self.svc.cached_rows()
        self.refresh_list()
        self.start_check()

    def start_check(self):
        if self.checking or self.installing:
            return
        self.checking = True
        self.notice = ""
        self.status = "Checking GitHub..."
        self.b_check.setEnabled(False)
        self.update()
        svc, br = self.svc, self.br

        def work():
            rows, notice = svc.check(lambda i, n, row: br.progress.emit(i, n))
            br.checked.emit(rows, notice)
        self.pool.start(Job(work))

    def on_progress(self, i, n):
        self.status = "Checking GitHub... %d / %d" % (i, n)
        self.update()

    def on_checked(self, rows, notice):
        self.checking = False
        self.rows = rows
        # keep selection only for rows that still exist
        self.selected &= {r.product.repo for r in rows}
        n_upd = sum(1 for r in rows if r.status == MD.UPDATE)
        when = time.strftime("%H:%M", time.localtime(self.svc.last_checked)) if self.svc.last_checked else "never"
        if notice == "offline":
            self.notice = "Offline: showing the saved list"
            self.status = "Last checked %s. %d update%s in the saved list." % (when, n_upd, "" if n_upd == 1 else "s")
        else:
            self.notice = notice
            self.status = "Checked at %s: %d product%s, %d update%s." % (
                when, len(rows), "" if len(rows) == 1 else "s", n_upd, "" if n_upd == 1 else "s")
        self.catalog_line, self.catalog_stale = self.svc.catalog_text()
        self.refresh_list()
        if notice != "offline":
            todo = [r.product for r in rows if r.product.checks_releases and r.latest]
            svc, br = self.svc, self.br

            def shots():
                for p in todo:
                    data = svc.screenshot(p, use_network=True)
                    br.shot.emit(p.repo, data)
            self.pool.start(Job(shots))

    def refresh_one(self, row):
        """Ask the GitHub API about this one product now (uses 1 of the 60 hourly requests)."""
        if self.checking or self.installing:
            return
        self.close_overlay()
        self.status = "Asking GitHub about %s..." % row.product.name
        self.update()
        svc, br = self.svc, self.br

        def work():
            try:
                br.refreshed.emit(row.product.repo, svc.refresh_one(row.product))
            except Exception as e:
                br.refreshed.emit(row.product.repo, str(e) or "could not reach GitHub")
        self.pool.start(Job(work))

    def on_refreshed(self, repo, res):
        if isinstance(res, str) or res is None:
            self.status = "Could not refresh %s: %s" % (repo, res or "GitHub no longer lists it")
        else:
            self.rows = [res if r.product.repo == repo else r for r in self.rows]
            self.rows.sort(key=MD.sort_key)
            self.status = "Refreshed %s directly from GitHub." % res.product.name
        self.refresh_list()

    # ---- installing -----------------------------------------------------
    def update_rows(self, rows):
        rows = [r for r in rows if r is not None and r.can_install]
        if not rows or self.installing:
            return
        if len(rows) == 1:
            self.run_queue(rows)
        else:
            self.show_confirm(rows)

    def run_queue(self, rows):
        self.close_overlay()
        self.installing, self.cancel_flag = True, False
        self.queue = list(rows)
        self.busy_text = {r.product.repo: ("Waiting...", None) for r in rows}
        self.notice = ""
        self.refresh_list()
        svc, br = self.svc, self.br
        queue = list(rows)

        def work():
            inst = svc.installer()          # one installer for the whole batch, so staged .pkg files share ONE elevated helper
            for r in queue:
                if self.cancel_flag:
                    br.inst_done.emit(r.product.repo, False, "Skipped (stopped).", None)
                    continue
                last = [0.0]

                def prog(stage, d, t, repo=r.product.repo):
                    now = time.time()
                    if stage != "download" or now - last[0] > 0.1 or (t and d >= t):
                        last[0] = now
                        br.inst_progress.emit(repo, stage, d, t)
                try:
                    res = inst.install(r, ext_installed=svc.ext_installed(r.product), progress=prog,
                                       cancel=lambda: self.cancel_flag)
                    svc.refresh_local()
                    br.inst_done.emit(r.product.repo, True, res["message"], None if res.get("staged") else svc.installed_for(r.product))
                except InterruptedError:
                    br.inst_done.emit(r.product.repo, False, "Cancelled.", None)
                except Exception as e:
                    br.inst_done.emit(r.product.repo, False, "Refused: %s" % e, None)
            if inst.staged:
                msgs = inst.finish_batch()
                svc.refresh_local()
                for repo, (ok, msg) in msgs.items():
                    pr = next((p for p in svc.products if p.repo == repo), None)
                    br.inst_done.emit(repo, ok, msg, svc.installed_for(pr) if ok and pr else None)
            br.queue_done.emit()
        self.install_pool.start(Job(work))

    def stop_queue(self):
        self.cancel_flag = True
        self.b_stop.setEnabled(False)

    def _row_widget(self, repo):
        for rw in self.all_row_widgets():
            if rw.row is not None and rw.row.product.repo == repo:
                return rw
        return None

    def on_inst_progress(self, repo, stage, d, t):
        # stage text follows the wording of the action: Installing for new products, Updating for updates
        if stage == "download":
            text, frac = "Downloading", (d / t if t else None)
        elif stage == "verify":
            text, frac = "Verifying SHA256", None
        else:
            row = next((r for r in self.rows if r.product.repo == repo), None)
            text, frac = (MD.progress_word(row) if row is not None else "Installing"), None
        self.busy_text[repo] = (text, frac)
        rw = self._row_widget(repo)
        if rw:
            rw.set_busy(text, frac)

    def on_inst_done(self, repo, ok, message, info):
        self.busy_text.pop(repo, None)
        row = next((r for r in self.rows if r.product.repo == repo), None)
        if row is not None:
            if ok and info is not None:
                row.installed = info
                row.status = MD.compute_status(row.product, row.releases, info)
            row.__dict__["flash"] = message
        rw = self._row_widget(repo)
        if rw:
            rw.busy = None
            rw.message = message
            rw.refresh_buttons()
            rw.update()
        self.selected.discard(repo)
        self.status = message

    def on_queue_done(self):
        self.installing = False
        self.b_stop.setEnabled(True)
        self.rows.sort(key=MD.sort_key)
        keep = {rw.row.product.repo: rw.message for rw in self.all_row_widgets() if rw.row is not None}
        self.refresh_list()
        for rw in self.all_row_widgets():
            if rw.row is not None and keep.get(rw.row.product.repo):
                rw.message = keep[rw.row.product.repo]
                rw.update()

    # ---- overlays -------------------------------------------------------
    def close_overlay(self):
        if self.overlay is not None:
            self.overlay.hide()
            self.overlay.deleteLater()
            self.overlay = None

    def _overlay(self, title, w=720, h=470):
        self.close_overlay()
        ov = Overlay(self, title, w, h)
        self.overlay = ov
        ov.show()
        ov.raise_()
        return ov

    def open_url(self, url):
        QDesktopServices.openUrl(QUrl(url))

    def show_changelog(self, row):
        if row is None or not row.releases:
            return
        ov = self._overlay("%s: changelog" % row.product.name)
        iv = MD.installed_text(row)
        ov.sub = "Installed: %s     Latest: %s" % (iv, row.latest.version or row.latest.tag)
        tb = QTextBrowser(ov.holder)
        tb.setGeometry(24, 92, ov.w - 48, ov.h - 92 - 64)
        tb.setOpenLinks(False)
        tb.setOpenExternalLinks(False)
        tb.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tb.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tb.setFrameShape(QTextBrowser.Shape.NoFrame)
        tb.setStyleSheet("QTextBrowser{background:%s;color:%s;border:1px solid %s;padding:6px;}" % (
            THEME.s("display"), THEME.s("text"), THEME.s("line")))
        tb.setFont(font("Barlow Condensed", 17, QFont.Weight.Medium))
        notes = row.notes() or row.releases[:1]
        md = []
        for r in notes:
            md.append("## %s  (%s)\n\n%s\n" % (r.name or r.tag, r.published[:10], r.body or "No release notes."))
        tb.setMarkdown("\n---\n".join(md))
        tb.show()
        ov.add_button("Page up", 24, ov.h - 46, 100, lambda: tb.verticalScrollBar().setValue(tb.verticalScrollBar().value() - tb.viewport().height() + 20))
        ov.add_button("Page down", 132, ov.h - 46, 100, lambda: tb.verticalScrollBar().setValue(tb.verticalScrollBar().value() + tb.viewport().height() - 20))
        rb = ov.add_button("Refresh now", 240, ov.h - 46, 120, lambda: self.refresh_one(row))
        self.bubbles.attach(rb, "Ask GitHub directly about this product, for the newest answer right now. Uses 1 of the 60 free requests per hour.")
        ov.add_button("Open on GitHub", ov.w - 24 - 100 - 8 - 140, ov.h - 46, 140, lambda: self.open_url(row.latest.html_url or row.product.github_url))
        ov.add_button("Close", ov.w - 24 - 100, ov.h - 46, 100, self.close_overlay, "primary")

    def show_confirm(self, rows):
        ov = self._overlay(MD.confirm_title(rows), 640, 420)
        ov.sub = "Each one is downloaded, its SHA256 checked, then %s. A mismatch stops that product." % ("installed" if not MD.split_actions(rows)[0] else "installed or updated")
        shown = ["%s %s" % (r.product.name, r.latest.version or r.latest.tag) for r in rows[:12]]
        names = ", ".join(shown) + (" and %d more" % (len(rows) - 12) if len(rows) > 12 else "")
        ov.lines = [names, "", "These installers are not code-signed (no paid certificate). Windows or macOS may show an 'unknown publisher' warning; "
                    "the code is open on GitHub and the checksum is verified here. Your presets are never touched."]
        ov.add_button("Cancel", ov.w - 24 - 100 - 8 - 100, ov.h - 46, 100, self.close_overlay)
        ov.add_button(MD.confirm_button(rows), ov.w - 24 - 100, ov.h - 46, 100, lambda: self.run_queue(rows), "primary")

    def show_first_run(self):
        """One time only: say how installing works on this system (admin once, or none)."""
        s = self.svc.settings
        if s["mode_seen"] or self.overlay is not None:
            return
        s.set("mode_seen", True)
        ov = self._overlay("Welcome to Studio 87 Gear Updater", 640, 330)
        ov.sub = "Install mode: %s" % MODE.MODE_LABEL[self.svc.mode]
        ov.lines = [MODE.EXPLAIN[self.svc.system], "", "Change this any time in Settings. Nothing is installed without your click, every download is checked "
                    "against its SHA256, and the installers are not code-signed."]
        ov.add_button("Open Settings", ov.w - 24 - 100 - 8 - 130, ov.h - 46, 130, self.show_settings)
        ov.add_button("Got it", ov.w - 24 - 100, ov.h - 46, 100, self.close_overlay, "primary")

    def show_settings(self):
        ov = self._overlay("Settings", 700, 580)
        s = self.svc.settings
        ov.sub = "Saved on this computer only."
        y = 100
        ov.label("Look", 28, y + 4)
        for i, (k, v) in enumerate(LOOKS.items()):
            b = ov.add_button(v["label"], 160 + i * 150, y, 140, lambda _=None, k=k: self.set_look(k), "tab")
            b.setChecked(s["theme"] == k)
            ov.look_buttons = getattr(ov, "look_buttons", {})
            ov.look_buttons[k] = b
        y += 56
        ov.label("Hover bubbles", 28, y + 4)
        bb = ov.add_button("On" if s["bubbles"] else "Off", 160, y, 80, lambda: None, "tab")
        bb.setChecked(bool(s["bubbles"]))

        def tog():
            s.set("bubbles", not s["bubbles"])
            bb.setText("On" if s["bubbles"] else "Off")
            bb.setChecked(bool(s["bubbles"]))
        bb.clicked.disconnect()
        bb.clicked.connect(tog)
        y += 56
        ov.label("GitHub account", 28, y + 4)
        au = self.svc.auth
        if not au.available:
            ov.add_button("No keychain found: signing in is off", 160, y, 300, lambda: None, "tab")
        else:
            sb = ov.add_button("Sign out" if au.signed_in else "Sign in with GitHub (optional)", 160, y, 300, lambda: None, "tab")
            sb.setChecked(au.signed_in)
            sb.clicked.disconnect()
            sb.clicked.connect(self.sign_out if au.signed_in else self.start_signin)
            ov.note_extra = "Optional. Raises GitHub's hourly limit from 60 to 5000 requests. No permissions are requested; the token stays in your system keychain."
        y += 56
        ov.label("Install mode", 28, y + 4)
        if self.svc.system == "linux":
            ov.add_button("No admin needed on Linux", 160, y, 280, lambda: None, "tab").setChecked(True)
        else:
            mb = {}

            def pick_mode(k):
                s.set("install_mode", k)
                for kk, bt in mb.items():
                    bt.setChecked(kk == k)
                if k == "all-users" and self.svc.system == "windows":
                    self.notice = "Restart the updater: it will ask for administrator rights once."
                self.update()
            for i, k in enumerate(MODE.MODES):
                mb[k] = ov.add_button(MODE.MODE_LABEL[k], 160 + i * 230, y, 220, lambda _=None, k=k: pick_mode(k), "tab")
                mb[k].setChecked(self.svc.mode == k)
        explain = MODE.EXPLAIN[self.svc.system]
        if self.svc.system == "linux":
            y += 56
            ov.label("Linux plugins go to", 28, y + 4)
            opts = (("auto", "Automatic"), ("native", "VST3 folder"), ("flatpak", "Flatpak DAW"))
            btns = {}
            for i, (k, label) in enumerate(opts):
                b = ov.add_button(label, 200 + i * 140, y, 130, lambda _=None, k=k: pick(k), "tab")
                b.setChecked(s["linux_target"] == k)
                btns[k] = b

            def pick(k):
                s.set("linux_target", k)
                for kk, bt in btns.items():
                    bt.setChecked(kk == k)
            explain += (" Automatic: Flatpak extension if that product's extension is already installed, otherwise ~/.vst3. "
                        "Presets are never touched.")
        ov.note, ov.note_y = explain, y + 56
        ov.lines = []
        ov.add_button("Close", ov.w - 24 - 100, ov.h - 46, 100, self.close_overlay, "primary")

    def set_look(self, k):
        self.svc.settings.set("theme", k)
        self.apply_look()
        if self.overlay is not None and hasattr(self.overlay, "look_buttons"):
            for kk, b in self.overlay.look_buttons.items():
                b.setChecked(kk == k)

    def show_about(self):
        ov = self._overlay("About Studio 87 Gear Updater", 720, 470)
        ov.sub = "Version %s  ·  free and open source (AGPL-3.0-or-later)" % __version__
        d = str(self.svc.data_dir)
        ov.lines = [
            "Studio 87 Gear Updater lists every Studio 87 plugin and app and tells you which have a newer version on GitHub.",
            "It collects nothing: no telemetry, no account, no background checks, no timers. It only reads public GitHub release data when you open it or click Check for updates, "
            "and downloads a release zip only when you click Update. Everything is verified against SHA256SUMS first; a mismatch is refused.",
            "The installers are not code-signed: Windows may say 'unknown publisher', macOS may need Privacy and Security, Open Anyway.",
            "Your presets and data folders are never touched. This app keeps its settings and a small list of installed versions in: " + d,
            "Remove it like any app: Linux: flatpak uninstall --user io.github.speakingcolors.Studio87GearUpdater; Windows: Settings, Apps; macOS: the Uninstall app in Applications.",
        ]
        ov.add_button("Ko-fi (optional tip)", 24, ov.h - 46, 170, lambda: self.open_url(KOFI))
        ov.add_button("GitHub", 202, ov.h - 46, 100, lambda: self.open_url("https://github.com/SpeakingColors/gearupdater"))
        ov.add_button("Close", ov.w - 24 - 100, ov.h - 46, 100, self.close_overlay, "primary")

    # ---- optional GitHub sign in (OAuth device flow) -------------------------
    def start_signin(self):
        au = self.svc.auth
        self.signin_cancel = False
        ov = self._overlay("Sign in with GitHub", 640, 340)
        ov.sub = "Optional. No permissions are requested."
        ov.lines = ["Asking GitHub for a code..."]
        ov.add_button("Cancel", ov.w - 24 - 100, ov.h - 46, 100, self.cancel_signin)
        br = self.br

        def work():
            try:
                dev = au.start()
                br.signin.emit("code", dev.get("user_code", ""), dev.get("verification_uri", "https://github.com/login/device"))
                au.poll(dev, lambda: self.signin_cancel)
                br.signin.emit("ok", "", "")
            except Exception as e:
                br.signin.emit("error", str(e)[:200], "")
        self.pool.start(Job(work))

    def cancel_signin(self):
        self.signin_cancel = True
        self.close_overlay()

    def on_signin(self, kind, a, b):
        if self.overlay is None or self.overlay.title != "Sign in with GitHub":
            if kind == "ok":
                self.status = "Signed in to GitHub."
                self.update()
            return
        ov = self.overlay
        if kind == "code":
            ov.lines = ["Open %s and type this code:" % b, "", a, "", "Waiting for you to approve it in the browser. You can cancel at any time."]
            ov.big_line = 2
            self.open_url(b)
        elif kind == "ok":
            self.close_overlay()
            self.status = "Signed in to GitHub. The hourly limit is now 5000 requests."
        else:
            ov.lines = ["Sign in did not finish: %s" % a]
        ov.update()

    def sign_out(self):
        self.svc.auth.sign_out()
        self.status = "Signed out of GitHub."
        self.show_settings()



class Overlay(QWidget):
    """Dimmed backdrop plus one centred card."""

    def __init__(self, root, title, w, h):
        super().__init__(root)
        self.root = root
        self.w, self.h = w, h
        self.big_line = None
        self.title, self.sub, self.lines, self.note = title, "", [], ""
        self.holder = QWidget(self)
        self.relayout(root)
        self.holder.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._labels = []

    def relayout(self, root=None):
        root = root or self.root
        self.setGeometry(CHEEK, 0, root.W - 2 * CHEEK, root.H)
        self.card = QRect((self.width() - self.w) // 2, (root.H - self.h) // 2, self.w, self.h)
        self.holder.setGeometry(self.card)

    def label(self, text, x, y):
        self._labels.append((text, x, y))
        self.update()

    def add_button(self, text, x, y, w, fn, kind="normal"):
        b = Btn(text, self.holder, kind, 15)
        b.setGeometry(x, y, w, 30)
        b.clicked.connect(fn)
        b.show()
        return b

    def showEvent(self, e):
        for ch in self.holder.findChildren(Btn) + self.holder.findChildren(QTextBrowser):
            ch.show()

    def mousePressEvent(self, e):
        e.accept()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        T = THEME
        p.fillRect(self.rect(), QColor(0, 0, 0, 170))
        c = self.card
        p.setBrush(T.c("panel"))
        p.setPen(QPen(T.c("line"), 1.5))
        p.drawRoundedRect(QRectF(c).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setPen(T.c("text"))
        p.setFont(font(px=26, weight=QFont.Weight.Bold))
        p.drawText(c.x() + 24, c.y() + 14, c.width() - 48, 36, Qt.AlignmentFlag.AlignVCenter, self.title)
        p.setPen(T.c("dim"))
        p.setFont(font(px=15, weight=QFont.Weight.Medium))
        p.drawText(c.x() + 24, c.y() + 50, c.width() - 48, 24, Qt.AlignmentFlag.AlignVCenter, self.sub)
        y = c.y() + 84
        p.setPen(T.c("text"))
        p.setFont(font(px=17, weight=QFont.Weight.Medium))
        for i, ln in enumerate(self.lines):
            if i == self.big_line:
                p.setFont(font(MONO, 34, QFont.Weight.Normal, spacing=4))
            else:
                p.setFont(font(px=17, weight=QFont.Weight.Medium))
            r = p.boundingRect(QRect(c.x() + 24, y, c.width() - 48, 400), Qt.TextFlag.TextWordWrap, ln or " ")
            p.drawText(QRect(c.x() + 24, y, c.width() - 48, r.height()), Qt.TextFlag.TextWordWrap, ln)
            y += r.height() + 8
        for text, x, yy in self._labels:
            p.drawText(c.x() + x, c.y() + yy, 200, 24, Qt.AlignmentFlag.AlignVCenter, text)
        extra = getattr(self, "note_extra", "")
        if extra:
            p.setPen(T.c("dim"))
            p.setFont(font(px=15, weight=QFont.Weight.Medium))
            p.drawText(QRect(c.x() + 28, c.y() + getattr(self, "note_y", 330) + 70, c.width() - 56, 60), Qt.TextFlag.TextWordWrap, extra)
        if self.note:
            p.setPen(T.c("dim"))
            r = QRect(c.x() + 28, c.y() + getattr(self, "note_y", 330), c.width() - 56, 90)
            p.drawText(r, Qt.TextFlag.TextWordWrap, self.note)
        p.end()


class FitView(QGraphicsView):
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class MainWindow(QMainWindow):
    """Design size LW x LH (default 1047 x 1150, 960..1500 by 760..1500) shown at scale s. Dragging a corner scales
    everything (same shape); dragging a side changes only the width or only the height and the layout adapts."""

    def __init__(self, svc, screen_size=None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        icon = ASSETS / "icon.png"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.scene = QGraphicsScene(0, 0, DW, DH)
        self.root = StudioRoot(svc, self)
        self.proxy = self.scene.addWidget(self.root)
        self.view = FitView(self.scene, self)
        self.view.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.TextAntialiasing)
        self.view.setBackgroundBrush(THEME.c("bg"))
        self.setCentralWidget(self.view)
        self._fixing = False
        self.LW, self.LH = DW, DH
        self.s_fit = fit_scale(screen_size or screen_available())
        self.s = self.s_fit
        self.setMinimumSize(1, 1)
        self.apply(DW, DH, self.s_fit)

    def logical_size(self):
        return (self.LW, self.LH, round(self.s * 100))

    def apply(self, lw, lh, s):
        """Set design size and scale; the window becomes exactly lw*s by lh*s."""
        self.LW, self.LH = max(MINW, min(MAXW, round(lw))), max(MINH, min(MAXH, round(lh)))
        self.s = max(S_MIN, min(S_MAX, s))
        self.scene.setSceneRect(0, 0, self.LW, self.LH)
        self.root.relayout(self.LW, self.LH)
        self._fixing = True
        self.resize(round(self.LW * self.s), round(self.LH * self.s))
        self._fixing = False
        self._last = self.size()
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.root.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fixing or not hasattr(self, "_last"):
            return
        w, h = self.width(), self.height()
        ow, oh = self._last.width(), self._last.height()
        lw, lh, s = self.LW, self.LH, self.s
        if w != ow and h != oh:                      # corner: same shape, everything scales
            fw, fh = w / ow, h / oh
            s = s * (fw if abs(fw - 1) >= abs(fh - 1) else fh)
        elif w != ow:                                # side: only the width changes
            lw = w / s
        elif h != oh:                                # top or bottom: only the height changes
            lh = h / s
        self.apply(lw, lh, s)

    def reset_100(self):
        """Normal size for this screen (also: double click on a wood side)."""
        self.apply(DW, DH, self.s_fit)

    def one_to_one(self):
        self.apply(DW, DH, 1.0)

    def zoom(self, step):
        self.apply(self.LW, self.LH, self.s + step)


def screen_available():
    scr = QApplication.primaryScreen()
    if scr is None:
        return (DW, DH)
    g = scr.availableGeometry()
    return (g.width(), g.height())


def fit_scale(avail):
    """Scale so the default window fits the screen (room for the title bar and frame); never larger than 1."""
    return max(S_MIN, min(1.0, (avail[0] - 24) / DW, (avail[1] - 70) / DH))


def run(argv=None, service=None):
    argv = list(argv or [])
    app = QApplication.instance() or QApplication([sys.argv[0]] + argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Studio 87")
    load_fonts()
    svc = service or Service()
    win = MainWindow(svc)
    win.show()
    QTimer.singleShot(0, win.root.start_open_check)
    QTimer.singleShot(400, win.root.show_first_run)
    return app.exec()
