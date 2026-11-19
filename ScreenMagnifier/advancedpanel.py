# -*- coding: utf-8 -*-
"""
AdvancedOverlayPanel: settings for the in-advanced zoom lens (global hotkeys, target, placement, lens look).
"""
from ManyQt.QtWidgets import QGridLayout, QSpinBox, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QComboBox, QFrame, \
    QCheckBox, QPushButton, QScrollArea
from ManyQt.QtCore import QRect, QTimer, Qt, pyqtSlot
from ManyQt.QtGui import QGuiApplication
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .advancedoverlay import AdvancedOverlayController
    from .regionselector import RegionSelector
    from .imagefilters import ImageFilters
    from .zoomoverlay import ZoomOverlay
except:
    from advancedoverlay import AdvancedOverlayController
    from regionselector import RegionSelector
    from imagefilters import ImageFilters
    from zoomoverlay import ZoomOverlay

PANEL_QSS = """
QWidget#gameContent { background: transparent; }
QLabel[role="title"] { color: #9AA3B8; font-size: 10px; font-weight: bold; letter-spacing: 1px; padding-top: 10px; }
QLabel[role="value"] { color: #E8EBF2; font-weight: bold; }
QLabel[role="hint"] { color: #7C8498; font-size: 10px; }
QLabel[role="ok"] { color: #43C16A; font-weight: bold; }
QLabel[role="bad"] { color: #FF5A6E; font-weight: bold; }
QLabel[role="warn"] { color: #FFB86B; font-size: 10px; }
QKeySequenceEdit QLineEdit { background: #2A2E3A; color: #E8EBF2; border: 1px solid #3A3F50; border-radius: 6px;
                             padding: 4px 6px; }
QPushButton[role="primary"] { background: #3A4BD8; border-color: #4F8BFF; font-weight: bold; padding: 8px; }
QPushButton[role="small"] { padding: 2px 6px; min-width: 18px; }
"""  # type: str

TARGET_NAMES = ['Screen centre', 'Pinned point', 'Mouse cursor']  # type: list[str]
PLACEMENT_NAMES = ['On target (scope)', 'Top-left corner', 'Top-right corner', 'Bottom-left corner',
                   'Bottom-right corner', 'Next to the target (follows a mouse target)', 'Custom area',
                   'Full screen']  # type: list[str]
SHAPE_NAMES = ['Circle', 'Rounded square', 'Rectangle']  # type: list[str]



class AdvancedOverlayPanel(QScrollArea):
    """
    AdvancedOverlayPanel class.
    """

    def __init__(self, *args, **kwargs):
        """
        :param controller: AdvancedOverlayController
        :param args: any
        :param kwargs: any
        """
        controller = kwargs.pop('controller', None)  # type: AdvancedOverlayController
        features = kwargs.pop('features', None)  # type: FeatureSettings | None
        super(AdvancedOverlayPanel, self).__init__(*args, **kwargs)
        self.__m_ctrl = controller  # type: AdvancedOverlayController
        self.__m_features = features  # type: FeatureSettings | None
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(250)
        content = QWidget()  # type: QWidget
        content.setObjectName('gameContent')
        content.setStyleSheet(PANEL_QSS)
        self.__m_layout = QVBoxLayout(content)  # type: QVBoxLayout
        self.__m_layout.setContentsMargins(14, 6, 14, 14)
        self.__m_layout.setSpacing(6)
        self._buildTop()
        self._buildLens()
        self._buildColorTools()
        self.__m_layout.addStretch(1)
        self.setWidget(content)
        ov = controller.getOverlay()  # type: ZoomOverlay
        controller.settingsChanged.connect(self.refresh)
        controller.overlayToggled.connect(self.refresh)
        ov.zoomChanged.connect(self.refresh)
        controller.getHotkeys().registrationChanged.connect(self.refresh)
        if features is not None:
            features.changed.connect(lambda *a: self.refresh())
        ov.captureStatusChanged.connect(self.refresh)
        ov.captureDetailChanged.connect(self.refresh)
        self.refresh()

    # ---------- Helpers ----------
    @staticmethod
    def _label(text, role):
        """
        :param text: str | unicode | QString
        :param role: str | unicode | QString
        :return: QLabel
        """
        lbl = QLabel(text)  # type: QLabel
        lbl.setProperty('role', role)
        return lbl

    def _buildAreaControls(self):
        """
        Custom area (draw it on the screen, or type it) and full-screen screen choice.
        :return:
        """
        ctrl = self.__m_ctrl  # type: AdvancedOverlayController
        self.__m_customBox = QWidget()  # type: QWidget
        grid = QGridLayout(self.__m_customBox)  # type: QGridLayout
        grid.setContentsMargins(0, 0, 0, 0)
        self.__m_draw = QPushButton(self.tr(u'Draw the area on the screen\u2026'))  # type: QPushButton
        self.__m_draw.setToolTip(self.tr(u'Drag a rectangle anywhere on the screen: the lens will fill it'))
        self.__m_draw.clicked.connect(self._drawArea)
        grid.addWidget(self.__m_draw, 0, 0, 1, 4)
        self.__m_areaSpins = []  # type: list[QSpinBox]
        for i, (label, lo) in enumerate(((self.tr(u'X'), -32768), (self.tr(u'Y'), -32768), (self.tr(u'Width'), 64),
                                         (self.tr(u'Height'), 64))):
            spin = QSpinBox()  # type: QSpinBox
            spin.setRange(lo, 32768)
            spin.setToolTip(self.tr(u'Pixels'))  # (no suffix: keeps the tab narrow in every language)
            spin.setKeyboardTracking(False)  # apply when typing is done, not at every digit
            spin.valueChanged.connect(self._typedArea)
            grid.addWidget(QLabel(label), 1 + i // 2, (i % 2) * 2)
            grid.addWidget(spin, 1 + i // 2, (i % 2) * 2 + 1)
            self.__m_areaSpins.append(spin)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.__m_layout.addWidget(self.__m_customBox)
        self.__m_screen = QComboBox()  # type: QComboBox
        self.__m_screen.setToolTip(self.tr(u'Screen covered by the full-screen lens'))
        self.__m_screen.activated.connect(lambda i: ctrl.setFullScreenIndex(i - 1))
        self.__m_layout.addWidget(self.__m_screen)
        self.__m_selector = None  # type: RegionSelector | None  # created on first use
        self.__m_lensWasVisible = False  # type: bool
        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda *a: self.refresh())
        if hasattr(app, "screenRemoved"):
            app.screenRemoved.connect(lambda *a: self.refresh())

    def _buildCornerRadius(self):
        """
        Corner radius of the rounded-square lens (hidden for the other shapes and the full-screen lens).
        :return:
        """
        self.__m_cornerBox = QWidget()  # type: QWidget
        box = QVBoxLayout(self.__m_cornerBox)  # type: QVBoxLayout
        box.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()  # type: QHBoxLayout
        row.addWidget(AdvancedOverlayPanel._label(self.tr(u'Corner radius').upper(), 'title'))
        row.addStretch(1)
        self.__m_cornerValue = QLabel()  # type: QLabel
        self.__m_cornerValue.setProperty('role', 'value')
        self.__m_cornerValue.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        row.addWidget(self.__m_cornerValue)
        box.addLayout(row)
        self.__m_corner = QSlider(Qt.Horizontal)  # type: QSlider
        self.__m_corner.setRange(0, 200)
        self.__m_corner.setToolTip(self.tr(u'0 = square corners; the largest values make a pill or a circle'))
        self.__m_corner.valueChanged.connect(self._cornerChanged)
        box.addWidget(self.__m_corner)
        self.__m_layout.addWidget(self.__m_cornerBox)

    @pyqtSlot(int)
    def _cornerChanged(self, radius):
        """
        :param radius: int
        :return:
        """
        self.__m_ctrl.setCornerRadius(radius)
        self.__m_cornerValue.setText(self._cornerText())

    def _cornerText(self):
        """
        :return: (str | unicode | QString) The radius, and what is drawn when the lens is too small for it.
        """
        ov = self.__m_ctrl.getOverlay()  # type: ZoomOverlay
        geo = ov.lensGeometry()  # type: QRect
        drawn = int(min(ov.getCornerRadius(), min(geo.width(), geo.height()) // 2))  # type: int
        return '{} px'.format(drawn) if drawn == ov.getCornerRadius() else self.tr(u'{} px (max)').format(drawn)

    def _screenItems(self):
        """
        :return: (list[str | unicode | QString]) Screen choices: the target's screen, then every screen.
        """
        items = [self.tr(u'Screen of the target')]  # type: list[str]
        primary = QGuiApplication.primaryScreen()
        for i, screen in enumerate(QGuiApplication.screens()):
            g = screen.geometry()
            text = self.tr(u'Screen {} \u00b7 {} \u00d7 {}').format(i + 1, g.width(), g.height())  # type: str
            items.append(text + (self.tr(u' (primary)') if screen is primary else ''))
        return items

    @pyqtSlot()
    def _drawArea(self):
        """
        Hide the window (and a visible lens, which may cover the screen), then let the user drag the lens area.
        :return:
        """
        if self.__m_selector is None:
            self.__m_selector = RegionSelector(regionSelected=self._onAreaDrawn,
                                               selectionCanceled=self._restoreAfterDrawing)  # type: RegionSelector
        ov = self.__m_ctrl.getOverlay()  # type: ZoomOverlay
        self.__m_lensWasVisible = ov.isVisible()  # type: bool
        if self.__m_lensWasVisible:
            ov.hideOverlay()
        self.window().hide()
        QTimer.singleShot(250, self.__m_selector.start)

    @pyqtSlot(QRect)
    def _onAreaDrawn(self, rect):
        """
        :param rect: (QRect) Global, device-independent area.
        :return:
        """
        if rect.width() >= 64 and rect.height() >= 64:
            self.__m_ctrl.setCustomRect(rect)
            self.__m_ctrl.setPlacement(ZoomOverlay.Custom)
        self._restoreAfterDrawing()

    @pyqtSlot()
    def _restoreAfterDrawing(self):
        """
        :return:
        """
        self.window().show()
        self.window().raise_()
        if self.__m_lensWasVisible:
            self.__m_ctrl.getOverlay().showOverlay()
        self.refresh()

    @pyqtSlot()
    def _typedArea(self):
        """
        :return:
        """
        x, y, w, h = [spin.value() for spin in self.__m_areaSpins]
        self.__m_ctrl.setCustomRect(QRect(x, y, w, h))
        self.refresh()

    def _titleRow(self, title, valueLabel=None):
        """
        :param title: str | unicode | QString
        :param valueLabel: QLabel | None
        :return:
        """
        row = QHBoxLayout()  # type: QHBoxLayout
        row.addWidget(AdvancedOverlayPanel._label(title.upper(), 'title'))
        row.addStretch(1)
        if valueLabel is not None:
            valueLabel.setProperty('role', 'value')
            valueLabel.setAlignment(Qt.AlignRight | Qt.AlignBottom)
            row.addWidget(valueLabel)
        self.__m_layout.addLayout(row)

    def _slider(self, lo, hi, slot):
        """
        :param lo: int
        :param hi: int
        :param slot: callable
        :return: QSlider
        """
        s = QSlider(Qt.Horizontal)  # type: QSlider
        s.setRange(lo, hi)
        s.valueChanged.connect(slot)
        self.__m_layout.addWidget(s)
        return s

    def _combo(self, items, slot):
        """
        :param items: list[str | unicode | QString]
        :param slot: callable
        :return: QComboBox
        """
        c = QComboBox()  # type: QComboBox
        c.addItems([self.tr(i) for i in items])
        c.currentIndexChanged.connect(slot)
        self.__m_layout.addWidget(c)
        return c

    def _buildTop(self):
        """
        :return:
        """
        self.__m_toggle = QPushButton()  # type: QPushButton
        self.__m_toggle.setProperty('role', 'primary')
        self.__m_toggle.setFocusPolicy(Qt.NoFocus)
        self.__m_toggle.clicked.connect(self.__m_ctrl.toggle)
        self.__m_layout.addWidget(self.__m_toggle)

    def _buildColorTools(self):
        """
        The zoomer's two optional color features, side by side.
        :return:
        """
        self._titleRow(self.tr(u'Color tools in the zoomer'))
        self.__m_readout = QCheckBox(self.tr(u'Color code under the crosshair (live HEX / RGB)'))  # type: QCheckBox
        self.__m_readout.toggled.connect(self.__m_ctrl.setColorReadout)
        self.__m_layout.addWidget(self.__m_readout)
        self.__m_zones = QCheckBox(
            self.tr(u'Color zones (target colors and faces of the Detection tab)'))  # type: QCheckBox
        self.__m_zones.setEnabled(self.__m_features is not None)
        if self.__m_features is not None:
            self.__m_zones.toggled.connect(lambda on: self.__m_features.set('zonesInZoomer', on))
        self.__m_layout.addWidget(self.__m_zones)
        self.__m_colorHint = AdvancedOverlayPanel._label('', 'hint')  # type: QLabel
        self.__m_colorHint.setWordWrap(True)
        self.__m_layout.addWidget(self.__m_colorHint)

    def _buildLens(self):
        """
        :return:
        """
        ctrl = self.__m_ctrl  # type: AdvancedOverlayController
        self.__m_pointLabel = QLabel()  # type: QLabel
        self._titleRow(self.tr(u'Magnify'), self.__m_pointLabel)
        self.__m_target = self._combo(TARGET_NAMES, ctrl.setTarget)  # type: QComboBox
        self._titleRow(self.tr(u'Show the lens'))
        self.__m_placement = self._combo(PLACEMENT_NAMES, ctrl.setPlacement)  # type: QComboBox
        self._buildAreaControls()
        self.__m_overlapHint = AdvancedOverlayPanel._label('', 'hint')  # type: QLabel
        self.__m_overlapHint.setWordWrap(True)
        self.__m_layout.addWidget(self.__m_overlapHint)
        self.__m_shape = self._combo(SHAPE_NAMES, ctrl.setShape)  # type: QComboBox
        self.__m_shape.currentIndexChanged.connect(lambda *a: self.refresh())  # show / hide the corner radius
        self._buildCornerRadius()
        self.__m_zoomValue = QLabel()  # type: QLabel
        self._titleRow(self.tr(u'Magnification'), self.__m_zoomValue)
        self.__m_zoom = self._slider(10, 160, lambda v: ctrl.setZoom(v / 10.0))  # type: QSlider
        self.__m_sizeValue = QLabel()  # type: QLabel
        self._titleRow(self.tr(u'Lens size'), self.__m_sizeValue)
        self.__m_size = self._slider(8, 45, lambda v: ctrl.setLensSize(v * 20))  # type: QSlider
        self.__m_opacityValue = QLabel()  # type: QLabel
        self._titleRow(self.tr(u'Opacity'), self.__m_opacityValue)
        self.__m_opacity = self._slider(30, 100, lambda v: ctrl.setOpacity(v / 100.0))  # type: QSlider
        self.__m_fpsValue = QLabel()  # type: QLabel
        self._titleRow(self.tr(u'Frame rate'), self.__m_fpsValue)
        self.__m_fps = self._slider(15, 144, ctrl.setFps)  # type: QSlider
        self.__m_crosshair = QCheckBox(self.tr(u'Crosshair'))  # type: QCheckBox
        self.__m_crosshair.toggled.connect(ctrl.setCrosshair)
        self.__m_layout.addWidget(self.__m_crosshair)
        tip = AdvancedOverlayPanel._label(self.tr(
            u'Run the game in borderless / windowed full-screen: exclusive full-screen hides every overlay. '
            u'The lens never takes focus and lets all clicks through to the game.'), 'hint')  # type: QLabel
        tip.setWordWrap(True)
        self.__m_layout.addWidget(tip)
        self._buildFilters()

    def _buildFilters(self):
        """
        FILTERS: an effect (with its strength) and brightness / contrast / saturation for the lens image.
        :return:
        """
        filters = self.__m_ctrl.getFilters()  # type: ImageFilters
        self._titleRow(self.tr(u'Filters'))
        self.__m_effect = self._combo([self.tr(n) for n in ImageFilters.EFFECT_NAMES], filters.setEffect)  # type: QComboBox
        if not ImageFilters.isAvailable():  # without NumPy, Qt alone does Invert and Grayscale
            model = self.__m_effect.model()
            for i, name in enumerate(ImageFilters.EFFECT_NAMES):
                if name not in ('None', 'Grayscale', 'Invert') and hasattr(model, 'item'):
                    model.item(i).setEnabled(False)
            self.__m_layout.addWidget(AdvancedOverlayPanel._label(
                self.tr(u'Install numpy for every effect and the sliders.'), 'hint'))
        self.__m_filterSliders = {}  # type: dict
        for name, title, lo in (('strength', self.tr(u'Strength'), 0), ('brightness', self.tr(u'Brightness'), -100),
                                ('contrast', self.tr(u'Contrast'), -100), ('saturation', self.tr(u'Saturation'), -100)):
            box = QWidget()  # type: QWidget
            column = QVBoxLayout(box)  # type: QVBoxLayout
            column.setContentsMargins(0, 0, 0, 0)
            row = QHBoxLayout()  # type: QHBoxLayout
            row.addWidget(AdvancedOverlayPanel._label(title.upper(), 'title'))
            row.addStretch(1)
            value = QLabel()  # type: QLabel
            value.setProperty('role', 'value')
            row.addWidget(value)
            column.addLayout(row)
            slider = QSlider(Qt.Horizontal)  # type: QSlider
            slider.setRange(lo, 100)
            slider.valueChanged.connect(getattr(filters, 'set' + name[0].upper() + name[1:]))
            slider.valueChanged.connect(lambda v, label=value, signed=lo < 0: label.setText(
                ('{:+d}' if signed and v else '{}').format(v) + ('' if signed else ' %')))
            column.addWidget(slider)
            box.setEnabled(ImageFilters.isAvailable())
            self.__m_layout.addWidget(box)
            self.__m_filterSliders[name] = (box, slider, value)
        reset = QPushButton(self.tr(u'Reset the filters'))  # type: QPushButton
        reset.clicked.connect(filters.reset)
        self.__m_layout.addWidget(reset)
        filters.changed.connect(self._refreshFilters)

    def _refreshFilters(self):
        """
        :return:
        """
        filters = self.__m_ctrl.getFilters()  # type: ImageFilters
        self.__m_effect.blockSignals(True)
        self.__m_effect.setCurrentIndex(filters.getEffect())
        self.__m_effect.blockSignals(False)
        for name, (box, slider, value) in self.__m_filterSliders.items():
            v = getattr(filters, 'get' + name[0].upper() + name[1:])()  # type: int
            if slider.value() != v:
                slider.blockSignals(True)
                slider.setValue(v)
                slider.blockSignals(False)
            signed = slider.minimum() < 0  # type: bool
            value.setText(('{:+d}' if signed and v else '{}').format(v) + ('' if signed else ' %'))
        self.__m_filterSliders['strength'][0].setVisible(filters.getEffect() != 0)  # only with an effect

    @pyqtSlot()
    def _refreshCaptureStatus(self, ov):
        """
        Explain whether 'On target' really works (the lens must be invisible to screen capture).
        :param ov: ZoomOverlay
        :return:
        """
        status = ov.getCaptureStatus()  # type: str
        text, role = '', 'hint'  # type: str, str
        if ov.getPlacement() in (ZoomOverlay.Custom, ZoomOverlay.FullScreen):
            if status == 'testing':
                text = self.tr(u'Checking that the lens is hidden from screen capture\u2026')
            elif status == 'excluded':
                text, role = self.tr(u'\u2713 Lens hidden from screen capture: it can cover what it magnifies.'), 'ok'
            elif status == 'windowCapture':
                text, role = self.tr(u'\u2713 Capturing the game window directly (Windows could not hide the lens '
                                     'from screen capture).'), 'ok'
            elif status == 'otherScreen':
                text, role = self.tr(u'\u26a0 The lens cannot cover what it magnifies here: {}. The full-screen lens '
                                     'is shown on screen {} instead.').format(
                    ov.getCaptureDetail(), (ov.getFallbackScreen() or 0) + 1), 'warn'
            elif status == 'failed':
                corner = self.tr(PLACEMENT_NAMES[int(ov.getEffectivePlacement())]).lower()  # type: str
                text, role = self.tr(u'\u26a0 The lens cannot cover what it magnifies here: {}. It is shown in the {} '
                                     'instead.').format(ov.getCaptureDetail(), corner), 'warn'
            elif not ZoomOverlay.canExcludeFromCapture() and ov.getPlacement() == ZoomOverlay.FullScreen:
                text = self.tr(u'Only Windows 10 (2004+) / 11 can hide the lens from capture: on this system a '
                               'full-screen lens needs a second screen (it moves there automatically).')
        elif ov.getPlacement() == ZoomOverlay.OnTarget:
            if status == 'testing':
                text = self.tr(u'Checking that the lens is hidden from screen capture\u2026')
            elif status == 'excluded':
                text, role = self.tr(u'\u2713 Lens hidden from screen capture: scope mode active.'), 'ok'
            elif status == 'windowCapture':
                text, role = self.tr(u'\u2713 Scope mode active: capturing the game window directly (Windows '
                                     'could not hide the lens from screen capture).'), 'ok'
            elif status == 'failed':
                corner = self.tr(PLACEMENT_NAMES[int(ov.getEffectivePlacement())]).lower()  # type: str
                text, role = self.tr(u'\u26a0 Scope mode is not possible here: {}. Without it the lens would '
                                     'magnify itself, so it is shown in the {} instead.').format(
                    ov.getCaptureDetail(), corner), 'warn'
            elif not ZoomOverlay.canExcludeFromCapture():
                text = self.tr(u'Only Windows 10 (2004+) / 11 can hide the lens from capture; on this system it '
                               'will be shown in a free corner.')
        self.__m_overlapHint.setText(text)
        self.__m_overlapHint.setProperty('role', role)
        self.__m_overlapHint.setVisible(bool(text))
        self.__m_overlapHint.style().unpolish(self.__m_overlapHint)
        self.__m_overlapHint.style().polish(self.__m_overlapHint)

    # ---------- Public API ----------
    @pyqtSlot()
    def refresh(self):
        """
        Pull every value from the controller / overlay into the widgets.
        :return:
        """
        ctrl = self.__m_ctrl  # type: AdvancedOverlayController
        ov = ctrl.getOverlay()  # type: ZoomOverlay
        widgets = [self.__m_readout, self.__m_zones, self.__m_target, self.__m_placement, self.__m_shape, self.__m_zoom,
                   self.__m_size, self.__m_opacity, self.__m_fps, self.__m_crosshair]  # type: list
        for w in widgets:
            w.blockSignals(True)
        self.__m_readout.setChecked(ov.isShowColorReadout())
        self.__m_zones.setChecked(self.__m_features is not None and self.__m_features.get('zonesInZoomer'))
        self.__m_target.setCurrentIndex(int(ov.getTarget()))
        self.__m_placement.setCurrentIndex(int(ov.getPlacement()))
        self.__m_shape.setCurrentIndex(int(ov.getShape()))
        self.__m_zoom.setValue(int(round(ov.getZoom() * 10)))
        self.__m_size.setValue(int(round(ov.getLensSize().width() / 20.0)))
        self.__m_opacity.setValue(int(round(ov.getLensOpacity() * 100)))
        self.__m_fps.setValue(ctrl.getGrabber().getFps())
        self.__m_crosshair.setChecked(ov.isShowCrosshair())
        for w in widgets:
            w.blockSignals(False)
        placement = ov.getPlacement()
        area = ov.lensGeometry() if placement == ZoomOverlay.Custom else ov.getCustomRect()  # type: QRect
        for spin, value in zip(self.__m_areaSpins, (area.x(), area.y(), area.width(), area.height())):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.__m_screen.blockSignals(True)
        self.__m_screen.clear()
        self.__m_screen.addItems(self._screenItems())
        self.__m_screen.setCurrentIndex(max(0, min(self.__m_screen.count() - 1, ov.getFullScreenIndex() + 1)))
        self.__m_screen.blockSignals(False)
        self.__m_customBox.setVisible(placement == ZoomOverlay.Custom)
        self.__m_screen.setVisible(placement == ZoomOverlay.FullScreen)
        sized = placement not in (ZoomOverlay.Custom, ZoomOverlay.FullScreen)  # type: bool
        self.__m_size.setEnabled(sized)  # the custom area / the screen gives the size
        self.__m_shape.setEnabled(placement != ZoomOverlay.FullScreen)  # always a rectangle
        self.__m_corner.blockSignals(True)
        self.__m_corner.setValue(ov.getCornerRadius())
        self.__m_corner.blockSignals(False)
        self.__m_cornerValue.setText(self._cornerText())
        self._refreshFilters()
        self.__m_cornerBox.setVisible(ov.getShape() == ZoomOverlay.RoundedRect and placement != ZoomOverlay.FullScreen)
        self.__m_zoomValue.setText('{:.1f}\u00d7'.format(ov.getZoom()))
        geo = ov.lensGeometry()  # type: QRect
        self.__m_sizeValue.setText('{} px'.format(ov.getLensSize().width()) if sized else
                                   '{} \u00d7 {}'.format(geo.width(), geo.height()))
        self.__m_opacityValue.setText('{} %'.format(self.__m_opacity.value()))
        self.__m_fpsValue.setText('{} fps'.format(self.__m_fps.value()))
        tp = ov.getTargetPoint()
        self.__m_pointLabel.setText('({}, {})'.format(tp.x(), tp.y()) if ov.getTarget() == ZoomOverlay.Point else '')
        self._refreshCaptureStatus(ov)
        self.__m_colorHint.setText(self.tr(u'Copy the color code: {}. Screen color picker (click anywhere on the screen): '
                    '{}. Change them in the Shortcuts tab; pick format and sample in the Colors '
                    'tab.').format(ctrl.getHotkey('copyZoomerColor') or self.tr(u'no shortcut'),
                                   ctrl.getHotkey('screenPicker') or self.tr(u'no shortcut')))
        self.__m_toggle.setText((self.tr(u'Hide the zoomer ({})') if ov.isVisible() else self.tr(
            u'Show the zoomer ({})')).format(ctrl.getHotkey('toggle') or self.tr(u'no shortcut')))

    # ---------- Qt overrides ----------
