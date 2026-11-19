# -*- coding: utf-8 -*-
"""
ZoomOverlay: a click-through, focus-less, always-on-top magnifier lens for use over games and other
full-screen applications.
- Never takes the keyboard focus and lets every mouse click through to the application below.
- Target: screen center (e.g. a game crosshair), a pinned point, or the mouse cursor.
- Placement: on the target (scope style) or in a screen corner (picture-in-picture).
- Circle or rounded-rectangle lens, crosshair, border, opacity, animated zoom badge.
- Frames are pushed with setFrame(); sourceRect() tells the capture code which global rect to grab.
- Windows 10 2004+: the lens hides itself from screen capture so it can sit on top of what it magnifies,
  and it re-asserts its top-most position every second (borderless games like to climb above it).
- The lens is a constant-alpha layered window (shape from a window mask, no per-pixel alpha): Windows
  refuses to hide per-pixel-alpha (UpdateLayeredWindow) windows from capture with ERROR_NOT_ENOUGH_MEMORY.
- externalSource: when frames come from a capture that can never contain the lens (e.g. a direct capture of
  the game window), scope mode works without hiding the lens at all.
- Self-capture guard: when the lens covers what it magnifies, it first checks with a tiny probe pattern that
  it really is invisible to screen capture. If it is not (the OS ignored the exclusion), it moves to a free
  screen corner instead of showing a "hall of mirrors", and reports why (captureStatusChanged).
"""
from ManyQt.QtCore import Qt, QTimer, QElapsedTimer, QRect, QRectF, QPoint, QPointF, QSize, QLineF, pyqtSignal, \
    pyqtSlot, pyqtProperty, Q_ENUMS, qVersion
from ManyQt.QtGui import QPainter, QColor, QPen, QImage, QFont, QFontMetrics, QPainterPath, QRegion, QCursor, \
    QGuiApplication
from ManyQt.QtWidgets import QWidget
from sys import platform, getwindowsversion
from enum import IntEnum


def clamp(x, a, b):
    """
    :param x: float | int
    :param a: float | int
    :param b: float | int
    :return: float | int
    """
    return a if x < a else b if x > b else x


def screenAtPoint(point):
    """
    :param point: QPoint
    :return: QScreen
    """
    screen = QGuiApplication.screenAt(point) if hasattr(QGuiApplication, 'screenAt') else None
    return screen if screen is not None else QGuiApplication.primaryScreen()


WDA_NONE = 0x00  # type: int
WDA_EXCLUDEFROMCAPTURE = 0x11  # type: int


def _user32():
    """
    Private user32 handle with its own prototypes (does not clash with other modules' argtypes).
    :return: ctypes.WinDLL
    """
    from ctypes import WinDLL, POINTER, c_int, c_long, c_ubyte
    from ctypes.wintypes import HWND, BOOL, DWORD
    u = WinDLL('user32', use_last_error=True)
    u.SetWindowDisplayAffinity.argtypes = [HWND, DWORD]
    u.SetWindowDisplayAffinity.restype = BOOL
    u.GetWindowDisplayAffinity.argtypes = [HWND, POINTER(DWORD)]
    u.GetWindowDisplayAffinity.restype = BOOL
    u.GetWindowLongW.argtypes = [HWND, c_int]
    u.GetWindowLongW.restype = c_long
    u.SetWindowLongW.argtypes = [HWND, c_int, c_long]
    u.SetWindowLongW.restype = c_long
    u.SetLayeredWindowAttributes.argtypes = [HWND, DWORD, c_ubyte, DWORD]
    u.SetLayeredWindowAttributes.restype = BOOL
    u.GetLayeredWindowAttributes.argtypes = [HWND, POINTER(DWORD), POINTER(c_ubyte), POINTER(DWORD)]
    u.GetLayeredWindowAttributes.restype = BOOL
    return u


def winGetDisplayAffinity(widget):
    """
    :param widget: QWidget
    :return: (int | None) Current display affinity of the window, None when unavailable.
    """
    if platform != 'win32':
        return None
    try:
        from ctypes.wintypes import DWORD, HWND
        from ctypes import byref
        value = DWORD(0)
        if _user32().GetWindowDisplayAffinity(HWND(int(widget.winId())), byref(value)):
            return int(value.value)
    except Exception:
        pass
    return None


def winSetCaptureExcluded(widget, exclude=True, forceLayered=True, alpha=255):
    """
    Hide (or show again) a top-level window from every screen-capture API (Windows 10 2004+).
    Strategy: keep an affinity that is already set; set it; if Windows refuses (ERROR_NOT_ENOUGH_MEMORY is
    returned for some layered windows), retry with WS_EX_LAYERED removed for the call, then restore it.
    :param widget: QWidget
    :param exclude: bool
    :param forceLayered: (bool) Older Windows builds only honor the exclusion for WS_EX_LAYERED windows.
    :param alpha: (int) Constant window alpha restored with SetLayeredWindowAttributes after a retry.
    :return: (tuple[bool, str | unicode | QString]) Success and, on failure, a human-readable reason.
    """
    if platform != 'win32':
        return False, 'only Windows can hide a window from screen capture'
    try:
        from ctypes import byref, c_ubyte, get_last_error
        from ctypes.wintypes import HWND, DWORD
        build = getwindowsversion().build  # type: int
        if exclude and build < 19041:
            return False, 'needs Windows 10 version 2004 (build 19041) or newer, this is build {}'.format(build)
        u = _user32()
        hwnd = HWND(int(widget.winId()))
        GWL_EXSTYLE, WS_EX_LAYERED, LWA_ALPHA = -20, 0x80000, 0x2
        wanted = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE  # type: int

        def current():
            """
            :return: int | None
            """
            value = DWORD(0)
            return int(value.value) if u.GetWindowDisplayAffinity(hwnd, byref(value)) else None

        if current() == wanted:
            return True, ''
        style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)  # type: int
        if exclude and forceLayered and not style & WS_EX_LAYERED:
            u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
            u.SetLayeredWindowAttributes(hwnd, 0, int(alpha), LWA_ALPHA)  # Keep it visible on screen.
            style |= WS_EX_LAYERED
        if u.SetWindowDisplayAffinity(hwnd, wanted):
            return True, ''
        error = get_last_error()  # type: int
        if style & WS_EX_LAYERED:
            # Retry as a plain window, then make it layered again (needed for click-through).
            u.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_LAYERED)
            ok = bool(u.SetWindowDisplayAffinity(hwnd, wanted))  # type: bool
            u.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            u.SetLayeredWindowAttributes(hwnd, 0, int(alpha), LWA_ALPHA)
            if ok and current() in (None, wanted):
                return True, ''
        perPixel = ''  # type: str
        if style & WS_EX_LAYERED:
            key, a, flags = DWORD(0), c_ubyte(0), DWORD(0)
            if not u.GetLayeredWindowAttributes(hwnd, byref(key), byref(a), byref(flags)):
                perPixel = ', per-pixel-alpha window'  # type: str
        return False, 'SetWindowDisplayAffinity failed (Windows error {}, build {}{})'.format(error, build, perPixel)
    except Exception as e:
        return False, 'capture exclusion unavailable: {}'.format(e)


def winMakeOverlay(widget):
    """
    Windows: no activation on click/show, click-through, keep top-most.
    :param widget: QWidget
    :return:
    """
    if platform != 'win32':
        return
    try:
        from ctypes import windll
        from ctypes.wintypes import HWND
        user32 = windll.user32
        hwnd = HWND(int(widget.winId()))
        GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED = -20, 0x20, 0x80000
        WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)  # type: int
        style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        if style & WS_EX_LAYERED:  # Qt made it layered (translucent / transparent for input).
            style |= WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        winKeepTopMost(widget)
    except Exception:
        pass


def winKeepTopMost(widget):
    """
    :param widget: QWidget
    :return: (bool) True if handled natively.
    """
    if platform != 'win32':
        return False
    try:
        from ctypes.wintypes import HWND, UINT
        from ctypes import c_int, windll
        user32 = windll.user32
        user32.SetWindowPos.argtypes = [HWND, HWND, c_int, c_int, c_int, c_int, UINT]
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
        return bool(user32.SetWindowPos(
            HWND(int(widget.winId())), HWND(-1), 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE))
    except Exception:
        return False


class ZoomOverlay(QWidget):
    """
    ZoomOverlay class.
    """

    class Target(IntEnum):
        """
        Target enumeration class: what is magnified.
        """
        Center = 0  # type: int
        Point = 1  # type: int
        Cursor = 2  # type: int

    class Placement(IntEnum):
        """
        Placement enumeration class: where the lens is drawn.
        """
        OnTarget = 0  # type: int
        TopLeft = 1  # type: int
        TopRight = 2  # type: int
        BottomLeft = 3  # type: int
        BottomRight = 4  # type: int

    class Shape(IntEnum):
        """
        Shape enumeration class.
        """
        Circle = 0  # type: int
        RoundedRect = 1  # type: int

    Center = Target.Center  # type: int
    Point = Target.Point  # type: int
    Cursor = Target.Cursor  # type: int
    OnTarget = Placement.OnTarget  # type: int
    TopLeft = Placement.TopLeft  # type: int
    TopRight = Placement.TopRight  # type: int
    BottomLeft = Placement.BottomLeft  # type: int
    BottomRight = Placement.BottomRight  # type: int
    Circle = Shape.Circle  # type: int
    RoundedRect = Shape.RoundedRect  # type: int
    zoomChanged = pyqtSignal(float)  # type: pyqtSignal
    overlayToggled = pyqtSignal(bool)  # type: pyqtSignal
    sourceChanged = pyqtSignal()  # type: pyqtSignal
    captureStatusChanged = pyqtSignal('QString')  # type: pyqtSignal
    captureDetailChanged = pyqtSignal('QString')  # type: pyqtSignal
    PROBE_COLORS = (QColor(255, 0, 255), QColor(0, 255, 0))  # type: tuple[QColor, QColor]
    PROBE_CELL = 8  # type: int  # Probe = 2 x 2 cells of this size (px) at the lens center.
    PROBE_DELAY_MS = 150  # type: int  # Time for the compositor to put the probe on screen.
    FALLBACK_ORDER = (Placement.TopRight, Placement.TopLeft, Placement.BottomRight, Placement.BottomLeft)  # type: tuple

    def __init__(self, *args, **kwargs):
        """
        :param zoom: (float | int) Magnification, 1 .. 16.
        :param lensSize: (QSize) Lens size in px.
        :param target: ZoomOverlay.Target | int
        :param targetPoint: (QPoint) Global point used by Target.Point.
        :param placement: ZoomOverlay.Placement | int
        :param shape: ZoomOverlay.Shape | int
        :param processor: (callable | None) f(QImage, QSize) -> QImage upscaler.
        :param borderColor: QColor | Qt.GlobalColor | int | str
        :param borderWidth: float | int
        :param showCrosshair: bool
        :param crosshairColor: QColor | Qt.GlobalColor | int | str
        :param lensOpacity: (float | int) 0.2 .. 1.0
        :param margin: (int) Distance from the screen edges for corner placements.
        :param excludeFromCapture: (bool) Windows: hide the lens from screen capture.
        :param externalSource: (bool) Frames never contain the lens (e.g. direct game-window capture).
        :param zoomChanged: callable | None
        :param overlayToggled: callable | None
        :param args: any
        :param kwargs: any
        """
        zoom = kwargs.pop('zoom', 2.5)  # type: float
        lensSize = kwargs.pop('lensSize', QSize(380, 380))  # type: QSize
        target = kwargs.pop('target', ZoomOverlay.Center)  # type: int
        targetPoint = kwargs.pop('targetPoint', QPoint())  # type: QPoint
        placement = kwargs.pop(
            'placement', ZoomOverlay.OnTarget if platform == 'win32' else ZoomOverlay.TopRight)  # type: int
        shape = kwargs.pop('shape', ZoomOverlay.Circle)  # type: int
        processor = kwargs.pop('processor', None)  # type: callable | None
        borderColor = kwargs.pop('borderColor', '#4F8BFF')  # type: QColor
        borderWidth = kwargs.pop('borderWidth', 3)  # type: float
        showCrosshair = kwargs.pop('showCrosshair', True)  # type: bool
        crosshairColor = kwargs.pop('crosshairColor', '#FF3B6B')  # type: QColor
        lensOpacity = kwargs.pop('lensOpacity', 1.0)  # type: float
        margin = kwargs.pop('margin', 32)  # type: int
        excludeFromCapture = kwargs.pop('excludeFromCapture', True)  # type: bool
        externalSource = kwargs.pop('externalSource', False)  # type: bool
        zoomChanged = kwargs.pop('zoomChanged', None)  # type: callable | None
        overlayToggled = kwargs.pop('overlayToggled', None)  # type: callable | None
        super(ZoomOverlay, self).__init__(*args, **kwargs)
        if callable(zoomChanged):
            self.zoomChanged.connect(zoomChanged)
        if callable(overlayToggled):
            self.overlayToggled.connect(overlayToggled)
        # Options.
        self.__m_zoom = clamp(float(zoom), 1.0, 16.0)  # type: float
        self.__m_lensSize = QSize(max(64, lensSize.width()), max(64, lensSize.height()))  # type: QSize
        self.__m_target = ZoomOverlay.Target(int(target))  # type: ZoomOverlay.Target
        self.__m_targetPoint = QPoint(targetPoint)  # type: QPoint
        self.__m_placement = ZoomOverlay.Placement(int(placement))  # type: ZoomOverlay.Placement
        self.__m_shape = ZoomOverlay.Shape(int(shape))  # type: ZoomOverlay.Shape
        self.__m_processor = processor if callable(processor) else None  # type: callable | None
        self.__m_borderColor = borderColor if isinstance(borderColor, QColor) else QColor(borderColor)  # type: QColor
        self.__m_borderWidth = max(0.0, float(borderWidth))  # type: float
        self.__m_showCrosshair = bool(showCrosshair)  # type: bool
        self.__m_crosshairColor = crosshairColor if isinstance(crosshairColor, QColor) else QColor(
            crosshairColor)  # type: QColor
        self.__m_lensOpacity = clamp(float(lensOpacity), 0.2, 1.0)  # type: float
        self.__m_margin = max(0, int(margin))  # type: int
        self.__m_excludeFromCapture = bool(excludeFromCapture)  # type: bool
        self.__m_externalSource = bool(externalSource)  # type: bool
        # State.
        self.__m_captureExcluded = False  # type: bool
        self.__m_captureStatus = 'unknown'  # type: str  # unknown | notNeeded | testing | excluded | failed
        self.__m_captureDetail = ''  # type: str
        self.__m_fallbackPlacement = None  # type: ZoomOverlay.Placement | None
        self.__m_probing = False  # type: bool
        self.__m_centerScreen = None  # type: QScreen | None
        self.__m_frame = QImage()  # type: QImage
        self.__m_serial = 0  # type: int
        self.__m_cacheKey = None  # type: tuple | None
        self.__m_cacheImage = QImage()  # type: QImage
        self.__m_badgeOpacity = 0.0  # type: float
        self.__m_badgeClock = QElapsedTimer()  # type: QElapsedTimer
        self.__m_badgeTimer = QTimer(self)  # type: QTimer
        self.__m_badgeTimer.timeout.connect(self._tick)
        self.__m_topTimer = QTimer(self)  # type: QTimer
        self.__m_topTimer.timeout.connect(self._keepOnTop)
        # Window flags: frameless, top-most, no taskbar entry, no focus, click-through.
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        if hasattr(Qt, 'WindowTransparentForInput'):
            flags |= Qt.WindowTransparentForInput
        if platform.startswith('linux'):
            flags |= Qt.X11BypassWindowManagerHint  # Stay above full-screen X11 windows, never focused.
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # No WA_TranslucentBackground: per-pixel alpha windows (UpdateLayeredWindow) cannot be hidden from
        # capture. The lens shape comes from a window mask instead.
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWindowOpacity(self.__m_lensOpacity)
        self.resize(self.__m_lensSize)
        if platform == 'win32' and self.__m_excludeFromCapture:
            self.winId()  # Create the native window now: the exclusion is most reliable before the first show.
            self.__m_captureExcluded, self.__m_captureDetail = winSetCaptureExcluded(
                self, alpha=int(round(self.__m_lensOpacity * 255)))

    # ---------- Helpers ----------
    def _lensPath(self, rect):
        """
        :param rect: QRectF
        :return: QPainterPath
        """
        path = QPainterPath()  # type: QPainterPath
        if self.__m_shape == ZoomOverlay.Circle:
            path.addEllipse(rect)
        else:
            r = min(rect.width(), rect.height()) * 0.12  # type: float
            path.addRoundedRect(rect, r, r)
        return path

    def _updateMask(self):
        """
        A window mask gives the lens its shape even without a compositor.
        :return:
        """
        if self.__m_shape == ZoomOverlay.Circle:
            self.setMask(QRegion(self.rect(), QRegion.Ellipse))
        else:
            poly = self._lensPath(QRectF(self.rect())).toFillPolygon().toPolygon()
            self.setMask(QRegion(poly))

    def _reposition(self):
        """
        :return:
        """
        geo = self.lensGeometry()  # type: QRect
        if geo != self.geometry():
            self.setGeometry(geo)

    def _reevaluate(self):
        """
        Placement-relevant option changed while visible: check again whether the lens is safe where it is.
        :return:
        """
        if self.isVisible():
            self.__m_captureStatus = 'unknown'  # type: str
            QTimer.singleShot(0, self._evaluateCapture)

    def _changed(self):
        """
        Geometry-affecting option changed.
        :return:
        """
        if self.isVisible():
            self._reposition()
        self.__m_cacheKey = None
        self.update()
        self.sourceChanged.emit()

    def _keepOnTop(self):
        """
        :return:
        """
        if not winKeepTopMost(self):
            self.raise_()
        if self.__m_captureExcluded and winGetDisplayAffinity(self) not in (None, WDA_EXCLUDEFROMCAPTURE):
            winSetCaptureExcluded(self, alpha=int(round(self.__m_lensOpacity * 255)))  # Put it back.

    def _setStatus(self, status, detail=''):
        """
        :param status: str | unicode | QString
        :param detail: str | unicode | QString
        :return:
        """
        self.__m_captureStatus = status  # type: str
        self.__m_captureDetail = detail  # type: str
        self.captureStatusChanged.emit(status)

    def _geometryFor(self, placement):
        """
        :param placement: ZoomOverlay.Placement
        :return: (QRect) Lens window rect for a given placement.
        """
        c = self.targetPos()  # type: QPoint
        g = screenAtPoint(c).geometry()  # type: QRect
        w, h, m = self.__m_lensSize.width(), self.__m_lensSize.height(), self.__m_margin  # type: int, int, int
        if placement == ZoomOverlay.OnTarget:
            x, y = c.x() - w // 2, c.y() - h // 2  # type: int, int
        else:
            x = g.left() + m if placement in (ZoomOverlay.TopLeft, ZoomOverlay.BottomLeft) else g.right() - m - w + 1
            y = g.top() + m if placement in (ZoomOverlay.TopLeft, ZoomOverlay.TopRight) else g.bottom() - m - h + 1
        x = int(clamp(x, g.left(), max(g.left(), g.right() - w + 1)))  # type: int
        y = int(clamp(y, g.top(), max(g.top(), g.bottom() - h + 1)))  # type: int
        return QRect(x, y, w, h)

    def _useFallback(self, detail):
        """
        The lens would capture itself: move it to the first screen corner that does not cover the source.
        :param detail: (str | unicode | QString)Why the exclusion is not possible.
        :return:
        """
        src = self.sourceRect()  # type: QRect
        fallback = ZoomOverlay.FALLBACK_ORDER[0]
        for pl in ZoomOverlay.FALLBACK_ORDER:
            if not self._geometryFor(pl).intersects(src):
                fallback = pl
                break
        self.__m_fallbackPlacement = fallback
        self.__m_frame = QImage()  # type: QImage  # Drop any frame that may contain the lens itself.
        self._reposition()
        self._setStatus('failed', detail)
        self.update()
        self.sourceChanged.emit()

    def _evaluateCapture(self):
        """
        Decide whether the requested placement is safe: runs after the native window is really shown.
        :return:
        """
        if not self.isVisible():
            return
        self.__m_fallbackPlacement = None
        if not self._geometryFor(self.__m_placement).intersects(self.sourceRect()):
            self._reposition()
            self._setStatus('notNeeded')
            return
        if self.__m_externalSource:
            self._reposition()
            self._setStatus('windowCapture')
            self.update()
            self.sourceChanged.emit()
            return
        if self.__m_excludeFromCapture:
            ok, detail = winSetCaptureExcluded(self, alpha=int(round(self.__m_lensOpacity * 255)))
            self.setWindowOpacity(self.__m_lensOpacity)  # Re-sync Qt after a possible style retry.
        else:
            ok, detail = False, 'hiding the lens from capture is turned off'
        self.__m_captureExcluded = ok  # type: bool
        if not ok:
            self._useFallback(detail)
            return
        self._reposition()
        self._startProbe()

    def _startProbe(self):
        """
        Paint a tiny 2 x 2 color pattern at the lens center, then check whether screen capture sees it.
        :return:
        """
        self.__m_probing = True  # type: bool
        self.__m_frame = QImage()  # type: QImage
        self._setStatus('testing')
        self.setWindowOpacity(1.0)
        self.repaint()
        QTimer.singleShot(ZoomOverlay.PROBE_DELAY_MS, self._finishProbe)

    def _probeRect(self):
        """
        :return: (QRect) Probe pattern rect in local coordinates.
        """
        cell = ZoomOverlay.PROBE_CELL  # type: int
        return QRect(self.width() // 2 - cell, self.height() // 2 - cell, cell * 2, cell * 2)

    def _probeSeenByCapture(self):
        """
        :return: (bool | None) True if the probe shows up in a screen grab, None if the grab failed.
        """
        local = self._probeRect()  # type: QRect
        topLeft = self.mapToGlobal(local.topLeft())  # type: QPoint
        screen = screenAtPoint(topLeft)
        sg = screen.geometry()  # type: QRect
        pm = screen.grabWindow(0, topLeft.x() - sg.x(), topLeft.y() - sg.y(), local.width(), local.height())
        if pm.isNull() or pm.width() < 2 or pm.height() < 2:
            return None
        img = pm.toImage()  # type: QImage
        hits = 0  # type: int
        for fx, fy, ci in ((0.25, 0.25, 0), (0.75, 0.25, 1), (0.25, 0.75, 1), (0.75, 0.75, 0)):
            col = QColor(img.pixel(int(fx * img.width()), int(fy * img.height())))  # type: QColor
            ref = ZoomOverlay.PROBE_COLORS[ci]  # type: QColor
            if abs(col.red() - ref.red()) <= 48 and abs(col.green() - ref.green()) <= 48 and \
                    abs(col.blue() - ref.blue()) <= 48:
                hits += 1
        return hits >= 3

    def _finishProbe(self):
        """
        :return:
        """
        if not self.__m_probing:
            return
        self.__m_probing = False  # type: bool
        self.setWindowOpacity(self.__m_lensOpacity)
        if not self.isVisible():
            return
        seen = self._probeSeenByCapture()  # type: bool | None
        if seen:
            self._useFallback('Windows accepted the request to hide the lens, but the lens still appears in '
                              'screen captures (build {})'.format(
                getwindowsversion().build if platform == 'win32' else '-'))
            return
        self._setStatus('excluded', '' if seen is False else 'could not be verified')
        self.update()
        self.sourceChanged.emit()

    def _showBadge(self):
        """
        :return:
        """
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
        self.__m_badgeOpacity = 1.0 if t < 800 else max(0.0, 1.0 - (t - 800) / 400.0)  # type: float
        if self.__m_badgeOpacity <= 0.0:
            self.__m_badgeTimer.stop()
        self.update()

    # ---------- Public API ----------
    def targetPos(self):
        """
        :return: (QPoint) Global point being magnified.
        """
        if self.__m_target == ZoomOverlay.Cursor:
            return QCursor.pos()
        if self.__m_target == ZoomOverlay.Point and not self.__m_targetPoint.isNull():
            return QPoint(self.__m_targetPoint)
        screen = self.__m_centerScreen or screenAtPoint(QCursor.pos())
        return screen.geometry().center()

    def sourceRect(self):
        """
        :return: (QRect) Global, device-independent rect that must be captured.
        """
        c = self.targetPos()  # type: QPoint
        w = max(2, int(round(self.__m_lensSize.width() / self.__m_zoom)))  # type: int
        h = max(2, int(round(self.__m_lensSize.height() / self.__m_zoom)))  # type: int
        return QRect(c.x() - w // 2, c.y() - h // 2, w, h)

    def lensGeometry(self):
        """
        :return: (QRect) Where the lens window goes (fallback corner included).
        """
        return self._geometryFor(self.getEffectivePlacement())

    def getEffectivePlacement(self):
        """
        :return: (ZoomOverlay.Placement) The placement in use: the requested one, or the safe fallback corner.
        """
        return self.__m_fallbackPlacement if self.__m_fallbackPlacement is not None else self.__m_placement

    def getCaptureStatus(self):
        """
        :return: (str | unicode | QString)unknown | notNeeded | testing | excluded | windowCapture | failed
        """
        return self.__m_captureStatus

    def isExternalSource(self):
        """
        :return: bool
        """
        return self.__m_externalSource

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setExternalSource(self, externalSource):
        """
        :param externalSource: (bool) True when frames come from a capture that never contains the lens.
        :return:
        """
        externalSource = bool(externalSource)  # type: bool
        if externalSource != self.__m_externalSource:
            self.__m_externalSource = externalSource  # type: bool
            self._reevaluate()

    def appendCaptureDetail(self, text):
        """
        Add information to the current status detail (e.g. why a capture fallback failed too).
        :param text: str | unicode | QString
        :return:
        """
        if u'{}'.format(text) and u'{}'.format(text) not in self.__m_captureDetail:
            self.__m_captureDetail = '; '.join(t for t in (self.__m_captureDetail, u'{}'.format(text)) if t)  # type: str
            self.captureDetailChanged.emit(self.__m_captureDetail)

    def getCaptureDetail(self):
        """
        :return: (str | unicode | QString)Reason when the status is 'failed'.
        """
        return self.__m_captureDetail

    def isOverlappingSource(self):
        """
        :return: (bool) True when the lens covers the area it magnifies (needs capture exclusion).
        """
        return self._geometryFor(self.__m_placement).intersects(self.sourceRect())

    def isCaptureExcluded(self):
        """
        :return: bool
        """
        return self.__m_captureExcluded

    @staticmethod
    def canExcludeFromCapture():
        """
        :return: (bool) True on platforms where the lens can hide itself from capture.
        """
        return platform == 'win32'

    @pyqtSlot()
    def showOverlay(self):
        """
        :return:
        """
        if self.isVisible():
            return
        self.__m_centerScreen = screenAtPoint(QCursor.pos())
        self.__m_frame = QImage()  # type: QImage
        self.setGeometry(self.lensGeometry())
        self._updateMask()
        self.__m_fallbackPlacement = None
        self.__m_captureStatus = 'unknown'  # type: str
        self.show()
        self._keepOnTop()
        self.__m_topTimer.start(1000)
        self.overlayToggled.emit(True)
        self.sourceChanged.emit()
        QTimer.singleShot(0, self._evaluateCapture)

    @pyqtSlot()
    def hideOverlay(self):
        """
        :return:
        """
        if not self.isVisible():
            return
        self.__m_topTimer.stop()
        self.__m_probing = False  # type: bool
        self.setWindowOpacity(self.__m_lensOpacity)
        self.hide()
        self.__m_frame = QImage()  # type: QImage
        self.overlayToggled.emit(False)

    @pyqtSlot()
    def toggle(self):
        """
        :return:
        """
        if self.isVisible():
            self.hideOverlay()
        else:
            self.showOverlay()

    @pyqtSlot(QImage)
    def setFrame(self, frame):
        """
        :param frame: QImage
        :return:
        """
        if not self.isVisible() or self.__m_probing or self.__m_captureStatus in ('unknown', 'testing'):
            return  # Never show a frame that may contain the lens itself.
        if self.__m_target == ZoomOverlay.Cursor or self.getEffectivePlacement() != ZoomOverlay.OnTarget:
            self._reposition()  # The cursor moves, or the corner may be on another screen.
        self.__m_frame = frame  # type: QImage
        self.__m_serial += 1
        self.update()

    @pyqtSlot()
    def zoomIn(self):
        """
        :return:
        """
        self.setZoom(self.__m_zoom * 1.25)

    @pyqtSlot()
    def zoomOut(self):
        """
        :return:
        """
        self.setZoom(self.__m_zoom / 1.25)

    def getZoom(self):
        """
        :return: float | int
        """
        return self.__m_zoom

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setZoom(self, zoom):
        """
        :param zoom: (float | int) 1 .. 16
        :return:
        """
        zoom = clamp(float(zoom), 1.0, 16.0)  # type: float
        if abs(zoom - self.__m_zoom) > 1e-6:
            self.__m_zoom = zoom  # type: float
            if self.isVisible():
                self._showBadge()
            self._changed()
            self.zoomChanged.emit(zoom)

    def getLensSize(self):
        """
        :return: QSize
        """
        return QSize(self.__m_lensSize)

    @pyqtSlot(QSize)
    def setLensSize(self, lensSize):
        """
        :param lensSize: QSize
        :return:
        """
        self.__m_lensSize = QSize(max(64, lensSize.width()), max(64, lensSize.height()))  # type: QSize
        self._changed()

    def getTarget(self):
        """
        :return: ZoomOverlay.Target
        """
        return self.__m_target

    @pyqtSlot(Target)
    @pyqtSlot(int)
    def setTarget(self, target):
        """
        :param target: ZoomOverlay.Target | int
        :return:
        """
        self.__m_target = ZoomOverlay.Target(int(target))  # type: ZoomOverlay.Target
        self._changed()
        self._reevaluate()

    def getTargetPoint(self):
        """
        :return: QPoint
        """
        return QPoint(self.__m_targetPoint)

    @pyqtSlot(QPoint)
    def setTargetPoint(self, targetPoint):
        """
        :param targetPoint: QPoint
        :return:
        """
        self.__m_targetPoint = QPoint(targetPoint)  # type: QPoint
        self._changed()

    def getPlacement(self):
        """
        :return: ZoomOverlay.Placement
        """
        return self.__m_placement

    @pyqtSlot(Placement)
    @pyqtSlot(int)
    def setPlacement(self, placement):
        """
        :param placement: ZoomOverlay.Placement | int
        :return:
        """
        self.__m_placement = ZoomOverlay.Placement(int(placement))  # type: ZoomOverlay.Placement
        self._changed()
        self._reevaluate()

    def getShape(self):
        """
        :return: ZoomOverlay.Shape
        """
        return self.__m_shape

    @pyqtSlot(Shape)
    @pyqtSlot(int)
    def setShape(self, shape):
        """
        :param shape: ZoomOverlay.Shape | int
        :return:
        """
        self.__m_shape = ZoomOverlay.Shape(int(shape))  # type: ZoomOverlay.Shape
        self._updateMask()
        self.update()

    def getProcessor(self):
        """
        :return: callable | None
        """
        return self.__m_processor

    @pyqtSlot(object)
    def setProcessor(self, processor):
        """
        :param processor: callable | None
        :return:
        """
        self.__m_processor = processor if callable(processor) else None  # type: callable | None
        self.refresh()

    @pyqtSlot()
    def refresh(self):
        """
        Re-run the processor (call after changing its settings).
        :return:
        """
        self.__m_cacheKey = None
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

    def getLensOpacity(self):
        """
        :return: float | int
        """
        return self.__m_lensOpacity

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setLensOpacity(self, lensOpacity):
        """
        :param lensOpacity: (float | int) 0.2 .. 1.0
        :return:
        """
        self.__m_lensOpacity = clamp(float(lensOpacity), 0.2, 1.0)  # type: float
        self.setWindowOpacity(self.__m_lensOpacity)

    def getMargin(self):
        """
        :return: int
        """
        return self.__m_margin

    @pyqtSlot(int)
    def setMargin(self, margin):
        """
        :param margin: int
        :return:
        """
        self.__m_margin = max(0, int(margin))  # type: int
        self._changed()

    def isExcludeFromCapture(self):
        """
        :return: bool
        """
        return self.__m_excludeFromCapture

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setExcludeFromCapture(self, excludeFromCapture):
        """
        :param excludeFromCapture: bool
        :return:
        """
        self.__m_excludeFromCapture = bool(excludeFromCapture)  # type: bool
        if self.isVisible() and not self.__m_excludeFromCapture:
            winSetCaptureExcluded(self, exclude=False)
        self._reevaluate()

    # ---------- Qt overrides ----------
    def sizeHint(self):
        """
        :return: QSize
        """
        return QSize(self.__m_lensSize)

    def showEvent(self, e):
        """
        :param e: QShowEvent
        :return:
        """
        super(ZoomOverlay, self).showEvent(e)
        winMakeOverlay(self)

    def resizeEvent(self, e):
        """
        :param e: QResizeEvent
        :return:
        """
        super(ZoomOverlay, self).resizeEvent(e)
        self._updateMask()

    # ---------- Painting ----------
    def paintEvent(self, event):
        """
        :param event: QPaintEvent
        :return:
        """
        p = QPainter(self)  # type: QPainter
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform, True)
        bw = self.__m_borderWidth  # type: float
        r = QRectF(self.rect()).adjusted(bw / 2.0, bw / 2.0, -bw / 2.0, -bw / 2.0)  # type: QRectF
        path = self._lensPath(r)  # type: QPainterPath
        p.fillRect(self.rect(), QColor(14, 15, 20))
        if self.__m_probing:
            pr = self._probeRect()  # type: QRect
            cell = ZoomOverlay.PROBE_CELL  # type: int
            a, b = ZoomOverlay.PROBE_COLORS
            p.setRenderHint(QPainter.Antialiasing, False)
            p.fillRect(QRect(pr.x(), pr.y(), cell, cell), a)
            p.fillRect(QRect(pr.x() + cell, pr.y(), cell, cell), b)
            p.fillRect(QRect(pr.x(), pr.y() + cell, cell, cell), b)
            p.fillRect(QRect(pr.x() + cell, pr.y() + cell, cell, cell), a)
            p.end()
            return
        f = self.__m_frame  # type: QImage
        if not f.isNull():
            dpr = float(self.devicePixelRatioF()) if hasattr(self, 'devicePixelRatioF') else 1.0  # type: float
            px = QSize(max(1, int(round(r.width() * dpr))), max(1, int(round(r.height() * dpr))))  # type: QSize
            key = (self.__m_serial, px.width(), px.height())  # type: tuple
            if key != self.__m_cacheKey:
                img = QImage()  # type: QImage
                if self.__m_processor is not None:
                    try:
                        img = self.__m_processor(f, px)  # type: QImage
                    except Exception:
                        img = QImage()  # type: QImage
                if img is None or img.isNull():
                    img = f.scaled(px, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)  # type: QImage
                self.__m_cacheKey = key  # type: tuple
                self.__m_cacheImage = img  # type: QImage
            p.save()
            p.setClipPath(path)
            p.drawImage(r, self.__m_cacheImage, QRectF(0, 0, self.__m_cacheImage.width(),
                                                       self.__m_cacheImage.height()))
            p.restore()
        if self.__m_showCrosshair:
            self._paintCrosshair(p, r)
        if bw > 0:
            p.setPen(QPen(QColor(0, 0, 0, 140), bw + 2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            p.setPen(QPen(self.__m_borderColor, bw))
            p.drawPath(path)
        if self.__m_badgeOpacity > 0.0:
            self._paintBadge(p, r)
        p.end()

    def _paintCrosshair(self, p, r):
        """
        :param p: QPainter
        :param r: QRectF
        :return:
        """
        c = r.center()  # type: QPointF
        arm = min(r.width(), r.height()) * 0.09  # type: float
        gap = max(4.0, arm * 0.35)  # type: float
        lines = [QLineF(c.x() - gap - arm, c.y(), c.x() - gap, c.y()),
                 QLineF(c.x() + gap, c.y(), c.x() + gap + arm, c.y()),
                 QLineF(c.x(), c.y() - gap - arm, c.x(), c.y() - gap),
                 QLineF(c.x(), c.y() + gap, c.x(), c.y() + gap + arm)]
        p.setPen(QPen(QColor(0, 0, 0, 150), 3.5))
        p.drawLines(lines)
        p.setPen(QPen(self.__m_crosshairColor, 1.5))
        p.drawLines(lines)
        p.setPen(Qt.NoPen)
        p.setBrush(self.__m_crosshairColor)
        p.drawEllipse(c, 1.6, 1.6)

    def _paintBadge(self, p, r):
        """
        :param p: QPainter
        :param r: QRectF
        :return:
        """
        p.setOpacity(self.__m_badgeOpacity)
        font = QFont(self.font())  # type: QFont
        font.setPointSizeF(12)
        font.setBold(True)
        p.setFont(font)
        text = '{:.1f}\u00d7'.format(self.__m_zoom)  # type: str
        fm = QFontMetrics(font)  # type: QFontMetrics
        tw = fm.horizontalAdvance(text) if hasattr(fm, 'horizontalAdvance') else fm.width(text)  # type: int
        box = QRectF(r.center().x() - (tw + 22) / 2.0, r.bottom() - fm.height() - 34, tw + 22, fm.height() + 10)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(14, 15, 20, 210))
        p.drawRoundedRect(box, box.height() / 2.0, box.height() / 2.0)
        p.setPen(QColor(240, 242, 248))
        p.drawText(box, Qt.AlignCenter, text)
        p.setOpacity(1.0)

    # ---------- Properties ----------
    Q_ENUMS('Target' if qVersion()[0] == '4' else Target)
    Q_ENUMS('Placement' if qVersion()[0] == '4' else Placement)
    Q_ENUMS('Shape' if qVersion()[0] == '4' else Shape)
    zoom = pyqtProperty(float, fget=getZoom, fset=setZoom, notify=zoomChanged)  # type: pyqtProperty
    lensSize = pyqtProperty(QSize, fget=getLensSize, fset=setLensSize)  # type: pyqtProperty
    target = pyqtProperty(int, fget=getTarget, fset=setTarget)  # type: pyqtProperty
    targetPoint = pyqtProperty(QPoint, fget=getTargetPoint, fset=setTargetPoint)  # type: pyqtProperty
    placement = pyqtProperty(int, fget=getPlacement, fset=setPlacement)  # type: pyqtProperty
    shape = pyqtProperty(int, fget=getShape, fset=setShape)  # type: pyqtProperty
    processor = pyqtProperty(object, fget=getProcessor, fset=setProcessor)  # type: pyqtProperty
    borderColor = pyqtProperty(QColor, fget=getBorderColor, fset=setBorderColor)  # type: pyqtProperty
    borderWidth = pyqtProperty(float, fget=getBorderWidth, fset=setBorderWidth)  # type: pyqtProperty
    showCrosshair = pyqtProperty(bool, fget=isShowCrosshair, fset=setShowCrosshair)  # type: pyqtProperty
    crosshairColor = pyqtProperty(QColor, fget=getCrosshairColor, fset=setCrosshairColor)  # type: pyqtProperty
    lensOpacity = pyqtProperty(float, fget=getLensOpacity, fset=setLensOpacity)  # type: pyqtProperty
    margin = pyqtProperty(int, fget=getMargin, fset=setMargin)  # type: pyqtProperty
    excludeFromCapture = pyqtProperty(bool, fget=isExcludeFromCapture, fset=setExcludeFromCapture)  # type: pyqtProperty
    externalSource = pyqtProperty(bool, fget=isExternalSource, fset=setExternalSource)  # type: pyqtProperty
