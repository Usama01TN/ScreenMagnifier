# -*- coding: utf-8 -*-
"""
ControlPanel: live settings for the magnifier (zoom, upscaling method, sharpening, frame rate, overlays).
"""
from ManyQt.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QSlider, QComboBox, QFrame, \
    QCheckBox, QPushButton, QScrollArea
from ManyQt.QtCore import Qt, pyqtSlot
from math import log, exp
from os.path import dirname
from sys import path

if dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .upscaler import Upscaler
    from .screengrabber import ScreenGrabber
    from .magnifierview import MagnifierViewWidget
except:
    from upscaler import Upscaler
    from screengrabber import ScreenGrabber
    from magnifierview import MagnifierViewWidget

PANEL_QSS = """
QWidget#panelContent { background: transparent; }
QLabel[role="title"] { color: #9AA3B8; font-size: 10px; font-weight: bold; letter-spacing: 1px;
                       padding-top: 10px; }
QLabel[role="value"] { color: #E8EBF2; font-weight: bold; }
QLabel[role="hint"] { color: #7C8498; font-size: 10px; }
QPushButton[role="preset"] { padding: 4px 0; min-width: 34px; }
"""  # type: str


class ControlPanel(QScrollArea):
    """
    ControlPanel class: one row per option, bound to the view, the upscaler and the grabber.
    """
    ZOOM_STEPS = 1000  # type: int

    def __init__(self, *args, **kwargs):
        """
        :param view: MagnifierViewWidget
        :param upscaler: Upscaler
        :param grabber: ScreenGrabber
        :param args: any
        :param kwargs: any
        """
        view = kwargs.pop('view', None)  # type: MagnifierViewWidget
        upscaler = kwargs.pop('upscaler', None)  # type: Upscaler
        grabber = kwargs.pop('grabber', None)  # type: ScreenGrabber
        super(ControlPanel, self).__init__(*args, **kwargs)
        self.__m_view = view  # type: MagnifierViewWidget
        self.__m_upscaler = upscaler  # type: Upscaler
        self.__m_grabber = grabber  # type: ScreenGrabber
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(250)
        content = QWidget()  # type: QWidget
        content.setObjectName('panelContent')
        content.setStyleSheet(PANEL_QSS)
        self.__m_layout = QVBoxLayout(content)  # type: QVBoxLayout
        self.__m_layout.setContentsMargins(14, 6, 14, 14)
        self.__m_layout.setSpacing(6)
        self._buildZoom()
        self._buildUpscaling()
        self._buildCapture()
        self._buildOverlays()
        self.__m_layout.addStretch(1)
        self.setWidget(content)
        view.zoomChanged.connect(self._syncZoom)
        self._syncZoom(view.getZoom())

    # ---------- Helpers ----------
    @staticmethod
    def _label(text, role):
        """
        :param text: str | unicode | QString
        :param role: (str | unicode | QString)title | value | hint
        :return: QLabel
        """
        lbl = QLabel(text)  # type: QLabel
        lbl.setProperty('role', role)
        return lbl

    def _row(self, title, valueLabel):
        """
        :param title: str | unicode | QString
        :param valueLabel: QLabel
        :return:
        """
        row = QHBoxLayout()  # type: QHBoxLayout
        row.addWidget(ControlPanel._label(title.upper(), 'title'))
        row.addStretch(1)
        valueLabel.setProperty('role', 'value')
        valueLabel.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        row.addWidget(valueLabel)
        self.__m_layout.addLayout(row)

    def _zoomToSlider(self, zoom):
        """
        Logarithmic mapping so that 1x..2x gets as much travel as 16x..32x.
        :param zoom: float | int
        :return: int
        """
        lo, hi = log(self.__m_view.getMinZoom()), log(self.__m_view.getMaxZoom())  # type: float, float
        return int(round((log(max(zoom, 1e-3)) - lo) / (hi - lo) * ControlPanel.ZOOM_STEPS))

    def _sliderToZoom(self, value):
        """
        :param value: int
        :return: float | int
        """
        lo, hi = log(self.__m_view.getMinZoom()), log(self.__m_view.getMaxZoom())  # type: float, float
        return exp(lo + (hi - lo) * value / float(ControlPanel.ZOOM_STEPS))

    def _buildZoom(self):
        """
        :return:
        """
        self.__m_zoomValue = QLabel()  # type: QLabel
        self._row(self.tr('Magnification'), self.__m_zoomValue)
        self.__m_zoomSlider = QSlider(Qt.Horizontal)  # type: QSlider
        self.__m_zoomSlider.setRange(0, ControlPanel.ZOOM_STEPS)
        self.__m_zoomSlider.valueChanged.connect(lambda v: self.__m_view.setZoom(self._sliderToZoom(v)))
        self.__m_layout.addWidget(self.__m_zoomSlider)
        presets = QGridLayout()  # type: QGridLayout
        presets.setSpacing(4)
        for i, z in enumerate((1, 2, 4, 8, 16)):
            btn = QPushButton('{}\u00d7'.format(z))  # type: QPushButton
            btn.setProperty('role', 'preset')
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(lambda checked=False, zz=z: self.__m_view.setZoom(zz))
            presets.addWidget(btn, 0, i)
        fit = QPushButton(self.tr('Fit region'))  # type: QPushButton
        fit.setFocusPolicy(Qt.NoFocus)
        fit.clicked.connect(self.__m_view.fitToView)
        presets.addWidget(fit, 1, 0, 1, 5)
        self.__m_layout.addLayout(presets)

    def _buildUpscaling(self):
        """
        :return:
        """
        self.__m_methodTime = QLabel()  # type: QLabel
        self._row(self.tr('Upscaling'), self.__m_methodTime)
        self.__m_method = QComboBox()  # type: QComboBox
        for method, name in self.__m_upscaler.availableMethods():
            self.__m_method.addItem(name, int(method))
        self.__m_method.setCurrentIndex(max(0, self.__m_method.findData(int(self.__m_upscaler.getMethod()))))
        self.__m_method.currentIndexChanged.connect(
            lambda i: self.__m_upscaler.setMethod(int(self.__m_method.itemData(i))))
        self.__m_layout.addWidget(self.__m_method)
        missing = []  # type: list[str]
        if not Upscaler.hasOpenCV():
            missing.append(self.tr('Install numpy + opencv-python for Bicubic, Lanczos and sharpening.'))
        elif not Upscaler.hasSuperRes():
            missing.append(self.tr('Install opencv-contrib-python for AI super-resolution.'))
        for text in missing:
            hint = ControlPanel._label(text, 'hint')  # type: QLabel
            hint.setWordWrap(True)
            self.__m_layout.addWidget(hint)
        self.__m_sharpValue = QLabel()  # type: QLabel
        self._row(self.tr('Sharpen'), self.__m_sharpValue)
        sharp = QSlider(Qt.Horizontal)  # type: QSlider
        sharp.setRange(0, 200)
        sharp.setEnabled(Upscaler.hasOpenCV())
        sharp.valueChanged.connect(self._setSharpness)
        sharp.setValue(int(round(self.__m_upscaler.getSharpness() * 100)))
        self._setSharpness(sharp.value())
        self.__m_layout.addWidget(sharp)

    def _buildCapture(self):
        """
        :return:
        """
        self.__m_fpsValue = QLabel()  # type: QLabel
        self._row(self.tr('Frame rate'), self.__m_fpsValue)
        fps = QSlider(Qt.Horizontal)  # type: QSlider
        fps.setRange(1, 60)
        fps.valueChanged.connect(self._setFps)
        fps.setValue(self.__m_grabber.getFps())
        self._setFps(fps.value())
        self.__m_layout.addWidget(fps)

    def _buildOverlays(self):
        """
        :return:
        """
        self.__m_layout.addWidget(ControlPanel._label(self.tr('OVERLAYS'), 'title'))
        v = self.__m_view  # type: MagnifierViewWidget
        for text, getter, setter in ((self.tr('Pixel grid (zoom \u2265 10\u00d7)'), v.isShowGrid, v.setShowGrid),
                                     (self.tr('Crosshair'), v.isShowCrosshair, v.setShowCrosshair),
                                     (self.tr('Invert colors'), v.isInvertColors, v.setInvertColors)):
            box = QCheckBox(text)  # type: QCheckBox
            box.setChecked(getter())
            box.toggled.connect(setter)
            self.__m_layout.addWidget(box)

    # ---------- Public API ----------
    @pyqtSlot(float)
    @pyqtSlot(int)
    def _syncZoom(self, zoom):
        """
        :param zoom: float | int
        :return:
        """
        self.__m_zoomValue.setText('{:.2f}\u00d7'.format(zoom))
        self.__m_zoomSlider.blockSignals(True)
        self.__m_zoomSlider.setValue(self._zoomToSlider(zoom))
        self.__m_zoomSlider.blockSignals(False)

    @pyqtSlot(int)
    def _setSharpness(self, value):
        """
        :param value: (int) 0 .. 200 %
        :return:
        """
        self.__m_sharpValue.setText('{} %'.format(int(value)))
        self.__m_upscaler.setSharpness(value / 100.0)

    @pyqtSlot(int)
    def _setFps(self, value):
        """
        :param value: int
        :return:
        """
        self.__m_fpsValue.setText('{} fps'.format(int(value)))
        self.__m_grabber.setFps(value)

    @pyqtSlot(float)
    @pyqtSlot(int)
    def showProcessTime(self, ms):
        """
        :param ms: float | int
        :return:
        """
        self.__m_methodTime.setText('{:.1f} ms'.format(ms))
