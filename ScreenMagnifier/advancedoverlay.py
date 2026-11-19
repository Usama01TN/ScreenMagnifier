# -*- coding: utf-8 -*-
"""
AdvancedOverlayController: connects GlobalHotkeys, ZoomOverlay and a dedicated ScreenGrabber, and persists the
game-overlay settings with QSettings.
Default hotkeys (all rebindable):
    Ctrl+Alt+Z  show / hide the zoom lens.
    Ctrl+Alt+=  zoom in            Ctrl+Alt+-  zoom out.
    Ctrl+Alt+X  pin the target at the mouse position.
    Ctrl+Alt+C  cycle the target: screen center -> pinned point -> mouse cursor.
    Ctrl+Alt+K  copy the zoomer color code (when "Color code under the crosshair" is on).
    Ctrl+Alt+P  screen color picker: a live zoom follows the mouse, click anywhere to copy.
    All hotkeys are defined in shortcuts.py and editable in the Shortcuts tab.
Scope mode (lens on top of what it magnifies) uses, in order:
    1. desktop capture with the lens hidden from capture (Windows 10 2004+), verified with a probe;
    2. direct capture of the game window (PrintWindow), which can never contain the lens;
    3. otherwise the lens moves to a free screen corner.
"""
from ManyQt.QtCore import QRect, Qt, QObject, QSize, QPoint, QSettings, QTimer, pyqtSignal, pyqtSlot
from ManyQt.QtGui import QCursor, QGuiApplication, QImage
from sys import path, platform
from os.path import dirname

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .screengrabber import ScreenGrabber, winWindowAt, winGrabWindowRect, isBlankImage
    from .mousecatcher import GlobalMouseCatcher
    from .imagefilters import ImageFilters
    from .shortcuts import HOTKEY_ACTIONS
    from .zoomoverlay import ZoomOverlay
    from .hotkeys import GlobalHotkeys
except:
    from screengrabber import ScreenGrabber, winWindowAt, winGrabWindowRect, isBlankImage
    from mousecatcher import GlobalMouseCatcher
    from imagefilters import ImageFilters
    from shortcuts import HOTKEY_ACTIONS
    from zoomoverlay import ZoomOverlay
    from hotkeys import GlobalHotkeys


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
    colorPickRequested = pyqtSignal()  # type: pyqtSignal  # 'copyZoomerColor': copy the zoomer's readoutColor().
    screenPickRequested = pyqtSignal(QPoint)  # type: pyqtSignal  # picker: copy the screen pixel at this position
    pickerToggled = pyqtSignal(bool)  # type: pyqtSignal
    message = pyqtSignal('QString')  # type: pyqtSignal

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
        self.__m_filters = ImageFilters(effect=int(s.value('filterEffect', 0)),
                                        brightness=int(s.value('filterBrightness', 0)),
                                        contrast=int(s.value('filterContrast', 0)),
                                        saturation=int(s.value('filterSaturation', 0)),
                                        strength=int(s.value('filterStrength', 100)),
                                        changed=self._filtersChanged)  # type: ImageFilters
        self.__m_upscale = processor  # type: callable | None
        self.__m_overlay = ZoomOverlay(
            zoom=float(s.value('zoom', 2.5)),
            lensSize=QSize(int(s.value('lensWidth', 380)), int(s.value('lensHeight', 380))),
            target=int(s.value('target', int(ZoomOverlay.Center))),
            targetPoint=QPoint(int(s.value('targetX', 0)), int(s.value('targetY', 0))),
            placement=int(s.value('placement', int(ZoomOverlay.OnTarget if ZoomOverlay.canExcludeFromCapture()
                                                   else ZoomOverlay.TopRight))),
            shape=int(s.value('shape', int(ZoomOverlay.Circle))),
            cornerRadius=int(s.value('cornerRadius', 45)),
            customRect=QRect(int(s.value('customX', 0)), int(s.value('customY', 0)), int(s.value('customW', 0)),
                             int(s.value('customH', 0))),
            fullScreenIndex=int(s.value('fullScreen', -1)),
            showCrosshair=toBool(s.value('crosshair', True), True),
            lensOpacity=float(s.value('opacity', 1.0)),
            processor=self._process, overlayToggled=self._onToggled)  # type: ZoomOverlay
        self.__m_grabber = ScreenGrabber(fps=int(s.value('fps', 60)), frameReady=self.__m_overlay.setFrame,
                                         parent=self)  # type: ScreenGrabber
        bindings = {}  # type: dict
        old = self.__m_settings.value('hotkeys/copyColor', None)  # Earlier versions: one hotkey for both actions.
        if old is not None:
            if self.__m_settings.value('hotkeys/screenPicker', None) is None:
                self.__m_settings.setValue('hotkeys/screenPicker', old)
            self.__m_settings.remove('hotkeys/copyColor')
        for name, title, default in HOTKEY_ACTIONS:
            seq = s.value('hotkeys/' + name, default)  # type: str
            if seq:
                bindings[name] = u'{}'.format(seq)
        self.__m_hotkeys = GlobalHotkeys(bindings=bindings, enabled=toBool(s.value('hotkeysEnabled', True), True),
                                         activated=self.onHotkey, parent=self)  # type: GlobalHotkeys
        self.__m_overlay.sourceChanged.connect(self._syncCapture)
        self.__m_tryingWindow = False  # type: bool
        self.__m_overlay.captureStatusChanged.connect(self._onCaptureStatus)
        self.__m_overlay.zoomChanged.connect(
            lambda z: None if self.__m_pickState is not None else self._save('zoom', z))
        self.__m_overlay.setShowColorReadout(toBool(self.__m_settings.value('colorReadout', False), False))  # opt-in
        self.__m_pickState = None  # type: dict | None  # Lens settings to restore after the screen color picker.
        self.__m_catcher = GlobalMouseCatcher(clicked=self._onPickerClick, keyPressed=self._onPickerKey,
                                              wheelTurned=lambda d: self.__m_overlay.setZoom(
                                                  self.__m_overlay.getZoom() * 1.25 ** (d / 120.0)),
                                              parent=self)  # type: GlobalMouseCatcher

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
        if shown and self.__m_overlay.getPlacement() == ZoomOverlay.FullScreen:  # it covers everything
            self._tell(self.tr(u'Full-screen zoom: press {} to hide it.').format(self.getHotkey('toggle') or '-'))

    def _syncCapture(self):
        """
        Point the grabber at what the lens shows; run it only while the lens is visible.
        :return: None
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
        if status in ('failed', 'otherScreen') and platform == 'win32' and not ov.isExternalSource() and \
                ov.getPlacement() in (ZoomOverlay.OnTarget, ZoomOverlay.Custom, ZoomOverlay.FullScreen) and \
                not self.__m_tryingWindow:  # capturing the game window keeps the lens where it was asked
            self.__m_tryingWindow = True  # type: bool
            try:
                self._tryWindowCapture()
            finally:
                self.__m_tryingWindow = False  # type: bool

    def _tryWindowCapture(self):
        """
        Scope mode without hiding the lens: capture the game window itself (the lens floats above it).
        :return: None
        """
        ov = self.__m_overlay  # type: ZoomOverlay
        hwnd = winWindowAt(ov.targetPos())
        if not hwnd:
            ov.appendCaptureDetail(self.tr(u'Window capture: no application window under the target'))
            return
        try:
            img, dpr = winGrabWindowRect(hwnd, ov.sourceRect())
        except Exception as e:
            ov.appendCaptureDetail(self.tr(u'Window capture failed: {}').format(e))
            return
        if isBlankImage(img):
            ov.appendCaptureDetail(self.tr(u'Window capture of the game returned a black image'))
            return
        ov.setExternalSource(True)  # -> status 'windowCapture' -> _windowCapture becomes the grabber.

    @staticmethod
    def _windowCapture(rect, background):
        """
        ScreenGrabber capture function: the application window under the rect center, looked up every frame
        so that Alt+Tab to another game keeps working.
        :param rect: QRect
        :param background: QColor
        :return: tuple[QImage, float | int]
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
    def _process(self, image, size):
        """
        The lens processor: filters on the small captured frame (cheap), then the upscaler.
        :param image: QImage
        :param size: QSize
        :return: QImage
        """
        image = self.__m_filters.apply(image)  # type: QImage
        return self.__m_upscale(image, size) if self.__m_upscale else image.scaled(
            size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    @pyqtSlot()
    def _filtersChanged(self):
        """
        :return:
        """
        f = self.__m_filters  # type: ImageFilters
        for key, value in (('filterEffect', f.getEffect()), ('filterBrightness', f.getBrightness()),
                           ('filterContrast', f.getContrast()), ('filterSaturation', f.getSaturation()),
                           ('filterStrength', f.getStrength())):
            self._save(key, value)
        if hasattr(self, '_AdvancedOverlayController__m_overlay'):
            self.__m_overlay.refresh()

    def getFilters(self):
        """
        :return: (ImageFilters) The zoomer's color filters.
        """
        return self.__m_filters

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
            if self.__m_pickState is not None:
                self.stopColorPicker()  # Hiding the lens while picking cancels the picker (and frees the mouse).
            else:
                ov.toggle()
        elif name == 'zoomIn':
            ov.zoomIn()
        elif name == 'zoomOut':
            ov.zoomOut()
        elif name == 'pinTarget':
            self.pinTarget(QCursor.pos())
        elif name == 'cycleTarget':
            self.setTarget((int(ov.getTarget()) + 1) % 3)
        elif name == 'screenPicker':  # One meaning: the screen color picker (start, or copy while it runs).
            if self.__m_pickState is not None:
                self.screenPickRequested.emit(QCursor.pos())
            else:
                self.startColorPicker()
        elif name == 'copyZoomerColor':  # One meaning: copy the zoomer's color code (only when it is shown).
            if self.__m_pickState is not None:
                self.screenPickRequested.emit(QCursor.pos())
            elif not ov.isVisible():
                self._tell(self.tr(u'The zoomer is hidden: show it with {}, or use the screen color picker ({}).')
                           .format(self.getHotkey('toggle') or '-', self.getHotkey('screenPicker') or '-'))
            elif not ov.isShowColorReadout():
                self._tell(self.tr(u'The zoomer color code is off: turn on "Color code under the crosshair" in the '
                                   'Zoomer tab.'))
            else:
                self.colorPickRequested.emit()
        elif name == 'pickerCancel':
            self.stopColorPicker()
        self.hotkeyTriggered.emit(name)

    @pyqtSlot()
    def toggle(self):
        """
        :return:
        """
        if self.__m_pickState is not None:
            self.stopColorPicker()
        else:
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

    @pyqtSlot(QRect)
    def setCustomRect(self, rect):
        """
        :param rect: (QRect) Lens rect of the Custom placement (global, device-independent px).
        :return:
        """
        self.__m_overlay.setCustomRect(rect)
        r = self.__m_overlay.getCustomRect()  # type: QRect
        for key, value in (('customX', r.x()), ('customY', r.y()), ('customW', r.width()), ('customH', r.height())):
            self._save(key, value)

    @pyqtSlot(int)
    def setFullScreenIndex(self, index):
        """
        :param index: (int) Screen of the FullScreen placement, -1 = the screen of the target.
        :return:
        """
        self.__m_overlay.setFullScreenIndex(index)
        self._save('fullScreen', int(index))

    @pyqtSlot(int)
    def setCornerRadius(self, radius):
        """
        :param radius: (int) Corner radius of the rounded-square lens in px.
        :return:
        """
        self.__m_overlay.setCornerRadius(radius)
        self._save('cornerRadius', int(radius))

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

    def _tell(self, text):
        """
        Explain why a hotkey did nothing - after the generic "hotkey pressed" notice, so it is the one shown.
        :param text: str | unicode | QString
        :return:
        """
        QTimer.singleShot(0, lambda: self.message.emit(text))

    # ---------- Screen color picker ----------
    def isColorPicking(self):
        """
        :return: bool
        """
        return self.__m_pickState is not None

    @pyqtSlot()
    def startColorPicker(self):
        """
        Screen color picker: a pixel-exact lens follows the mouse anywhere on the screen with the live color of
        the pixel under the crosshair; left click (anywhere) or the hotkey copies, right click / Esc cancels,
        wheel zooms, arrows move 1 px (Linux).
        :return: None
        """
        if self.__m_pickState is not None:
            return
        ov = self.__m_overlay  # type: ZoomOverlay
        self.__m_pickState = {'visible': ov.isVisible(), 'target': ov.getTarget(), 'placement': ov.getPlacement(),
                              'zoom': ov.getZoom(), 'lensSize': ov.getLensSize(), 'pixelated': ov.isPixelated(),
                              'readout': ov.isShowColorReadout(), 'fps': self.__m_grabber.getFps()}  # type: dict
        ov.hideOverlay()
        ov.setTarget(ZoomOverlay.Cursor)
        ov.setPlacement(ZoomOverlay.NearTarget)
        ov.setZoom(10.0)
        ov.setLensSize(QSize(180, 180))
        ov.setPixelated(True)
        ov.setShowColorReadout(True)
        self.__m_grabber.setFps(60)
        ov.showOverlay()
        if not self.__m_catcher.start():
            self.message.emit(self.__m_catcher.getError() + ' - press {} again to copy.'.format(
                self.getHotkey('screenPicker') or 'the hotkey'))
        if self.__m_catcher.getBackendName() != 'qtgrab':  # Esc while another application has the keyboard.
            self.__m_hotkeys.setBinding('pickerCancel', 'Esc')
        self.pickerToggled.emit(True)

    @pyqtSlot()
    def stopColorPicker(self, delayMs=0):
        """
        :param delayMs: (int) Keep the lens visible this long (e.g. to show the "copied" message).
        :return: None
        """
        if self.__m_pickState is None:
            return
        self.__m_catcher.stop()
        if 'pickerCancel' in self.__m_hotkeys.getBindings():
            self.__m_hotkeys.setBinding('pickerCancel', '')
        if delayMs > 0:
            QTimer.singleShot(int(delayMs), self.stopColorPicker)
            self.__m_pickState['delayed'] = True
            return
        state, self.__m_pickState = self.__m_pickState, None
        ov = self.__m_overlay  # type: ZoomOverlay
        ov.hideOverlay()
        ov.setTarget(state['target'])
        ov.setPlacement(state['placement'])
        ov.setZoom(state['zoom'])
        ov.setLensSize(state['lensSize'])
        ov.setPixelated(state['pixelated'])
        ov.setShowColorReadout(state['readout'])
        self.__m_grabber.setFps(state['fps'])
        if state['visible']:
            ov.showOverlay()
        self.pickerToggled.emit(False)

    def _onPickerClick(self, pos, button):
        """
        :param pos: QPoint
        :param button: int
        :return:
        """
        if button == 1:
            self.screenPickRequested.emit(pos)
        else:
            self.stopColorPicker()

    def _onPickerKey(self, key):
        """
        :param key: (int) Qt key (keyboard grabbed by the qtgrab backend).
        :return:
        """
        steps = {int(Qt.Key_Left): (-1, 0), int(Qt.Key_Right): (1, 0), int(Qt.Key_Up): (0, -1),
                 int(Qt.Key_Down): (0, 1)}  # type: dict
        if key == int(Qt.Key_Escape):
            self.stopColorPicker()
        elif key in (int(Qt.Key_Return), int(Qt.Key_Enter), int(Qt.Key_Space)):
            self.screenPickRequested.emit(QCursor.pos())
        elif key in steps:
            QCursor.setPos(QCursor.pos() + QPoint(*steps[key]))

    def setColorReadout(self, on):
        """
        :param on: (bool) Live color code of the crosshair pixel in the lens (saved).
        :return:
        """
        self.__m_overlay.setShowColorReadout(on)
        self._save('colorReadout', bool(on))

    @pyqtSlot()
    def shutdown(self):
        """
        :return:
        """
        self.__m_catcher.stop()
        self.__m_overlay.hideOverlay()
        self.__m_grabber.stop()
        self.__m_hotkeys.shutdown()
        self.__m_overlay.close()
        self.__m_settings.sync()
