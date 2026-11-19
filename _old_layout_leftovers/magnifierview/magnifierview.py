# -*- coding: utf-8 -*-
"""
MagnifierViewWidget: displays a frame with adjustable magnification.
- Only the visible crop of the frame is upscaled, straight to the on-screen size (HiDPI aware), through an
  optional processor callable(QImage crop, QSize target) -> QImage, so any upscaler can be plugged in.
- Processed output is cached per (frame, crop, size), hover/grid repaints cost nothing extra.
- Wheel zooms around the cursor, drag pans, double-click fits the frame into the view.
- Pixel grid at high zoom, hovered-pixel highlight, crosshair, colour inversion and an animated zoom badge.
- pixelHovered(QPoint, QColor) reports the source pixel and its colour under the mouse.
"""
from ManyQt.QtCore import Qt, QTimer, QElapsedTimer, QRect, QRectF, QPoint, QPointF, QSize, QLineF, pyqtSignal, \
    pyqtSlot, pyqtProperty
from ManyQt.QtGui import QPainter, QColor, QPen, QImage, QFont, QFontMetrics, QPainterPath
from ManyQt.QtWidgets import QWidget
from math import floor, ceil


def clamp(x, a, b):
    """
    :param x: float | int
    :param a: float | int
    :param b: float | int
    :return: float | int
    """
    return a if x < a else b if x > b else x


def axisLayout(frameSize, viewSize, centre, zoom):
    """
    Lay out one axis of the frame inside the view.
    :param frameSize: (int) Frame size along the axis in source pixels.
    :param viewSize: (float | int) View size along the axis in px.
    :param centre: (float | int) Requested center in source pixels.
    :param zoom: (float | int) View px per source pixel.
    :return: (tuple[int, int, float, float]) First source pixel, pixel count, view offset of that pixel,
        clamped center.
    """
    disp = frameSize * zoom  # type: float
    if disp <= viewSize:
        return 0, frameSize, (viewSize - disp) / 2.0, frameSize / 2.0
    visible = viewSize / float(zoom)  # type: float
    centre = clamp(centre, visible / 2.0, frameSize - visible / 2.0)  # type: float
    s0 = centre - visible / 2.0  # type: float
    i0 = int(floor(s0))  # type: int
    i1 = min(frameSize, int(ceil(s0 + visible)))  # type: int
    return i0, i1 - i0, (i0 - s0) * zoom, centre


class MagnifierViewWidget(QWidget):
    """
    MagnifierViewWidget class.
    """
    zoomChanged = pyqtSignal(float)  # type: pyqtSignal
    pixelHovered = pyqtSignal(QPoint, QColor)  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param zoom: (float | int) View px per source pixel.
        :param minZoom: float | int
        :param maxZoom: float | int
        :param zoomStep: (float | int) Multiplier per wheel notch / zoomIn().
        :param processor: (callable | None) f(QImage crop, QSize target) -> QImage. None = Qt scaling.
        :param showGrid: bool
        :param gridMinZoom: (float | int) Grid is drawn from this zoom on.
        :param gridColor: QColor | Qt.GlobalColor | int | str
        :param showCrosshair: bool
        :param crosshairColor: QColor | Qt.GlobalColor | int | str
        :param invertColors: bool
        :param panEnabled: (bool) False keeps the frame centred (useful when following the cursor).
        :param showZoomBadge: bool
        :param background: QColor | Qt.GlobalColor | int | str
        :param placeholderText: str | unicode | QString
        :param zoomChanged: callable | None
        :param pixelHovered: callable | None
        :param args: any
        :param kwargs: any
        """
        zoom = kwargs.pop('zoom', 3.0)  # type: float
        minZoom = kwargs.pop('minZoom', 0.25)  # type: float
        maxZoom = kwargs.pop('maxZoom', 32.0)  # type: float
        zoomStep = kwargs.pop('zoomStep', 1.2)  # type: float
        processor = kwargs.pop('processor', None)  # type: callable | None
        showGrid = kwargs.pop('showGrid', True)  # type: bool
        gridMinZoom = kwargs.pop('gridMinZoom', 10.0)  # type: float
        gridColor = kwargs.pop('gridColor', QColor(0, 0, 0, 70))  # type: QColor
        showCrosshair = kwargs.pop('showCrosshair', False)  # type: bool
        crosshairColor = kwargs.pop('crosshairColor', '#FF3B6B')  # type: QColor
        invertColors = kwargs.pop('invertColors', False)  # type: bool
        panEnabled = kwargs.pop('panEnabled', True)  # type: bool
        showZoomBadge = kwargs.pop('showZoomBadge', True)  # type: bool
        background = kwargs.pop('background', '#15161C')  # type: QColor
        placeholderText = kwargs.pop('placeholderText', 'No image')  # type: str
        zoomChanged = kwargs.pop('zoomChanged', None)  # type: callable | None
        pixelHovered = kwargs.pop('pixelHovered', None)  # type: callable | None
        super(MagnifierViewWidget, self).__init__(*args, **kwargs)
        if callable(zoomChanged):
            self.zoomChanged.connect(zoomChanged)
        if callable(pixelHovered):
            self.pixelHovered.connect(pixelHovered)
        # Options.
        self.__m_minZoom = max(0.01, float(minZoom))  # type: float
        self.__m_maxZoom = max(self.__m_minZoom, float(maxZoom))  # type: float
        self.__m_zoom = clamp(float(zoom), self.__m_minZoom, self.__m_maxZoom)  # type: float
        self.__m_zoomStep = max(1.01, float(zoomStep))  # type: float
        self.__m_processor = processor if callable(processor) else None  # type: callable | None
        self.__m_showGrid = bool(showGrid)  # type: bool
        self.__m_gridMinZoom = max(1.0, float(gridMinZoom))  # type: float
        self.__m_gridColor = gridColor if isinstance(gridColor, QColor) else QColor(gridColor)  # type: QColor
        self.__m_showCrosshair = bool(showCrosshair)  # type: bool
        self.__m_crosshairColor = crosshairColor if isinstance(crosshairColor, QColor) else QColor(
            crosshairColor)  # type: QColor
        self.__m_invertColors = bool(invertColors)  # type: bool
        self.__m_panEnabled = bool(panEnabled)  # type: bool
        self.__m_showZoomBadge = bool(showZoomBadge)  # type: bool
        self.__m_background = background if isinstance(background, QColor) else QColor(background)  # type: QColor
        self.__m_placeholderText = placeholderText  # type: str
        # Frame state.
        self.__m_frame = QImage()  # type: QImage
        self.__m_serial = 0  # type: int
        self.__m_version = 0  # type: int
        self.__m_centre = QPointF()  # type: QPointF
        # Processed-crop cache.
        self.__m_cacheKey = None  # type: tuple | None
        self.__m_cacheImage = QImage()  # type: QImage
        # Interaction.
        self.__m_hover = QPoint(-1, -1)  # type: QPoint
        self.__m_dragFrom = None  # type: QPointF | None
        # Zoom badge animation.
        self.__m_badgeOpacity = 0.0  # type: float
        self.__m_badgeClock = QElapsedTimer()  # type: QElapsedTimer
        self.__m_badgeTimer = QTimer(self)  # type: QTimer
        self.__m_badgeTimer.timeout.connect(self._tick)
        # Widget flags.
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.WheelFocus)
        self.setCursor(Qt.CrossCursor)

    # ---------- Helpers ----------
    def _layout(self):
        """
        :return: (tuple[QRect, QPointF]) Visible source crop and the view position of its top-left pixel.
        """
        f = self.__m_frame  # type: QImage
        z = self.__m_zoom  # type: float
        x0, cw, ox, cx = axisLayout(f.width(), float(self.width()), self.__m_centre.x(), z)
        y0, ch, oy, cy = axisLayout(f.height(), float(self.height()), self.__m_centre.y(), z)
        self.__m_centre = QPointF(cx, cy)  # type: QPointF
        return QRect(x0, y0, cw, ch), QPointF(ox, oy)

    def _devicePixelRatio(self):
        """
        :return: float | int
        """
        return float(self.devicePixelRatioF()) if hasattr(self, 'devicePixelRatioF') else float(
            self.devicePixelRatio())

    def _processed(self, crop, pxSize):
        """
        :param crop: QRect
        :param pxSize: QSize
        :return: (QImage) Cached processed crop.
        """
        key = (self.__m_serial, self.__m_version, crop.x(), crop.y(), crop.width(), crop.height(),
               pxSize.width(), pxSize.height(), self.__m_invertColors)  # type: tuple
        if key != self.__m_cacheKey:
            src = self.__m_frame.copy(crop)  # type: QImage
            img = QImage()  # type: QImage
            if self.__m_processor is not None:
                try:
                    img = self.__m_processor(src, pxSize)  # type: QImage
                except Exception as e:
                    print('MagnifierViewWidget: processor failed ({}), using Qt scaling.'.format(e))
                    img = QImage()  # type: QImage
            if img is None or img.isNull():
                mode = Qt.FastTransformation if self.__m_zoom >= 2.0 else Qt.SmoothTransformation  # type: int
                img = src.scaled(pxSize, Qt.IgnoreAspectRatio, mode)  # type: QImage
            if self.__m_invertColors:
                img = img.convertToFormat(QImage.Format_RGB32)  # type: QImage
                img.invertPixels()
            self.__m_cacheKey = key  # type: tuple
            self.__m_cacheImage = img  # type: QImage
        return self.__m_cacheImage

    def _emitHover(self):
        """
        :return:
        """
        if self.__m_frame.isNull() or not self.rect().contains(self.__m_hover):
            self.pixelHovered.emit(QPoint(-1, -1), QColor())
            return
        s = self.mapToSource(QPointF(self.__m_hover))  # type: QPointF
        ix, iy = int(floor(s.x())), int(floor(s.y()))  # type: int, int
        if 0 <= ix < self.__m_frame.width() and 0 <= iy < self.__m_frame.height():
            self.pixelHovered.emit(QPoint(ix, iy), QColor(self.__m_frame.pixel(ix, iy)))
        else:
            self.pixelHovered.emit(QPoint(-1, -1), QColor())

    def _showBadge(self):
        """
        :return:
        """
        if self.__m_showZoomBadge:
            self.__m_badgeClock.start()
            self.__m_badgeOpacity = 1.0  # type: float
            if not self.__m_badgeTimer.isActive():
                self.__m_badgeTimer.start(16)

    # ---------- Animation tick ----------
    def _tick(self):
        """
        :return:
        """
        t = self.__m_badgeClock.elapsed()  # type: int
        hold, fade = 700, 450  # type: int, int
        self.__m_badgeOpacity = 1.0 if t < hold else max(0.0, 1.0 - (t - hold) / float(fade))  # type: float
        if self.__m_badgeOpacity <= 0.0:
            self.__m_badgeTimer.stop()
        self.update()

    # ---------- Public API ----------
    def getFrame(self):
        """
        :return: QImage
        """
        return self.__m_frame

    @pyqtSlot(QImage)
    def setFrame(self, frame):
        """
        :param frame: QImage
        :return:
        """
        frame = QImage() if frame is None else frame  # type: QImage
        if frame.size() != self.__m_frame.size() or not self.__m_panEnabled:
            self.__m_centre = QPointF(frame.width() / 2.0, frame.height() / 2.0)  # type: QPointF
        self.__m_frame = frame  # type: QImage
        self.__m_serial += 1
        if self.__m_hover.x() >= 0:
            self._emitHover()
        self.update()

    @pyqtSlot()
    def clear(self):
        """
        :return:
        """
        self.setFrame(QImage())
        self.__m_cacheImage = QImage()  # type: QImage
        self.__m_cacheKey = None

    @pyqtSlot()
    def refresh(self):
        """
        Re-run the processor on the current frame (call after changing the processor's settings).
        :return:
        """
        self.__m_version += 1
        self.update()

    def mapToSource(self, pos):
        """
        :param pos: (QPointF) View position.
        :return: (QPointF) Position in source (frame) pixels.
        """
        if self.__m_frame.isNull():
            return QPointF(-1, -1)
        crop, off = self._layout()
        z = self.__m_zoom  # type: float
        return QPointF(crop.x() + (pos.x() - off.x()) / z, crop.y() + (pos.y() - off.y()) / z)

    def getVisibleSourceRect(self):
        """
        :return: (QRectF) Part of the frame that is currently visible, in source pixels.
        """
        if self.__m_frame.isNull():
            return QRectF()
        tl = self.mapToSource(QPointF(0, 0))  # type: QPointF
        br = self.mapToSource(QPointF(self.width(), self.height()))  # type: QPointF
        return QRectF(tl, br).intersected(QRectF(0, 0, self.__m_frame.width(), self.__m_frame.height()))

    def zoomAt(self, pos, zoom):
        """
        Zoom while keeping the source pixel under pos fixed.
        :param pos: (QPointF) View position.
        :param zoom: float | int
        :return:
        """
        zoom = clamp(float(zoom), self.__m_minZoom, self.__m_maxZoom)  # type: float
        if abs(zoom - self.__m_zoom) < 1e-6:
            return
        if not self.__m_frame.isNull() and self.__m_panEnabled:
            s = self.mapToSource(pos)  # type: QPointF
            self.__m_centre = QPointF(s.x() + (self.width() / 2.0 - pos.x()) / zoom,
                                      s.y() + (self.height() / 2.0 - pos.y()) / zoom)  # type: QPointF
        self.__m_zoom = zoom  # type: float
        self._showBadge()
        self.update()
        self.zoomChanged.emit(zoom)

    @pyqtSlot()
    def zoomIn(self):
        """
        :return:
        """
        self.zoomAt(QPointF(self.width() / 2.0, self.height() / 2.0), self.__m_zoom * self.__m_zoomStep)

    @pyqtSlot()
    def zoomOut(self):
        """
        :return:
        """
        self.zoomAt(QPointF(self.width() / 2.0, self.height() / 2.0), self.__m_zoom / self.__m_zoomStep)

    @pyqtSlot()
    def fitToView(self):
        """
        Choose the zoom that shows the whole frame.
        :return:
        """
        f = self.__m_frame  # type: QImage
        if f.isNull() or self.width() < 2 or self.height() < 2:
            return
        z = min(self.width() / float(f.width()), self.height() / float(f.height()))  # type: float
        self.__m_centre = QPointF(f.width() / 2.0, f.height() / 2.0)  # type: QPointF
        self.zoomAt(QPointF(self.width() / 2.0, self.height() / 2.0), floor(z * 100.0) / 100.0)

    def getZoom(self):
        """
        :return: float | int
        """
        return self.__m_zoom

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setZoom(self, zoom):
        """
        :param zoom: float | int
        :return:
        """
        self.zoomAt(QPointF(self.width() / 2.0, self.height() / 2.0), zoom)

    def getMinZoom(self):
        """
        :return: float | int
        """
        return self.__m_minZoom

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setMinZoom(self, minZoom):
        """
        :param minZoom: float | int
        :return:
        """
        self.__m_minZoom = max(0.01, min(float(minZoom), self.__m_maxZoom))  # type: float
        self.setZoom(self.__m_zoom)

    def getMaxZoom(self):
        """
        :return: float | int
        """
        return self.__m_maxZoom

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setMaxZoom(self, maxZoom):
        """
        :param maxZoom: float | int
        :return:
        """
        self.__m_maxZoom = max(self.__m_minZoom, float(maxZoom))  # type: float
        self.setZoom(self.__m_zoom)

    def getZoomStep(self):
        """
        :return: float | int
        """
        return self.__m_zoomStep

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setZoomStep(self, zoomStep):
        """
        :param zoomStep: float | int
        :return:
        """
        self.__m_zoomStep = max(1.01, float(zoomStep))  # type: float

    def getProcessor(self):
        """
        :return: callable | None
        """
        return self.__m_processor

    @pyqtSlot(object)
    def setProcessor(self, processor):
        """
        :param processor: (callable | None) f(QImage, QSize) -> QImage
        :return:
        """
        self.__m_processor = processor if callable(processor) else None  # type: callable | None
        self.refresh()

    def isShowGrid(self):
        """
        :return: bool
        """
        return self.__m_showGrid

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setShowGrid(self, showGrid):
        """
        :param showGrid: bool
        :return:
        """
        self.__m_showGrid = bool(showGrid)  # type: bool
        self.update()

    def getGridMinZoom(self):
        """
        :return: float | int
        """
        return self.__m_gridMinZoom

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setGridMinZoom(self, gridMinZoom):
        """
        :param gridMinZoom: float | int
        :return:
        """
        self.__m_gridMinZoom = max(1.0, float(gridMinZoom))  # type: float
        self.update()

    def getGridColor(self):
        """
        :return: QColor
        """
        return self.__m_gridColor

    @pyqtSlot(QColor)
    @pyqtSlot(Qt.GlobalColor)
    @pyqtSlot(int)
    @pyqtSlot(str)
    @pyqtSlot('QString')
    def setGridColor(self, gridColor):
        """
        :param gridColor: QColor | Qt.GlobalColor | int | str | QString
        :return:
        """
        self.__m_gridColor = gridColor if isinstance(gridColor, QColor) else QColor(gridColor)  # type: QColor
        self.update()

    def isShowCrosshair(self):
        """
        :return: bool
        """
        return self.__m_showCrosshair

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setShowCrosshair(self, showCrosshair):
        """
        :param showCrosshair: bool
        :return:
        """
        self.__m_showCrosshair = bool(showCrosshair)  # type: bool
        self.update()

    def getCrosshairColor(self):
        """
        :return: QColor
        """
        return self.__m_crosshairColor

    @pyqtSlot(QColor)
    @pyqtSlot(Qt.GlobalColor)
    @pyqtSlot(int)
    @pyqtSlot(str)
    @pyqtSlot('QString')
    def setCrosshairColor(self, crosshairColor):
        """
        :param crosshairColor: QColor | Qt.GlobalColor | int | str | QString
        :return:
        """
        self.__m_crosshairColor = crosshairColor if isinstance(crosshairColor, QColor) else QColor(
            crosshairColor)  # type: QColor
        self.update()

    def isInvertColors(self):
        """
        :return: bool
        """
        return self.__m_invertColors

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setInvertColors(self, invertColors):
        """
        :param invertColors: bool
        :return:
        """
        self.__m_invertColors = bool(invertColors)  # type: bool
        self.update()

    def isPanEnabled(self):
        """
        :return: bool
        """
        return self.__m_panEnabled

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setPanEnabled(self, panEnabled):
        """
        :param panEnabled: bool
        :return:
        """
        self.__m_panEnabled = bool(panEnabled)  # type: bool
        if not self.__m_panEnabled:
            self.__m_dragFrom = None
            self.__m_centre = QPointF(self.__m_frame.width() / 2.0, self.__m_frame.height() / 2.0)  # type: QPointF
            self.update()

    def isShowZoomBadge(self):
        """
        :return: bool
        """
        return self.__m_showZoomBadge

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setShowZoomBadge(self, showZoomBadge):
        """
        :param showZoomBadge: bool
        :return:
        """
        self.__m_showZoomBadge = bool(showZoomBadge)  # type: bool
        self.update()

    def getBackground(self):
        """
        :return: QColor
        """
        return self.__m_background

    @pyqtSlot(QColor)
    @pyqtSlot(Qt.GlobalColor)
    @pyqtSlot(int)
    @pyqtSlot(str)
    @pyqtSlot('QString')
    def setBackground(self, background):
        """
        :param background: QColor | Qt.GlobalColor | int | str | QString
        :return:
        """
        self.__m_background = background if isinstance(background, QColor) else QColor(background)  # type: QColor
        self.update()

    def getPlaceholderText(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_placeholderText

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setPlaceholderText(self, placeholderText):
        """
        :param placeholderText: str | unicode | QString
        :return:
        """
        self.__m_placeholderText = placeholderText  # type: str
        self.update()

    # ---------- Qt overrides ----------
    def sizeHint(self):
        """
        :return: QSize
        """
        return QSize(720, 480)

    def minimumSizeHint(self):
        """
        :return: QSize
        """
        return QSize(120, 80)

    def wheelEvent(self, e):
        """
        :param e: QWheelEvent
        :return:
        """
        delta = e.angleDelta().y() or e.angleDelta().x()  # type: int
        if delta:
            pos = e.position() if hasattr(e, 'position') else e.posF()  # type: QPointF
            self.zoomAt(pos, self.__m_zoom * (self.__m_zoomStep ** (delta / 120.0)))
        e.accept()

    def mousePressEvent(self, e):
        """
        :param e: QMouseEvent
        :return:
        """
        if e.button() == Qt.LeftButton and self.__m_panEnabled and not self.__m_frame.isNull():
            self.__m_dragFrom = QPointF(e.pos())  # type: QPointF
            self.setCursor(Qt.ClosedHandCursor)
        super(MagnifierViewWidget, self).mousePressEvent(e)

    def mouseMoveEvent(self, e):
        """
        :param e: QMouseEvent
        :return:
        """
        self.__m_hover = e.pos()  # type: QPoint
        if self.__m_dragFrom is not None:
            d = QPointF(e.pos()) - self.__m_dragFrom  # type: QPointF
            z = self.__m_zoom  # type: float
            self._layout()  # Clamp the centre before moving it.
            self.__m_centre = QPointF(self.__m_centre.x() - d.x() / z, self.__m_centre.y() - d.y() / z)  # type: QPointF
            self.__m_dragFrom = QPointF(e.pos())  # type: QPointF
        self._emitHover()
        self.update()
        super(MagnifierViewWidget, self).mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        """
        :param e: QMouseEvent
        :return:
        """
        if e.button() == Qt.LeftButton and self.__m_dragFrom is not None:
            self.__m_dragFrom = None
            self.setCursor(Qt.CrossCursor)
        super(MagnifierViewWidget, self).mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        """
        :param e: QMouseEvent
        :return:
        """
        if e.button() == Qt.LeftButton:
            self.fitToView()
        super(MagnifierViewWidget, self).mouseDoubleClickEvent(e)

    def leaveEvent(self, e):
        """
        :param e: QEvent
        :return:
        """
        self.__m_hover = QPoint(-1, -1)  # type: QPoint
        self._emitHover()
        self.update()
        super(MagnifierViewWidget, self).leaveEvent(e)

    # ---------- Painting ----------
    def paintEvent(self, event):
        """
        :param event: QPaintEvent
        :return:
        """
        p = QPainter(self)  # type: QPainter
        p.fillRect(self.rect(), self.__m_background)
        if self.__m_frame.isNull():
            self._paintPlaceholder(p)
            p.end()
            return
        z = self.__m_zoom  # type: float
        crop, off = self._layout()
        if crop.isEmpty():
            p.end()
            return
        target = QRectF(off.x(), off.y(), crop.width() * z, crop.height() * z)  # type: QRectF
        dpr = self._devicePixelRatio()  # type: float
        pxSize = QSize(max(1, int(round(target.width() * dpr))), max(1, int(round(target.height() * dpr))))
        img = self._processed(crop, pxSize)  # type: QImage
        p.drawImage(target, img, QRectF(0, 0, img.width(), img.height()))
        if self.__m_showGrid and z >= self.__m_gridMinZoom:
            self._paintGrid(p, crop, off, target)
        self._paintHoverPixel(p, crop, off)
        if self.__m_showCrosshair:
            self._paintCrosshair(p)
        if self.__m_badgeOpacity > 0.0:
            self._paintBadge(p)
        p.end()

    def _paintGrid(self, p, crop, off, target):
        """
        :param p: QPainter
        :param crop: QRect
        :param off: QPointF
        :param target: QRectF
        :return:
        """
        z = self.__m_zoom  # type: float
        vis = target.intersected(QRectF(self.rect()))  # type: QRectF
        lines = []  # type: list[QLineF]
        for i in range(crop.width() + 1):
            x = off.x() + i * z  # type: float
            if vis.left() <= x <= vis.right():
                lines.append(QLineF(x, vis.top(), x, vis.bottom()))
        for j in range(crop.height() + 1):
            y = off.y() + j * z  # type: float
            if vis.top() <= y <= vis.bottom():
                lines.append(QLineF(vis.left(), y, vis.right(), y))
        pen = QPen(self.__m_gridColor, 0)  # type: QPen
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawLines(lines)

    def _paintHoverPixel(self, p, crop, off):
        """
        :param p: QPainter
        :param crop: QRect
        :param off: QPointF
        :return:
        """
        z = self.__m_zoom  # type: float
        if z < 4.0 or self.__m_dragFrom is not None or not self.rect().contains(self.__m_hover):
            return
        s = self.mapToSource(QPointF(self.__m_hover))  # type: QPointF
        ix, iy = int(floor(s.x())), int(floor(s.y()))  # type: int, int
        if not (0 <= ix < self.__m_frame.width() and 0 <= iy < self.__m_frame.height()):
            return
        r = QRectF(off.x() + (ix - crop.x()) * z, off.y() + (iy - crop.y()) * z, z, z)  # type: QRectF
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 200), 1))
        p.drawRect(r.adjusted(-1, -1, 1, 1))
        p.setPen(QPen(QColor(255, 255, 255, 230), 1))
        p.drawRect(r)

    def _paintCrosshair(self, p):
        """
        :param p: QPainter
        :return:
        """
        cx, cy = self.width() / 2.0, self.height() / 2.0  # type: float, float
        gap = max(6.0, self.__m_zoom * 0.75)  # type: float
        lines = [QLineF(0, cy, cx - gap, cy), QLineF(cx + gap, cy, self.width(), cy),
                 QLineF(cx, 0, cx, cy - gap), QLineF(cx, cy + gap, cx, self.height())]  # type: list[QLineF]
        p.setPen(QPen(QColor(0, 0, 0, 110), 3))
        p.drawLines(lines)
        p.setPen(QPen(self.__m_crosshairColor, 1))
        p.drawLines(lines)

    def _paintBadge(self, p):
        """
        :param p: QPainter
        :return:
        """
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setOpacity(self.__m_badgeOpacity)
        font = QFont(self.font())  # type: QFont
        font.setPointSizeF(13)
        font.setBold(True)
        p.setFont(font)
        text = '{:.2f}\u00d7'.format(self.__m_zoom)  # type: str
        fm = QFontMetrics(font)  # type: QFontMetrics
        tw = fm.horizontalAdvance(text) if hasattr(fm, 'horizontalAdvance') else fm.width(text)  # type: int
        box = QRectF(self.width() - tw - 40, self.height() - fm.height() - 30, tw + 24, fm.height() + 12)
        path = QPainterPath()  # type: QPainterPath
        path.addRoundedRect(box, box.height() / 2.0, box.height() / 2.0)
        p.fillPath(path, QColor(18, 20, 28, 210))
        p.setPen(QColor(240, 242, 248))
        p.drawText(box, Qt.AlignCenter, text)
        p.setOpacity(1.0)

    def _paintPlaceholder(self, p):
        """
        :param p: QPainter
        :return:
        """
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(24, 24, -24, -24)  # type: QRectF
        pen = QPen(self.__m_background.lighter(260), 1.5, Qt.DashLine)  # type: QPen
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 16, 16)
        font = QFont(self.font())  # type: QFont
        font.setPointSizeF(12)
        p.setFont(font)
        p.setPen(self.__m_background.lighter(400))
        p.drawText(r, Qt.AlignCenter | Qt.TextWordWrap, self.__m_placeholderText)

    # ---------- Properties ----------
    frame = pyqtProperty(QImage, fget=getFrame, fset=setFrame)  # type: pyqtProperty
    processor = pyqtProperty(object, fget=getProcessor, fset=setProcessor)  # type: pyqtProperty
    zoom = pyqtProperty(float, fget=getZoom, fset=setZoom, notify=zoomChanged)  # type: pyqtProperty
    minZoom = pyqtProperty(float, fget=getMinZoom, fset=setMinZoom)  # type: pyqtProperty
    maxZoom = pyqtProperty(float, fget=getMaxZoom, fset=setMaxZoom)  # type: pyqtProperty
    zoomStep = pyqtProperty(float, fget=getZoomStep, fset=setZoomStep)  # type: pyqtProperty
    showGrid = pyqtProperty(bool, fget=isShowGrid, fset=setShowGrid)  # type: pyqtProperty
    gridMinZoom = pyqtProperty(float, fget=getGridMinZoom, fset=setGridMinZoom)  # type: pyqtProperty
    gridColor = pyqtProperty(QColor, fget=getGridColor, fset=setGridColor)  # type: pyqtProperty
    showCrosshair = pyqtProperty(bool, fget=isShowCrosshair, fset=setShowCrosshair)  # type: pyqtProperty
    crosshairColor = pyqtProperty(QColor, fget=getCrosshairColor, fset=setCrosshairColor)  # type: pyqtProperty
    invertColors = pyqtProperty(bool, fget=isInvertColors, fset=setInvertColors)  # type: pyqtProperty
    panEnabled = pyqtProperty(bool, fget=isPanEnabled, fset=setPanEnabled)  # type: pyqtProperty
    showZoomBadge = pyqtProperty(bool, fget=isShowZoomBadge, fset=setShowZoomBadge)  # type: pyqtProperty
    background = pyqtProperty(QColor, fget=getBackground, fset=setBackground)  # type: pyqtProperty
    placeholderText = pyqtProperty('QString', fget=getPlaceholderText, fset=setPlaceholderText)  # type: pyqtProperty
