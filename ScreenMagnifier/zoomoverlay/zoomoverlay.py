# -*- coding: utf-8 -*-
"""
ZoomOverlay: a click-through, focus-less, always-on-top magnifier lens for use over games and other
full-screen applications.
- Never takes the keyboard focus and lets every mouse click through to the application below.
- Target: screen center (e.g. a game crosshair), a pinned point, or the mouse cursor.
- Placement: on the target (scope style) or in a screen corner (picture-in-picture).
- Circle, rounded-rectangle (adjustable corner radius) or rectangle lens, crosshair, border, opacity, animated
  zoom badge.
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
    QGuiApplication, QTransform
from ManyQt.QtWidgets import QWidget
from enum import IntEnum
from sys import platform

try:
    from sys import getwindowsversion  # Windows only.
except:
    getwindowsversion = None


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
    except:
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
        return False, u'Only Windows can hide a window from screen capture'
    try:
        from ctypes import byref, c_ubyte, get_last_error
        from ctypes.wintypes import HWND, DWORD
        build = getwindowsversion().build  # type: int
        if exclude and build < 19041:
            return False, u'Needs Windows 10 version 2004 (build 19041) or newer, this is build {}'.format(build)
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
            return True, u''
        style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)  # type: int
        if exclude and forceLayered and not style & WS_EX_LAYERED:
            u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
            u.SetLayeredWindowAttributes(hwnd, 0, int(alpha), LWA_ALPHA)  # Keep it visible on screen.
            style |= WS_EX_LAYERED
        if u.SetWindowDisplayAffinity(hwnd, wanted):
            return True, u''
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
        return False, u'SetWindowDisplayAffinity failed (Windows error {}, build {}{})'.format(error, build, perPixel)
    except Exception as e:
        return False, u'Capture exclusion unavailable: {}'.format(e)


def winMakeOverlay(widget):
    """
    Windows: no activation on click/show, click-through, keep top-most.
    :param widget: QWidget
    :return: None
    """
    if platform != 'win32':
        return
    try:
        from ctypes.wintypes import HWND
        from ctypes import windll
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
    except:
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
    except:
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
        NearTarget = 5  # type: int  # Beside the target (follows a cursor target), never over the picked pixel.
        Custom = 6  # type: int  # A rectangle of the user's choice (position and size, any aspect ratio).
        FullScreen = 7  # type: int  # A whole screen (the target's screen, or a chosen one).

    class Shape(IntEnum):
        """
        Shape enumeration class.
        """
        Circle = 0  # type: int
        RoundedRect = 1  # type: int
        Rectangle = 2  # type: int

    Center = Target.Center  # type: int
    Point = Target.Point  # type: int
    Cursor = Target.Cursor  # type: int
    OnTarget = Placement.OnTarget  # type: int
    TopLeft = Placement.TopLeft  # type: int
    TopRight = Placement.TopRight  # type: int
    BottomLeft = Placement.BottomLeft  # type: int
    BottomRight = Placement.BottomRight  # type: int
    NearTarget = Placement.NearTarget  # type: int
    Custom = Placement.Custom  # type: int
    FullScreen = Placement.FullScreen  # type: int
    Circle = Shape.Circle  # type: int
    RoundedRect = Shape.RoundedRect  # type: int
    Rectangle = Shape.Rectangle  # type: int
    zoomChanged = pyqtSignal(float)  # type: pyqtSignal
    readoutChanged = pyqtSignal(QColor, 'QString')  # type: pyqtSignal  # color code / zone under the crosshair
    overlayToggled = pyqtSignal(bool)  # type: pyqtSignal
    sourceChanged = pyqtSignal()  # type: pyqtSignal
    captureStatusChanged = pyqtSignal('QString')  # type: pyqtSignal
    captureDetailChanged = pyqtSignal('QString')  # type: pyqtSignal
    PROBE_COLORS = (QColor(255, 0, 255), QColor(0, 255, 0))  # type: tuple[QColor, QColor]
    PROBE_CELL = 8  # type: int  # Probe = 2 x 2 cells of this size (px) at the lens centre.
    PROBE_DELAY_MS = 150  # type: int  # Time for the compositor to put the probe on screen.
    FALLBACK_ORDER = (Placement.TopRight, Placement.TopLeft, Placement.BottomRight, Placement.BottomLeft)  # type: tuple

    def __init__(self, *args, **kwargs):
        """
        :param zoom: (float | int) Magnification, 1 .. 16.
        :param lensSize: (QSize) Lens size in px (placements other than Custom / FullScreen).
        :param customRect: (QRect) Lens rect of the Custom placement (global, device-independent px).
        :param fullScreenIndex: (int) Screen of the FullScreen placement, -1 = the screen of the target.
        :param cornerRadius: (int) Corner radius of the RoundedRect shape in px (at most half the short side).
        :param target: ZoomOverlay.Target | int
        :param targetPoint: (QPoint) Global point used by Target.Point.
        :param placement: ZoomOverlay.Placement | int
        :param shape: ZoomOverlay.Shape | int
        :param processor: (callable | None) f(QImage, QSize) -> QImage upscaler.
        :param borderColor: QColor | Qt.GlobalColor | int | str
        :param borderWidth: float | int
        :param showCrosshair: bool
        :param showColorReadout: (bool) Live color code (swatch, HEX, RGB) of the crosshair pixel.
        :param pixelated: (bool) Exact pixels + pixel grid instead of the upscaler (color picking).
        :param readoutSource: (str | unicode | QString)
                                Color code of: 'original' screen pixel or 'zoomed' (displayed) image.
        :param readoutSample: (int) Average of N x N pixels for the color code (1, 3, 5, 9).
        :param colorFormatter: (callable | None) QColor -> str: text of the color code (e.g. the application's copy
            format, so the code shown is the code copied); None = #RRGGBB.
        :param colorNamer: (callable | None) QColor -> str: color name shown under the code; None = no name.
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
        customRect = kwargs.pop('customRect', QRect())  # type: QRect
        fullScreenIndex = kwargs.pop('fullScreenIndex', -1)  # type: int
        target = kwargs.pop('target', ZoomOverlay.Center)  # type: int
        targetPoint = kwargs.pop('targetPoint', QPoint())  # type: QPoint
        placement = kwargs.pop(
            'placement', ZoomOverlay.OnTarget if platform == 'win32' else ZoomOverlay.TopRight)  # type: int
        shape = kwargs.pop('shape', ZoomOverlay.Circle)  # type: int
        cornerRadius = kwargs.pop('cornerRadius', 45)  # type: int
        processor = kwargs.pop('processor', None)  # type: callable | None
        borderColor = kwargs.pop('borderColor', '#4F8BFF')  # type: QColor
        borderWidth = kwargs.pop('borderWidth', 3)  # type: float
        showCrosshair = kwargs.pop('showCrosshair', True)  # type: bool
        showColorReadout = kwargs.pop('showColorReadout', True)  # type: bool
        pixelated = kwargs.pop('pixelated', False)  # type: bool
        readoutSource = kwargs.pop('readoutSource', 'original')  # type: str
        readoutSample = kwargs.pop('readoutSample', 1)  # type: int
        colorFormatter = kwargs.pop('colorFormatter', None)  # type: callable | None
        colorNamer = kwargs.pop('colorNamer', None)  # type: callable | None
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
        self.__m_showColorReadout = bool(showColorReadout)  # type: bool
        self.__m_pixelated = bool(pixelated)  # type: bool
        self.__m_readoutSource = 'zoomed' if u'{}'.format(readoutSource) == 'zoomed' else 'original'  # type: str
        self.__m_readoutSample = max(1, int(readoutSample))  # type: int
        self.__m_colorFormatter = colorFormatter if callable(colorFormatter) else None
        self.__m_colorNamer = colorNamer if callable(colorNamer) else None
        self.__m_names = {}  # type: dict  # rgb -> name cache (the namer runs at frame rate)
        self.__m_lastReadout = (None, '')  # type: tuple  # last (rgb, zone) emitted by readoutChanged
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
        self.__m_fallbackScreen = None  # type: int | None  # FullScreen moved to another (safe) screen.
        self.__m_customRect = QRect(customRect)  # type: QRect
        self.__m_cornerRadius = max(0, int(cornerRadius))  # type: int
        self.__m_fullScreenIndex = int(fullScreenIndex)  # type: int
        self.__m_probing = False  # type: bool
        self.__m_centerScreen = None  # type: QScreen | None
        self.__m_frame = QImage()  # type: QImage
        self.__m_annotations = []  # type: list
        self.__m_annotationSize = QSize()  # type: QSize
        self.__m_overlayImage = QImage()  # type: QImage
        self.__m_annotationOrigin = None  # type: list | None  # [x, y, dpr] screen position of the analysed frame.
        self.__m_frameOrigin = None  # type: list | None  # [x, y, dpr] screen position of the shown frame.
        self.__m_serial = 0  # type: int
        self.__m_cacheKey = None  # type: tuple | None
        self.__m_cacheImage = QImage()  # type: QImage
        self.__m_badgeOpacity = 0.0  # type: float
        self.__m_toastText = ''  # type: str
        self.__m_toastColor = QColor()  # type: QColor
        self.__m_toastOpacity = 0.0  # type: float
        self.__m_toastClock = QElapsedTimer()  # type: QElapsedTimer
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
        if self._isRectangular():
            path.addRect(rect)
        elif self.__m_shape == ZoomOverlay.Circle:
            path.addEllipse(rect)
        else:
            r = self._radiusFor(rect)  # type: float
            path.addRoundedRect(rect, r, r)
        return path

    def _radiusFor(self, rect):
        """
        :param rect: QRectF | QRect
        :return: (float | int) Corner radius actually drawn: the chosen one, at most half the short side (a pill / circle).
        """
        if self._isRectangular() or self.__m_shape == ZoomOverlay.Circle:
            return 0.0
        return min(float(self.__m_cornerRadius), min(rect.width(), rect.height()) / 2.0)

    def _isRectangular(self):
        """
        :return: (bool) Drawn as a plain rectangle: the Rectangle shape, or a full-screen lens.
        """
        return self.__m_shape == ZoomOverlay.Rectangle or (
                self.getEffectivePlacement() == ZoomOverlay.FullScreen)

    def _updateMask(self):
        """
        A window mask gives the lens its shape even without a compositor.
        :return:
        """
        if self._isRectangular():
            self.clearMask()
        elif self.__m_shape == ZoomOverlay.Circle:
            self.setMask(QRegion(self.rect(), QRegion.Ellipse))
        else:
            try:
                poly = self._lensPath(QRectF(self.rect())).toFillPolygon().toPolygon()
            except:
                poly = self._lensPath(QRectF(self.rect())).toFillPolygon(QTransform()).toPolygon()
            self.setMask(QRegion(poly))

    def _reposition(self):
        """
        :return:
        """
        geo = self.lensGeometry()  # type: QRect
        if geo != self.geometry():
            resized = geo.size() != self.size()  # type: bool
            self.setGeometry(geo)
            if resized:
                self._updateMask()  # the shape follows the new size (custom area, full screen, fallback)

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

    @staticmethod
    def _screens():
        """
        :return: (list[QScreen])
        """
        return QGuiApplication.screens()

    def _fullScreenGeometry(self):
        """
        :return: (QRect) The screen of the FullScreen placement: the safe screen chosen by the fallback, the screen
            the user chose, or the screen of the target.
        """
        screens = self._screens()  # type: list
        index = self.__m_fallbackScreen if self.__m_fallbackScreen is not None else self.__m_fullScreenIndex
        return screens[index].geometry() if 0 <= index < len(screens) else screenAtPoint(self.targetPos()).geometry()

    def _customGeometry(self):
        """
        :return: (QRect) The Custom rect, kept on a screen (a monitor may have been removed since it was drawn).
        """
        r = QRect(self.__m_customRect)  # type: QRect
        if r.width() < 64 or r.height() < 64:  # not drawn yet: the regular lens at the screen centre
            g = screenAtPoint(self.targetPos()).geometry()  # type: QRect
            r = QRect(0, 0, self.__m_lensSize.width(), self.__m_lensSize.height())
            r.moveCenter(g.center())
            return r
        g = screenAtPoint(r.center()).geometry()  # type: QRect
        r.setSize(r.size().boundedTo(g.size()))
        r.moveLeft(int(clamp(r.left(), g.left(), g.right() - r.width() + 1)))
        r.moveTop(int(clamp(r.top(), g.top(), g.bottom() - r.height() + 1)))
        return r

    def _geometryFor(self, placement):
        """
        :param placement: ZoomOverlay.Placement
        :return: (QRect) Lens window rect for a given placement.
        """
        if placement == ZoomOverlay.Custom:
            return self._customGeometry()
        if placement == ZoomOverlay.FullScreen:
            return self._fullScreenGeometry()
        c = self.targetPos()  # type: QPoint
        g = screenAtPoint(c).geometry()  # type: QRect
        w, h, m = self.__m_lensSize.width(), self.__m_lensSize.height(), self.__m_margin  # type: int, int, int
        if placement == ZoomOverlay.OnTarget:
            x, y = c.x() - w // 2, c.y() - h // 2  # type: int, int
        elif placement == ZoomOverlay.NearTarget:  # Beside the target, flipped near the screen edges.
            off = int(max(28, max(w, h) / (2.0 * self.__m_zoom) + 12))  # type: int  # clear of the source area
            x = c.x() + off if c.x() + off + w <= g.right() else c.x() - off - w  # type: int
            y = c.y() + off if c.y() + off + h <= g.bottom() else c.y() - off - h  # type: int
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
        if self.__m_placement == ZoomOverlay.FullScreen:  # a second monitor is safe on every system
            src = self.sourceRect()  # type: QRect
            for index, screen in enumerate(self._screens()):
                if not screen.geometry().intersects(src):
                    self.__m_fallbackScreen = index  # type: int | None
                    self.__m_frame = QImage()  # type: QImage
                    self._reposition()
                    self._setStatus('otherScreen', detail)
                    self.update()
                    self.sourceChanged.emit()
                    return
        self.__m_fallbackPlacement = ZoomOverlay.FALLBACK_ORDER[0]  # corners use the regular lens size
        src = self.sourceRect()  # type: QRect  # (the source of the corner lens)
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
        :return: None
        """
        if not self.isVisible():
            return
        self.__m_fallbackPlacement = None
        self.__m_fallbackScreen = None
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
            ok, detail = False, u'Hiding the lens from capture is turned off'
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
        :return: None
        """
        if not self.__m_probing:
            return
        self.__m_probing = False  # type: bool
        self.setWindowOpacity(self.__m_lensOpacity)
        if not self.isVisible():
            return
        seen = self._probeSeenByCapture()  # type: bool | None
        if seen:
            self._useFallback(u'Windows accepted the request to hide the lens, but the lens still appears in '
                              u'screen captures (build {})'.format(
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
        if self.__m_badgeOpacity > 0.0:
            t = self.__m_badgeClock.elapsed()  # type: int
            self.__m_badgeOpacity = 1.0 if t < 800 else max(0.0, 1.0 - (t - 800) / 400.0)  # type: float
        if self.__m_toastOpacity > 0.0:
            t = self.__m_toastClock.elapsed()  # type: int
            self.__m_toastOpacity = 1.0 if t < 1100 else max(0.0, 1.0 - (t - 1100) / 400.0)  # type: float
        if self.__m_badgeOpacity <= 0.0 and self.__m_toastOpacity <= 0.0:
            self.__m_badgeTimer.stop()
        self.update()

    # ---------- Public API ----------
    def getFrame(self):
        """
        :return: (QImage) Last frame shown in the lens (its center is the target point).
        """
        return self.__m_frame

    def displayedColor(self, size=1):
        """
        Color under the crosshair as the lens SHOWS it (upscaled / sharpened image).
        :param size: (int) Average of size x size displayed pixels.
        :return: (QColor) Invalid before the first frame.
        """
        img = self.__m_cacheImage  # type: QImage
        if img.isNull():
            return QColor()
        cx, cy, half = img.width() // 2, img.height() // 2, max(0, int(size) // 2)  # type: int, int, int
        r = g = b = n = 0  # type: int
        for y in range(max(0, cy - half), min(img.height(), cy + half + 1)):
            for x in range(max(0, cx - half), min(img.width(), cx + half + 1)):
                c = QColor(img.pixel(x, y))  # type: QColor
                r, g, b, n = r + c.red(), g + c.green(), b + c.blue(), n + 1
        return QColor(r // n, g // n, b // n)

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
        size = self._geometryFor(self.getEffectivePlacement()).size()  # type: QSize  # the lens in use
        w = max(2, int(round(size.width() / self.__m_zoom)))  # type: int
        h = max(2, int(round(size.height() / self.__m_zoom)))  # type: int
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
        self.__m_fallbackScreen = None
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
        self.hideOverlay() if self.isVisible() else self.showOverlay()

    def _paintAnnotations(self, p, r, path):
        """
        Annotations / overlay image mapped from frame pixels onto the lens rect, clipped to the lens shape.
        :param p: QPainter
        :param r: (QRectF) Lens image rect.
        :param path: (QPainterPath) Lens shape.
        :return: None
        """
        f = self.__m_frame  # type: QImage
        if f.isNull():
            return
        p.save()
        p.setClipPath(path)
        a, o = self.__m_annotationOrigin, self.__m_frameOrigin
        size = self.__m_annotationSize  # type: QSize
        aw = size.width() if size.width() > 0 else f.width()  # type: int
        ah = size.height() if size.height() > 0 else f.height()  # type: int
        if a and o and float(a[2]) > 0:  # Screen-locked: from both frames' positions and pixels-per-point.
            fx = fy = float(o[2]) / float(a[2])  # type: float  # annotation px -> frame px
            dx, dy = (float(a[0]) - float(o[0])) * float(o[2]), (float(a[1]) - float(o[1])) * float(o[2])
        else:
            fx, fy, dx, dy = f.width() / float(aw), f.height() / float(ah), 0.0, 0.0
        kx, ky = r.width() / float(f.width()), r.height() / float(f.height())  # type: float, float  # frame -> lens
        sx, sy = fx * kx, fy * ky  # type: float, float  # annotation px -> lens px
        if not self.__m_overlayImage.isNull():
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            ov = self.__m_overlayImage  # type: QImage
            p.drawImage(QRectF(r.left() + dx * kx, r.top() + dy * ky, aw * sx, ah * sy), ov,
                        QRectF(0, 0, ov.width(), ov.height()))
        for a in self.__m_annotations:
            rect = a.get('rect')
            if not rect or len(rect) != 4:
                continue
            q = QRectF(r.left() + (rect[0] * fx + dx) * kx, r.top() + (rect[1] * fy + dy) * ky, rect[2] * sx,
                       rect[3] * sy)  # type: QRectF
            color = QColor(a.get('color', '#FFD400'))  # type: QColor
            if a.get('style') == 'blur':
                src = QRect(int(rect[0] * fx + dx), int(rect[1] * fy + dy), max(1, int(rect[2] * fx)),
                            max(1, int(rect[3] * fy))).intersected(f.rect())  # type: QRect
                if not src.isEmpty():
                    cells = max(1, int(a.get('blocks', 8)))  # type: int
                    small = f.copy(src).scaled(cells, max(1, int(cells * src.height() / float(src.width()))),
                                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)  # type: QImage
                    p.setRenderHint(QPainter.SmoothPixmapTransform, False)
                    p.drawImage(q, small, QRectF(0, 0, small.width(), small.height()))
                continue
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 150), 4))
            p.drawRect(q)
            p.setPen(QPen(color, 2))
            p.drawRect(q)
            for pt in a.get('points', []) or []:
                p.setPen(QPen(QColor(0, 0, 0, 160), 1))
                p.setBrush(color)
                p.drawEllipse(QPointF(r.left() + (pt[0] * fx + dx) * kx, r.top() + (pt[1] * fy + dy) * ky), 3.0, 3.0)
        p.restore()

    def centerColor(self):
        """
        :return: (QColor) Exact color of the screen pixel under the crosshair (center of the last frame).
        """
        f = self.__m_frame  # type: QImage
        return QColor(f.pixel(f.width() // 2, f.height() // 2)) if not f.isNull() else QColor()

    def _paintPixelGrid(self, p, r, path):
        """
        Pixel grid and center-pixel outline (pixel-exact mode, when a screen pixel is >= 6 lens px wide).
        :param p: QPainter
        :param r: QRectF
        :param path: QPainterPath
        :return: None
        """
        f = self.__m_frame  # type: QImage
        if f.isNull():
            return
        kx, ky = r.width() / float(f.width()), r.height() / float(f.height())  # type: float, float
        p.save()
        p.setClipPath(path)
        p.setRenderHint(QPainter.Antialiasing, False)
        if kx >= 6.0:
            lines = [QLineF(r.left() + i * kx, r.top(), r.left() + i * kx, r.bottom()) for i in range(f.width() + 1)]
            lines += [QLineF(r.left(), r.top() + j * ky, r.right(), r.top() + j * ky) for j in range(f.height() + 1)]
            p.setPen(QPen(QColor(0, 0, 0, 60), 1))
            p.drawLines(lines)
        cell = QRectF(r.left() + (f.width() // 2) * kx, r.top() + (f.height() // 2) * ky, kx, ky)  # type: QRectF
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 220), 3))
        p.drawRect(cell.adjusted(-1, -1, 1, 1))
        p.setPen(QPen(QColor(255, 255, 255, 240), 1))
        p.drawRect(cell.adjusted(-1, -1, 1, 1))
        p.restore()

    def readoutColor(self):
        """
        THE color code of the zoomer: what the readout shows and what copying takes (same function, always equal).
        :return: (QColor) Invalid before the first frame.
        """
        if self.__m_readoutSource == 'zoomed' and not self.__m_pixelated:
            shown = self.displayedColor(self.__m_readoutSample)  # type: QColor
            if shown.isValid():
                return shown
        f = self.__m_frame  # type: QImage
        if f.isNull():
            return QColor()
        cx, cy, half = f.width() // 2, f.height() // 2, self.__m_readoutSample // 2  # type: int, int, int
        r = g = b = n = 0  # type: int
        for y in range(max(0, cy - half), min(f.height(), cy + half + 1)):
            for x in range(max(0, cx - half), min(f.width(), cx + half + 1)):
                c = QColor(f.pixel(x, y))  # type: QColor
                r, g, b, n = r + c.red(), g + c.green(), b + c.blue(), n + 1
        return QColor(int(round(r / float(n))), int(round(g / float(n))), int(round(b / float(n))))

    def zoneAtCrosshair(self):
        """
        :return: (str | unicode | QString) Label of the color zone (annotation) under the crosshair, '' if none.
        """
        f = self.__m_frame  # type: QImage
        if f.isNull() or not self.__m_annotations:
            return ''
        a, o = self.__m_annotationOrigin, self.__m_frameOrigin
        size = self.__m_annotationSize  # type: QSize
        if a and o and float(a[2]) > 0:
            fx = fy = float(o[2]) / float(a[2])  # type: float
            dx, dy = (float(a[0]) - float(o[0])) * float(o[2]), (float(a[1]) - float(o[1])) * float(o[2])
        else:
            fx = f.width() / float(size.width() if size.width() > 0 else f.width())  # type: float
            fy = f.height() / float(size.height() if size.height() > 0 else f.height())  # type: float
            dx = dy = 0.0  # type: float
        cx, cy = (f.width() / 2.0 - dx) / fx, (f.height() / 2.0 - dy) / fy  # type: float, float  # annotation px
        for ann in self.__m_annotations:
            x, y, w, h = ann.get('rect', [0, 0, 0, 0])
            if ann.get('label') and x <= cx < x + w and y <= cy < y + h:
                return u'{}'.format(ann['label'])
        return ''

    def readoutText(self):
        """
        The two lines of the color code - the SAME text the application shows elsewhere and copies.
        :return: (tuple[str | unicode | QString, str | unicode | QString])
                    Code (formatter, default #RRGGBB) and details (RGB for HEX codes, name, zone).
        """
        color = self.readoutColor()  # type: QColor
        if not color.isValid():
            return '', ''
        try:
            code = u'{}'.format(self.__m_colorFormatter(color)) if self.__m_colorFormatter else u'{}'.format(color.name()).upper()
        except Exception:
            code = u'{}'.format(color.name()).upper()  # type: str
        details = []  # type: list
        if code.startswith('#') or code.startswith('0x') or len(code) == 6:
            details.append('{}, {}, {}'.format(color.red(), color.green(), color.blue()))
        if self.__m_colorNamer is not None:
            if color.rgb() not in self.__m_names:
                try:
                    self.__m_names[color.rgb()] = u'{}'.format(self.__m_colorNamer(color))
                except Exception:
                    self.__m_names[color.rgb()] = ''
                if len(self.__m_names) > 4096:
                    self.__m_names.clear()
            if self.__m_names.get(color.rgb()):
                details.append(self.__m_names[color.rgb()])
        zone = self.zoneAtCrosshair()  # type: str
        if zone:  # First: in a round lens the end of the line may be shortened with '...'.
            details.insert(0, 'zone: ' + zone)
        return code, u'  \u00b7  '.join(details)

    def _emitReadout(self):
        """
        readoutChanged when the color code or its zone changed (shown lens with the color code on).
        :return:
        """
        color = self.readoutColor()  # type: QColor
        key = (color.rgb() if color.isValid() else None, self.zoneAtCrosshair())  # type: tuple
        if key != self.__m_lastReadout:
            self.__m_lastReadout = key  # type: tuple
            self.readoutChanged.emit(color, key[1])

    def _paintReadout(self, p, r):
        """
        Live color of the crosshair pixel: swatch + HEX + RGB, updated with every frame.
        :param p: QPainter
        :param r: QRectF
        :return: None
        """
        color = self.readoutColor()  # type: QColor
        if not color.isValid():
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        font = QFont(self.font())  # type: QFont
        font.setPointSizeF(10.5)
        font.setBold(True)
        small = QFont(font)  # type: QFont
        small.setBold(False)
        small.setPointSizeF(8.5)
        hexText, rgbText = self.readoutText()  # type: str, str
        w = max(QFontMetrics(font).boundingRect(hexText).width(),
                QFontMetrics(small).boundingRect(rgbText).width()) + 52
        w = min(w, r.width() - 16)  # type: float
        h = 40.0  # type: float
        if self.__m_shape == ZoomOverlay.Circle and not self._isRectangular():
            inset = r.height() * 0.16  # type: float
            radius = r.width() / 2.0  # type: float  # Fit the circle's width at the box's lower edge.
            dy = (r.bottom() - inset) - r.center().y()  # type: float
            w = min(w, 2.0 * (max(0.0, radius * radius - dy * dy) ** 0.5) - 10.0)  # type: float
        else:  # rounded corners: lift the box with the radius and keep it clear of the corner arcs
            radius = self._radiusFor(r)  # type: float
            inset = max(r.height() * 0.05, radius * 0.29)  # type: float
            if inset < radius:
                cut = radius - (max(0.0, radius * radius - (radius - inset) ** 2) ** 0.5)  # type: float
                w = min(w, r.width() - 2.0 * cut - 10.0)  # type: float
        box = QRectF(r.center().x() - w / 2.0, r.bottom() - inset - h, w, h)  # type: QRectF
        hexText = QFontMetrics(font).elidedText(hexText, Qt.ElideRight, int(w - 46))  # type: str
        rgbText = QFontMetrics(small).elidedText(rgbText, Qt.ElideRight, int(w - 46))  # type: str
        bg = QPainterPath()  # type: QPainterPath
        bg.addRoundedRect(box, 10, 10)
        p.fillPath(bg, QColor(14, 15, 20, 225))
        p.setPen(QPen(QColor(255, 255, 255, 210), 1.5))
        p.setBrush(color)
        p.drawRoundedRect(QRectF(box.left() + 8, box.top() + 8, 24, 24), 6, 6)
        p.setPen(QColor(240, 242, 248))
        p.setFont(font)
        p.drawText(QRectF(box.left() + 40, box.top() + 3, w - 44, 20), Qt.AlignLeft | Qt.AlignVCenter, hexText)
        p.setFont(small)
        p.setPen(QColor(170, 178, 196))
        p.drawText(QRectF(box.left() + 40, box.top() + 20, w - 44, 16), Qt.AlignLeft | Qt.AlignVCenter, rgbText)
        p.restore()

    def isShowColorReadout(self):
        """
        :return: bool
        """
        return self.__m_showColorReadout

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setShowColorReadout(self, showColorReadout):
        """
        :param showColorReadout: (bool) Live color code of the crosshair pixel inside the lens.
        :return:
        """
        self.__m_showColorReadout = bool(showColorReadout)  # type: bool
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

    def getColorNamer(self):
        """
        :return: callable | None
        """
        return self.__m_colorNamer

    @pyqtSlot(object)
    def setColorNamer(self, colorNamer):
        """
        :param colorNamer: (callable | None) QColor -> str.
        :return:
        """
        self.__m_colorNamer = colorNamer if callable(colorNamer) else None
        self.__m_names = {}  # type: dict
        self.update()

    def getReadoutSource(self):
        """
        :return: (str | unicode | QString) 'original' or 'zoomed'.
        """
        return self.__m_readoutSource

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setReadoutSource(self, readoutSource):
        """
        :param readoutSource: (str | unicode | QString) 'original' (screen pixel) or 'zoomed' (displayed image).
        :return:
        """
        self.__m_readoutSource = 'zoomed' if u'{}'.format(readoutSource) == 'zoomed' else 'original'  # type: str
        self.update()

    def getReadoutSample(self):
        """
        :return: int
        """
        return self.__m_readoutSample

    @pyqtSlot(int)
    def setReadoutSample(self, readoutSample):
        """
        :param readoutSample: (int) N x N average.
        :return:
        """
        self.__m_readoutSample = max(1, int(readoutSample))  # type: int
        self.update()

    def isPixelated(self):
        """
        :return: bool
        """
        return self.__m_pixelated

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setPixelated(self, pixelated):
        """
        :param pixelated: (bool) Exact pixels (no upscaler) + pixel grid: what a color picker needs.
        :return:
        """
        self.__m_pixelated = bool(pixelated)  # type: bool
        self.__m_cacheKey = None
        self.update()

    # ---------- Annotations API ----------
    def getAnnotations(self):
        """
        :return: list[dict]
        """
        return list(self.__m_annotations)

    def setAnnotations(self, annotations, sourceSize=None, origin=None):
        """
        :param annotations: (list[dict]) {'rect': [x, y, w, h], 'color': '#RRGGBB', 'style': 'box' | 'blur',
            'points': [[x, y], ...]} in source-frame pixels.
        :param sourceSize: (QSize | None) Size of the frame the coordinates refer to; None = current frame.
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
        :param overlayImage: (QImage) ARGB image aligned with the whole frame, null = none.
        :return:
        """
        self.__m_overlayImage = QImage() if overlayImage is None else overlayImage  # type: QImage
        self.update()

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

    def getCustomRect(self):
        """
        :return: (QRect) Lens rect of the Custom placement (global, device-independent px).
        """
        return QRect(self.__m_customRect)

    @pyqtSlot(QRect)
    def setCustomRect(self, customRect):
        """
        :param customRect: QRect
        :return:
        """
        self.__m_customRect = QRect(customRect).normalized()  # type: QRect
        if self.__m_placement == ZoomOverlay.Custom:
            self._changed()
            self._reevaluate()

    def getFullScreenIndex(self):
        """
        :return: (int) Screen of the FullScreen placement, -1 = the screen of the target.
        """
        return self.__m_fullScreenIndex

    @pyqtSlot(int)
    def setFullScreenIndex(self, fullScreenIndex):
        """
        :param fullScreenIndex: int
        :return:
        """
        self.__m_fullScreenIndex = int(fullScreenIndex)  # type: int
        if self.__m_placement == ZoomOverlay.FullScreen:
            self._changed()
            self._reevaluate()

    def getFallbackScreen(self):
        """
        :return: (int | None) The safe screen a full-screen lens moved to, None if it did not.
        """
        return self.__m_fallbackScreen

    def getCornerRadius(self):
        """
        :return: (int) Corner radius of the RoundedRect shape in px.
        """
        return self.__m_cornerRadius

    @pyqtSlot(int)
    def setCornerRadius(self, cornerRadius):
        """
        :param cornerRadius: (int) px, 0 = square corners (drawn at most half the short side).
        :return:
        """
        self.__m_cornerRadius = max(0, int(cornerRadius))  # type: int
        self._updateMask()
        self.update()

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
            key = (self.__m_serial, px.width(), px.height(), self.__m_pixelated)  # type: tuple
            if key != self.__m_cacheKey:
                img = QImage()  # type: QImage
                if self.__m_pixelated:  # Exact pixels for color picking.
                    img = f.scaled(px, Qt.IgnoreAspectRatio, Qt.FastTransformation)  # type: QImage
                elif self.__m_processor is not None:
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
            p.drawImage(r, self.__m_cacheImage, QRectF(0, 0, self.__m_cacheImage.width(), self.__m_cacheImage.height()))
            p.restore()
            if self.__m_annotations or not self.__m_overlayImage.isNull():
                self._paintAnnotations(p, r, path)
        if self.__m_pixelated:
            self._paintPixelGrid(p, r, path)
        elif self.__m_showCrosshair:
            self._paintCrosshair(p, r)
        if self.__m_showColorReadout:
            self._paintReadout(p, r)
            self._emitReadout()
        if bw > 0:
            p.setPen(QPen(QColor(0, 0, 0, 140), bw + 2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            p.setPen(QPen(self.__m_borderColor, bw))
            p.drawPath(path)
        if self.__m_badgeOpacity > 0.0:
            self._paintBadge(p, r.adjusted(0, 0, 0, -48) if self.__m_showColorReadout else r)
        if self.__m_toastOpacity > 0.0:
            self._paintToast(p, r.adjusted(0, r.height() * 0.08, 0, 0))
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
    Q_ENUMS('Target' if qVersion()[0] == '4' else Target)
    Q_ENUMS('Placement' if qVersion()[0] == '4' else Placement)
    Q_ENUMS('Shape' if qVersion()[0] == '4' else Shape)
    zoom = pyqtProperty(float, fget=getZoom, fset=setZoom, notify=zoomChanged)  # type: pyqtProperty
    lensSize = pyqtProperty(QSize, fget=getLensSize, fset=setLensSize)  # type: pyqtProperty
    target = pyqtProperty(int, fget=getTarget, fset=setTarget)  # type: pyqtProperty
    targetPoint = pyqtProperty(QPoint, fget=getTargetPoint, fset=setTargetPoint)  # type: pyqtProperty
    placement = pyqtProperty(int, fget=getPlacement, fset=setPlacement)  # type: pyqtProperty
    shape = pyqtProperty(int, fget=getShape, fset=setShape)  # type: pyqtProperty
    customRect = pyqtProperty(QRect, fget=getCustomRect, fset=setCustomRect)  # type: pyqtProperty
    cornerRadius = pyqtProperty(int, fget=getCornerRadius, fset=setCornerRadius)  # type: pyqtProperty
    fullScreenIndex = pyqtProperty(int, fget=getFullScreenIndex, fset=setFullScreenIndex)  # type: pyqtProperty
    processor = pyqtProperty(object, fget=getProcessor, fset=setProcessor)  # type: pyqtProperty
    borderColor = pyqtProperty(QColor, fget=getBorderColor, fset=setBorderColor)  # type: pyqtProperty
    borderWidth = pyqtProperty(float, fget=getBorderWidth, fset=setBorderWidth)  # type: pyqtProperty
    showCrosshair = pyqtProperty(bool, fget=isShowCrosshair, fset=setShowCrosshair)  # type: pyqtProperty
    crosshairColor = pyqtProperty(QColor, fget=getCrosshairColor, fset=setCrosshairColor)  # type: pyqtProperty
    lensOpacity = pyqtProperty(float, fget=getLensOpacity, fset=setLensOpacity)  # type: pyqtProperty
    margin = pyqtProperty(int, fget=getMargin, fset=setMargin)  # type: pyqtProperty
    excludeFromCapture = pyqtProperty(bool, fget=isExcludeFromCapture, fset=setExcludeFromCapture)  # type: pyqtProperty
    externalSource = pyqtProperty(bool, fget=isExternalSource, fset=setExternalSource)  # type: pyqtProperty
    overlayImage = pyqtProperty(QImage, fget=getOverlayImage, fset=setOverlayImage)  # type: pyqtProperty
    frame = pyqtProperty(QImage, fget=getFrame, fset=setFrame)  # type: pyqtProperty
    showColorReadout = pyqtProperty(bool, fget=isShowColorReadout, fset=setShowColorReadout)  # type: pyqtProperty
    pixelated = pyqtProperty(bool, fget=isPixelated, fset=setPixelated)  # type: pyqtProperty
    readoutSource = pyqtProperty('QString', fget=getReadoutSource, fset=setReadoutSource)  # type: pyqtProperty
    readoutSample = pyqtProperty(int, fget=getReadoutSample, fset=setReadoutSample)  # type: pyqtProperty
    annotations = pyqtProperty(list, fget=getAnnotations, fset=setAnnotations)  # type: pyqtProperty
    colorFormatter = pyqtProperty(object, fget=getColorFormatter, fset=setColorFormatter)  # type: pyqtProperty
    colorNamer = pyqtProperty(object, fget=getColorNamer, fset=setColorNamer)  # type: pyqtProperty
