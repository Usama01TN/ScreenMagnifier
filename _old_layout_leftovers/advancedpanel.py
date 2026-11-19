# -*- coding: utf-8 -*-
"""
AdvancedOverlayPanel: settings for the in-advanced zoom lens (global hotkeys, target, placement, lens look).
"""
from ManyQt.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QSlider, QComboBox, QFrame, \
    QCheckBox, QPushButton, QScrollArea, QKeySequenceEdit, QLineEdit
from ManyQt.QtCore import Qt, QEvent, pyqtSlot
from ManyQt.QtGui import QKeySequence
from os.path import dirname
from sys import path

if dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .advancedoverlay import AdvancedOverlayController, HOTKEY_ACTIONS
    from .zoomoverlay import ZoomOverlay
except:
    from advancedoverlay import AdvancedOverlayController, HOTKEY_ACTIONS
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
                   'Bottom-right corner']  # type: list[str]
SHAPE_NAMES = ['Circle', 'Rounded square']  # type: list[str]


def firstChord(sequence):
    """
    :param sequence: QKeySequence
    :return: (str | unicode | QString)First chord in portable text ('' when empty).
    """
    text = sequence.toString(QKeySequence.PortableText)  # type: str
    return text.split(', ')[0] if text else ''


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
        super(AdvancedOverlayPanel, self).__init__(*args, **kwargs)
        self.__m_ctrl = controller  # type: AdvancedOverlayController
        self.__m_edits = {}  # type: dict  # name -> (QKeySequenceEdit, status QLabel)
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
        self._buildHotkeys()
        self._buildLens()
        self.__m_layout.addStretch(1)
        self.setWidget(content)
        ov = controller.getOverlay()  # type: ZoomOverlay
        controller.settingsChanged.connect(self.refresh)
        controller.overlayToggled.connect(self.refresh)
        ov.zoomChanged.connect(self.refresh)
        controller.getHotkeys().registrationChanged.connect(self.refresh)
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

    def _buildHotkeys(self):
        """
        :return:
        """
        self._titleRow(self.tr('Global hotkeys'))
        self.__m_hkEnabled = QCheckBox(self.tr('Work while other apps / games have focus'))  # type: QCheckBox
        self.__m_hkEnabled.toggled.connect(self.__m_ctrl.setHotkeysEnabled)
        self.__m_layout.addWidget(self.__m_hkEnabled)
        grid = QGridLayout()  # type: QGridLayout
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        for row, (name, title, default) in enumerate(HOTKEY_ACTIONS):
            edit = QKeySequenceEdit()  # type: QKeySequenceEdit
            edit.setToolTip(self.tr('Click, then press the new shortcut (default {}).').format(default))
            edit.installEventFilter(self)
            for inner in edit.findChildren(QLineEdit):  # Focus is forwarded to an internal line edit.
                inner.installEventFilter(self)
            edit.editingFinished.connect(lambda n=name, e=edit: self._recorded(n, e))
            status = QLabel()  # type: QLabel
            status.setFixedWidth(16)
            clear = QPushButton('\u2715')  # type: QPushButton
            clear.setProperty('role', 'small')
            clear.setToolTip(self.tr('Remove this shortcut'))
            clear.setFocusPolicy(Qt.NoFocus)
            clear.clicked.connect(lambda checked=False, n=name, e=edit: (e.clear(), self.__m_ctrl.setHotkey(n, '')))
            grid.addWidget(QLabel(self.tr(title)), row * 2, 0, 1, 3)
            grid.addWidget(edit, row * 2 + 1, 0)
            grid.addWidget(status, row * 2 + 1, 1)
            grid.addWidget(clear, row * 2 + 1, 2)
            self.__m_edits[name] = (edit, status)
        self.__m_layout.addLayout(grid)
        self.__m_hkInfo = AdvancedOverlayPanel._label('', 'hint')  # type: QLabel
        self.__m_hkInfo.setWordWrap(True)
        self.__m_layout.addWidget(self.__m_hkInfo)
        self.__m_toggle = QPushButton()  # type: QPushButton
        self.__m_toggle.setProperty('role', 'primary')
        self.__m_toggle.setFocusPolicy(Qt.NoFocus)
        self.__m_toggle.clicked.connect(self.__m_ctrl.toggle)
        self.__m_layout.addWidget(self.__m_toggle)

    def _buildLens(self):
        """
        :return:
        """
        ctrl = self.__m_ctrl  # type: AdvancedOverlayController
        self.__m_pointLabel = QLabel()  # type: QLabel
        self._titleRow(self.tr('Magnify'), self.__m_pointLabel)
        self.__m_target = self._combo(TARGET_NAMES, ctrl.setTarget)  # type: QComboBox
        self._titleRow(self.tr('Show the lens'))
        self.__m_placement = self._combo(PLACEMENT_NAMES, ctrl.setPlacement)  # type: QComboBox
        self.__m_overlapHint = AdvancedOverlayPanel._label('', 'hint')  # type: QLabel
        self.__m_overlapHint.setWordWrap(True)
        self.__m_layout.addWidget(self.__m_overlapHint)
        self.__m_shape = self._combo(SHAPE_NAMES, ctrl.setShape)  # type: QComboBox
        self.__m_zoomValue = QLabel()  # type: QLabel
        self._titleRow(self.tr('Magnification'), self.__m_zoomValue)
        self.__m_zoom = self._slider(10, 160, lambda v: ctrl.setZoom(v / 10.0))  # type: QSlider
        self.__m_sizeValue = QLabel()  # type: QLabel
        self._titleRow(self.tr('Lens size'), self.__m_sizeValue)
        self.__m_size = self._slider(8, 45, lambda v: ctrl.setLensSize(v * 20))  # type: QSlider
        self.__m_opacityValue = QLabel()  # type: QLabel
        self._titleRow(self.tr('Opacity'), self.__m_opacityValue)
        self.__m_opacity = self._slider(30, 100, lambda v: ctrl.setOpacity(v / 100.0))  # type: QSlider
        self.__m_fpsValue = QLabel()  # type: QLabel
        self._titleRow(self.tr('Frame rate'), self.__m_fpsValue)
        self.__m_fps = self._slider(15, 144, ctrl.setFps)  # type: QSlider
        self.__m_crosshair = QCheckBox(self.tr('Crosshair'))  # type: QCheckBox
        self.__m_crosshair.toggled.connect(ctrl.setCrosshair)
        self.__m_layout.addWidget(self.__m_crosshair)
        tip = AdvancedOverlayPanel._label(self.tr(
            'Run the game in borderless / windowed full-screen: exclusive full-screen hides every overlay. '
            'The lens never takes focus and lets all clicks through to the game.'), 'hint')  # type: QLabel
        tip.setWordWrap(True)
        self.__m_layout.addWidget(tip)

    @pyqtSlot()
    def _recorded(self, name, edit):
        """
        :param name: str | unicode | QString
        :param edit: QKeySequenceEdit
        :return:
        """
        seq = firstChord(edit.keySequence())  # type: str
        edit.setKeySequence(QKeySequence(seq))
        edit.clearFocus()  # Ends recording -> FocusOut resumes the hotkeys.
        self.__m_ctrl.setHotkey(name, seq)

    def _refreshCaptureStatus(self, ov):
        """
        Explain whether 'On target' really works (the lens must be invisible to screen capture).
        :param ov: ZoomOverlay
        :return:
        """
        status = ov.getCaptureStatus()  # type: str
        text, role = '', 'hint'  # type: str, str
        if ov.getPlacement() == ZoomOverlay.OnTarget:
            if status == 'testing':
                text = self.tr('Checking that the lens is hidden from screen capture\u2026')
            elif status == 'excluded':
                text, role = self.tr('\u2713 Lens hidden from screen capture: scope mode active.'), 'ok'
            elif status == 'windowCapture':
                text, role = self.tr('\u2713 Scope mode active: capturing the game window directly (Windows '
                                     'could not hide the lens from screen capture).'), 'ok'
            elif status == 'failed':
                corner = PLACEMENT_NAMES[int(ov.getEffectivePlacement())].lower()  # type: str
                text, role = self.tr('\u26a0 Scope mode is not possible here: {}. Without it the lens would '
                                     'magnify itself, so it is shown in the {} instead.').format(
                    ov.getCaptureDetail(), corner), 'warn'
            elif not ZoomOverlay.canExcludeFromCapture():
                text = self.tr('Only Windows 10 (2004+) / 11 can hide the lens from capture; on this system it '
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
        hk = ctrl.getHotkeys()
        widgets = [self.__m_hkEnabled, self.__m_target, self.__m_placement, self.__m_shape, self.__m_zoom,
                   self.__m_size, self.__m_opacity, self.__m_fps, self.__m_crosshair]  # type: list
        for w in widgets:
            w.blockSignals(True)
        self.__m_hkEnabled.setChecked(ctrl.isHotkeysEnabled())
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
        self.__m_zoomValue.setText('{:.1f}\u00d7'.format(ov.getZoom()))
        self.__m_sizeValue.setText('{} px'.format(ov.getLensSize().width()))
        self.__m_opacityValue.setText('{} %'.format(self.__m_opacity.value()))
        self.__m_fpsValue.setText('{} fps'.format(self.__m_fps.value()))
        tp = ov.getTargetPoint()
        self.__m_pointLabel.setText('({}, {})'.format(tp.x(), tp.y()) if ov.getTarget() == ZoomOverlay.Point else '')
        self._refreshCaptureStatus(ov)
        for name, (edit, status) in self.__m_edits.items():
            if not edit.hasFocus():
                edit.blockSignals(True)
                edit.setKeySequence(QKeySequence(ctrl.getHotkey(name)))
                edit.blockSignals(False)
            state = hk.getStatus(name)
            status.setText({True: '\u2713', False: '\u2717'}.get(state, '\u2013'))
            status.setProperty('role', {True: 'ok', False: 'bad'}.get(state, 'hint'))
            status.setToolTip({True: self.tr('Registered'), False: self.tr(
                'Could not register: invalid, or already used by another application')}.get(
                state, self.tr('Inactive')))
            status.style().unpolish(status)
            status.style().polish(status)
        backend = {'windows': 'Windows RegisterHotKey', 'pynput': 'pynput'}.get(hk.getBackendName(), 'none')
        self.__m_hkInfo.setText(hk.getError() or self.tr('Backend: {}').format(backend))
        self.__m_toggle.setText(self.tr('Hide lens') if ov.isVisible() else self.tr('Show lens now'))

    # ---------- Qt overrides ----------
    def eventFilter(self, obj, e):
        """
        Suspend the global hotkeys while a shortcut is being recorded, otherwise the OS swallows it.
        :param obj: QObject
        :param e: QEvent
        :return: bool
        """
        if isinstance(obj, QKeySequenceEdit) or isinstance(obj.parent(), QKeySequenceEdit):
            if e.type() == QEvent.FocusIn:
                self.__m_ctrl.getHotkeys().setEnabled(False)
            elif e.type() == QEvent.FocusOut:
                self.__m_ctrl.getHotkeys().setEnabled(self.__m_ctrl.isHotkeysEnabled())
        return super(AdvancedOverlayPanel, self).eventFilter(obj, e)
