# -*- coding: utf-8 -*-
"""
MagnifierViewWidget: displays a frame with adjustable magnification.
- Only the visible crop of the frame is upscaled, straight to the on-screen size (HiDPI aware), through an
  optional processor callable(QImage crop, QSize target) -> QImage, so any upscaler can be plugged in.
- Processed output is cached per (frame, crop, size), hover/grid repaints cost nothing extra.
- Wheel zooms around the cursor, drag pans, double-click fits the frame into the view.
- Pixel grid at high zoom, hovered-pixel highlight, crosshair, colour inversion and an animated zoom badge.
- pixelHovered(QPoint, QColor) reports the source pixel and its colour under the mouse; pixelClicked on a click.
- Eyedropper (pickMode): a bubble shows the color of the ZOOMED image under the cursor (displayedColorAt), and a
  click emits colorPicked(source pixel, displayed color, source color) instead of panning.
- Annotations: boxes, labels, points and privacy blur (pixelation) in source coordinates, plus an optional
  frame-aligned ARGB overlay image (e.g. a color-detection mask), drawn above the magnified image. With
  setFrameOrigin() and an annotation origin, annotations computed on an older frame stay locked onto the screen
  content while the captured area moves (follow-cursor mode).
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
    pixelClicked = pyqtSignal(QPoint, QColor)  # type: pyqtSignal
    colorPicked = pyqtSignal(QPoint, QColor, QColor)  # type: pyqtSignal  # source pixel, displayed color, source color
    pickHovered = pyqtSignal(QColor, QColor)  # type: pyqtSignal  # displayed color, source color (pick mode)

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
        :param showAnnotations: (bool) Draw annotations and the overlay image.
        :param pickMode: (bool) Eyedropper: clicks emit colorPicked instead of panning.
        :param colorFormatter: (callable | None) QColor -> str: text of the eyedropper bubble (None = #RRGGBB).
        :param background: QColor | Qt.GlobalColor | int | str
        :param placeholderText: str | unicode | QString
        :param zoomChanged: callable | None
        :param pixelHovered: callable | None
        :param pixelClicked: callable | None
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
        showAnnotations = kwargs.pop('showAnnotations', True)  # type: bool
        pickMode = kwargs.pop('pickMode', False)  # type: bool
        colorFormatter = kwargs.pop('colorFormatter', None)  # type: callable | None
        background = kwargs.pop('background', '#15161C')  # type: QColor
        placeholderText = kwargs.pop('placeholderText', 'No image')  # type: str
        zoomChanged = kwargs.pop('zoomChanged', None)  # type: callable | None
        pixelHovered = kwargs.pop('pixelHovered', None)  # type: callable | None
        pixelClicked = kwargs.pop('pixelClicked', None)  # type: callable | None
        super(MagnifierViewWidget, self).__init__(*args, **kwargs)
        if callable(pixelClicked):
            self.pixelClicked.connect(pixelClicked)
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
        self.__m_showAnnotations = bool(showAnnotations)  # type: bool
        self.__m_pickMode = bool(pickMode)  # type: bool
        self.__m_colorFormatter = colorFormatter if callable(colorFormatter) else None
        self.__m_bubbleColor = QColor()  # type: QColor  # color given by the application (setBubbleColor)
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
        self.__m_cacheTarget = QRectF()  # type: QRectF  # Where the zoomed image was last drawn.
        # Annotations.
        self.__m_annotations = []  # type: list
        self.__m_annotationSize = QSize()  # type: QSize
        self.__m_overlayImage = QImage()  # type: QImage
        self.__m_annotationOrigin = None  # type: list | None  # [x, y, dpr] screen position of the analysed frame
        self.__m_frameOrigin = None  # type: list | None  # [x, y, dpr] screen position of the shown frame
        # Interaction.
        self.__m_pressPos = None  # type: QPoint | None
        self.__m_hover = QPoint(-1, -1)  # type: QPoint
        self.__m_dragFrom = None  # type: QPointF | None
        # Zoom badge animation.
        self.__m_badgeOpacity = 0.0  # type: float
        self.__m_toastText = ''  # type: str
        self.__m_toastColor = QColor()  # type: QColor
        self.__m_toastOpacity = 0.0  # type: float
        self.__m_toastClock = QElapsedTimer()  # type: QElapsedTimer
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
        if self.__m_badgeOpacity > 0.0:
            t = self.__m_badgeClock.elapsed()  # type: int
            hold, fade = 700, 450  # type: int, int
            self.__m_badgeOpacity = 1.0 if t < hold else max(0.0, 1.0 - (t - hold) / float(fade))  # type: float
        if self.__m_toastOpacity > 0.0:
            t = self.__m_toastClock.elapsed()  # type: int
            self.__m_toastOpacity = 1.0 if t < 1100 else max(0.0, 1.0 - (t - 1100) / 400.0)  # type: float
        if self.__m_badgeOpacity <= 0.0 and self.__m_toastOpacity <= 0.0:
            self.__m_badgeTimer.stop()
        self.update()

    def _annotationTransform(self):
        """
        Annotation pixels -> pixels of the shown frame: frameX = annX * ax + dx.
        With both origins known, annotations are screen-locked: (ax, dx) come from the two frames' screen positions
        and pixels-per-point (correct even when the captured area changed size); otherwise the annotation frame
        size is scaled to the shown frame.
        :return: (tuple[float, float, float, float]) ax, ay, dx, dy.
        """
        a, o, f = self.__m_annotationOrigin, self.__m_frameOrigin, self.__m_frame
        if a and o and float(a[2]) > 0:
            k = float(o[2]) / float(a[2])  # type: float
            return k, k, (float(a[0]) - float(o[0])) * float(o[2]), (float(a[1]) - float(o[1])) * float(o[2])
        size = self.__m_annotationSize  # type: QSize
        return (f.width() / float(size.width()) if size.width() > 0 else 1.0,
                f.height() / float(size.height()) if size.height() > 0 else 1.0, 0.0, 0.0)

    def _frameToView(self, crop, off, rect, ax, ay, shift=(0.0, 0.0)):
        """
        :param crop: QRect
        :param off: QPointF
        :param rect: (list[float]) [x, y, w, h] in annotation-source pixels.
        :param ax: (float | int) Annotation -> frame scale (x).
        :param ay: (float | int) Annotation -> frame scale (y).
        :param shift: (tuple[float, float]) Annotation -> frame offset in frame px.
        :return: QRectF
        """
        z = self.__m_zoom  # type: float
        return QRectF(off.x() + (rect[0] * ax + shift[0] - crop.x()) * z,
                      off.y() + (rect[1] * ay + shift[1] - crop.y()) * z, rect[2] * ax * z, rect[3] * ay * z)

    def _paintOverlayImage(self, p, crop, target):
        """
        Draw only the visible part of the (frame-aligned, possibly lower resolution) overlay image.
        :param p: QPainter
        :param crop: QRect
        :param target: QRectF
        :return:
        """
        ov, f = self.__m_overlayImage, self.__m_frame  # type: QImage, QImage
        ax, ay, dx, dy = self._annotationTransform()
        size = self.__m_annotationSize  # type: QSize
        kx = (size.width() if size.width() > 0 else f.width()) / float(ov.width()) * ax  # type: float  # mask -> frame
        ky = (size.height() if size.height() > 0 else f.height()) / float(ov.height()) * ay  # type: float
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.drawImage(target, ov, QRectF((crop.x() - dx) / kx, (crop.y() - dy) / ky, crop.width() / kx,
                                       crop.height() / ky))
        p.restore()

    def _paintAnnotations(self, p, crop, off):
        """
        :param p: QPainter
        :param crop: QRect
        :param off: QPointF
        :return:
        """
        f = self.__m_frame  # type: QImage
        ax, ay, dx, dy = self._annotationTransform()
        shift = (dx, dy)  # type: tuple
        view = QRectF(self.rect())  # type: QRectF
        font = QFont(self.font())  # type: QFont
        font.setPointSizeF(8.5)
        font.setBold(True)
        fm = QFontMetrics(font)  # type: QFontMetrics
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setFont(font)
        for a in self.__m_annotations:
            rect = a.get('rect')
            if not rect or len(rect) != 4:
                continue
            r = self._frameToView(crop, off, rect, ax, ay, shift)  # type: QRectF
            if not r.intersects(view):
                continue
            color = QColor(a.get('color', '#FFD400'))  # type: QColor
            if a.get('style') == 'blur':
                src = QRect(int(rect[0] * ax + dx), int(rect[1] * ay + dy), max(1, int(rect[2] * ax)),
                            max(1, int(rect[3] * ay))).intersected(f.rect())  # type: QRect
                if not src.isEmpty():
                    cells = max(1, int(a.get('blocks', 8)))  # type: int  # Pixelation blocks across.
                    small = f.copy(src).scaled(cells, max(1, int(cells * src.height() / float(src.width()))),
                                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)  # type: QImage
                    p.setRenderHint(QPainter.SmoothPixmapTransform, False)
                    p.drawImage(self._frameToView(crop, off, [(src.x() - dx) / ax, (src.y() - dy) / ay,
                                                              src.width() / ax, src.height() / ay], ax, ay, shift),
                                small, QRectF(0, 0, small.width(), small.height()))
                continue
            pen = QPen(QColor(0, 0, 0, 150), 4)  # type: QPen
            p.setBrush(Qt.NoBrush)
            p.setPen(pen)
            p.drawRect(r)
            p.setPen(QPen(color, 2))
            p.drawRect(r)
            for pt in a.get('points', []) or []:
                c = QPointF(off.x() + (pt[0] * ax + dx - crop.x()) * self.__m_zoom,
                            off.y() + (pt[1] * ay + dy - crop.y()) * self.__m_zoom)  # type: QPointF
                p.setPen(QPen(QColor(0, 0, 0, 160), 1))
                p.setBrush(color)
                p.drawEllipse(c, 3.0, 3.0)
            label = u'{}'.format(a.get('label', '') or '')  # type: str
            if label:
                tw = fm.horizontalAdvance(label) if hasattr(fm, 'horizontalAdvance') else fm.width(label)  # type: int
                tag = QRectF(r.left(), r.top() - fm.height() - 4, tw + 10, fm.height() + 4)  # type: QRectF
                if tag.top() < 0:
                    tag.moveTop(r.top() + 2)
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(tag, 3, 3)
                p.setPen(Qt.black if color.lightnessF() > 0.55 else Qt.white)
                p.drawText(tag, Qt.AlignCenter, label)
        p.restore()

    # ---------- Eyedropper ----------
    def displayedColorAt(self, pos, size=1):
        """
        Color of the ZOOMED image as it is drawn (after upscaling, sharpening, inversion; without annotations).
        :param pos: (QPoint | QPointF) Widget position.
        :param size: (int) Average of size x size displayed pixels (1, 3, 5...).
        :return: (QColor) Invalid outside the image.
        """
        img, t = self.__m_cacheImage, self.__m_cacheTarget  # type: QImage, QRectF
        if img.isNull() or t.isEmpty() or not t.contains(QPointF(pos)):
            return QColor()
        x = int((pos.x() - t.left()) * img.width() / t.width())  # type: int
        y = int((pos.y() - t.top()) * img.height() / t.height())  # type: int
        half = max(0, int(size) // 2)  # type: int
        r = g = b = n = 0  # type: int
        for yy in range(max(0, y - half), min(img.height(), y + half + 1)):
            for xx in range(max(0, x - half), min(img.width(), x + half + 1)):
                c = QColor(img.pixel(xx, yy))  # type: QColor
                r, g, b, n = r + c.red(), g + c.green(), b + c.blue(), n + 1
        return QColor(r // n, g // n, b // n) if n else QColor()

    def _sourcePixelAt(self, pos):
        """
        :param pos: QPoint
        :return: (QPoint) Source pixel under a widget position, (-1, -1) outside the frame.
        """
        s = self.mapToSource(QPointF(pos))  # type: QPointF
        ix, iy = int(floor(s.x())), int(floor(s.y()))  # type: int, int
        if 0 <= ix < self.__m_frame.width() and 0 <= iy < self.__m_frame.height():
            return QPoint(ix, iy)
        return QPoint(-1, -1)

    def _paintPickBubble(self, p):
        """
        Eyedropper bubble next to the cursor: color swatch + code (colorFormatter, default #RRGGBB).
        :param p: QPainter
        :return:
        """
        color = self.__m_bubbleColor if self.__m_bubbleColor.isValid() else self.displayedColorAt(self.__m_hover)
        if not color.isValid():
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        c = QPointF(self.__m_hover)  # type: QPointF
        p.setPen(QPen(QColor(0, 0, 0, 200), 3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, 9, 9)
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.5))
        p.drawEllipse(c, 9, 9)
        font = QFont(self.font())  # type: QFont
        font.setPointSizeF(10)
        font.setBold(True)
        p.setFont(font)
        fm = QFontMetrics(font)  # type: QFontMetrics
        try:
            text = u'{}'.format(self.__m_colorFormatter(color)) if self.__m_colorFormatter else u'{}'.format(color.name()).upper()
        except Exception:
            text = u'{}'.format(color.name()).upper()  # type: str
        tw = fm.horizontalAdvance(text) if hasattr(fm, 'horizontalAdvance') else fm.width(text)  # type: int
        box = QRectF(c.x() + 18, c.y() + 18, tw + 48, 34)  # type: QRectF
        if box.right() > self.width() - 4:
            box.moveRight(c.x() - 18)
        if box.bottom() > self.height() - 4:
            box.moveBottom(c.y() - 18)
        path = QPainterPath()  # type: QPainterPath
        path.addRoundedRect(box, 9, 9)
        p.fillPath(path, QColor(18, 20, 28, 230))
        p.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
        p.setBrush(color)
        p.drawRoundedRect(QRectF(box.left() + 8, box.top() + 7, 20, 20), 5, 5)
        p.setPen(QColor(240, 242, 248))
        p.drawText(QRectF(box.left() + 36, box.top(), tw + 8, box.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.restore()

    def zoneAt(self, pixel):
        """
        :param pixel: (QPoint) Source pixel of the frame.
        :return: (str | unicode | QString) Label of the annotation (color zone) containing it, '' if none.
        """
        if not self.__m_annotations or not self.__m_showAnnotations or pixel is None or pixel.x() < 0:
            return ''
        ax, ay, dx, dy = self._annotationTransform()
        x, y = (pixel.x() + 0.5 - dx) / ax, (pixel.y() + 0.5 - dy) / ay  # type: float, float  # annotation px
        for ann in self.__m_annotations:
            rx, ry, rw, rh = ann.get('rect', [0, 0, 0, 0])
            if ann.get('label') and rx <= x < rx + rw and ry <= y < ry + rh:
                return u'{}'.format(ann['label'])
        return ''

    def setBubbleColor(self, color):
        """
        Color shown by the eyedropper bubble (the application's live color: sample size / pick source applied).
        :param color: (QColor | None) None = the displayed pixel under the cursor.
        :return:
        """
        self.__m_bubbleColor = QColor(color) if color is not None else QColor()  # type: QColor
        self.update()

    def getColorFormatter(self):
        """
        :return: callable | None
        """
        return self.__m_colorFormatter

    @pyqtSlot(object)
    def setColorFormatter(self, colorFormatter):
        """
        :param colorFormatter: (callable | None) QColor -> str.
        :return:
        """
        self.__m_colorFormatter = colorFormatter if callable(colorFormatter) else None
        self.update()

    def isPickMode(self):
        """
        :return: bool
        """
        return self.__m_pickMode

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setPickMode(self, pickMode):
        """
        Eyedropper: clicks pick colors (colorPicked) instead of panning; a bubble shows the color under the cursor.
        :param pickMode: bool
        :return:
        """
        self.__m_pickMode = bool(pickMode)  # type: bool
        self.__m_dragFrom = None
        self.update()

    # ---------- Annotations API ----------
    def getAnnotations(self):
        """
        :return: (list[dict]) Current annotations.
        """
        return list(self.__m_annotations)

    def setAnnotations(self, annotations, sourceSize=None, origin=None):
        """
        Draw boxes / labels / points / privacy blur over the frame.
        :param annotations: (list[dict]) Items {'rect': [x, y, w, h], 'color': '#RRGGBB', 'label': str,
            'style': 'box' | 'blur', 'points': [[x, y], ...], 'blocks': int} in source-frame pixels.
        :param sourceSize: (QSize | None) Size of the frame the coordinates refer to (they are rescaled to the
            current frame); None = the current frame.
        :param origin: (list | None) [x, y, dpr] screen position of that frame (see setFrameOrigin()).
        :return:
        """
        self.__m_annotations = list(annotations or [])  # type: list
        self.__m_annotationOrigin = list(origin) if origin else None
        self.__m_annotationSize = QSize(sourceSize) if sourceSize is not None else QSize(self.__m_frame.size())
        self.update()

    @pyqtSlot(QPoint, float)
    def setFrameOrigin(self, origin, dpr=1.0):
        """
        Screen position of the frames passed to setFrame() (top-left, device independent) and their pixel ratio.
        :param origin: QPoint
        :param dpr: (float | int) Frame pixels per screen point.
        :return:
        """
        self.__m_frameOrigin = [origin.x(), origin.y(), float(dpr)] if origin is not None else None

    @pyqtSlot()
    def clearAnnotations(self):
        """
        :return:
        """
        self.__m_annotations = []  # type: list
        self.__m_overlayImage = QImage()  # type: QImage
        self.update()

    def getOverlayImage(self):
        """
        :return: QImage
        """
        return self.__m_overlayImage

    @pyqtSlot(QImage)
    def setOverlayImage(self, overlayImage):
        """
        :param overlayImage: (QImage) ARGB image aligned with the whole frame (any resolution), null = none.
        :return:
        """
        self.__m_overlayImage = QImage() if overlayImage is None else overlayImage  # type: QImage
        self.update()

    def isShowAnnotations(self):
        """
        :return: bool
        """
        return self.__m_showAnnotations

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setShowAnnotations(self, showAnnotations):
        """
        :param showAnnotations: bool
        :return:
        """
        self.__m_showAnnotations = bool(showAnnotations)  # type: bool
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

    def mapFromSource(self, pos):
        """
        Inverse of mapToSource().
        :param pos: (QPointF) Position in source (frame) pixels.
        :return: (QPointF) View position.
        """
        if self.__m_frame.isNull():
            return QPointF(-1, -1)
        crop, off = self._layout()
        z = self.__m_zoom  # type: float
        return QPointF(off.x() + (pos.x() - crop.x()) * z, off.y() + (pos.y() - crop.y()) * z)

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
        if e.button() == Qt.LeftButton:
            self.__m_pressPos = e.pos()  # type: QPoint
        if e.button() == Qt.LeftButton and self.__m_panEnabled and not self.__m_frame.isNull() and \
                not self.__m_pickMode:
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
        if self.__m_pickMode:
            sp = self._sourcePixelAt(e.pos())  # type: QPoint
            self.pickHovered.emit(self.displayedColorAt(e.pos()),
                                  QColor(self.__m_frame.pixel(sp)) if sp.x() >= 0 else QColor())
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
        if e.button() == Qt.LeftButton and self.__m_pressPos is not None:
            moved = (e.pos() - self.__m_pressPos).manhattanLength()  # type: int
            self.__m_pressPos = None
            if moved <= 3 and not self.__m_frame.isNull():  # A click, not a pan.
                sp = self._sourcePixelAt(e.pos())  # type: QPoint
                if sp.x() >= 0 and self.__m_pickMode:
                    self.colorPicked.emit(sp, self.displayedColorAt(e.pos()), QColor(self.__m_frame.pixel(sp)))
                elif sp.x() >= 0:
                    self.pixelClicked.emit(sp, QColor(self.__m_frame.pixel(sp)))
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
        self.__m_cacheTarget = QRectF(target)  # type: QRectF
        if self.__m_showAnnotations:
            if not self.__m_overlayImage.isNull():
                self._paintOverlayImage(p, crop, target)
            if self.__m_annotations:
                self._paintAnnotations(p, crop, off)
        if self.__m_showGrid and z >= self.__m_gridMinZoom:
            self._paintGrid(p, crop, off, target)
        self._paintHoverPixel(p, crop, off)
        if self.__m_showCrosshair:
            self._paintCrosshair(p)
        if self.__m_badgeOpacity > 0.0:
            self._paintBadge(p)
        if self.__m_pickMode and self.rect().contains(self.__m_hover):
            self._paintPickBubble(p)
        if self.__m_toastOpacity > 0.0:
            self._paintToast(p, QRectF(self.rect()))
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
        text = u'{:.2f}\u00d7'.format(self.__m_zoom)  # type: str
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

    def _paintToast(self, p, area):
        """
        Confirmation bubble (e.g. "#3A7BD5 copied") with an optional color swatch.
        :param p: QPainter
        :param area: (QRectF) Area the bubble is centred in (top).
        :return:
        """
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setOpacity(self.__m_toastOpacity)
        font = QFont(self.font())  # type: QFont
        font.setPointSizeF(10.5)
        font.setBold(True)
        p.setFont(font)
        fm = QFontMetrics(font)  # type: QFontMetrics
        text = self.__m_toastText  # type: str
        tw = fm.horizontalAdvance(text) if hasattr(fm, 'horizontalAdvance') else fm.width(text)  # type: int
        swatch = 16 if self.__m_toastColor.isValid() else 0  # type: int
        w = tw + 28 + (swatch + 8 if swatch else 0)  # type: float
        box = QRectF(area.center().x() - w / 2.0, area.top() + 16, w, fm.height() + 14)  # type: QRectF
        path = QPainterPath()  # type: QPainterPath
        path.addRoundedRect(box, box.height() / 2.0, box.height() / 2.0)
        p.fillPath(path, QColor(18, 20, 28, 225))
        x = box.left() + 14  # type: float
        if swatch:
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
            p.setBrush(self.__m_toastColor)
            p.drawEllipse(QRectF(x, box.center().y() - swatch / 2.0, swatch, swatch))
            x += swatch + 8
        p.setPen(QColor(240, 242, 248))
        p.drawText(QRectF(x, box.top(), tw + 4, box.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.restore()

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def showToast(self, text, color=None):
        """
        Show a short animated confirmation (fades out after about 1.5 s).
        :param text: str | unicode | QString
        :param color: (QColor | str | None) Swatch shown before the text.
        :return:
        """
        self.__m_toastText = u'{}'.format(text)  # type: str
        self.__m_toastColor = QColor(color) if color is not None else QColor()  # type: QColor
        self.__m_toastClock.start()
        self.__m_toastOpacity = 1.0  # type: float
        if not self.__m_badgeTimer.isActive():
            self.__m_badgeTimer.start(16)
        self.update()

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
    showAnnotations = pyqtProperty(bool, fget=isShowAnnotations, fset=setShowAnnotations)  # type: pyqtProperty
    pickMode = pyqtProperty(bool, fget=isPickMode, fset=setPickMode)  # type: pyqtProperty
    overlayImage = pyqtProperty(QImage, fget=getOverlayImage, fset=setOverlayImage)  # type: pyqtProperty
    annotations = pyqtProperty(list, fget=getAnnotations, fset=setAnnotations)  # type: pyqtProperty
    background = pyqtProperty(QColor, fget=getBackground, fset=setBackground)  # type: pyqtProperty
    placeholderText = pyqtProperty('QString', fget=getPlaceholderText, fset=setPlaceholderText)  # type: pyqtProperty
    colorFormatter = pyqtProperty(object, fget=getColorFormatter, fset=setColorFormatter)  # type: pyqtProperty
