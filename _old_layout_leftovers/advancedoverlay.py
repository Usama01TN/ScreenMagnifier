# -*- coding: utf-8 -*-
"""
AdvancedOverlayController: connects GlobalHotkeys, ZoomOverlay and a dedicated ScreenGrabber, and persists the
game-overlay settings with QSettings.
Default hotkeys (all rebindable):
    Ctrl+Alt+Z  show / hide the zoom lens.
    Ctrl+Alt+=  zoom in            Ctrl+Alt+-  zoom out.
    Ctrl+Alt+X  pin the target at the mouse position.
    Ctrl+Alt+C  cycle the target: screen center -> pinned point -> mouse cursor.
Scope mode (lens on top of what it magnifies) uses, in order:
    1. desktop capture with the lens hidden from capture (Windows 10 2004+), verified with a probe;
    2. direct capture of the game window (PrintWindow), which can never contain the lens;
    3. otherwise the lens moves to a free screen corner.
"""
from ManyQt.QtCore import QObject, QSize, QPoint, QSettings, pyqtSignal, pyqtSlot
from ManyQt.QtGui import QCursor, QGuiApplication, QImage
from sys import path, platform
from os.path import dirname

if dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .screengrabber import ScreenGrabber, winWindowAt, winGrabWindowRect, isBlankImage
    from .zoomoverlay import ZoomOverlay
    from .hotkeys import GlobalHotkeys
except:
    from screengrabber import ScreenGrabber, winWindowAt, winGrabWindowRect, isBlankImage
    from zoomoverlay import ZoomOverlay
    from hotkeys import GlobalHotkeys

HOTKEY_ACTIONS = [
    ('toggle', 'Show / hide zoom', 'Ctrl+Alt+Z'),
    ('zoomIn', 'Zoom in', 'Ctrl+Alt+='),
    ('zoomOut', 'Zoom out', 'Ctrl+Alt+-'),
    ('pinTarget', 'Pin target at mouse', 'Ctrl+Alt+X'),
    ('cycleTarget', 'Cycle target', 'Ctrl+Alt+C'),
]  # type: list[tuple[str, str, str]]


def toBool(value, default=False):
    """
    QSettings returns 'true' / 'false' strings with the INI backend.
    :param value: any
    :param default: bool
    :return: bool
    """
    if value is None:
        return default
    if hasattr(value, 'encode'):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


class AdvancedOverlayController(QObject):
    """
    AdvancedOverlayController class.
    """
    settingsChanged = pyqtSignal()  # type: pyqtSignal
    overlayToggled = pyqtSignal(bool)  # type: pyqtSignal
    hotkeyTriggered = pyqtSignal('QString')  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param processor: (callable | None) Upscaler for the lens, f(QImage, QSize) -> QImage.
        :param settings: (QSettings | None) Where to persist; default organisation/application names.
        :param args: any
        :param kwargs: any
        """
        processor = kwargs.pop('processor', None)  # type: callable | None
        settings = kwargs.pop('settings', None)  # type: QSettings | None
        super(AdvancedOverlayController, self).__init__(*args, **kwargs)
        self.__m_settings = settings if settings is not None else QSettings('ScreenMagnifier', 'GameOverlay')
        s = self.__m_settings  # type: QSettings
        self.__m_overlay = ZoomOverlay(
            zoom=float(s.value('zoom', 2.5)),
            lensSize=QSize(int(s.value('lensWidth', 380)), int(s.value('lensHeight', 380))),
            target=int(s.value('target', int(ZoomOverlay.Center))),
            targetPoint=QPoint(int(s.value('targetX', 0)), int(s.value('targetY', 0))),
            placement=int(s.value('placement', int(ZoomOverlay.OnTarget if ZoomOverlay.canExcludeFromCapture()
                                                   else ZoomOverlay.TopRight))),
            shape=int(s.value('shape', int(ZoomOverlay.Circle))),
            showCrosshair=toBool(s.value('crosshair', True), True),
            lensOpacity=float(s.value('opacity', 1.0)),
            processor=processor, overlayToggled=self._onToggled)  # type: ZoomOverlay
        self.__m_grabber = ScreenGrabber(fps=int(s.value('fps', 60)), frameReady=self.__m_overlay.setFrame,
                                         parent=self)  # type: ScreenGrabber
        bindings = {}  # type: dict
        for name, title, default in HOTKEY_ACTIONS:
            seq = s.value('hotkeys/' + name, default)  # type: str
            if seq:
                bindings[name] = u'{}'.format(seq)
        self.__m_hotkeys = GlobalHotkeys(bindings=bindings, enabled=toBool(s.value('hotkeysEnabled', True), True),
                                         activated=self.onHotkey, parent=self)  # type: GlobalHotkeys
        self.__m_overlay.sourceChanged.connect(self._syncCapture)
        self.__m_tryingWindow = False  # type: bool
        self.__m_overlay.captureStatusChanged.connect(self._onCaptureStatus)
        self.__m_overlay.zoomChanged.connect(lambda z: self._save('zoom', z))

    # ---------- Helpers ----------
    def _save(self, key, value):
        """
        :param key: str | unicode | QString
        :param value: any
        :return:
        """
        self.__m_settings.setValue(key, value)
        self.settingsChanged.emit()

    def _onToggled(self, shown):
        """
        :param shown: bool
        :return:
        """
        self._syncCapture()
        self.overlayToggled.emit(bool(shown))

    @pyqtSlot()
    def _syncCapture(self):
        """
        Point the grabber at what the lens shows; run it only while the lens is visible.
        :return:
        """
        ov = self.__m_overlay  # type: ZoomOverlay
        if not ov.isVisible():
            self.__m_grabber.stop()
            return
        src = ov.sourceRect()
        if ov.getTarget() == ZoomOverlay.Cursor:
            pos = QCursor.pos()  # type: QPoint
            sc = QGuiApplication.screenAt(pos) if hasattr(QGuiApplication, 'screenAt') else None
            dpr = float((sc or QGuiApplication.primaryScreen()).devicePixelRatio())  # type: float
            self.__m_grabber.setFollowSize(QSize(int(src.width() * dpr), int(src.height() * dpr)))
            self.__m_grabber.setFollowCursor(True)
        else:
            self.__m_grabber.setFollowCursor(False)
            self.__m_grabber.setRegion(src)
        self.__m_grabber.start()

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def _onCaptureStatus(self, status):
        """
        Pick the capture engine for the lens' current status; try window capture when hiding the lens failed.
        :param status: str | unicode | QString
        :return:
        """
        ov = self.__m_overlay  # type: ZoomOverlay
        self.__m_grabber.setCaptureFunction(self._windowCapture if status == 'windowCapture' else None)
        if status == 'failed' and platform == 'win32' and not ov.isExternalSource() and \
                ov.getPlacement() == ZoomOverlay.OnTarget and not self.__m_tryingWindow:
            self.__m_tryingWindow = True  # type: bool
            try:
                self._tryWindowCapture()
            finally:
                self.__m_tryingWindow = False  # type: bool

    def _tryWindowCapture(self):
        """
        Scope mode without hiding the lens: capture the game window itself (the lens floats above it).
        :return:
        """
        ov = self.__m_overlay  # type: ZoomOverlay
        hwnd = winWindowAt(ov.targetPos())
        if not hwnd:
            ov.appendCaptureDetail('window capture: no application window under the target')
            return
        try:
            img, dpr = winGrabWindowRect(hwnd, ov.sourceRect())
        except Exception as e:
            ov.appendCaptureDetail('window capture failed: {}'.format(e))
            return
        if isBlankImage(img):
            ov.appendCaptureDetail('window capture of the game returned a black image')
            return
        ov.setExternalSource(True)  # -> status 'windowCapture' -> _windowCapture becomes the grabber.

    def _windowCapture(self, rect, background):
        """
        ScreenGrabber capture function: the application window under the rect center, looked up every frame
        so that Alt+Tab to another game keeps working.
        :param rect: QRect
        :param background: QColor
        :return: tuple[QImage, float]
        """
        hwnd = winWindowAt(rect.center())
        if hwnd:
            img, dpr = winGrabWindowRect(hwnd, rect, background)
            if not img.isNull():
                return img, dpr
        img = QImage(max(1, rect.width()), max(1, rect.height()), QImage.Format_RGB32)  # type: QImage
        img.fill(background)
        return img, 1.0

    def getCaptureEngine(self):
        """
        :return: (str | unicode | QString)'desktop' or 'window'.
        """
        return 'window' if self.__m_grabber.getCaptureFunction() is not None else 'desktop'

    # ---------- Public API ----------
    def getOverlay(self):
        """
        :return: ZoomOverlay
        """
        return self.__m_overlay

    def getGrabber(self):
        """
        :return: ScreenGrabber
        """
        return self.__m_grabber

    def getHotkeys(self):
        """
        :return: GlobalHotkeys
        """
        return self.__m_hotkeys

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def onHotkey(self, name):
        """
        :param name: str | unicode | QString
        :return:
        """
        ov = self.__m_overlay  # type: ZoomOverlay
        if name == 'toggle':
            ov.toggle()
        elif name == 'zoomIn':
            ov.zoomIn()
        elif name == 'zoomOut':
            ov.zoomOut()
        elif name == 'pinTarget':
            self.pinTarget(QCursor.pos())
        elif name == 'cycleTarget':
            self.setTarget((int(ov.getTarget()) + 1) % 3)
        self.hotkeyTriggered.emit(name)

    @pyqtSlot()
    def toggle(self):
        """
        :return:
        """
        self.__m_overlay.toggle()

    @pyqtSlot(QPoint)
    def pinTarget(self, point):
        """
        :param point: (QPoint) Global position.
        :return:
        """
        self.__m_overlay.setTargetPoint(point)
        self._save('targetX', point.x())
        self._save('targetY', point.y())
        self.setTarget(ZoomOverlay.Point)

    @pyqtSlot(int)
    def setTarget(self, target):
        """
        :param target: ZoomOverlay.Target | int
        :return:
        """
        self.__m_overlay.setTarget(target)
        self._save('target', int(target))

    @pyqtSlot(int)
    def setPlacement(self, placement):
        """
        :param placement: ZoomOverlay.Placement | int
        :return:
        """
        self.__m_overlay.setPlacement(placement)
        self._save('placement', int(placement))

    @pyqtSlot(int)
    def setShape(self, shape):
        """
        :param shape: ZoomOverlay.Shape | int
        :return:
        """
        self.__m_overlay.setShape(shape)
        self._save('shape', int(shape))

    @pyqtSlot(int)
    def setLensSize(self, size):
        """
        :param size: (int) Square lens edge in px.
        :return:
        """
        self.__m_overlay.setLensSize(QSize(int(size), int(size)))
        self._save('lensWidth', int(size))
        self._save('lensHeight', int(size))

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setZoom(self, zoom):
        """
        :param zoom: float | int
        :return:
        """
        self.__m_overlay.setZoom(zoom)

    @pyqtSlot(int)
    def setFps(self, fps):
        """
        :param fps: int
        :return:
        """
        self.__m_grabber.setFps(fps)
        self._save('fps', int(fps))

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setCrosshair(self, on):
        """
        :param on: bool
        :return:
        """
        self.__m_overlay.setShowCrosshair(bool(on))
        self._save('crosshair', bool(on))

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setOpacity(self, opacity):
        """
        :param opacity: float | int
        :return:
        """
        self.__m_overlay.setLensOpacity(opacity)
        self._save('opacity', float(opacity))

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setHotkeysEnabled(self, enabled):
        """
        :param enabled: bool
        :return:
        """
        self.__m_hotkeys.setEnabled(bool(enabled))
        self._save('hotkeysEnabled', bool(enabled))

    def isHotkeysEnabled(self):
        """
        :return: (bool) The saved preference (hotkeys may be suspended temporarily while recording one).
        """
        return toBool(self.__m_settings.value('hotkeysEnabled', True), True)

    def setHotkey(self, name, sequence):
        """
        :param name: str | unicode | QString
        :param sequence: (str | unicode | QString)Qt portable text, '' to unbind.
        :return:
        """
        self.__m_hotkeys.setBinding(name, sequence)
        self._save('hotkeys/' + name, sequence)

    def getHotkey(self, name):
        """
        :param name: str | unicode | QString
        :return: str | unicode | QString
        """
        return self.__m_hotkeys.getBindings().get(name, '')

    @pyqtSlot()
    def shutdown(self):
        """
        :return:
        """
        self.__m_overlay.hideOverlay()
        self.__m_grabber.stop()
        self.__m_hotkeys.shutdown()
        self.__m_overlay.close()
        self.__m_settings.sync()
