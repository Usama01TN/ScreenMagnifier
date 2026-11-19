# coding=utf-8
"""
Screen Magnifier application window: wires RegionSelector, ScreenGrabber, Upscaler, MagnifierViewWidget,
ControlPanel, the zoomer (advanced zoom lens), color / face detection (AnalysisController) and the optional analysis
server (RemoteClient) together.
"""
from ManyQt.QtWidgets import QMainWindow, QDockWidget, QToolBar, QAction, QLabel, QFileDialog, QApplication, QMenu, \
    QSystemTrayIcon, QToolButton, QTabBar, QMessageBox, QActionGroup, QScrollArea, QComboBox, QCheckBox, QWidget, \
    QVBoxLayout, QHBoxLayout
from ManyQt.QtCore import QObject, QSettings, QUrl, Qt, QRect, QRectF, QSize, QPoint, QPointF, QTimer, QElapsedTimer, \
    QEvent, QDir, QDateTime, pyqtSlot
from ManyQt.QtGui import QImage, QColor, QKeySequence, QIcon, QPixmap, QPainter, QPen, QBrush, QCursor, QDesktopServices
from os.path import dirname, join, isfile
from sys import path, platform
from math import ceil, floor
from os import getpid
import sys

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .advancedoverlay import AdvancedOverlayController
    from .support import DONATION_LINKS, restartCommand
    from .facepointer import FacePointer, FOLLOW_ZOOMER
    from .analysiscontroller import AnalysisController
    from .colordetector import sampleColor, refinePick
    from .shortcuts import ShortcutStore, shortcutInfo
    from .advancedpanel import AdvancedOverlayPanel
    from .magnifierview import MagnifierViewWidget
    from .shortcutspanel import ShortcutsPanel
    from .detectionpanel import DetectionPanel
    from .regionselector import RegionSelector
    from .screengrabber import ScreenGrabber
    from .colorpanel import ColorPickerPanel
    from .translator import LanguageManager
    from .controlpanel import ControlPanel
    from .remoteclient import RemoteClient
    from .features import FeatureSettings
    from .zoomoverlay import ZoomOverlay
    from .serverpanel import ServerPanel
    from .upscaler import Upscaler
except:
    from advancedoverlay import AdvancedOverlayController
    from support import DONATION_LINKS, restartCommand
    from facepointer import FacePointer, FOLLOW_ZOOMER
    from analysiscontroller import AnalysisController
    from colordetector import sampleColor, refinePick
    from shortcuts import ShortcutStore, shortcutInfo
    from advancedpanel import AdvancedOverlayPanel
    from magnifierview import MagnifierViewWidget
    from shortcutspanel import ShortcutsPanel
    from detectionpanel import DetectionPanel
    from regionselector import RegionSelector
    from screengrabber import ScreenGrabber
    from colorpanel import ColorPickerPanel
    from translator import LanguageManager
    from controlpanel import ControlPanel
    from remoteclient import RemoteClient
    from features import FeatureSettings
    from zoomoverlay import ZoomOverlay
    from serverpanel import ServerPanel
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

RESTART_QUESTION = 'The interface language changes when ScreenMagnifier restarts. Restart now?'  # type: str
PLACEHOLDER = ('Select a screen region to magnify\n\n'
               'Ctrl+R - select region\nF - follow cursor\nSpace - freeze\n'
               'Wheel - zoom at cursor\nDrag - pan\nDouble-click - fit\n'
               'I - eyedropper: click to copy colors\nC - copy the color under the mouse\n'
               'Right-click - copy it in any format')  # type: str

RESOURCES = join(dirname(__file__), 'resources')  # type: str  # icon-<size>.png, icon.ico, icon.icns


def makeAppIcon():
    """
    The application / tray icon: resources/icon-<size>.png (hand-tuned small sizes), or a drawn magnifier.
    :return: QIcon
    """
    icon = QIcon()  # type: QIcon
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        file = join(RESOURCES, 'icon-{}.png'.format(size))  # type: str
        if isfile(file):
            icon.addFile(file, QSize(size, size))
    if not icon.isNull():
        return icon
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


class CheckBoxLabelLink(QObject):
    """
    CheckBoxLabelLink class: a wrapping label that acts as its check box's text - a click on it toggles the box, and
    it follows the box's enabled state.
    """

    def __init__(self, box, label, *args, **kwargs):
        """
        :param box: QCheckBox
        :param label: QLabel
        :param args: any
        :param kwargs: any
        """
        super(CheckBoxLabelLink, self).__init__(*args, **kwargs)
        self.__m_box = box  # type: QCheckBox
        self.__m_label = label  # type: QLabel

    def eventFilter(self, obj, e):
        """
        :param obj: QObject
        :param e: QEvent
        :return: bool
        """
        if obj is self.__m_label and e.type() == QEvent.MouseButtonRelease and self.__m_box.isEnabled():
            self.__m_box.click()
            return True
        if obj is self.__m_box and e.type() in (QEvent.EnabledChange, QEvent.ToolTipChange):
            self.__m_label.setEnabled(self.__m_box.isEnabled())
            self.__m_label.setToolTip(self.__m_box.toolTip())
        return super(CheckBoxLabelLink, self).eventFilter(obj, e)


class MainWindow(QMainWindow):
    """
    MainWindow class.
    """

    def __init__(self, *args, **kwargs):
        """
        :param excludeFromCapture: (bool) Windows only: make the magnifier invisible to screen capture.
        :param languageManager: (LanguageManager | None) Interface language (main.run installs it before the window).
        :param args: any
        :param kwargs: any
        """
        excludeSelf = kwargs.pop('excludeFromCapture', True)  # type: bool
        languageManager = kwargs.pop('languageManager', None)  # type: LanguageManager | None
        super(MainWindow, self).__init__(*args, **kwargs)
        self.__m_languages = languageManager if languageManager is not None else LanguageManager(
            folder=join(dirname(__file__), 'translations'), parent=self)  # type: LanguageManager
        self.setWindowTitle(self.tr(u'Screen Magnifier'))
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
        QApplication.instance().setWindowIcon(self.windowIcon())  # Dialogs and every other window too.
        # Components.
        self.__m_upscaler = Upscaler(method=Upscaler.AIFast if Upscaler.hasSuperRes() else Upscaler.Lanczos,
                                     sharpness=0.25, errorOccurred=self.onError, parent=self)  # type: Upscaler
        # Optional analysis server: upscaling / analysis can run on another computer.
        self.__m_client = RemoteClient(parent=self)  # type: RemoteClient
        self.__m_remoteView = self.__m_client.processor('view', self.__m_upscaler.process)
        self.__m_remoteLens = self.__m_client.processor('lens', self.__m_upscaler.process)
        # Color detection and optional AI face detection (local worker thread or server).
        self.__m_analysis = AnalysisController(client=self.__m_client, parent=self)  # type: AnalysisController
        self.__m_zoomerTargetBefore = None  # type: int | None  # restored when the face pointer stops
        self.__m_facePointer = FacePointer(detector=self.__m_analysis.getFaceDetector(),
                                           ignoreRects=self._facePointerIgnored, moveZoomer=self._moveZoomerTo,
                                           parent=self)  # type: FacePointer
        self.__m_facePointer.enabledChanged.connect(self._onFacePointerToggled)
        self.__m_view = MagnifierViewWidget(zoom=3.0, minZoom=0.25, maxZoom=32.0, processor=self._processView,
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
        self.__m_store = ShortcutStore(parent=self)  # type: ShortcutStore  # window shortcuts (registry)
        self.__m_features = FeatureSettings(parent=self)  # type: FeatureSettings  # where zones are shown
        self.__m_actions = {}  # type: dict  # shortcut name -> (QAction, tooltip)
        self.__m_store.changed.connect(self._applyShortcut)
        self.__m_game = AdvancedOverlayController(
            processor=self._processLens, parent=self)  # type: AdvancedOverlayController
        self.__m_upscaler.methodChanged.connect(self.__m_game.getOverlay().refresh)
        self.__m_upscaler.sharpnessChanged.connect(self.__m_game.getOverlay().refresh)
        self.__m_view.installEventFilter(self)
        self.setCentralWidget(self.__m_view)
        self.__m_dock = QDockWidget(self.tr(u'Magnifier'), self)  # type: QDockWidget
        self.__m_dock.setObjectName('settingsDock')
        self.__m_dock.setWidget(self.__m_panel)
        self.__m_dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable |
                                  QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.__m_dock)
        self.__m_gameDock = QDockWidget(self.tr(u'Zoomer'), self)  # type: QDockWidget
        self.__m_gameDock.setObjectName('gameDock')
        self.__m_gameDock.setWidget(AdvancedOverlayPanel(controller=self.__m_game, features=self.__m_features))
        self.__m_gameDock.setFeatures(self.__m_dock.features())
        self.addDockWidget(Qt.RightDockWidgetArea, self.__m_gameDock)
        self.tabifyDockWidget(self.__m_dock, self.__m_gameDock)
        self.__m_detectPanel = DetectionPanel(controller=self.__m_analysis, features=self.__m_features,
                                              facePointer=self.__m_facePointer,
                                              hotkeyText=self.__m_game.getHotkey)  # type: DetectionPanel
        self.__m_serverPanel = ServerPanel(client=self.__m_client, analysis=self.__m_analysis,
                                           upscaler=self.__m_upscaler)  # type: ServerPanel
        self.__m_colorPanel = ColorPickerPanel()  # type: ColorPickerPanel
        self.__m_colorDock = QDockWidget(self.tr(u'Colors'), self)  # type: QDockWidget
        self.__m_detectDock = QDockWidget(self.tr(u'Detection (Beta)'), self)  # type: QDockWidget
        self.__m_serverDock = QDockWidget(self.tr(u'Server'), self)  # type: QDockWidget
        self.__m_shortcutDock = QDockWidget(self.tr(u'Shortcuts'), self)  # type: QDockWidget
        for dock, name, panel in ((self.__m_colorDock, 'colorDock', self.__m_colorPanel),
                                  (self.__m_detectDock, 'detectionDock', self.__m_detectPanel),
                                  (self.__m_serverDock, 'serverDock', self.__m_serverPanel),
                                  (self.__m_shortcutDock, 'shortcutDock',
                                   ShortcutsPanel(store=self.__m_store, controller=self.__m_game))):
            dock.setObjectName(name)
            dock.setWidget(panel)
            dock.setFeatures(self.__m_dock.features())
            self.addDockWidget(Qt.RightDockWidgetArea, dock)
            self.tabifyDockWidget(self.__m_dock, dock)
        self.__m_dock.raise_()
        self.__m_grabber.setIgnoreWidgets(self._dockWidgets())
        self._buildToolBar()
        self._buildStatusBar()
        self._buildTray()
        self.__m_game.overlayToggled.connect(self.onGameOverlayToggled)
        self.__m_game.hotkeyTriggered.connect(self.onGameHotkey)
        # Detection / server wiring.
        self.__m_client.upscaleReady.connect(self._onRemoteResult)
        self.__m_analysis.annotationsReady.connect(self._onAnnotations)
        self.__m_view.pixelClicked.connect(self._onPixelClicked)
        self.__m_view.colorPicked.connect(self._onColorPicked)
        self.__m_view.pickHovered.connect(self._onPickHovered)
        self.__m_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.__m_view.customContextMenuRequested.connect(self._onViewMenu)
        self.__m_colorPanel.colorCopied.connect(self._onColorCopied)
        self.__m_colorPanel.notify.connect(self._notify)
        self.__m_game.colorPickRequested.connect(self._onColorPickHotkey)
        self.__m_game.screenPickRequested.connect(self._onScreenPick)
        self.__m_game.message.connect(self._notify)
        self.__m_game.pickerToggled.connect(lambda on: self._notify(self.tr(
            u'Screen color picker: click anywhere to copy - right-click / Esc cancels - wheel zooms')) if on else None)
        self._action(self.tr(u'Copy color code'), self.copyHoveredColor, 'copyHoveredColor',
                     tip=self.tr(u'Copy the color under the mouse in the magnifier'))
        self.__m_game.getGrabber().frameReady.connect(self._onLensFrame)
        self.__m_game.overlayToggled.connect(lambda shown: None if shown else self.__m_analysis.forget('lens'))
        self.__m_features.changed.connect(self._onFeatureChanged)
        QTimer.singleShot(0, self._fullTabNames)
        self._fitPanels()
        # One live color, one text: the Colors tab, the zoomer and the eyedropper share formatter and namer.
        self.__m_mouseInView = False  # type: bool
        self.__m_pendingReadout = (QColor(), '')  # type: tuple
        self.__m_readoutTimer = QTimer(self)  # type: QTimer
        self.__m_readoutTimer.setSingleShot(True)
        self.__m_readoutTimer.timeout.connect(self._applyZoomerReadout)
        lens = self.__m_game.getOverlay()
        lens.setColorFormatter(self.__m_colorPanel.formatCode)
        lens.setColorNamer(self.__m_colorPanel.colorName)
        self.__m_view.setColorFormatter(self.__m_colorPanel.formatCode)
        lens.readoutChanged.connect(self._onZoomerReadout)
        for dock in self._dockWidgets()[1:]:
            dock.visibilityChanged.connect(lambda *a: QTimer.singleShot(0, self._syncPanelAction))
        self.__m_colorPanel.optionsChanged.connect(self._syncLensReadout)
        self._syncLensReadout()
        self.__m_detectPanel.notify.connect(self._notify)
        self.__m_serverPanel.notify.connect(self._notify)
        self.__m_serverPanel.offloadChanged.connect(self._onOffloadChanged)
        self.__m_statsTimer = QTimer(self)  # type: QTimer
        self.__m_statsTimer.timeout.connect(self._updateStats)
        self.__m_statsTimer.start(500)

    # ---------- Helpers ----------
    def _action(self, text, slot, shortcut=None, checkable=False, tip=''):
        """
        :param text: str | unicode | QString
        :param slot: callable
        :param shortcut: (str | None) Name of a window shortcut of the registry (shortcuts.py), editable in the
            Shortcuts tab; None = no shortcut.
        :param checkable: bool
        :param tip: str | unicode | QString
        :return: QAction
        """
        act = QAction(text, self)  # type: QAction
        act.setCheckable(checkable)
        act.setShortcutContext(Qt.WindowShortcut)
        act.setToolTip(tip or text)
        (act.toggled if checkable else act.triggered).connect(slot)
        self.addAction(act)
        if shortcut:
            self.__m_actions[shortcut] = (act, tip or text)
            self._applyShortcut(shortcut)
        return act

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def _applyShortcut(self, name):
        """
        (Re)apply a window shortcut after a change in the Shortcuts tab; the tooltip shows the keys.
        :param name: str | unicode | QString
        :return:
        """
        entry = self.__m_actions.get(u'{}'.format(name))
        if entry is None:
            return
        act, tip = entry
        keys = self.__m_store.sequences(u'{}'.format(name))  # type: list
        act.setShortcuts([QKeySequence(k) for k in keys])
        act.setToolTip('{}  ({})'.format(tip, ', '.join(QKeySequence(k).toString(QKeySequence.NativeText)
                                                        for k in keys)) if keys else tip)

    def _buildToolBar(self):
        """
        :return:
        """
        tb = QToolBar(self.tr(u'Main'), self)  # type: QToolBar
        tb.setObjectName('mainToolBar')
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(Qt.TopToolBarArea, tb)
        self.__m_actSelect = self._action(self.tr(u'\u2b1a  Region'), self.selectRegion, 'selectRegion',
                                          tip=self.tr(u'Pick a screen region to magnify'))  # type: QAction
        self.__m_actFollow = self._action(self.tr(u'\u2316  Follow'), self.setFollowMode, 'followCursor', True,
                                          self.tr(u'Magnify around the mouse pointer'))  # type: QAction
        self.__m_actFreeze = self._action(self.tr(u'\u2744  Freeze'), self.setFrozen, 'freeze', True,
                                          self.tr(u'Pause live capture'))  # type: QAction
        actOut = self._action(self.tr(u'\u2212'), self.__m_view.zoomOut, 'viewZoomOut', tip=self.tr(u'Zoom out'))
        actIn = self._action(self.tr(u'+'), self.__m_view.zoomIn, 'viewZoomIn', tip=self.tr(u'Zoom in'))
        actFit = self._action(self.tr(u'Fit'), self.__m_view.fitToView, 'viewFit', tip=self.tr(u'Fit region'))
        actSave = self._action(self.tr(u'Save\u2026'), self.saveSnapshot, 'saveSnapshot',
                               tip=self.tr(u'Save the upscaled region'))
        actCopy = self._action(self.tr(u'Copy'), self.copySnapshot, 'copySnapshot',
                               tip=self.tr(u'Copy the upscaled region'))
        actScreenPick = self._action(self.tr(u'Screen color picker'), lambda: self.__m_game.startColorPicker(),
                                     'screenPickerWindow',
                                     tip=self.tr(u'Screen color picker (Ctrl+Alt+P anywhere): live zoom at the mouse, '
                                                 'click anywhere on the screen to copy'))  # type: QAction
        self.__m_actPick = self._action(self.tr(u'Eyedropper on the magnifier'), self.setPickMode, 'eyedropper', True,
                                        self.tr(u'Eyedropper: click the zoomed image to copy colors'))  # type: QAction
        self._action(self.tr(u'Stop picking'), lambda: self.__m_actPick.setChecked(False), 'stopEyedropper')
        self.__m_actTop = self._action(self.tr(u'Pin on top'), self.setAlwaysOnTop, 'pinOnTop', True,
                                       self.tr(u'Keep the magnifier above other windows'))  # type: QAction
        self.__m_actGame = self._action(self.tr(u'\u25ce  Zoomer'), self.setGameOverlay, None, True,
                                        self.tr(u'Show / hide the in-advanced zoom lens (global hotkey: {})').format(
                                            self.__m_game.getHotkey('toggle') or '-'))  # type: QAction
        self.__m_actQuit = self._action(self.tr(u'Quit'), self.quitApp, 'quit',
                                        tip=self.tr(u'Quit Screen Magnifier'))  # type: QAction
        settings = self._action(self.tr(u'\u2699  Panel'), self.setSidePanelVisible, 'toggleSidePanel', True,
                                tip=self.tr(u'Show / hide the side panel (every tab)'))  # type: QAction
        self.__m_actPanel = settings  # type: QAction
        settings.setChecked(True)
        for a in (self.__m_actSelect, self.__m_actFollow, self.__m_actFreeze, None, actOut, actIn, actFit, None,
                  actSave, actCopy, 'pick', None, self.__m_actGame, self.__m_actTop, settings):
            if a is None:
                tb.addSeparator()
            elif a == 'pick':  # Both color pickers in one dropdown: a shorter toolbar.
                pick = QToolButton()  # type: QToolButton
                pick.setText(self.tr(u'\u25c9  Pick'))
                pick.setToolTip(self.tr(u'Color pickers'))
                pick.setPopupMode(QToolButton.InstantPopup)
                menu = QMenu(pick)  # type: QMenu
                menu.setToolTipsVisible(True)
                menu.addAction(self.__m_actPick)
                menu.addAction(actScreenPick)
                pick.setMenu(menu)
                tb.addWidget(pick)
            else:
                tb.addAction(a)

    def _buildStatusBar(self):
        """
        :return:
        """
        self.__m_modeLabel = QLabel(self.tr(u'No region'))  # type: QLabel
        self.__m_pixelLabel = QLabel()  # type: QLabel
        self.__m_perfLabel = QLabel()  # type: QLabel
        sb = self.statusBar()
        sb.addWidget(self.__m_modeLabel)
        sb.addWidget(self.__m_pixelLabel, 1)
        sb.addPermanentWidget(self.__m_perfLabel)
        support = QToolButton()  # type: QToolButton  # Always visible: right end of the status bar.
        support.setText(self.tr(u'\u2665 Support'))
        support.setToolTip(self.tr(u'Support the project: make a donation'))
        support.setAutoRaise(True)
        support.setPopupMode(QToolButton.InstantPopup)
        support.setMenu(self.supportMenu(support))
        support.setStyleSheet('QToolButton { color: #F2557A; font-weight: bold; padding: 0 6px; } '
                              'QToolButton::menu-indicator { image: none; }')
        language = QToolButton()  # type: QToolButton  # Interface language, next to Support.
        language.setText('\U0001F310 ' + self.__m_languages.nativeName(self.__m_languages.getLanguage()))
        language.setToolTip(self.tr(u'Interface language'))
        language.setAutoRaise(True)
        language.setPopupMode(QToolButton.InstantPopup)
        language.setStyleSheet('QToolButton { padding: 0 6px; } QToolButton::menu-indicator { image: none; }')
        language.setMenu(self.languageMenu(language))
        self.statusBar().addPermanentWidget(language)
        self.__m_langButton = language  # type: QToolButton
        self.statusBar().addPermanentWidget(support)
        self.__m_actSupport = support  # type: QToolButton

    def _buildTray(self):
        """
        System tray icon: keeps the app (and its global hotkeys) running while the window is hidden.
        :return: None
        """
        self.__m_tray = None  # type: QSystemTrayIcon | None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        menu = QMenu(self)  # type: QMenu
        menu.addAction(self.tr(u'Show magnifier'), self.showFromTray)
        menu.addAction(self.__m_actGame)
        menu.addSeparator()
        menu.addMenu(self.supportMenu(menu))
        menu.addSeparator()
        menu.addAction(self.__m_actQuit)
        self.__m_tray = QSystemTrayIcon(makeAppIcon(), self)  # type: QSystemTrayIcon
        self.__m_tray.setToolTip(self.tr(u'Screen Magnifier'))
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
            text = self.tr(u'Following cursor')  # type: str
        else:
            r = self.__m_grabber.getRegion()  # type: QRect
            text = self.tr(u'No region') if r.isEmpty() else self.tr(u'Region {} \u00d7 {} at ({}, {})').format(
                r.width(), r.height(), r.x(), r.y())  # type: str
        if self.__m_actFreeze.isChecked():
            text += self.tr(u'  \u2022  frozen')
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
        if u'{}'.format(name) == 'facePointer':
            self.__m_facePointer.toggle()
            return
        info = shortcutInfo('global', u'{}'.format(name))  # type: tuple | None
        self.statusBar().showMessage(self.tr(u'Global hotkey: {}').format(self.tr(info[3]) if info else name), 1500)

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
    def _facePointerIgnored(self):
        """
        :return: (list[QRect]) What the face pointer must not scan: this application's windows (a magnified face is
            not a face to follow), and the zoomer lens unless screen capture does not see it anyway.
        """
        lens = self.__m_game.getOverlay()  # type: ZoomOverlay
        rects = []  # type: list
        for w in QApplication.topLevelWidgets():
            if not w.isVisible() or w.isMinimized():
                continue
            if w is lens and lens.getCaptureStatus() == 'excluded':
                continue  # hidden from capture: the faces behind it are the real ones
            rects.append(w.frameGeometry())
        return rects

    def _moveZoomerTo(self, point):
        """
        The face pointer in 'Only the zoomer' mode: the zoomer magnifies the face, the mouse pointer stays still.
        :param point: QPoint
        :return:
        """
        lens = self.__m_game.getOverlay()  # type: ZoomOverlay
        if lens.getTarget() != ZoomOverlay.Point:
            if self.__m_zoomerTargetBefore is None:
                self.__m_zoomerTargetBefore = int(lens.getTarget())  # type: int | None
            self.__m_game.setTarget(ZoomOverlay.Point)
        lens.setTargetPoint(point)

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def _onFacePointerToggled(self, enabled):
        """
        :param enabled: bool
        :return:
        """
        if not enabled and self.__m_zoomerTargetBefore is not None:
            self.__m_game.setTarget(self.__m_zoomerTargetBefore)  # What the zoomer magnified before.
            self.__m_zoomerTargetBefore = None
        key = self.__m_game.getHotkey('facePointer') or '-'  # type: str
        self.statusBar().showMessage(self.tr(u'Face pointer on: move the mouse to take the control back ({} stops it).')
                                     .format(key) if enabled else self.tr(u'Face pointer off.'), 4000)

    def quitApp(self):
        """
        :return:
        """
        self.__m_facePointer.setEnabled(False)
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
            self.statusBar().showMessage(self.tr(u'Nothing to save yet.'), 3000)
            return
        name = 'magnified_{}.png'.format(QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss'))  # type: str
        res = QFileDialog.getSaveFileName(self, self.tr(u'Save upscaled image'), join(QDir.homePath(), name),
                                          self.tr(u'PNG image (*.png);;JPEG image (*.jpg *.jpeg)'))
        fileName = res[0] if isinstance(res, tuple) else res  # type: str
        if fileName:
            ok = img.save(fileName)  # type: bool
            self.statusBar().showMessage(self.tr(u'Saved {} \u00d7 {} image to {}').format(
                img.width(), img.height(), fileName) if ok else self.tr(u'Could not save {}').format(fileName), 5000)

    @pyqtSlot()
    def copySnapshot(self):
        """
        :return:
        """
        img = self._upscaledSnapshot()  # type: QImage
        if not img.isNull():
            QApplication.clipboard().setImage(img)
            self.statusBar().showMessage(self.tr(u'Copied {} \u00d7 {} image to the clipboard.').format(
                img.width(), img.height()), 3000)

    # ---------- Slots ----------
    @pyqtSlot(QImage)
    def onFrame(self, image):
        """
        :param image: QImage
        :return:
        """
        origin, dpr = self.__m_grabber.getCaptureRect().topLeft(), self.__m_grabber.getDevicePixelRatio()
        self.__m_view.setFrameOrigin(origin, dpr)
        self.__m_view.setFrame(image)
        if self.__m_features.get('zonesInMagnifier'):
            self.__m_analysis.submit('view', image, origin, dpr)
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
        if pos.x() >= 0 and color.isValid():
            self.__m_mouseInView = True  # type: bool
            hovered = self._colorAtView(self.__m_view.mapFromGlobal(QCursor.pos()))  # type: QColor
            hovered = hovered if hovered.isValid() else self._sampleView(pos)  # type: QColor
            self.__m_colorPanel.setLiveColor(hovered, 'magnifier', self.__m_view.zoneAt(pos))
            self.__m_view.setBubbleColor(hovered)  # The eyedropper bubble shows the color that will be copied.
        if pos.x() < 0 or not color.isValid():
            self.__m_pixelLabel.setText('')
            return
        g = self.__m_grabber.mapToGlobal(pos)  # type: QPoint
        self.__m_pixelLabel.setText(self.tr(u'Screen ({}, {})   {}   rgb({}, {}, {})').format(
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
        self.__m_perfLabel.setText(self.tr(u'{:.0f} fps   grab {:.1f} ms   {} {:.1f} ms   {:.2f}\u00d7').format(
            fps if self.__m_grabber.isActive() else 0.0, self.__m_grabber.getLastGrabTime(),
            self.tr(self.__m_upscaler.getMethodName()).split(' (')[0], up, self.__m_view.getZoom()))

    # ---------- Color codes ----------
    def _sampleView(self, pos):
        """
        :param pos: (QPoint) Source pixel of the magnifier frame.
        :return: (QColor) Averaged color (sample size of the Colors tab), invalid outside the frame.
        """
        return sampleColor(self.__m_view.getFrame(), pos.x(), pos.y(), self.__m_colorPanel.getSampleSize())

    def _colorAtView(self, pos):
        """
        Color under a magnifier position, from the source chosen in the Colors tab.
        :param pos: (QPoint) Widget position.
        :return: QColor
        """
        size = self.__m_colorPanel.getSampleSize()  # type: int
        if self.__m_colorPanel.getPickSource() == 'zoomed':
            color = self.__m_view.displayedColorAt(pos, size)  # type: QColor
            if color.isValid():
                return color
        s = self.__m_view.mapToSource(QPointF(pos))  # type: QPointF
        return self._sampleView(QPoint(int(floor(s.x())), int(floor(s.y()))))

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setPickMode(self, on):
        """
        Eyedropper on the zoomed image.
        :param on: bool
        :return:
        """
        self.__m_view.setPickMode(bool(on))
        if on:
            self.__m_view.setFocus()
            self.statusBar().showMessage(self.tr(u'Eyedropper: click the zoomed image to copy a color - Esc to stop'))
        else:
            self.statusBar().clearMessage()

    @pyqtSlot(QPoint, QColor, QColor)
    def _onColorPicked(self, pos, displayed, source):
        """
        :param pos: QPoint
        :param displayed: QColor
        :param source: QColor
        :return:
        """
        self.__m_colorPanel.copyColor(self._colorAtView(self._viewPos(pos)))

    def _viewPos(self, pixel):
        """
        :param pixel: (QPoint) Source pixel of the magnifier frame.
        :return: (QPoint) Widget position of that pixel's center (where it was clicked).
        """
        p = self.__m_view.mapFromSource(QPointF(pixel.x() + 0.5, pixel.y() + 0.5))  # type: QPointF
        return QPoint(int(floor(p.x())), int(floor(p.y())))

    @pyqtSlot(QColor, QColor)
    def _onPickHovered(self, displayed, source):
        """
        :param displayed: QColor
        :param source: QColor
        :return:
        """
        pos = self.__m_view.mapFromGlobal(QCursor.pos())  # type: QPoint
        color = self._colorAtView(pos)  # type: QColor
        if color.isValid():
            s = self.__m_view.mapToSource(QPointF(pos))  # type: QPointF
            self.__m_colorPanel.setLiveColor(color, 'magnifier',
                                             self.__m_view.zoneAt(QPoint(int(floor(s.x())), int(floor(s.y())))))
            self.__m_view.setBubbleColor(color)

    @pyqtSlot(QColor, 'QString')
    def _onZoomerReadout(self, color, zone):
        """
        The zoomer's color code changed: it becomes the live color of the Colors tab (screen color picker while it
        runs; otherwise the zoomer, unless the mouse is over the magnifier). Coalesced to ~15 updates per second.
        :param color: QColor
        :param zone: str | unicode | QString
        :return:
        """
        self.__m_pendingReadout = (QColor(color), u'{}'.format(zone))  # type: tuple
        if not self.__m_readoutTimer.isActive():
            self.__m_readoutTimer.start(66)

    @pyqtSlot()
    def _applyZoomerReadout(self):
        """
        :return:
        """
        color, zone = self.__m_pendingReadout
        lens = self.__m_game.getOverlay()
        if self.__m_game.isColorPicking():
            source = 'picker'  # type: str
        elif self.__m_mouseInView or not lens.isVisible() or not lens.isShowColorReadout():
            return
        else:
            source = 'zoomer'  # type: str
        if color.isValid():
            self.__m_colorPanel.setLiveColor(color, source, zone)

    @pyqtSlot()
    def copyHoveredColor(self):
        """
        C key: copy the color under the mouse in the magnifier, in the default format.
        :return:
        """
        self.__m_colorPanel.copyColor()

    @pyqtSlot(QPoint, QColor)
    def _onPixelClicked(self, pos, color):
        """
        A click (not a pan) in the magnifier: detection "Pick" mode first, else optional copy on click.
        :param pos: QPoint
        :param color: QColor
        :return:
        """
        if self.__m_detectPanel.isPicking():
            refined = refinePick(self.__m_view.getFrame(), pos.x(), pos.y())  # type: QColor  # anti-aliasing safe
            self.__m_detectPanel.onPixelClicked(pos, refined if refined.isValid() else color)
        elif self.__m_colorPanel.isCopyOnClick():
            self.__m_colorPanel.copyColor(self._colorAtView(self._viewPos(pos)))

    @pyqtSlot(QPoint)
    def _onViewMenu(self, pos):
        """
        Right-click in the magnifier: copy the color there in any format.
        :param pos: (QPoint) Widget position.
        :return:
        """
        color = self._colorAtView(pos)  # type: QColor
        if color.isValid():
            self.__m_colorPanel.setCurrentColor(color)
            menu = self.__m_colorPanel.buildCopyMenu(color, self)  # type: QMenu
            (getattr(menu, 'exec_', None) or getattr(menu, 'exec'))(self.__m_view.mapToGlobal(pos))

    @pyqtSlot()
    def _onColorPickHotkey(self):
        """
        "Copy the zoomer color code" hotkey (the zoomer is shown with its color code on): copies exactly the color
        shown by the zoomer readout (same function, same pick source and sample size).
        :return:
        """
        lens = self.__m_game.getOverlay()
        color = lens.readoutColor()  # type: QColor
        text = self.__m_colorPanel.copyColor(color) if color.isValid() else ''  # type: str
        if text:
            lens.showToast(self.tr(u'{} copied').format(text), color)

    @pyqtSlot(QPoint)
    def _onScreenPick(self, pos):
        """
        Screen color picker: copy the exact screen pixel at the click (fresh grab, not the lens frame).
        :param pos: (QPoint) Global position.
        :return:
        """
        size = self.__m_colorPanel.getSampleSize()  # type: int
        image, dpr = ScreenGrabber.grabRect(QRect(pos.x() - size // 2, pos.y() - size // 2, size, size))
        color = sampleColor(image, image.width() // 2, image.height() // 2, max(1, int(round(size * dpr))))
        if not color.isValid():
            color = self.__m_game.getOverlay().centerColor()  # type: QColor
        text = self.__m_colorPanel.copyColor(color)  # type: str
        if text:
            self.__m_game.getOverlay().showToast(self.tr(u'{} copied').format(text), color)
        self.__m_game.stopColorPicker(900)

    @pyqtSlot(QColor, 'QString')
    def _onColorCopied(self, color, text):
        """
        :param color: QColor
        :param text: str | unicode | QString
        :return:
        """
        if self.isVisible() and not self.isMinimized():
            self.__m_view.showToast(self.tr(u'{} copied').format(text), color)

    # ---------- Detection / server wiring ----------
    def _dockWidgets(self):
        """
        :return: (list[QWidget]) This window and its docks (ignored by follow-cursor capture).
        """
        return [self, self.__m_dock, self.__m_gameDock, self.__m_colorDock, self.__m_detectDock, self.__m_serverDock,
                self.__m_shortcutDock]

    def _processView(self, image, size):
        """
        Magnifier processor: the server when offloading is on and connected, else the local upscaler.
        :param image: QImage
        :param size: QSize
        :return: QImage
        """
        if self.__m_serverPanel.isOffloadView():
            return self.__m_remoteView(image, size)
        return self.__m_upscaler.process(image, size)

    def _processLens(self, image, size):
        """
        Zoomer (advanced zoom lens) processor.
        :param image: QImage
        :param size: QSize
        :return: QImage
        """
        if self.__m_serverPanel.isOffloadLens():
            return self.__m_remoteLens(image, size)
        return self.__m_upscaler.process(image, size)

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def _onRemoteResult(self, channel):
        """
        A server result arrived: repaint the consumer (it picks the result up from the client's cache).
        :param channel: str | unicode | QString
        :return:
        """
        if u'{}'.format(channel) == 'view':
            self.__m_view.refresh()
        elif u'{}'.format(channel) == 'lens':
            self.__m_game.getOverlay().refresh()

    @pyqtSlot()
    def _onOffloadChanged(self):
        """
        :return:
        """
        self.__m_view.refresh()
        self.__m_game.getOverlay().refresh()

    @pyqtSlot('QString', object, object, object, object)
    def _onAnnotations(self, source, annotations, size, overlay, origin):
        """
        :param source: str | unicode | QString
        :param annotations: list[dict]
        :param size: QSize
        :param overlay: QImage
        :param origin: (list | None) [x, y, dpr] screen position of the analysed frame.
        :return:
        """
        target = self.__m_view if u'{}'.format(source) == 'view' else self.__m_game.getOverlay()
        target.setAnnotations(annotations, size if size is not None and size.isValid() else None, origin)
        target.setOverlayImage(overlay)

    @pyqtSlot(QImage)
    def _onLensFrame(self, image):
        """
        :param image: QImage
        :return:
        """
        grabber = self.__m_game.getGrabber()
        origin, dpr = grabber.getCaptureRect().topLeft(), grabber.getDevicePixelRatio()
        self.__m_game.getOverlay().setFrameOrigin(origin, dpr)
        if self.__m_features.get('zonesInZoomer') and self.__m_game.getOverlay().isVisible():
            self.__m_analysis.submit('lens', image, origin, dpr)

    def supportMenu(self, parent):
        """
        "Support the project" menu: one entry per donation platform (support.py).
        :param parent: QWidget
        :return: QMenu
        """
        menu = QMenu(self.tr(u'\u2665  Support the project'), parent)  # type: QMenu
        for name, url in DONATION_LINKS:
            act = menu.addAction(self.tr(u'Donate with {}').format(name))  # type: QAction
            act.setToolTip(url)
            act.triggered.connect(lambda checked=False, u=url: self.openDonation(u))
        return menu

    def languageMenu(self, parent):
        """
        Interface languages: automatic (system language) or one of the catalogs.
        :param parent: QWidget
        :return: QMenu
        """
        lm = self.__m_languages  # type: LanguageManager
        menu = QMenu(parent)  # type: QMenu
        group = QActionGroup(menu)  # type: QActionGroup
        entries = [('auto', self.tr(u'Automatic ({})').format(lm.nativeName(lm.systemLanguage())))]  # type: list
        entries += lm.availableLanguages()
        for i, (code, name) in enumerate(entries):
            act = menu.addAction(name)  # type: QAction
            act.setCheckable(True)
            act.setChecked(code == lm.getRequestedLanguage())
            act.setData(code)
            group.addAction(act)
            act.triggered.connect(lambda checked=False, c=code: self.chooseLanguage(c))
            if i == 0:
                menu.addSeparator()
        return menu

    def getLanguageManager(self):
        """
        :return: LanguageManager
        """
        return self.__m_languages

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def chooseLanguage(self, code):
        """
        Save the interface language; it applies when the application restarts (offered right away).
        :param code: (str | unicode | QString) Language code or 'auto'.
        :return:
        """
        lm = self.__m_languages  # type: LanguageManager
        QSettings('ScreenMagnifier', 'General').setValue('language', u'{}'.format(code))
        if lm.resolve(code) == lm.getLanguage():
            return
        text = self.tr(RESTART_QUESTION)  # type: str
        other = lm.translateIn(code, RESTART_QUESTION)  # type: str  # also in the language just chosen
        if other != text:
            text += '\n\n' + other
        box = QMessageBox(QMessageBox.Question, self.tr(u'Language'), text, QMessageBox.NoButton,
                          self)  # type: QMessageBox
        restart = box.addButton(self.tr(u'Restart now'), QMessageBox.AcceptRole)
        box.addButton(self.tr(u'Later'), QMessageBox.RejectRole)
        (getattr(box, 'exec_', None) or getattr(box, 'exec'))()
        if box.clickedButton() is restart:
            self.restartApplication()

    @pyqtSlot()
    def restartApplication(self):
        """
        Start a new instance (it waits until this one has exited), then quit.
        :return:
        """
        from subprocess import Popen
        command, env = restartCommand(sys.argv, ('--wait-pid', u'{}'.format(getpid())))
        flags = {'creationflags': 0x00000008} if platform == 'win32' else {'start_new_session': True}  # Detached.
        Popen(command, env=env, close_fds=True, **flags)
        self.quitApp()

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def openDonation(self, url):
        """
        :param url: str | unicode | QString
        :return:
        """
        if not QDesktopServices.openUrl(QUrl(u'{}'.format(url))):
            QApplication.clipboard().setText(u'{}'.format(url))
            self._notify(self.tr(u'Could not open a browser - the link was copied: {}').format(url))

    def _fitPanels(self):
        """
        Every side-panel tab fits any panel width, in every language (translations are often longer than English):
        descriptive labels wrap, combo boxes do not force their width (the list still shows full texts), and a
        horizontal scroll bar appears only if something still cannot shrink - nothing is ever cut off.
        :return:
        """
        for dock in self._dockWidgets()[1:]:
            area = dock.widget()
            if not isinstance(area, QScrollArea) or area.widget() is None:
                continue
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            for label in area.widget().findChildren(QLabel):
                image = label.pixmap()  # None (PyQt5) or a null QPixmap (PyQt6) when the label shows text
                if label.property('role') in ('mono', 'big') or (image is not None and not image.isNull()):
                    continue  # Color codes stay on one line; images are not text.
                label.setWordWrap(True)
            for combo in area.widget().findChildren(QComboBox):
                combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                combo.setMinimumContentsLength(10)
                QApplication.sendEvent(combo, QEvent(QEvent.StyleChange))  # QComboBox caches its minimum size
                combo.updateGeometry()
            for box in area.widget().findChildren(QCheckBox):
                if box.minimumSizeHint().width() > 220:
                    self._wrapCheckBox(box)
        if hasattr(self, "resizeDocks"):
            self.resizeDocks([self.__m_dock], [440], Qt.Horizontal)
        else:
            self.__m_dock.resize(440, self.__m_dock.height())

    @staticmethod
    def _wrapCheckBox(box):
        """
        QCheckBox cannot wrap its text: move a long text into a word-wrapping label beside the box (clicking the
        label toggles it; enabled state and tooltip follow). The QCheckBox object, its signals and state are kept.
        :param box: QCheckBox
        :return: None
        """
        layout = box.parentWidget().layout() if box.parentWidget() is not None else None
        index = layout.indexOf(box) if layout is not None else -1  # type: int
        if index < 0 or not isinstance(layout, (QVBoxLayout, QHBoxLayout)):
            return
        row = QWidget(box.parentWidget())  # type: QWidget
        line = QHBoxLayout(row)  # type: QHBoxLayout
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        label = QLabel(box.text(), row)  # type: QLabel
        label.setWordWrap(True)
        label.setToolTip(box.toolTip())
        label.setEnabled(box.isEnabled())
        link = CheckBoxLabelLink(box, label, parent=row)  # type: CheckBoxLabelLink
        label.installEventFilter(link)
        box.installEventFilter(link)
        layout.insertWidget(index, row)
        box.setAccessibleName(box.text())  # screen readers still announce the check box by its text
        box.setProperty('fullText', box.text())
        box.setText('')
        line.addWidget(box, 0, Qt.AlignTop)
        line.addWidget(label, 1)

    def _fullTabNames(self):
        """
        Side panel tabs keep their full names ("Magnifier", not "M..."): the tab bar scrolls when they do not fit.
        :return:
        """
        for bar in self.findChildren(QTabBar):
            bar.setElideMode(Qt.ElideNone)
            bar.setUsesScrollButtons(True)
            bar.setExpanding(False)

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setSidePanelVisible(self, on):
        """
        Show / hide the whole side panel (every tab).
        :param on: bool
        :return:
        """
        for dock in self._dockWidgets()[1:]:
            dock.setVisible(bool(on))
        if on:
            self.__m_dock.raise_()
        if self.__m_actPanel.isChecked() != bool(on):
            self.__m_actPanel.blockSignals(True)
            self.__m_actPanel.setChecked(bool(on))
            self.__m_actPanel.blockSignals(False)

    def _syncPanelAction(self):
        """
        Docks closed / reopened by hand: the Panel button follows (checked while any tab is shown).
        :return:
        """
        shown = any(d.isVisible() for d in self._dockWidgets()[1:])  # type: bool
        self.__m_actPanel.blockSignals(True)
        self.__m_actPanel.setChecked(shown)
        self.__m_actPanel.blockSignals(False)

    def _onFeatureChanged(self, name, on):
        """
        A "where are the zones shown" switch changed: switching one off clears its zones immediately.
        :param name: str | unicode | QString
        :param on: bool
        :return:
        """
        source = {'zonesInMagnifier': 'view', 'zonesInZoomer': 'lens'}.get(u'{}'.format(name))  # type: str | None
        if source and not on:
            self.__m_analysis.forget(source)

    def _syncLensReadout(self):
        """
        The zoomer color code follows the Colors tab (pick source, sample size), so it always shows what is copied.
        :return:
        """
        lens = self.__m_game.getOverlay()
        lens.setReadoutSource(self.__m_colorPanel.getPickSource())
        lens.setReadoutSample(self.__m_colorPanel.getSampleSize())
        lens.update()  # the copy format may have changed: same text everywhere
        self.__m_view.update()

    def _notify(self, message):
        """
        Status bar message; also a tray balloon when the window is hidden (e.g. while gaming).
        :param message: str | unicode | QString
        :return:
        """
        self.statusBar().showMessage(u'{}'.format(message), 4000)
        if self.__m_tray is not None and not self.isVisible():
            self.__m_tray.showMessage(
                self.tr(u'Screen Magnifier'), u'{}'.format(message), QSystemTrayIcon.Information, 2500)

    # ---------- Qt overrides ----------
    def eventFilter(self, obj, e):
        """
        :param obj: QObject
        :param e: QEvent
        :return: bool
        """
        if obj is self.__m_view and e.type() == QEvent.Resize and self.__m_grabber.isFollowCursor():
            self._updateFollowSize()
        if obj is self.__m_view and e.type() in (QEvent.Enter, QEvent.Leave):
            self.__m_mouseInView = e.type() == QEvent.Enter  # type: bool
            if not self.__m_mouseInView:  # The live color goes back to the zoomer, if it shows its color code.
                lens = self.__m_game.getOverlay()
                self._onZoomerReadout(lens.readoutColor(), lens.zoneAtCrosshair())
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
                self.__m_grabber.setIgnoreWidgets([] if excluded else self._dockWidgets())

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
                self.__m_tray.showMessage(self.tr(u'Screen Magnifier is still running'), self.tr(
                    'Press {} in any app or game to toggle the zoom lens. Right-click the tray icon to quit.').format(
                    self.__m_game.getHotkey(
                        'toggle') or self.tr(u'The game-zoom hotkey')), QSystemTrayIcon.Information, 4000)
            return
        self.__m_game.shutdown()
        self.__m_analysis.shutdown()
        self.__m_client.disconnectFromServer()
        self.__m_serverPanel.stopLocalServer()
        if self.__m_tray is not None:
            self.__m_tray.hide()
        self.__m_grabber.stop()
        self.__m_statsTimer.stop()
        self.__m_selector.close()
        super(MainWindow, self).closeEvent(e)
