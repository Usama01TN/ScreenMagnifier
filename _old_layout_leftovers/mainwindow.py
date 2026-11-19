# coding=utf-8
"""
Screen Magnifier application window: wires RegionSelector, ScreenGrabber, Upscaler, MagnifierViewWidget and
ControlPanel together.
"""
from ManyQt.QtWidgets import QMainWindow, QDockWidget, QToolBar, QAction, QLabel, QFileDialog, QApplication, QMenu, \
    QSystemTrayIcon
from ManyQt.QtCore import Qt, QRect, QRectF, QSize, QPoint, QTimer, QElapsedTimer, QEvent, QDir, QDateTime, pyqtSlot
from ManyQt.QtGui import QImage, QColor, QKeySequence, QIcon, QPixmap, QPainter, QPen, QBrush
from os.path import dirname, join
from sys import path, platform
from math import ceil

if dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .advancedoverlay import AdvancedOverlayController
    from .advancedpanel import AdvancedOverlayPanel
    from .magnifierview import MagnifierViewWidget
    from .regionselector import RegionSelector
    from .screengrabber import ScreenGrabber
    from .controlpanel import ControlPanel
    from .upscaler import Upscaler
except:
    from advancedoverlay import AdvancedOverlayController
    from advancedpanel import AdvancedOverlayPanel
    from magnifierview import MagnifierViewWidget
    from regionselector import RegionSelector
    from screengrabber import ScreenGrabber
    from controlpanel import ControlPanel
    from upscaler import Upscaler

APP_QSS = """
QMainWindow, QDockWidget, QScrollArea { background: #1B1D24; color: #E8EBF2; }
QToolBar { background: #22252E; border: none; border-bottom: 1px solid #2E3240; spacing: 4px; padding: 4px; }
QToolBar::separator { background: #3A3F50; width: 1px; margin: 6px 6px; }
QToolButton { color: #E8EBF2; background: transparent; border: 1px solid transparent; border-radius: 6px;
              padding: 5px 10px; }
QToolButton:hover { background: #2E3240; }
QToolButton:checked { background: #3A4BD8; border-color: #4F8BFF; }
QStatusBar { background: #22252E; color: #AEB5C6; border-top: 1px solid #2E3240; }
QStatusBar QLabel { color: #AEB5C6; padding: 0 8px; }
QDockWidget::title { background: #22252E; padding: 6px 10px; color: #9AA3B8; }
QTabBar::tab { background: #22252E; color: #9AA3B8; padding: 6px 14px; border: none; }
QTabBar::tab:selected { background: #2A2E3A; color: #E8EBF2; border-bottom: 2px solid #4F8BFF; }
QMenu { background: #22252E; color: #E8EBF2; border: 1px solid #3A3F50; }
QMenu::item:selected { background: #3A4BD8; }
QLabel, QCheckBox { color: #E8EBF2; }
QComboBox, QPushButton { background: #2A2E3A; color: #E8EBF2; border: 1px solid #3A3F50; border-radius: 6px;
                         padding: 5px 8px; }
QPushButton:hover, QComboBox:hover { border-color: #4F8BFF; }
QComboBox QAbstractItemView { background: #2A2E3A; color: #E8EBF2; selection-background-color: #3A4BD8; }
QSlider::groove:horizontal { height: 4px; background: #3A3F50; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #4F8BFF; border-radius: 2px; }
QSlider::handle:horizontal { background: #E8EBF2; width: 14px; margin: -6px 0; border-radius: 7px; }
"""  # type: str

PLACEHOLDER = ('Select a screen region to magnify\n\n'
               'Ctrl+R - select region\nF - follow cursor\nSpace - freeze\n'
               'Wheel - zoom at cursor\nDrag - pan\nDouble-click - fit')  # type: str


def makeAppIcon():
    """
    Draw the application / tray icon: a magnifying glass.
    :return: QIcon
    """
    icon = QIcon()  # type: QIcon
    for size in (16, 24, 32, 48, 64, 128):
        pm = QPixmap(size, size)  # type: QPixmap
        pm.fill(Qt.transparent)
        p = QPainter(pm)  # type: QPainter
        p.setRenderHint(QPainter.Antialiasing, True)
        s = float(size)  # type: float
        p.setPen(QPen(QColor('#E8EBF2'), s * 0.13, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPoint(int(s * 0.62), int(s * 0.62)), QPoint(int(s * 0.9), int(s * 0.9)))
        p.setPen(QPen(QColor('#4F8BFF'), s * 0.1))
        p.setBrush(QBrush(QColor(79, 139, 255, 70)))
        p.drawEllipse(QRectF(s * 0.1, s * 0.1, s * 0.56, s * 0.56))
        p.end()
        icon.addPixmap(pm)
    return icon


def excludeFromCapture(widget):
    """
    Windows 10 2004+: hide a window from screen capture so the magnifier can sit over what it magnifies.
    :param widget: QWidget
    :return: (bool) True if the window is now excluded.
    """
    if platform != 'win32':
        return False
    try:
        from ctypes import windll
        WDA_EXCLUDEFROMCAPTURE = 0x11  # type: int
        return bool(windll.user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


class MainWindow(QMainWindow):
    """
    MainWindow class.
    """

    def __init__(self, *args, **kwargs):
        """
        :param excludeFromCapture: (bool) Windows only: make the magnifier invisible to screen capture.
        :param args: any
        :param kwargs: any
        """
        excludeSelf = kwargs.pop('excludeFromCapture', True)  # type: bool
        super(MainWindow, self).__init__(*args, **kwargs)
        self.setWindowTitle(self.tr('Screen Magnifier'))
        self.resize(1040, 680)
        self.setStyleSheet(APP_QSS)
        # State.
        self.__m_excludeSelf = bool(excludeSelf)  # type: bool
        self.__m_excluded = False  # type: bool
        self.__m_selecting = False  # type: bool
        self.__m_fitPending = False  # type: bool
        self.__m_lastFrames = 0  # type: int
        self.__m_fpsClock = QElapsedTimer()  # type: QElapsedTimer
        self.__m_fpsClock.start()
        self.__m_quitting = False  # type: bool
        self.__m_trayHintShown = False  # type: bool
        self.setWindowIcon(makeAppIcon())
        # Components.
        self.__m_upscaler = Upscaler(method=Upscaler.AIFast if Upscaler.hasSuperRes() else Upscaler.Lanczos,
                                     sharpness=0.25, errorOccurred=self.onError, parent=self)  # type: Upscaler
        self.__m_view = MagnifierViewWidget(zoom=3.0, minZoom=0.25, maxZoom=32.0, processor=self.__m_upscaler.process,
                                            placeholderText=self.tr(PLACEHOLDER), zoomChanged=self.onZoomChanged,
                                            pixelHovered=self.onPixelHovered)  # type: MagnifierViewWidget
        self.__m_grabber = ScreenGrabber(fps=30, frameReady=self.onFrame, captureFailed=self.onCaptureFailed,
                                         parent=self)  # type: ScreenGrabber
        self.__m_selector = RegionSelector(regionSelected=self.onRegionSelected,
                                           selectionCanceled=self.onSelectionCanceled)  # type: RegionSelector
        self.__m_panel = ControlPanel(view=self.__m_view, upscaler=self.__m_upscaler,
                                      grabber=self.__m_grabber)  # type: ControlPanel
        self.__m_upscaler.methodChanged.connect(self.__m_view.refresh)
        self.__m_upscaler.sharpnessChanged.connect(self.__m_view.refresh)
        # In-advanced zoom lens: global hotkeys + click-through overlay, shares the upscaler.
        self.__m_game = AdvancedOverlayController(
            processor=self.__m_upscaler.process, parent=self)  # type: AdvancedOverlayController
        self.__m_upscaler.methodChanged.connect(self.__m_game.getOverlay().refresh)
        self.__m_upscaler.sharpnessChanged.connect(self.__m_game.getOverlay().refresh)
        self.__m_view.installEventFilter(self)
        self.setCentralWidget(self.__m_view)
        self.__m_dock = QDockWidget(self.tr('Settings'), self)  # type: QDockWidget
        self.__m_dock.setObjectName('settingsDock')
        self.__m_dock.setWidget(self.__m_panel)
        self.__m_dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable |
                                  QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.__m_dock)
        self.__m_gameDock = QDockWidget(self.tr('Advanced zoom'), self)  # type: QDockWidget
        self.__m_gameDock.setObjectName('gameDock')
        self.__m_gameDock.setWidget(AdvancedOverlayPanel(controller=self.__m_game))
        self.__m_gameDock.setFeatures(self.__m_dock.features())
        self.addDockWidget(Qt.RightDockWidgetArea, self.__m_gameDock)
        self.tabifyDockWidget(self.__m_dock, self.__m_gameDock)
        self.__m_dock.raise_()
        self.__m_grabber.setIgnoreWidgets([self, self.__m_dock, self.__m_gameDock])
        self._buildToolBar()
        self._buildStatusBar()
        self._buildTray()
        self.__m_game.overlayToggled.connect(self.onGameOverlayToggled)
        self.__m_game.hotkeyTriggered.connect(self.onGameHotkey)
        self.__m_statsTimer = QTimer(self)  # type: QTimer
        self.__m_statsTimer.timeout.connect(self._updateStats)
        self.__m_statsTimer.start(500)

    # ---------- Helpers ----------
    def _action(self, text, slot, shortcuts=(), checkable=False, tip=''):
        """
        :param text: str | unicode | QString
        :param slot: callable
        :param shortcuts: (tuple) QKeySequence | str values.
        :param checkable: bool
        :param tip: str | unicode | QString
        :return: QAction
        """
        act = QAction(text, self)  # type: QAction
        act.setCheckable(checkable)
        if shortcuts:
            act.setShortcuts([QKeySequence(s) for s in shortcuts])
            act.setShortcutContext(Qt.WindowShortcut)
        act.setToolTip('{}  ({})'.format(tip or text, ', '.join(QKeySequence(s).toString() for s in shortcuts))
                       if shortcuts else (tip or text))
        (act.toggled if checkable else act.triggered).connect(slot)
        self.addAction(act)
        return act

    def _buildToolBar(self):
        """
        :return:
        """
        tb = QToolBar(self.tr('Main'), self)  # type: QToolBar
        tb.setObjectName('mainToolBar')
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(Qt.TopToolBarArea, tb)
        self.__m_actSelect = self._action(self.tr('\u2b1a  Select region'), self.selectRegion, ('Ctrl+R',),
                                          tip=self.tr('Pick a screen region to magnify'))  # type: QAction
        self.__m_actFollow = self._action(self.tr('\u2316  Follow cursor'), self.setFollowMode, ('F',), True,
                                          self.tr('Magnify around the mouse pointer'))  # type: QAction
        self.__m_actFreeze = self._action(self.tr('\u2744  Freeze'), self.setFrozen, ('Space',), True,
                                          self.tr('Pause live capture'))  # type: QAction
        actOut = self._action(self.tr('\u2212'), self.__m_view.zoomOut, ('-',), tip=self.tr('Zoom out'))
        actIn = self._action(self.tr('+'), self.__m_view.zoomIn, ('+', '='), tip=self.tr('Zoom in'))
        actFit = self._action(self.tr('Fit'), self.__m_view.fitToView, ('0',), tip=self.tr('Fit region'))
        actSave = self._action(self.tr('Save\u2026'), self.saveSnapshot, (QKeySequence.Save,),
                               tip=self.tr('Save the upscaled region'))
        actCopy = self._action(self.tr('Copy'), self.copySnapshot, (QKeySequence.Copy,),
                               tip=self.tr('Copy the upscaled region'))
        self.__m_actTop = self._action(self.tr('Pin on top'), self.setAlwaysOnTop, ('T',), True,
                                       self.tr('Keep the magnifier above other windows'))  # type: QAction
        self.__m_actGame = self._action(self.tr('\u25ce  Advanced zoom'), self.setGameOverlay, (), True,
                                        self.tr('Show / hide the in-advanced zoom lens (global hotkey: {})').format(
                                            self.__m_game.getHotkey('toggle') or '-'))  # type: QAction
        self.__m_actQuit = self._action(self.tr('Quit'), self.quitApp, (QKeySequence.Quit, 'Ctrl+Q'),
                                        tip=self.tr('Quit Screen Magnifier'))  # type: QAction
        settings = self.__m_dock.toggleViewAction()  # type: QAction
        settings.setText(self.tr('\u2699  Settings'))
        settings.setShortcut(QKeySequence('Ctrl+,'))
        for a in (self.__m_actSelect, self.__m_actFollow, self.__m_actFreeze, None, actOut, actIn, actFit, None,
                  actSave, actCopy, None, self.__m_actGame, self.__m_actTop, settings):
            if a is None:
                tb.addSeparator()
            else:
                tb.addAction(a)

    def _buildStatusBar(self):
        """
        :return:
        """
        self.__m_modeLabel = QLabel(self.tr('No region'))  # type: QLabel
        self.__m_pixelLabel = QLabel()  # type: QLabel
        self.__m_perfLabel = QLabel()  # type: QLabel
        sb = self.statusBar()
        sb.addWidget(self.__m_modeLabel)
        sb.addWidget(self.__m_pixelLabel, 1)
        sb.addPermanentWidget(self.__m_perfLabel)

    def _buildTray(self):
        """
        System tray icon: keeps the app (and its global hotkeys) running while the window is hidden.
        :return: None
        """
        self.__m_tray = None  # type: QSystemTrayIcon | None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        menu = QMenu(self)  # type: QMenu
        menu.addAction(self.tr('Show magnifier'), self.showFromTray)
        menu.addAction(self.__m_actGame)
        menu.addSeparator()
        menu.addAction(self.__m_actQuit)
        self.__m_tray = QSystemTrayIcon(makeAppIcon(), self)  # type: QSystemTrayIcon
        self.__m_tray.setToolTip(self.tr('Screen Magnifier'))
        self.__m_tray.setContextMenu(menu)
        self.__m_tray.activated.connect(self.onTrayActivated)
        self.__m_tray.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)

    def hasTray(self):
        """
        :return: bool
        """
        return self.__m_tray is not None

    def _updateFollowSize(self):
        """
        In follow mode the capture is exactly what the view can show at the current zoom.
        :return:
        """
        z = self.__m_view.getZoom()  # type: float
        size = QSize(int(ceil(self.__m_view.width() / z)) + 1, int(ceil(self.__m_view.height() / z)) + 1)
        self.__m_grabber.setFollowSize(size)

    def _syncCapture(self):
        """
        Run the grabber only when there is something to capture.
        :return:
        """
        want = not self.__m_selecting and not self.__m_actFreeze.isChecked() and self.isVisible() and \
               not self.isMinimized() and (self.__m_grabber.isFollowCursor() or
                                           not self.__m_grabber.getRegion().isEmpty())  # type: bool
        self.__m_grabber.setActive(want)
        self._updateModeLabel()

    def _updateModeLabel(self):
        """
        :return:
        """
        if self.__m_grabber.isFollowCursor():
            text = self.tr('Following cursor')  # type: str
        else:
            r = self.__m_grabber.getRegion()  # type: QRect
            text = self.tr('No region') if r.isEmpty() else self.tr('Region {} \u00d7 {} at ({}, {})').format(
                r.width(), r.height(), r.x(), r.y())  # type: str
        if self.__m_actFreeze.isChecked():
            text += self.tr('  \u2022  frozen')
        self.__m_modeLabel.setText(text)

    def _restoreWindow(self):
        """
        :return:
        """
        self.__m_selecting = False  # type: bool
        self.show()
        self.raise_()
        self.activateWindow()

    def _upscaledSnapshot(self):
        """
        :return: (QImage) Whole current frame upscaled at the current magnification (longest side <= 8192 px).
        """
        frame = self.__m_view.getFrame()  # type: QImage
        if frame.isNull():
            return QImage()
        z = min(self.__m_view.getZoom(), 8192.0 / max(frame.width(), frame.height()))  # type: float
        img = self.__m_upscaler.process(frame, QSize(max(1, int(frame.width() * z)), max(1, int(frame.height() * z))))
        if self.__m_view.isInvertColors():
            img = img.convertToFormat(QImage.Format_RGB32)  # type: QImage
            img.invertPixels()
        return img

    # ---------- Public API ----------
    @pyqtSlot()
    def selectRegion(self):
        """
        Hide the magnifier, freeze the desktop and let the user drag a region.
        :return:
        """
        self.__m_selecting = True  # type: bool
        self._syncCapture()
        self.hide()
        QTimer.singleShot(250, self.__m_selector.start)

    @pyqtSlot(QRect)
    def onRegionSelected(self, rect):
        """
        :param rect: QRect
        :return:
        """
        self.__m_grabber.setRegion(rect)
        self.__m_fitPending = True  # type: bool
        self.__m_actFreeze.setChecked(False)
        self.__m_actFollow.setChecked(False)
        self._restoreWindow()
        self._syncCapture()

    @pyqtSlot()
    def onSelectionCanceled(self):
        """
        :return:
        """
        self._restoreWindow()
        self._syncCapture()

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setFollowMode(self, on):
        """
        :param on: bool
        :return:
        """
        self.__m_grabber.setFollowCursor(bool(on))
        self.__m_view.setPanEnabled(not on)
        if on:
            self._updateFollowSize()
        elif not self.__m_grabber.getRegion().isEmpty():
            self.__m_fitPending = True  # type: bool
        else:
            self.__m_view.clear()
        self._syncCapture()

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setFrozen(self, frozen):
        """
        :param frozen: bool
        :return:
        """
        self._syncCapture()

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setAlwaysOnTop(self, on):
        """
        :param on: bool
        :return:
        """
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on))
        self.show()

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setGameOverlay(self, on):
        """
        :param on: bool
        :return:
        """
        ov = self.__m_game.getOverlay()
        if bool(on) != ov.isVisible():
            self.__m_game.toggle()

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def onGameOverlayToggled(self, shown):
        """
        :param shown: bool
        :return:
        """
        self.__m_actGame.blockSignals(True)
        self.__m_actGame.setChecked(bool(shown))
        self.__m_actGame.blockSignals(False)

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def onGameHotkey(self, name):
        """
        :param name: str | unicode | QString
        :return:
        """
        self.statusBar().showMessage(self.tr('Global hotkey: {}').format(name), 1500)

    @pyqtSlot()
    def showFromTray(self):
        """
        :return:
        """
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @pyqtSlot(QSystemTrayIcon.ActivationReason)
    def onTrayActivated(self, reason):
        """
        :param reason: QSystemTrayIcon.ActivationReason
        :return:
        """
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.showFromTray()

    @pyqtSlot()
    def quitApp(self):
        """
        :return:
        """
        self.__m_quitting = True  # type: bool
        self.close()
        QApplication.instance().quit()

    @pyqtSlot()
    def saveSnapshot(self):
        """
        :return:
        """
        img = self._upscaledSnapshot()  # type: QImage
        if img.isNull():
            self.statusBar().showMessage(self.tr('Nothing to save yet.'), 3000)
            return
        name = 'magnified_{}.png'.format(QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss'))  # type: str
        res = QFileDialog.getSaveFileName(self, self.tr('Save upscaled image'), join(QDir.homePath(), name),
                                          self.tr('PNG image (*.png);;JPEG image (*.jpg *.jpeg)'))
        fileName = res[0] if isinstance(res, tuple) else res  # type: str
        if fileName:
            ok = img.save(fileName)  # type: bool
            self.statusBar().showMessage(self.tr('Saved {} \u00d7 {} image to {}').format(
                img.width(), img.height(), fileName) if ok else self.tr('Could not save {}').format(fileName), 5000)

    @pyqtSlot()
    def copySnapshot(self):
        """
        :return:
        """
        img = self._upscaledSnapshot()  # type: QImage
        if not img.isNull():
            QApplication.clipboard().setImage(img)
            self.statusBar().showMessage(self.tr('Copied {} \u00d7 {} image to the clipboard.').format(
                img.width(), img.height()), 3000)

    # ---------- Slots ----------
    @pyqtSlot(QImage)
    def onFrame(self, image):
        """
        :param image: QImage
        :return:
        """
        self.__m_view.setFrame(image)
        if self.__m_fitPending and not self.__m_grabber.isFollowCursor():
            self.__m_fitPending = False  # type: bool
            self.__m_view.fitToView()

    @pyqtSlot(float)
    @pyqtSlot(int)
    def onZoomChanged(self, zoom):
        """
        :param zoom: float | int
        :return:
        """
        if self.__m_grabber.isFollowCursor():
            self._updateFollowSize()

    @pyqtSlot(QPoint, QColor)
    def onPixelHovered(self, pos, color):
        """
        :param pos: QPoint
        :param color: QColor
        :return:
        """
        if pos.x() < 0 or not color.isValid():
            self.__m_pixelLabel.setText('')
            return
        g = self.__m_grabber.mapToGlobal(pos)  # type: QPoint
        self.__m_pixelLabel.setText(self.tr('Screen ({}, {})   {}   rgb({}, {}, {})').format(
            g.x(), g.y(), color.name().upper(), color.red(), color.green(), color.blue()))

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def onCaptureFailed(self, message):
        """
        :param message: str | unicode | QString
        :return:
        """
        self.statusBar().showMessage(message, 10000)
        self.__m_view.setPlaceholderText(message)

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def onError(self, message):
        """
        :param message: str | unicode | QString
        :return:
        """
        self.statusBar().showMessage(message, 8000)

    @pyqtSlot()
    def _updateStats(self):
        """
        :return:
        """
        frames = self.__m_grabber.getFrameCount()  # type: int
        secs = max(1e-3, self.__m_fpsClock.restart() / 1000.0)  # type: float
        fps = (frames - self.__m_lastFrames) / secs  # type: float
        self.__m_lastFrames = frames  # type: int
        up = self.__m_upscaler.getLastProcessTime()  # type: float
        self.__m_panel.showProcessTime(up)
        self.__m_perfLabel.setText(self.tr('{:.0f} fps   grab {:.1f} ms   {} {:.1f} ms   {:.2f}\u00d7').format(
            fps if self.__m_grabber.isActive() else 0.0, self.__m_grabber.getLastGrabTime(),
            self.__m_upscaler.getMethodName().split(' (')[0], up, self.__m_view.getZoom()))

    # ---------- Qt overrides ----------
    def eventFilter(self, obj, e):
        """
        :param obj: QObject
        :param e: QEvent
        :return: bool
        """
        if obj is self.__m_view and e.type() == QEvent.Resize and self.__m_grabber.isFollowCursor():
            self._updateFollowSize()
        return super(MainWindow, self).eventFilter(obj, e)

    def hideEvent(self, e):
        """
        :param e: QHideEvent
        :return:
        """
        super(MainWindow, self).hideEvent(e)
        self._syncCapture()

    def changeEvent(self, e):
        """
        :param e: QEvent
        :return:
        """
        super(MainWindow, self).changeEvent(e)
        if e.type() == QEvent.WindowStateChange:
            self._syncCapture()

    def showEvent(self, e):
        """
        :param e: QShowEvent
        :return:
        """
        super(MainWindow, self).showEvent(e)
        if not self.__m_selecting:
            QTimer.singleShot(0, self._syncCapture)
        if self.__m_excludeSelf:
            excluded = excludeFromCapture(self)  # type: bool
            if excluded != self.__m_excluded:
                self.__m_excluded = excluded  # type: bool
                # Invisible to capture: the magnifier may hover over what it magnifies.
                self.__m_grabber.setIgnoreWidgets([] if excluded else [self, self.__m_dock])

    def closeEvent(self, e):
        """
        Closing the window hides it to the tray (hotkeys keep working); Quit really exits.
        :param e: QCloseEvent
        :return: None
        """
        if self.__m_tray is not None and not self.__m_quitting:
            e.ignore()
            self.hide()
            if not self.__m_trayHintShown:
                self.__m_trayHintShown = True  # type: bool
                self.__m_tray.showMessage(self.tr('Screen Magnifier is still running'), self.tr(
                    'Press {} in any app or game to toggle the zoom lens. Right-click the tray icon to quit.').format(
                    self.__m_game.getHotkey('toggle') or self.tr('the game-zoom hotkey')),
                                          QSystemTrayIcon.Information, 4000)
            return
        self.__m_game.shutdown()
        if self.__m_tray is not None:
            self.__m_tray.hide()
        self.__m_grabber.stop()
        self.__m_statsTimer.stop()
        self.__m_selector.close()
        super(MainWindow, self).closeEvent(e)
