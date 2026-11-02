"""Small custom-painted widgets. Everything is laid out in design pixels; the window scales them uniformly."""
import random

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget

from .theme import THEME, WOOD

CAT_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><path d="M8 6 L24 22 H40 L56 6 L60 36 Q60 58 32 60 Q4 58 4 36 Z" fill="#FF7BB1"/>'
           b'<path d="M12 14 L21 23 H14 Z M52 14 L43 23 H50 Z" fill="#FBBDD0"/><ellipse cx="22" cy="36" rx="4" ry="5" fill="#16171a"/>'
           b'<ellipse cx="42" cy="36" rx="4" ry="5" fill="#16171a"/><path d="M29 44 H35 L32 48 Z" fill="#16171a"/>'
           b'<path d="M32 48 Q28 53 24 50 M32 48 Q36 53 40 50" stroke="#16171a" stroke-width="2" fill="none"/>'
           b'<path d="M2 40 H14 M2 46 H14 M62 40 H50 M62 46 H50" stroke="#FBBDD0" stroke-width="1.6"/></svg>')
_cat = None


def paint_cat(p, rect):
    global _cat
    if _cat is None:
        _cat = QSvgRenderer(CAT_SVG)
    _cat.render(p, QRectF(rect))


def font(family="Barlow Condensed", px=14, weight=QFont.Weight.Medium, italic=False, spacing=0.0):
    f = QFont(family)
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setItalic(italic)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


MONO = "JetBrains Mono"


def wood_pixmap(w, h, left):
    """The PurrOne wood: dark #3d2210, warm #7b4a26 at 40%, mid #5a3419 at 75%, fixed-seed vertical grain, thin black edge."""
    pm = QPixmap(w, h)
    p = QPainter(pm)
    p.fillRect(0, 0, w, h, QColor(WOOD["dark"]))
    rnd = random.Random(87 if left else 88)
    x = 0
    while x < w:
        gw = 1 + rnd.randrange(3)
        warm = rnd.random() < 0.5
        col = QColor(WOOD["warm"] if warm else WOOD["mid"])
        col.setAlphaF(0.4 if warm else 0.75)
        p.fillRect(x, 0, min(gw, w - x), h, col)
        x += gw + rnd.randrange(3)
    p.setPen(QColor(0, 0, 0, 178))
    p.drawRect(0, 0, w - 1, h - 1)
    g = QLinearGradient(w - 8 if left else 0, 0, w if left else 8, 0)
    g.setColorAt(0, QColor(0, 0, 0, 0 if left else 153))
    g.setColorAt(1, QColor(0, 0, 0, 153 if left else 0))
    p.fillRect(w - 8 if left else 0, 0, 8, h, QBrush(g))
    p.end()
    return pm


class Btn(QAbstractButton):
    """Flat rounded button. kind: 'normal', 'primary', 'tab'."""

    def __init__(self, text, parent=None, kind="normal", px=15):
        super().__init__(parent)
        self.setText(text)
        self.kind = kind
        self.px = px
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(kind == "tab")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.tip = ""

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        T = THEME
        on = self.isEnabled()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.kind == "primary":
            bg = T.c("primary")
            fg = T.c("primary_text")
            if self._hover and on:
                bg = bg.lighter(115)
            border = bg
        elif self.kind == "tab" and self.isChecked():
            bg, fg, border = T.c("panel2"), T.c("accent"), T.c("accent")
        else:
            bg = T.c("btn_hot") if (self._hover and on) else T.c("btn")
            fg, border = T.c("text"), T.c("line")
        if not on:
            bg, fg, border = T.c("panel"), T.c("dim"), T.c("line")
        if self.isDown():
            bg = bg.darker(115)
        p.setBrush(bg)
        p.setPen(QPen(border, 1))
        p.drawRoundedRect(r, 4, 4)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(T.c("info"), 1, Qt.PenStyle.DotLine))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 3, 3)
        p.setPen(fg)
        p.setFont(font(px=self.px, weight=QFont.Weight.DemiBold, spacing=0.4))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class Check(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resize(20, 20)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(2.5, 2.5, 15, 15)
        p.setPen(QPen(THEME.c("line") if self.isEnabled() else THEME.c("panel2"), 1.5))
        p.setBrush(THEME.c("display"))
        p.drawRoundedRect(r, 3, 3)
        if self.isChecked():
            p.setPen(QPen(THEME.c("good"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawLine(6, 10, 9, 13)
            p.drawLine(9, 13, 14, 6)


class Bubble(QLabel):
    """Info bubble: appears after about one second of hovering, hides on leave or click."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setMaximumWidth(300)
        self.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(THEME.c("display"))
        p.setPen(QPen(THEME.c("info"), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
        p.end()
        super().paintEvent(e)


class BubbleManager:
    def __init__(self, root, enabled=lambda: True, delay=1000):
        self.root, self.enabled = root, enabled
        self.bubble = Bubble(root)
        self.timer = QTimer(root)
        self.timer.setSingleShot(True)
        self.timer.setInterval(delay)
        self.timer.timeout.connect(self._show)
        self.target = None

    def attach(self, widget, text):
        widget.setProperty("tip", text)
        widget.installEventFilter(self.filter)
        widget.setMouseTracking(True)

    @property
    def filter(self):
        if not hasattr(self, "_f"):
            mgr = self

            class F(QWidget):
                def eventFilter(self_, obj, ev):
                    t = ev.type()
                    if t == QEvent.Type.Enter:
                        mgr.target = obj
                        mgr.timer.start()
                    elif t in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Hide):
                        mgr.timer.stop()
                        mgr.bubble.hide()
                        mgr.target = None
                    return False
            self._f = F(self.root)
        return self._f

    def _show(self):
        w = self.target
        if w is None or not self.enabled():
            return
        text = w.property("tip")
        if callable(text):
            text = text()
        if not text:
            return
        b = self.bubble
        b.setFont(font("Barlow Condensed", 15, QFont.Weight.Medium))
        b.setStyleSheet("color:%s; padding:7px 10px;" % THEME.s("text"))
        b.setText(text)
        b.setFixedWidth(min(300, QFontMetrics(b.font()).horizontalAdvance(text) + 28))
        b.adjustSize()
        pos = w.mapTo(self.root, QPoint(0, w.height() + 4))
        x = max(40, min(pos.x(), self.root.width() - 40 - b.width()))
        y = pos.y()
        if y + b.height() > self.root.height() - 8:
            y = w.mapTo(self.root, QPoint(0, 0)).y() - b.height() - 4
        b.move(x, y)
        b.raise_()
        b.show()
