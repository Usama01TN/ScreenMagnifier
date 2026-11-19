# -*- coding: utf-8 -*-
"""
RegionSelector: full-desktop overlay to pick a screen region with the mouse.
- Freezes the whole virtual desktop (all monitors) and dims it.
- Drag to draw the selection; the selection is shown un-dimmed with corner handles and a size label.
- A pixel loupe follows the cursor for pixel-exact selection (coordinates + color under the cursor).
- Arrow keys move the cursor by 1 px (10 px with Shift). Esc / right click cancels.
- Emits regionSelected(QRect) in global, device-independent coordinates.
"""
from ManyQt.QtGui import QPainter, QColor, QPen, QPainterPath, QPixmap, QFont, QFontMetrics, QCursor, QGuiApplication, \
    QImage
from ManyQt.QtCore import Qt, QRect, QRectF, QPoint, QPointF, QSize, QLineF, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtWidgets import QWidget


def clamp(x, a, b):
    """
    :param x: float | int
    :param a: float | int
    :param b: float | int
    :return: float | int
    """
    return a if x < a else b if x > b else x


def virtualGeometry():
    """
    :return: (QRect) Union of all screen geometries.
    """
    rect = QRect()  # type: QRect
    for screen in QGuiApplication.screens():
        rect = rect.united(screen.geometry())  # type: QRect
    return rect


def grabDesktop():
    """
    Compose a screenshot of every screen into one pixmap covering the virtual desktop.
    :return: (tuple[QPixmap, float, QRect]) Pixmap in physical pixels, its scale and the virtual geometry.
    """
    vg = virtualGeometry()  # type: QRect
    dpr = max([float(s.devicePixelRatio()) for s in QGuiApplication.screens()] or [1.0])  # type: float
    pm = QPixmap(max(1, int(vg.width() * dpr)), max(1, int(vg.height() * dpr)))  # type: QPixmap
    pm.fill(Qt.black)
    p = QPainter(pm)  # type: QPainter
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    for screen in QGuiApplication.screens():
        g = screen.geometry()  # type: QRect
        shot = screen.grabWindow(0)  # type: QPixmap
        if shot.isNull():
            continue
        shot.setDevicePixelRatio(1.0)
        p.drawPixmap(QRectF((g.x() - vg.x()) * dpr, (g.y() - vg.y()) * dpr, g.width() * dpr, g.height() * dpr),
                     shot, QRectF(0, 0, shot.width(), shot.height()))
    p.end()
    return pm, dpr, vg


class RegionSelector(QWidget):
    """
    RegionSelector class.
    """
    regionSelected = pyqtSignal(QRect)  # type: pyqtSignal
    selectionCanceled = pyqtSignal()  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param dimColor: (QColor | Qt.GlobalColor | int | str) Overlay drawn outside the selection.
        :param borderColor: QColor | Qt.GlobalColor | int | str
        :param borderWidth: (float | int) px
        :param showLoupe: bool
        :param loupeZoom: (int) Loupe magnification.
        :param loupeSize: (int) Loupe diameter in px.
        :param minSize: (QSize) Smallest accepted selection.
        :param hintText: str | unicode | QString
        :param regionSelected: callable | None
        :param selectionCanceled: callable | None
        :param args: any
        :param kwargs: any
        """
        dimColor = kwargs.pop('dimColor', QColor(8, 10, 18, 140))  # type: QColor
        borderColor = kwargs.pop('borderColor', '#4F8BFF')  # type: QColor
        borderWidth = kwargs.pop('borderWidth', 2)  # type: float
        showLoupe = kwargs.pop('showLoupe', True)  # type: bool
        loupeZoom = kwargs.pop('loupeZoom', 8)  # type: int
        loupeSize = kwargs.pop('loupeSize', 132)  # type: int
        minSize = kwargs.pop('minSize', QSize(8, 8))  # type: QSize
        hintText = kwargs.pop('hintText', u'Drag to select a region  \u2022  Arrows: 1 px nudge  \u2022  '
                                          'Esc / right-click: cancel')  # type: str
        regionSelected = kwargs.pop('regionSelected', None)  # type: callable | None
        selectionCanceled = kwargs.pop('selectionCanceled', None)  # type: callable | None
        super(RegionSelector, self).__init__(*args, **kwargs)
        if callable(regionSelected):
            self.regionSelected.connect(regionSelected)
        if callable(selectionCanceled):
            self.selectionCanceled.connect(selectionCanceled)
        # Options.
        self.__m_dimColor = dimColor if isinstance(dimColor, QColor) else QColor(dimColor)  # type: QColor
        self.__m_borderColor = borderColor if isinstance(borderColor, QColor) else QColor(borderColor)  # type: QColor
        self.__m_borderWidth = max(0.0, float(borderWidth))  # type: float
        self.__m_showLoupe = bool(showLoupe)  # type: bool
        self.__m_loupeZoom = max(2, int(loupeZoom))  # type: int
        self.__m_loupeSize = max(48, int(loupeSize))  # type: int
        self.__m_minSize = QSize(minSize)  # type: QSize
        self.__m_hintText = hintText  # type: str
        # State.
        self.__m_snapshot = QPixmap()  # type: QPixmap
        self.__m_snapshotImage = None  # type: QImage | None
        self.__m_dpr = 1.0  # type: float
        self.__m_anchor = None  # type: QPoint | None
        self.__m_cursor = QPoint(-1, -1)  # type: QPoint
        self.__m_selection = QRect()  # type: QRect
        # Widget flags.
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    # ---------- Helpers ----------
    def _selectionFrom(self, a, b):
        """
        :param a: QPoint
        :param b: QPoint
        :return: (QRect) Rect spanning both points (exclusive of the far edge), clipped to the overlay.
        """
        x0, x1 = min(a.x(), b.x()), max(a.x(), b.x())  # type: int, int
        y0, y1 = min(a.y(), b.y()), max(a.y(), b.y())  # type: int, int
        return QRect(x0, y0, x1 - x0, y1 - y0).intersected(self.rect())

    def _pixelColor(self, pos):
        """
        :param pos: (QPoint) Local logical position.
        :return: QColor
        """
        img = self.__m_snapshotImage
        if img is None:
            return QColor()
        x = int(clamp(pos.x() * self.__m_dpr, 0, img.width() - 1))  # type: int
        y = int(clamp(pos.y() * self.__m_dpr, 0, img.height() - 1))  # type: int
        return QColor(img.pixel(x, y))

    def _finish(self, rect):
        """
        :param rect: (QRect | None) Local selection, None to cancel.
        :return:
        """
        self.releaseKeyboard()
        self.hide()
        self.__m_snapshot = QPixmap()  # type: QPixmap
        self.__m_snapshotImage = None
        self.__m_anchor = None
        if rect is None:
            self.selectionCanceled.emit()
        else:
            self.regionSelected.emit(rect.translated(self.geometry().topLeft()))

    # ---------- Public API ----------
    @pyqtSlot()
    def start(self):
        """
        Freeze the desktop and show the overlay. Hide your own windows before calling.
        :return:
        """
        self.__m_snapshot, self.__m_dpr, vg = grabDesktop()
        self.__m_snapshotImage = self.__m_snapshot.toImage()
        self.__m_anchor = None
        self.__m_selection = QRect()  # type: QRect
        self.setGeometry(vg)
        self.__m_cursor = self.mapFromGlobal(QCursor.pos())  # type: QPoint
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.grabKeyboard()

    @pyqtSlot()
    def cancel(self):
        """
        :return:
        """
        if self.isVisible():
            self._finish(None)

    def getSelection(self):
        """
        :return: (QRect) Current selection in global coordinates.
        """
        return self.__m_selection.translated(self.geometry().topLeft())

    def getDimColor(self):
        """
        :return: QColor
        """
        return self.__m_dimColor

    @pyqtSlot(QColor)
    @pyqtSlot(Qt.GlobalColor)
    @pyqtSlot(int)
    @pyqtSlot(str)
    @pyqtSlot('QString')
    def setDimColor(self, dimColor):
        """
        :param dimColor: QColor | Qt.GlobalColor | int | str | QString
        :return:
        """
        self.__m_dimColor = dimColor if isinstance(dimColor, QColor) else QColor(dimColor)  # type: QColor
        self.update()

    def getBorderColor(self):
        """
        :return: QColor
        """
        return self.__m_borderColor

    @pyqtSlot(QColor)
    @pyqtSlot(Qt.GlobalColor)
    @pyqtSlot(int)
    @pyqtSlot(str)
    @pyqtSlot('QString')
    def setBorderColor(self, borderColor):
        """
        :param borderColor: QColor | Qt.GlobalColor | int | str | QString
        :return:
        """
        self.__m_borderColor = borderColor if isinstance(borderColor, QColor) else QColor(borderColor)  # type: QColor
        self.update()

    def getBorderWidth(self):
        """
        :return: float | int
        """
        return self.__m_borderWidth

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setBorderWidth(self, borderWidth):
        """
        :param borderWidth: float | int
        :return:
        """
        self.__m_borderWidth = max(0.0, float(borderWidth))  # type: float
        self.update()

    def isShowLoupe(self):
        """
        :return: bool
        """
        return self.__m_showLoupe

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setShowLoupe(self, showLoupe):
        """
        :param showLoupe: bool
        :return:
        """
        self.__m_showLoupe = bool(showLoupe)  # type: bool
        self.update()

    def getLoupeZoom(self):
        """
        :return: int
        """
        return self.__m_loupeZoom

    @pyqtSlot(int)
    def setLoupeZoom(self, loupeZoom):
        """
        :param loupeZoom: int
        :return:
        """
        self.__m_loupeZoom = max(2, int(loupeZoom))  # type: int
        self.update()

    def getLoupeSize(self):
        """
        :return: int
        """
        return self.__m_loupeSize

    @pyqtSlot(int)
    def setLoupeSize(self, loupeSize):
        """
        :param loupeSize: int
        :return:
        """
        self.__m_loupeSize = max(48, int(loupeSize))  # type: int
        self.update()

    def getMinSize(self):
        """
        :return: QSize
        """
        return QSize(self.__m_minSize)

    @pyqtSlot(QSize)
    def setMinSize(self, minSize):
        """
        :param minSize: QSize
        :return:
        """
        self.__m_minSize = QSize(minSize)  # type: QSize

    def getHintText(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_hintText

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setHintText(self, hintText):
        """
        :param hintText: str | unicode | QString
        :return:
        """
        self.__m_hintText = hintText  # type: str
        self.update()

    # ---------- Qt overrides ----------
    def mousePressEvent(self, e):
        """
        :param e: QMouseEvent
        :return:
        """
        if e.button() == Qt.RightButton:
            self._finish(None)
            return
        if e.button() == Qt.LeftButton:
            self.__m_anchor = e.pos()  # type: QPoint
            self.__m_selection = QRect()  # type: QRect
            self.update()
        super(RegionSelector, self).mousePressEvent(e)

    def mouseMoveEvent(self, e):
        """
        :param e: QMouseEvent
        :return:
        """
        self.__m_cursor = e.pos()  # type: QPoint
        if self.__m_anchor is not None:
            self.__m_selection = self._selectionFrom(self.__m_anchor, e.pos())  # type: QRect
        self.update()
        super(RegionSelector, self).mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        """
        :param e: QMouseEvent
        :return: None
        """
        if e.button() == Qt.LeftButton and self.__m_anchor is not None:
            sel = self._selectionFrom(self.__m_anchor, e.pos())  # type: QRect
            self.__m_anchor = None
            if sel.width() >= self.__m_minSize.width() and sel.height() >= self.__m_minSize.height():
                self._finish(sel)
                return
            self.__m_selection = QRect()  # type: QRect
            self.update()
        super(RegionSelector, self).mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        """
        :param e: QKeyEvent
        :return:
        """
        if e.key() == Qt.Key_Escape:
            self._finish(None)
            return
        steps = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if e.key() in steps:
            dx, dy = steps[e.key()]
            k = 10 if e.modifiers() & Qt.ShiftModifier else 1  # type: int
            QCursor.setPos(QCursor.pos() + QPoint(dx * k, dy * k))
            return
        super(RegionSelector, self).keyPressEvent(e)

    def leaveEvent(self, e):
        """
        :param e: QEvent
        :return:
        """
        self.__m_cursor = QPoint(-1, -1)  # type: QPoint
        self.update()
        super(RegionSelector, self).leaveEvent(e)

    # ---------- Painting ----------
    def paintEvent(self, event):
        """
        :param event: QPaintEvent
        :return:
        """
        p = QPainter(self)  # type: QPainter
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing, True)
        r = QRectF(self.rect())  # type: QRectF
        if self.__m_snapshot.isNull():
            p.fillRect(r, Qt.black)
        else:
            p.drawPixmap(r, self.__m_snapshot, QRectF(0, 0, self.__m_snapshot.width(), self.__m_snapshot.height()))
        sel = QRectF(self.__m_selection)  # type: QRectF
        dim = QPainterPath()  # type: QPainterPath
        dim.addRect(r)
        if not sel.isEmpty():
            hole = QPainterPath()  # type: QPainterPath
            hole.addRect(sel)
            dim = dim.subtracted(hole)  # type: QPainterPath
        p.fillPath(dim, self.__m_dimColor)
        if not sel.isEmpty():
            self._paintSelection(p, sel)
        self._paintHint(p)
        if self.__m_showLoupe and self.rect().contains(self.__m_cursor):
            self._paintLoupe(p)
        p.end()

    def _paintSelection(self, p, sel):
        """
        :param p: QPainter
        :param sel: QRectF
        :return:
        """
        pen = QPen(self.__m_borderColor, self.__m_borderWidth)  # type: QPen
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        hw = self.__m_borderWidth / 2.0  # type: float
        p.drawRect(sel.adjusted(-hw, -hw, hw, hw))
        p.setPen(QPen(Qt.white, 1.5))
        p.setBrush(self.__m_borderColor)
        for c in (sel.topLeft(), sel.topRight(), sel.bottomLeft(), sel.bottomRight()):
            p.drawEllipse(c, 4.5, 4.5)
        # Size label.
        font = QFont(self.font())  # type: QFont
        font.setPointSizeF(9.5)
        font.setBold(True)
        p.setFont(font)
        dpr = self.__m_dpr  # type: float
        text = '{} \u00d7 {}'.format(int(sel.width()), int(sel.height()))  # type: str
        if dpr != 1.0:
            text += '   ({} \u00d7 {} px)'.format(int(sel.width() * dpr), int(sel.height() * dpr))
        fm = QFontMetrics(font)  # type: QFontMetrics
        tw = fm.horizontalAdvance(text) if hasattr(fm, 'horizontalAdvance') else fm.width(text)  # type: int
        box = QRectF(sel.left(), sel.top() - fm.height() - 12, tw + 16, fm.height() + 6)  # type: QRectF
        if box.top() < 2:
            box.moveTop(sel.top() + 6)
            box.moveLeft(sel.left() + 6)
        p.setPen(Qt.NoPen)
        p.setBrush(self.__m_borderColor)
        p.drawRoundedRect(box, 5, 5)
        p.setPen(Qt.white)
        p.drawText(box, Qt.AlignCenter, text)

    def _paintHint(self, p):
        """
        :param p: QPainter
        :return: None
        """
        if not self.__m_hintText:
            return
        screen = QGuiApplication.screenAt(self.mapToGlobal(self.__m_cursor)) if hasattr(
            QGuiApplication, 'screenAt') else None
        screen = screen or QGuiApplication.primaryScreen()
        sg = screen.geometry().translated(-self.geometry().topLeft())  # type: QRect
        font = QFont(self.font())  # type: QFont
        font.setPointSizeF(10.5)
        p.setFont(font)
        fm = QFontMetrics(font)  # type: QFontMetrics
        tw = fm.horizontalAdvance(self.__m_hintText) if hasattr(fm, 'horizontalAdvance') else fm.width(
            self.__m_hintText)  # type: int
        box = QRectF(sg.center().x() - (tw + 32) / 2.0, sg.top() + 24, tw + 32, fm.height() + 16)  # type: QRectF
        if box.intersects(QRectF(self.__m_selection)) or box.contains(QPointF(self.__m_cursor)):
            box.moveBottom(sg.bottom() - 24)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 22, 30, 215))
        p.drawRoundedRect(box, box.height() / 2.0, box.height() / 2.0)
        p.setPen(QColor(235, 238, 245))
        p.drawText(box, Qt.AlignCenter, self.__m_hintText)

    def _paintLoupe(self, p):
        """
        :param p: QPainter
        :return:
        """
        size = float(self.__m_loupeSize)  # type: float
        zoom = self.__m_loupeZoom  # type: int
        cells = int(size / zoom) | 1  # type: int  # odd -> a true centre pixel
        size = float(cells * zoom)  # type: float
        c = self.__m_cursor  # type: QPoint
        dpr = self.__m_dpr  # type: float
        # Place the loupe bottom-right of the cursor, flip near the edges.
        x = c.x() + 24.0  # type: float
        y = c.y() + 24.0  # type: float
        if x + size > self.width() - 4:
            x = c.x() - 24.0 - size
        if y + size + 40 > self.height() - 4:
            y = c.y() - 24.0 - size - 40
        target = QRectF(x, y, size, size)  # type: QRectF
        half = cells // 2  # type: int
        px, py = int(c.x() * dpr), int(c.y() * dpr)  # type: int, int
        src = QRectF(px - half, py - half, cells, cells)  # type: QRectF
        clip = QPainterPath()  # type: QPainterPath
        clip.addRoundedRect(target, 10, 10)
        p.save()
        p.setClipPath(clip)
        p.fillRect(target, Qt.black)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.drawPixmap(target, self.__m_snapshot, src)
        grid = QPen(QColor(0, 0, 0, 50), 1)  # type: QPen
        p.setPen(grid)
        lines = []  # type: list[QLineF]
        for i in range(1, cells):
            lines.append(QLineF(x + i * zoom, y, x + i * zoom, y + size))
            lines.append(QLineF(x, y + i * zoom, x + size, y + i * zoom))
        p.drawLines(lines)
        centre = QRectF(x + half * zoom, y + half * zoom, zoom, zoom)  # type: QRectF
        p.setPen(QPen(Qt.white, 1))
        p.drawRect(centre.adjusted(-1, -1, 1, 1))
        p.setPen(QPen(Qt.black, 1))
        p.drawRect(centre)
        p.restore()
        p.setPen(QPen(self.__m_borderColor, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(target, 10, 10)
        # Info box under the loupe.
        col = self._pixelColor(c)  # type: QColor
        g = self.mapToGlobal(c)  # type: QPoint
        info = QRectF(x, y + size + 6, size, 34)  # type: QRectF
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 22, 30, 225))
        p.drawRoundedRect(info, 7, 7)
        font = QFont(self.font())  # type: QFont
        font.setPointSizeF(8.5)
        p.setFont(font)
        p.setBrush(col)
        p.setPen(QPen(QColor(255, 255, 255, 160), 1))
        p.drawRoundedRect(QRectF(info.left() + 7, info.top() + 9, 16, 16), 3, 3)
        p.setPen(QColor(235, 238, 245))
        p.drawText(info.adjusted(30, 2, -4, -2), Qt.AlignVCenter | Qt.AlignLeft,
                   '{}, {}\n{}'.format(g.x(), g.y(), col.name().upper()))

    # ---------- Properties ----------
    dimColor = pyqtProperty(QColor, fget=getDimColor, fset=setDimColor)  # type: pyqtProperty
    borderColor = pyqtProperty(QColor, fget=getBorderColor, fset=setBorderColor)  # type: pyqtProperty
    borderWidth = pyqtProperty(float, fget=getBorderWidth, fset=setBorderWidth)  # type: pyqtProperty
    showLoupe = pyqtProperty(bool, fget=isShowLoupe, fset=setShowLoupe)  # type: pyqtProperty
    loupeZoom = pyqtProperty(int, fget=getLoupeZoom, fset=setLoupeZoom)  # type: pyqtProperty
    loupeSize = pyqtProperty(int, fget=getLoupeSize, fset=setLoupeSize)  # type: pyqtProperty
    minSize = pyqtProperty(QSize, fget=getMinSize, fset=setMinSize)  # type: pyqtProperty
    hintText = pyqtProperty('QString', fget=getHintText, fset=setHintText)  # type: pyqtProperty
