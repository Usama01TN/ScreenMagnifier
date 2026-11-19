# -*- coding: utf-8 -*-
"""
ScreenGrabber: live capture of a screen region at a fixed frame rate.
- Fixed-region mode: captures region (global, device-independent coordinates).
- Follow-cursor mode: captures a followSize area (in output image pixels) centred on the mouse cursor.
- Multi-monitor: regions spanning several screens are composed of each screen's grab.
- HiDPI: frames are delivered in physical pixels of the screen under the region center.
- Windows/macOS/X11 supported by Qt's QScreen.grabWindow; Wayland compositors usually refuse
  screen grabs, in which case captureFailed is emitted once.
- captureFunction: plug in another capture method, e.g. winGrabWindowRect() which captures one application
  window directly with PrintWindow, so overlays drawn above it (a magnifier lens) are never captured.
"""
from ManyQt.QtCore import Qt, QTimer, QElapsedTimer, QRect, QRectF, QSize, QPoint, QObject, pyqtSignal, pyqtSlot, \
    pyqtProperty
from ManyQt.QtGui import QImage, QPainter, QColor, QCursor, QGuiApplication
from sys import platform
from os import getpid


def screenAtPoint(point):
    """
    :param point: QPoint
    :return: QScreen
    """
    screen = QGuiApplication.screenAt(point) if hasattr(QGuiApplication, 'screenAt') else None
    return screen if screen is not None else QGuiApplication.primaryScreen()


_WIN = {}  # type: dict  # Lazily created ctypes handles for the Windows window-capture helpers.


def _winApi():
    """
    Private user32 / gdi32 / dwmapi handles with 64-bit safe prototypes.
    :return: dict
    """
    if _WIN:
        return _WIN
    from ctypes import WinDLL, POINTER, c_long, c_void_p, c_int
    from ctypes.wintypes import BOOL, UINT, DWORD, RECT
    u = WinDLL('user32', use_last_error=True)
    g = WinDLL('gdi32', use_last_error=True)
    H = c_void_p
    for name, args, res in (('GetTopWindow', [H], H), ('GetWindow', [H, UINT], H),
                            ('IsWindowVisible', [H], BOOL), ('IsIconic', [H], BOOL),
                            ('GetWindowThreadProcessId', [H, POINTER(DWORD)], DWORD),
                            ('GetWindowLongW', [H, c_int], c_long),
                            ('GetWindowRect', [H, POINTER(RECT)], BOOL),
                            ('GetDC', [H], H), ('ReleaseDC', [H, H], c_int),
                            ('PrintWindow', [H, H, UINT], BOOL)):
        f = getattr(u, name)
        f.argtypes, f.restype = args, res
    for name, args, res in (('CreateCompatibleDC', [H], H), ('CreateCompatibleBitmap', [H, c_int, c_int], H),
                            ('SelectObject', [H, H], H), ('DeleteObject', [H], BOOL),
                            ('DeleteDC', [H], BOOL), ('GdiFlush', [], BOOL),
                            ('BitBlt', [H, c_int, c_int, c_int, c_int, H, c_int,
                                        c_int, DWORD], BOOL),
                            ('PatBlt', [H, c_int, c_int, c_int, c_int, DWORD],
                             BOOL),
                            ('CreateDIBSection', [H, c_void_p, UINT, POINTER(c_void_p), H, DWORD], H)):
        f = getattr(g, name)
        f.argtypes, f.restype = args, res
    try:
        d = WinDLL('dwmapi')
        d.DwmGetWindowAttribute.argtypes = [H, DWORD, c_void_p, DWORD]
        d.DwmGetWindowAttribute.restype = c_long
    except Exception:
        d = None
    _WIN.update(user32=u, gdi32=g, dwmapi=d)
    return _WIN


def toPhysical(point):
    """
    Qt (device-independent) global point -> Windows physical pixels (Qt keeps each screen's origin unscaled).
    :param point: QPoint
    :return: (tuple[int, int, float]) x, y and the device pixel ratio of that screen.
    """
    screen = screenAtPoint(point)
    sg = screen.geometry()  # type: QRect
    dpr = float(screen.devicePixelRatio())  # type: float
    return int(round(sg.x() + (point.x() - sg.x()) * dpr)), int(round(sg.y() + (point.y() - sg.y()) * dpr)), dpr


def winWindowAt(point):
    """
    Topmost real application window under a global point, ignoring this process' windows, click-through
    overlays (WS_EX_TRANSPARENT), tool windows and cloaked windows. Windows only.
    :param point: QPoint
    :return: (int | None) HWND
    """
    if platform != 'win32':
        return None
    try:
        from ctypes.wintypes import DWORD, RECT
        from ctypes import byref
        api = _winApi()
        u, d = api['user32'], api['dwmapi']
        px, py, dpr = toPhysical(point)
        pid = getpid()  # type: int
        GW_HWNDNEXT, GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, DWMWA_CLOAKED = 2, -20, 0x20, 0x80, 14
        hwnd = u.GetTopWindow(None)
        for _ in range(10000):
            if not hwnd:
                break
            if u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd):
                owner = DWORD(0)
                u.GetWindowThreadProcessId(hwnd, byref(owner))
                ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE)  # type: int
                if owner.value != pid and not ex & (WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW):
                    cloaked = DWORD(0)
                    if d is not None:
                        d.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, byref(cloaked), 4)
                    r = RECT()
                    if not cloaked.value and u.GetWindowRect(
                            hwnd, byref(r)) and r.left <= px < r.right and r.top <= py < r.bottom:
                        return hwnd
            hwnd = u.GetWindow(hwnd, GW_HWNDNEXT)
    except Exception:
        pass
    return None


def winGrabWindowRect(hwnd, rect, background=QColor(16, 16, 20)):
    """
    Capture the part of one window that lies under a global rect with PrintWindow(PW_RENDERFULLCONTENT).
    Windows drawn ON TOP of that window (such as a magnifier lens) are never part of the result.
    :param hwnd: (int) Window to capture.
    :param rect: (QRect) Global, device-independent rect.
    :param background: QColor
    :return: (tuple[QImage, float | int]) Image in physical pixels (null on failure) and the device pixel ratio.
    """
    if platform != 'win32' or not hwnd or rect.isEmpty():
        return QImage(), 1.0
    from ctypes import c_long, c_void_p, byref, Structure, sizeof, string_at
    from ctypes.wintypes import WORD, DWORD, RECT
    api = _winApi()
    u, g = api['user32'], api['gdi32']
    x0, y0, dpr = toPhysical(rect.topLeft())
    pw, ph = max(1, int(round(rect.width() * dpr))), max(1, int(round(rect.height() * dpr)))  # type: int, int
    r = RECT()
    if not u.GetWindowRect(hwnd, byref(r)):
        return QImage(), dpr
    ww, wh = r.right - r.left, r.bottom - r.top  # type: int, int
    if ww <= 0 or wh <= 0:
        return QImage(), dpr

    class BITMAPINFOHEADER(Structure):
        """
        BITMAPINFOHEADER structure.
        """
        _fields_ = [('biSize', DWORD), ('biWidth', c_long), ('biHeight', c_long), ('biPlanes', WORD),
                    ('biBitCount', WORD), ('biCompression', DWORD), ('biSizeImage', DWORD),
                    ('biXPelsPerMeter', c_long), ('biYPelsPerMeter', c_long), ('biClrUsed', DWORD),
                    ('biClrImportant', DWORD)]

    screenDc = u.GetDC(None)
    fullDc = g.CreateCompatibleDC(screenDc)
    fullBmp = g.CreateCompatibleBitmap(screenDc, ww, wh)
    oldFull = g.SelectObject(fullDc, fullBmp)
    cropDc = g.CreateCompatibleDC(screenDc)
    bmi = BITMAPINFOHEADER(sizeof(BITMAPINFOHEADER), pw, -ph, 1, 32, 0, 0, 0, 0, 0, 0)  # Top-down BGRA.
    bits = c_void_p()
    dib = g.CreateDIBSection(cropDc, byref(bmi), 0, byref(bits), None, 0)
    image = QImage()  # type: QImage
    try:
        if dib and bits.value:
            oldCrop = g.SelectObject(cropDc, dib)
            PW_RENDERFULLCONTENT, SRCCOPY, BLACKNESS = 0x2, 0x00CC0020, 0x00000042
            ok = u.PrintWindow(hwnd, fullDc, PW_RENDERFULLCONTENT)
            g.PatBlt(cropDc, 0, 0, pw, ph, BLACKNESS)
            if ok:
                g.BitBlt(cropDc, 0, 0, pw, ph, fullDc, x0 - r.left, y0 - r.top, SRCCOPY)
                g.GdiFlush()
                data = string_at(bits.value, pw * ph * 4)  # type: bytes
                image = QImage(data, pw, ph, pw * 4, QImage.Format_RGB32).copy()
            g.SelectObject(cropDc, oldCrop)
    finally:
        if dib:
            g.DeleteObject(dib)
        g.SelectObject(fullDc, oldFull)
        g.DeleteObject(fullBmp)
        g.DeleteDC(fullDc)
        g.DeleteDC(cropDc)
        u.ReleaseDC(None, screenDc)
    return image, dpr


def isBlankImage(image):
    """
    :param image: QImage
    :return: (bool) True when the image is null or (almost) entirely black, e.g. a failed window capture.
    """
    if image.isNull():
        return True
    w, h = image.width(), image.height()  # type: int, int
    for j in range(1, 8):
        for i in range(1, 8):
            if QColor(image.pixel(min(w - 1, w * i // 8), min(h - 1, h * j // 8))).value() > 6:
                return False
    return True


def globalRect(widget):
    """
    :param widget: QWidget
    :return: (QRect) Widget area in global coordinates (frame included for top-level windows).
    """
    if widget.isWindow():
        return widget.frameGeometry()
    return QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())


class ScreenGrabber(QObject):
    """
    ScreenGrabber class.
    """
    frameReady = pyqtSignal(QImage)  # type: pyqtSignal
    captureFailed = pyqtSignal('QString')  # type: pyqtSignal
    regionChanged = pyqtSignal(QRect)  # type: pyqtSignal
    activeChanged = pyqtSignal(bool)  # type: pyqtSignal
    fpsChanged = pyqtSignal(int)  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param region: (QRect) Global region to capture in fixed mode.
        :param fps: (int) Frames per second, 1 .. 120.
        :param followCursor: (bool) Capture around the mouse cursor instead of region.
        :param followSize: (QSize) Follow-mode capture size in output image pixels.
        :param autoStart: bool
        :param ignoreWidgets: (list[QWidget]) In follow mode, frames are not grabbed while the cursor is over
            one of these windows (prevents the "hall of mirrors" effect on the magnifier itself).
        :param background: (QColor | Qt.GlobalColor | int | str) Fill colour for areas outside every screen.
        :param captureFunction: (callable | None) f(QRect, QColor) -> (QImage, float) replacing the desktop grab.
        :param frameReady: callable | None
        :param captureFailed: callable | None
        :param args: any
        :param kwargs: any
        """
        region = kwargs.pop('region', QRect())  # type: QRect
        fps = kwargs.pop('fps', 30)  # type: int
        followCursor = kwargs.pop('followCursor', False)  # type: bool
        followSize = kwargs.pop('followSize', QSize(240, 160))  # type: QSize
        autoStart = kwargs.pop('autoStart', False)  # type: bool
        ignoreWidgets = kwargs.pop('ignoreWidgets', [])  # type: list
        background = kwargs.pop('background', QColor(16, 16, 20))  # type: QColor
        captureFunction = kwargs.pop('captureFunction', None)  # type: callable | None
        frameReady = kwargs.pop('frameReady', None)  # type: callable | None
        captureFailed = kwargs.pop('captureFailed', None)  # type: callable | None
        super(ScreenGrabber, self).__init__(*args, **kwargs)
        if callable(frameReady):
            self.frameReady.connect(frameReady)
        if callable(captureFailed):
            self.captureFailed.connect(captureFailed)
        # Options.
        self.__m_region = QRect(region)  # type: QRect
        self.__m_fps = max(1, min(120, int(fps)))  # type: int
        self.__m_followCursor = bool(followCursor)  # type: bool
        self.__m_followSize = QSize(max(1, followSize.width()), max(1, followSize.height()))  # type: QSize
        self.__m_ignoreWidgets = list(ignoreWidgets)  # type: list
        self.__m_background = background if isinstance(background, QColor) else QColor(background)  # type: QColor
        self.__m_captureFunction = captureFunction if callable(captureFunction) else None  # type: callable | None
        # State.
        self.__m_captureRect = QRect()  # type: QRect
        self.__m_devicePixelRatio = 1.0  # type: float
        self.__m_lastGrabMs = 0.0  # type: float
        self.__m_failed = False  # type: bool
        self.__m_frameCount = 0  # type: int
        self.__m_clock = QElapsedTimer()  # type: QElapsedTimer
        self.__m_timer = QTimer(self)  # type: QTimer
        self.__m_timer.setTimerType(Qt.PreciseTimer)
        self.__m_timer.timeout.connect(self._tick)
        if autoStart:
            self.start()

    # ---------- Helpers ----------
    @staticmethod
    def virtualGeometry():
        """
        :return: (QRect) Union of all screen geometries.
        """
        rect = QRect()  # type: QRect
        for screen in QGuiApplication.screens():
            rect = rect.united(screen.geometry())  # type: QRect
        return rect

    @staticmethod
    def grabRect(rect, background=QColor(16, 16, 20)):
        """
        Grab a global rect, composing every screen it touches, in physical pixels.
        :param rect: QRect
        :param background: QColor
        :return: (tuple[QImage, float]) Image (null on failure) and the device pixel ratio used.
        """
        if rect.isEmpty():
            return QImage(), 1.0
        dpr = float(screenAtPoint(rect.center()).devicePixelRatio())  # type: float
        img = QImage(max(1, int(round(rect.width() * dpr))), max(1, int(round(rect.height() * dpr))),
                     QImage.Format_RGB32)  # type: QImage
        img.fill(background)
        p = QPainter(img)  # type: QPainter
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        grabbed = False  # type: bool
        for screen in QGuiApplication.screens():
            geo = screen.geometry()  # type: QRect
            inter = geo.intersected(rect)  # type: QRect
            if inter.isEmpty():
                continue
            pm = screen.grabWindow(0, inter.x() - geo.x(), inter.y() - geo.y(), inter.width(), inter.height())
            if pm.isNull() or pm.width() == 0:
                continue
            pm.setDevicePixelRatio(1.0)
            target = QRectF((inter.x() - rect.x()) * dpr, (inter.y() - rect.y()) * dpr,
                            inter.width() * dpr, inter.height() * dpr)  # type: QRectF
            p.drawPixmap(target, pm, QRectF(0, 0, pm.width(), pm.height()))
            grabbed = True  # type: bool
        p.end()
        return (img if grabbed else QImage()), dpr

    def _followRect(self):
        """
        :return: (QRect | None) Follow-mode capture rect, None when the cursor is over an ignored widget.
        """
        pos = QCursor.pos()  # type: QPoint
        for w in self.__m_ignoreWidgets:
            try:
                if w.isVisible() and globalRect(w).contains(pos):
                    return None
            except Exception:
                continue
        dpr = float(screenAtPoint(pos).devicePixelRatio())  # type: float
        w = max(1, int(round(self.__m_followSize.width() / dpr)))  # type: int
        h = max(1, int(round(self.__m_followSize.height() / dpr)))  # type: int
        return QRect(pos.x() - w // 2, pos.y() - h // 2, w, h)

    # ---------- Grab tick ----------
    def _tick(self):
        """
        :return: None
        """
        rect = self._followRect() if self.__m_followCursor else QRect(self.__m_region)  # type: QRect | None
        if rect is None or rect.isEmpty():
            return
        self.__m_clock.start()
        grab = self.__m_captureFunction or ScreenGrabber.grabRect
        try:
            img, dpr = grab(rect, self.__m_background)
        except Exception:
            img, dpr = QImage(), 1.0
        self.__m_lastGrabMs = float(self.__m_clock.nsecsElapsed()) / 1e6  # type: float
        if img.isNull():
            if not self.__m_failed:
                self.__m_failed = True  # type: bool
                self.captureFailed.emit('Screen capture returned no image. On Wayland, start the app with '
                                        'QT_QPA_PLATFORM=xcb; on macOS, allow Screen Recording permission.')
            return
        self.__m_failed = False  # type: bool
        self.__m_captureRect = rect  # type: QRect
        self.__m_devicePixelRatio = dpr  # type: float
        self.__m_frameCount += 1
        self.frameReady.emit(img)

    # ---------- Public API ----------
    @pyqtSlot()
    def start(self):
        """
        :return:
        """
        if not self.__m_timer.isActive():
            self.__m_timer.start(int(round(1000.0 / self.__m_fps)))
            self._tick()
            self.activeChanged.emit(True)

    @pyqtSlot()
    def stop(self):
        """
        :return:
        """
        if self.__m_timer.isActive():
            self.__m_timer.stop()
            self.activeChanged.emit(False)

    @pyqtSlot()
    def grabNow(self):
        """
        Grab a single frame immediately (works while stopped).
        :return:
        """
        self._tick()

    def isActive(self):
        """
        :return: bool
        """
        return self.__m_timer.isActive()

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setActive(self, active):
        """
        :param active: bool
        :return:
        """
        self.start() if active else self.stop()

    def getRegion(self):
        """
        :return: QRect
        """
        return QRect(self.__m_region)

    @pyqtSlot(QRect)
    def setRegion(self, region):
        """
        :param region: QRect
        :return:
        """
        region = QRect(region).normalized()  # type: QRect
        if region != self.__m_region:
            self.__m_region = region  # type: QRect
            self.regionChanged.emit(QRect(region))

    def getFps(self):
        """
        :return: int
        """
        return self.__m_fps

    @pyqtSlot(int)
    def setFps(self, fps):
        """
        :param fps: (int) 1 .. 120
        :return:
        """
        fps = max(1, min(120, int(fps)))  # type: int
        if fps != self.__m_fps:
            self.__m_fps = fps  # type: int
            if self.__m_timer.isActive():
                self.__m_timer.setInterval(int(round(1000.0 / fps)))
            self.fpsChanged.emit(fps)

    def isFollowCursor(self):
        """
        :return: bool
        """
        return self.__m_followCursor

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setFollowCursor(self, followCursor):
        """
        :param followCursor: bool
        :return:
        """
        self.__m_followCursor = bool(followCursor)  # type: bool

    def getFollowSize(self):
        """
        :return: QSize
        """
        return QSize(self.__m_followSize)

    @pyqtSlot(QSize)
    def setFollowSize(self, followSize):
        """
        :param followSize: (QSize) In output image pixels.
        :return:
        """
        self.__m_followSize = QSize(max(1, followSize.width()), max(1, followSize.height()))  # type: QSize

    def getIgnoreWidgets(self):
        """
        :return: list[QWidget]
        """
        return list(self.__m_ignoreWidgets)

    def setIgnoreWidgets(self, ignoreWidgets):
        """
        :param ignoreWidgets: list[QWidget]
        :return:
        """
        self.__m_ignoreWidgets = list(ignoreWidgets)  # type: list

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

    def getCaptureFunction(self):
        """
        :return: callable | None
        """
        return self.__m_captureFunction

    @pyqtSlot(object)
    def setCaptureFunction(self, captureFunction):
        """
        :param captureFunction: (callable | None) f(QRect, QColor) -> (QImage, float); None = desktop grab.
        :return:
        """
        self.__m_captureFunction = captureFunction if callable(captureFunction) else None  # type: callable | None

    def getCaptureRect(self):
        """
        :return: (QRect) Global rect of the last delivered frame.
        """
        return QRect(self.__m_captureRect)

    def getDevicePixelRatio(self):
        """
        :return: (float | int) Image pixels per logical pixel of the last frame.
        """
        return self.__m_devicePixelRatio

    def getLastGrabTime(self):
        """
        :return: (float | int) ms spent in the last grab.
        """
        return self.__m_lastGrabMs

    def getFrameCount(self):
        """
        :return: int
        """
        return self.__m_frameCount

    def mapToGlobal(self, imagePoint):
        """
        Map a pixel of the last frame to global screen coordinates.
        :param imagePoint: QPoint
        :return: QPoint
        """
        dpr = self.__m_devicePixelRatio  # type: float
        return QPoint(self.__m_captureRect.x() + int(imagePoint.x() / dpr),
                      self.__m_captureRect.y() + int(imagePoint.y() / dpr))

    # ---------- Properties ----------
    region = pyqtProperty(QRect, fget=getRegion, fset=setRegion, notify=regionChanged)  # type: pyqtProperty
    fps = pyqtProperty(int, fget=getFps, fset=setFps, notify=fpsChanged)  # type: pyqtProperty
    followCursor = pyqtProperty(bool, fget=isFollowCursor, fset=setFollowCursor)  # type: pyqtProperty
    followSize = pyqtProperty(QSize, fget=getFollowSize, fset=setFollowSize)  # type: pyqtProperty
    active = pyqtProperty(bool, fget=isActive, fset=setActive, notify=activeChanged)  # type: pyqtProperty
    background = pyqtProperty(QColor, fget=getBackground, fset=setBackground)  # type: pyqtProperty
    captureFunction = pyqtProperty(object, fget=getCaptureFunction, fset=setCaptureFunction)  # type: pyqtProperty
