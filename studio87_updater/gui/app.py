"""The Qt window. Everything is drawn in a 1000 x 640 design space and scaled uniformly, aspect locked."""
import os
import sys
import time
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QFontMetrics, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QApplication, QGraphicsScene, QGraphicsView, QMainWindow, QTextBrowser, QWidget)

from .. import APP_NAME, __version__
from .. import model as MD
from ..service import THEMES, Service
from .theme import LOOKS, THEME
from .widgets import MONO, BubbleManager, Btn, Check, font, paint_cat, wood_pixmap

DW, DH = 1000, 640
CHEEK = 34
PAGE = 5
ROW_H = 88
LIST_Y = 104
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
    inst_progress = Signal(str, str, int, int)
    inst_done = Signal(str, bool, str, object)
    queue_done = Signal()


class Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.fn()
        except Exception as e:      # never let a worker die silently
            print("worker error:", e, file=sys.stderr)


class RowWidget(QWidget):
    W, H = 912, 84

    def __init__(self, ui, parent):
        super().__init__(parent)
        self.ui = ui
        self.row = None
        self.busy = None            # (text, fraction or None)
        self.message = ""
        self.resize(self.W, self.H)
        self.check = Check(self)
        self.check.move(8, 32)
        self.b_main = Btn("Update", self, "primary", 15)
        self.b_log = Btn("Changelog", self, "normal", 14)
        self.b_git = Btn("GitHub", self, "normal", 14)
        for b, y in ((self.b_main, 5), (self.b_log, 31), (self.b_git, 57)):
            b.setGeometry(self.W - 118, y, 110, 22)
        self.check.toggled.connect(lambda on: ui.toggle_select(self.row, on))
        self.b_main.clicked.connect(lambda: ui.update_rows([self.row]))
        self.b_log.clicked.connect(lambda: ui.show_changelog(self.row))
        self.b_git.clicked.connect(lambda: ui.open_url(self.row.product.github_url))
        ui.bubbles.attach(self.check, "Tick to include this product in 'Update selected'.")
        ui.bubbles.attach(self.b_log, "Read the release notes for every version newer than the one you have.")
        ui.bubbles.attach(self.b_git, "Open the project page in your browser.")
        ui.bubbles.attach(self.b_main, lambda: self.main_tip())

    def main_tip(self):
        r = self.row
        if r is None:
            return ""
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
        busy = self.busy is not None
        self.b_main.setText(r.action_label if r.status in (MD.UPDATE, MD.NOT_INSTALLED, MD.UNKNOWN_INSTALL) else "Reinstall")
        self.b_main.kind = "primary" if r.status == MD.UPDATE else "normal"
        self.b_main.setEnabled(r.can_install and not busy and not self.ui.installing)
        self.b_main.setVisible(r.status != MD.GITHUB_ONLY)
        self.b_log.setVisible(r.status != MD.GITHUB_ONLY)
        self.b_log.setEnabled(bool(r.releases))
        self.check.setVisible(r.status != MD.GITHUB_ONLY)
        self.check.setEnabled(r.can_install and not busy)
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
        p.drawRoundedRect(QRectF(0.5, 0.5, self.W - 1, self.H - 1), 6, 6)
        # screenshot (visual cue) with the cat icon on top
        tr = QRect(34, 4, 156, 76)
        p.setBrush(T.c("display"))
        p.setPen(QPen(T.c("line"), 1))
        p.drawRoundedRect(tr, 4, 4)
        pm = self.ui.thumb(r.product.repo)
        if pm is not None:
            p.save()
            path_rect = tr.adjusted(1, 1, -1, -1)
            p.setClipRect(path_rect)
            sc = min(path_rect.width() / pm.width(), path_rect.height() / pm.height())
            tw, th = round(pm.width() * sc), round(pm.height() * sc)
            p.drawPixmap(QRect(path_rect.x() + (path_rect.width() - tw) // 2, path_rect.y() + (path_rect.height() - th) // 2, tw, th), pm)
            p.restore()
        else:
            p.setPen(T.c("dim"))
            p.setFont(font(px=13, weight=QFont.Weight.Medium, spacing=1))
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, "NO SCREENSHOT")
        paint_cat(p, QRect(tr.x() + 4, tr.y() + 4, 22, 22))
        # text block, at most 5 lines
        x, w = 204, 576
        p.setPen(T.c("title") if T.name != "purr" else T.c("text"))
        p.setFont(font(px=20, weight=QFont.Weight.Bold))
        p.drawText(x, 2, w, 22, Qt.AlignmentFlag.AlignVCenter, r.product.name)
        nw = QFontMetrics(p.font()).horizontalAdvance(r.product.name) + 10
        p.setFont(font(px=12, weight=QFont.Weight.DemiBold, spacing=1.2))
        p.setPen(T.c("info"))
        label = r.product.kind_label.upper()
        p.drawText(x + nw, 2, 200, 22, Qt.AlignmentFlag.AlignVCenter, label)
        if r.latest and r.latest.is_test_build:
            lw = QFontMetrics(p.font()).horizontalAdvance(label) + 14
            p.setPen(T.c("dim"))
            p.drawText(x + nw + lw, 2, 200, 22, Qt.AlignmentFlag.AlignVCenter, "TEST BUILD")
        # line 2
        mono = font(MONO, 12, QFont.Weight.Normal)
        p.setFont(mono)
        p.setPen(T.c("text"))
        if r.status == MD.GITHUB_ONLY:
            l2 = "Not checked for updates yet"
        else:
            l2 = "Installed %s    >    Latest %s" % (MD.installed_text(r), r.latest.version if r.latest else "none")
        p.drawText(x, 24, w, 15, Qt.AlignmentFlag.AlignVCenter, l2)
        # line 3: status or progress
        col = {MD.UPDATE: "accent", MD.CURRENT: "good", MD.ERROR: "bad", MD.UNKNOWN_INSTALL: "info"}.get(r.status, "dim")
        p.setFont(font(px=15, weight=QFont.Weight.DemiBold, spacing=0.3))
        if self.busy:
            text, frac = self.busy
            p.setPen(T.c("accent"))
            p.drawText(x, 39, 125, 16, Qt.AlignmentFlag.AlignVCenter, text)
            if frac is not None:
                bar = QRectF(x + 130, 43, 300, 8)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(T.c("display"))
                p.drawRoundedRect(bar, 4, 4)
                p.setBrush(T.c("info"))
                p.drawRoundedRect(QRectF(bar.x(), bar.y(), max(6, bar.width() * frac), bar.height()), 4, 4)
        else:
            p.setBrush(T.c(col))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(x, 43, 8, 8)
            p.setPen(T.c(col))
            msg = self.message or MD.status_line(r)
            p.drawText(x + 14, 39, w - 14, 16, Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(p.font()).elidedText(msg, Qt.TextElideMode.ElideRight, w - 14))
        # line 4: short changelog line
        p.setFont(font(px=14, weight=QFont.Weight.Medium))
        p.setPen(T.c("text"))
        cl = r.changelog_line if r.status != MD.GITHUB_ONLY else "Open the project page to see what it is and how to get it."
        p.drawText(x, 55, w, 15, Qt.AlignmentFlag.AlignVCenter, QFontMetrics(p.font()).elidedText(cl, Qt.TextElideMode.ElideRight, w))
        # line 5: details
        p.setFont(font(px=13, weight=QFont.Weight.Medium))
        p.setPen(T.c("dim"))
        if r.latest:
            a = r.latest.zip_asset()
            bits = [r.latest.published[:10], human_size(a.size) if a else "no zip", MD.method_text(r, self.ui.svc.system)]
            if r.from_cache:
                bits.append("saved list")
            p.drawText(x, 69, w, 13, Qt.AlignmentFlag.AlignVCenter, "   ".join(b for b in bits if b))
        p.end()


class StudioRoot(QWidget):
    """The whole window content, 1000 x 640 design pixels."""

    def __init__(self, svc, window=None):
        super().__init__()
        self.svc, self.win = svc, window
        THEME.set(svc.settings["theme"])
        self.resize(DW, DH)
        self.rows, self.view_rows, self.page, self.tab = [], [], 0, "updates"
        self.selected, self.installing, self.checking = set(), False, False
        self.thumbs, self.status, self.notice = {}, "", ""
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(3)
        self.install_pool = QThreadPool()
        self.install_pool.setMaxThreadCount(1)
        self.br = Bridge()
        self.br.progress.connect(self.on_progress)
        self.br.checked.connect(self.on_checked)
        self.br.shot.connect(self.on_shot)
        self.br.inst_progress.connect(self.on_inst_progress)
        self.br.inst_done.connect(self.on_inst_done)
        self.br.queue_done.connect(self.on_queue_done)
        self.bubbles = BubbleManager(self, lambda: bool(self.svc.settings["bubbles"]))
        self.cancel_flag = False
        self.queue = []
        self.overlay = None
        self._build()
        self.apply_look()

    # ---- construction ---------------------------------------------------
    def _build(self):
        cx = CHEEK + 10
        self.b_check = Btn("Check for updates", self, "primary", 16)
        self.b_check.setGeometry(DW - CHEEK - 10 - 176 - 86 - 86 - 12, 12, 176, 34)
        self.b_set = Btn("Settings", self, "normal", 16)
        self.b_set.setGeometry(DW - CHEEK - 10 - 86 - 86 - 6, 12, 80, 34)
        self.b_about = Btn("About", self, "normal", 16)
        self.b_about.setGeometry(DW - CHEEK - 10 - 80, 12, 80, 34)
        self.tabs = {}
        x = cx
        for key, label, wd in (("updates", "Updates", 110), ("installed", "Installed", 100), ("missing", "Not installed", 118), ("all", "All", 70)):
            b = Btn(label, self, "tab", 15)
            b.setGeometry(x, 64, wd, 30)
            b.clicked.connect(lambda _, k=key: self.set_tab(k))
            self.tabs[key] = b
            x += wd + 6
        self.b_all = Btn("Update all", self, "primary", 15)
        self.b_all.setGeometry(DW - cx - 118, 64, 118, 30)
        self.b_sel = Btn("Update selected", self, "normal", 15)
        self.b_sel.setGeometry(DW - cx - 118 - 144 - 8, 64, 144, 30)
        self.b_stop = Btn("Stop after this one", self, "normal", 14)
        self.b_stop.setGeometry(DW - cx - 118 - 144 - 8 - 150, 64, 142, 30)
        self.b_stop.hide()
        self.rowws = []
        for i in range(PAGE):
            rw = RowWidget(self, self)
            rw.move(cx, LIST_Y + i * ROW_H)
            self.rowws.append(rw)
        self.b_prev = Btn("<", self, "normal", 16)
        self.b_prev.setGeometry(DW // 2 - 90, 554, 40, 28)
        self.b_next = Btn(">", self, "normal", 16)
        self.b_next.setGeometry(DW // 2 + 50, 554, 40, 28)
        self.b_zoom_out = Btn("-", self, "normal", 16)
        self.b_zoom_100 = Btn("100%", self, "normal", 13)
        self.b_zoom_in = Btn("+", self, "normal", 16)
        zx = DW - cx - 3 * 40 - 8
        for b, dx in ((self.b_zoom_out, 0), (self.b_zoom_100, 44), (self.b_zoom_in, 88)):
            b.setGeometry(zx + dx - 70, 606, 40 if b is not self.b_zoom_100 else 56, 24)
        self.b_zoom_100.setGeometry(zx + 44 - 70, 606, 56, 24)
        self.b_zoom_in.setGeometry(zx + 106 - 70, 606, 40, 24)
        self.b_check.clicked.connect(self.start_check)
        self.b_set.clicked.connect(self.show_settings)
        self.b_about.clicked.connect(self.show_about)
        self.b_all.clicked.connect(lambda: self.update_rows([r for r in self.rows if r.status == MD.UPDATE]))
        self.b_sel.clicked.connect(lambda: self.update_rows([r for r in self.rows if r.product.repo in self.selected and r.can_install]))
        self.b_stop.clicked.connect(self.stop_queue)
        self.b_prev.clicked.connect(lambda: self.goto(self.page - 1))
        self.b_next.clicked.connect(lambda: self.goto(self.page + 1))
        self.b_zoom_out.clicked.connect(lambda: self.win and self.win.zoom(-0.1))
        self.b_zoom_in.clicked.connect(lambda: self.win and self.win.zoom(0.1))
        self.b_zoom_100.clicked.connect(lambda: self.win and self.win.reset_100())
        B = self.bubbles.attach
        B(self.b_check, "Ask GitHub about every product now. It only reads public release data; nothing is sent about you or this computer.")
        B(self.b_set, "Look, hover bubbles and where Linux plugins go.")
        B(self.b_about, "What this is, what it collects (nothing), and how to remove it.")
        B(self.b_all, "Update every product that has a newer version. Products with an unknown installed version are left alone.")
        B(self.b_sel, "Update the products you ticked, one after another.")
        B(self.b_stop, "Finish the current product, then stop the rest.")
        B(self.b_prev, "Previous page.")
        B(self.b_next, "Next page.")
        B(self.b_zoom_out, "Make the window smaller. You can also drag any edge or corner; the shape stays the same.")
        B(self.b_zoom_in, "Make the window larger.")
        B(self.b_zoom_100, "Back to the normal size. Double click on either wood side does the same.")
        for k, b in self.tabs.items():
            B(b, {"updates": "Products that have a newer version than the one installed.",
                  "installed": "Everything found on this computer.",
                  "missing": "Products that are not installed here yet.",
                  "all": "Every Studio 87 product, including ones that only link to GitHub."}[k])

    def apply_look(self):
        THEME.set(self.svc.settings["theme"])
        self.update()
        for w in self.findChildren(QWidget):
            w.update()

    # ---- painting -------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        T = THEME
        p.fillRect(self.rect(), T.c("bg"))
        # header
        p.fillRect(CHEEK, 0, DW - 2 * CHEEK, 58, T.c("panel"))
        p.setPen(QPen(T.c("line"), 1))
        p.drawLine(CHEEK, 58, DW - CHEEK, 58)
        paint_cat(p, QRect(CHEEK + 12, 8, 42, 42))
        p.setPen(T.c("text"))
        p.setFont(font(px=30, weight=QFont.Weight.Bold, italic=True))
        p.drawText(CHEEK + 64, 6, 260, 36, Qt.AlignmentFlag.AlignVCenter, "Updater")
        p.setPen(T.c("dim"))
        p.setFont(font(px=14, weight=QFont.Weight.Medium, spacing=3))
        p.drawText(CHEEK + 64 + 118, 6, 200, 36, Qt.AlignmentFlag.AlignVCenter, "STUDIO 87")
        # footer bar + strip
        p.setPen(T.c("dim"))
        p.setFont(font(px=14, weight=QFont.Weight.Medium))
        msg = self.status
        p.drawText(CHEEK + 10, 550, DW // 2 - 110 - CHEEK, 36, Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(p.font()).elidedText(msg, Qt.TextElideMode.ElideRight, DW // 2 - 120 - CHEEK))
        pages = max(1, -(-len(self.view_rows) // PAGE))
        p.setPen(T.c("text"))
        p.setFont(font(MONO, 13, QFont.Weight.Normal))
        p.drawText(DW // 2 - 50, 554, 100, 28, Qt.AlignmentFlag.AlignCenter, "%d / %d" % (self.page + 1, pages))
        if self.notice:
            p.setPen(T.c("bad"))
            p.setFont(font(px=14, weight=QFont.Weight.DemiBold))
            p.drawText(DW // 2 + 100, 550, DW // 2 - 100 - CHEEK - 10, 36, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       QFontMetrics(p.font()).elidedText(self.notice, Qt.TextElideMode.ElideLeft, DW // 2 - 110 - CHEEK - 10))
        p.fillRect(CHEEK, 598, DW - 2 * CHEEK, DH - 598, T.c("panel"))
        p.setPen(QPen(T.c("line"), 1))
        p.drawLine(CHEEK, 598, DW - CHEEK, 598)
        p.setPen(T.c("dim"))
        p.setFont(font(px=14, weight=QFont.Weight.Medium))
        p.drawText(CHEEK + 10, 598, 400, DH - 598, Qt.AlignmentFlag.AlignVCenter, "Studio 87  ·  Updater v%s" % __version__)
        sz = self.win.logical_size() if self.win else (DW, DH)
        p.setFont(font(MONO, 12, QFont.Weight.Normal))
        p.drawText(CHEEK + 10 + 400, 598, 200, DH - 598, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter, "%d x %d px" % sz)
        if not self.view_rows:
            p.setPen(T.c("dim"))
            p.setFont(font(px=20, weight=QFont.Weight.Medium))
            p.drawText(CHEEK, LIST_Y, DW - 2 * CHEEK, 200, Qt.AlignmentFlag.AlignCenter, self.empty_text())
        # wood cheeks
        if not hasattr(self, "_wl"):
            self._wl, self._wr = wood_pixmap(CHEEK, DH, True), wood_pixmap(CHEEK, DH, False)
        p.drawPixmap(0, 0, self._wl)
        p.drawPixmap(DW - CHEEK, 0, self._wr)
        p.end()

    def empty_text(self):
        if self.checking and not self.rows:
            return "Checking GitHub..."
        if self.tab == "updates" and self.rows:
            return "Everything you have is up to date."
        if not self.rows:
            return "Nothing to show yet. Click 'Check for updates'."
        return "Nothing here."

    def mouseDoubleClickEvent(self, e):
        x = e.position().x()
        if (x < CHEEK or x > DW - CHEEK) and self.win:
            self.win.reset_100()
        else:
            super().mouseDoubleClickEvent(e)

    # ---- list -----------------------------------------------------------
    def filtered(self):
        t = self.tab
        if t == "updates":
            return [r for r in self.rows if r.status == MD.UPDATE]
        if t == "installed":
            return [r for r in self.rows if r.installed and r.installed.state == "installed"]
        if t == "missing":
            return [r for r in self.rows if r.status == MD.NOT_INSTALLED]
        return list(self.rows)

    def set_tab(self, key):
        self.tab, self.page = key, 0
        self.refresh_list()

    def goto(self, page):
        pages = max(1, -(-len(self.view_rows) // PAGE))
        self.page = max(0, min(pages - 1, page))
        self.refresh_list()

    def refresh_list(self):
        self.view_rows = self.filtered()
        pages = max(1, -(-len(self.view_rows) // PAGE))
        self.page = min(self.page, pages - 1)
        chunk = self.view_rows[self.page * PAGE:(self.page + 1) * PAGE]
        for i, rw in enumerate(self.rowws):
            if i < len(chunk):
                rw.bind(chunk[i])
                if chunk[i].product.repo in self.busy_text:
                    rw.set_busy(*self.busy_text[chunk[i].product.repo])
                rw.show()
            else:
                rw.row = None
                rw.hide()
        n_upd = sum(1 for r in self.rows if r.status == MD.UPDATE)
        n_inst = sum(1 for r in self.rows if r.installed and r.installed.state == "installed")
        n_miss = sum(1 for r in self.rows if r.status == MD.NOT_INSTALLED)
        for k, label, n in (("updates", "Updates", n_upd), ("installed", "Installed", n_inst), ("missing", "Not installed", n_miss), ("all", "All", len(self.rows))):
            b = self.tabs[k]
            b.setText("%s (%d)" % (label, n) if self.rows else label)
            b.setChecked(k == self.tab)
        self.b_all.setText("Update all (%d)" % n_upd if n_upd else "Update all")
        self.b_all.setEnabled(n_upd > 0 and not self.installing)
        ns = len([r for r in self.rows if r.product.repo in self.selected and r.can_install])
        self.b_sel.setText("Update selected (%d)" % ns if ns else "Update selected")
        self.b_sel.setEnabled(ns > 0 and not self.installing)
        self.b_prev.setEnabled(self.page > 0)
        self.b_next.setEnabled(self.page < pages - 1)
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
        pm = QPixmap.fromImage(img.scaled(QSize(308, 148), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        return pm

    def load_visible_thumbs(self):
        start = self.page * PAGE
        for r in self.view_rows[start:start + PAGE]:
            repo = r.product.repo
            if repo not in self.thumbs and r.product.checks_releases:
                pm = self._make_thumb(self.svc.screenshot(r.product, use_network=False))
                if pm is not None:
                    self.thumbs[repo] = pm

    def on_shot(self, repo, data):
        pm = self._make_thumb(data)
        if pm is not None:
            self.thumbs[repo] = pm
            for rw in self.rowws:
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
        self.refresh_list()
        if notice != "offline":
            todo = [r.product for r in rows if r.product.checks_releases and r.latest]
            svc, br = self.svc, self.br

            def shots():
                for p in todo:
                    data = svc.screenshot(p, use_network=True)
                    if data:
                        br.shot.emit(p.repo, data)
            self.pool.start(Job(shots))

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
                    res = svc.installer().install(r, ext_installed=svc.ext_installed(r.product), progress=prog,
                                                  cancel=lambda: self.cancel_flag)
                    svc.refresh_local()
                    br.inst_done.emit(r.product.repo, True, res["message"], svc.installed_for(r.product))
                except InterruptedError:
                    br.inst_done.emit(r.product.repo, False, "Cancelled.", None)
                except Exception as e:
                    br.inst_done.emit(r.product.repo, False, "Refused: %s" % e, None)
            br.queue_done.emit()
        self.install_pool.start(Job(work))

    def stop_queue(self):
        self.cancel_flag = True
        self.b_stop.setEnabled(False)

    def _row_widget(self, repo):
        for rw in self.rowws:
            if rw.row is not None and rw.row.product.repo == repo:
                return rw
        return None

    def on_inst_progress(self, repo, stage, d, t):
        if stage == "download":
            text, frac = "Downloading", (d / t if t else None)
        elif stage == "verify":
            text, frac = "Verifying SHA256", None
        else:
            text, frac = "Installing", None
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
        keep = {rw.row.product.repo: rw.message for rw in self.rowws if rw.row is not None}
        self.refresh_list()
        for rw in self.rowws:
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
        ov.add_button("Open on GitHub", ov.w - 24 - 100 - 8 - 140, ov.h - 46, 140, lambda: self.open_url(row.latest.html_url or row.product.github_url))
        ov.add_button("Close", ov.w - 24 - 100, ov.h - 46, 100, self.close_overlay, "primary")

    def show_confirm(self, rows):
        ov = self._overlay("Update %d products?" % len(rows), 640, 420)
        ov.sub = "Each one is downloaded, its SHA256 checked, then installed. A mismatch stops that product."
        shown = ["%s %s" % (r.product.name, r.latest.version or r.latest.tag) for r in rows[:12]]
        names = ", ".join(shown) + (" and %d more" % (len(rows) - 12) if len(rows) > 12 else "")
        ov.lines = [names, "", "These installers are not code-signed (no paid certificate). Windows or macOS may show an 'unknown publisher' warning; "
                    "the code is open on GitHub and the checksum is verified here. Your presets are never touched."]
        ov.add_button("Cancel", ov.w - 24 - 100 - 8 - 100, ov.h - 46, 100, self.close_overlay)
        ov.add_button("Update %d" % len(rows), ov.w - 24 - 100, ov.h - 46, 100, lambda: self.run_queue(rows), "primary")

    def show_settings(self):
        ov = self._overlay("Settings", 640, 420)
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
            ov.note = ("Automatic: Flatpak extension if that product's extension is already installed, otherwise ~/.vst3. "
                       "Presets are never touched.")
        ov.lines = []
        ov.add_button("Close", ov.w - 24 - 100, ov.h - 46, 100, self.close_overlay, "primary")

    def set_look(self, k):
        self.svc.settings.set("theme", k)
        self.apply_look()
        if self.overlay is not None and hasattr(self.overlay, "look_buttons"):
            for kk, b in self.overlay.look_buttons.items():
                b.setChecked(kk == k)

    def show_about(self):
        ov = self._overlay("About Studio 87 Updater", 720, 470)
        ov.sub = "Version %s  ·  free and open source (AGPL-3.0-or-later)" % __version__
        d = str(self.svc.data_dir)
        ov.lines = [
            "Studio 87 Updater lists every Studio 87 plugin and app and tells you which have a newer version on GitHub.",
            "It collects nothing: no telemetry, no account, no background checks, no timers. It only reads public GitHub release data when you open it or click Check for updates, "
            "and downloads a release zip only when you click Update. Everything is verified against SHA256SUMS first; a mismatch is refused.",
            "The installers are not code-signed: Windows may say 'unknown publisher', macOS may need Privacy and Security, Open Anyway.",
            "Your presets and data folders are never touched. This app keeps its settings and a small list of installed versions in: " + d,
            "Remove it like any app: Linux: flatpak uninstall --user io.github.speakingcolors.Studio87Updater; Windows: Settings, Apps; macOS: the Uninstall app in Applications.",
        ]
        ov.add_button("Ko-fi (optional tip)", 24, ov.h - 46, 170, lambda: self.open_url(KOFI))
        ov.add_button("GitHub", 202, ov.h - 46, 100, lambda: self.open_url("https://github.com/SpeakingColors/gearupdater"))
        ov.add_button("Close", ov.w - 24 - 100, ov.h - 46, 100, self.close_overlay, "primary")


class Overlay(QWidget):
    """Dimmed backdrop plus one centred card."""

    def __init__(self, root, title, w, h):
        super().__init__(root)
        self.setGeometry(CHEEK, 0, DW - 2 * CHEEK, DH)
        self.w, self.h = w, h
        self.title, self.sub, self.lines, self.note = title, "", [], ""
        self.card = QRect((self.width() - w) // 2, (DH - h) // 2, w, h)
        self.holder = QWidget(self)
        self.holder.setGeometry(self.card)
        self.holder.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.root = root
        self._labels = []

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
        for ln in self.lines:
            r = p.boundingRect(QRect(c.x() + 24, y, c.width() - 48, 400), Qt.TextFlag.TextWordWrap, ln or " ")
            p.drawText(QRect(c.x() + 24, y, c.width() - 48, r.height()), Qt.TextFlag.TextWordWrap, ln)
            y += r.height() + 8
        for text, x, yy in self._labels:
            p.drawText(c.x() + x, c.y() + yy, 200, 24, Qt.AlignmentFlag.AlignVCenter, text)
        if self.note:
            p.setPen(T.c("dim"))
            r = QRect(c.x() + 28, c.y() + 250, c.width() - 56, 80)
            p.drawText(r, Qt.TextFlag.TextWordWrap, self.note)
        p.end()


class FitView(QGraphicsView):
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class MainWindow(QMainWindow):
    def __init__(self, svc):
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
        self.setMinimumSize(500, 320)
        self.resize(DW, DH)
        self._last = QSize(DW, DH)
        self._fixing = False

    def logical_size(self):
        return (self.width(), self.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._fixing:
            w, h = self.width(), self.height()
            lw, lh = self._last.width(), self._last.height()
            ratio = DW / DH
            if abs(w - lw) >= abs(h - lh):
                nh = round(w / ratio)
                nw = w
            else:
                nw = round(h * ratio)
                nh = h
            if (nw, nh) != (w, h):
                self._fixing = True
                self.resize(nw, nh)
                self._fixing = False
        self._last = self.size()
        self.root.b_zoom_100.setText("%d%%" % round(100 * self.width() / DW))
        self.root.update()

    def reset_100(self):
        self.resize(DW, DH)

    def zoom(self, step):
        pct = max(0.5, min(3.0, self.width() / DW + step))
        self.resize(round(DW * pct), round(DH * pct))


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
    return app.exec()
