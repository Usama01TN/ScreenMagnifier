# -*- coding: utf-8 -*-
"""
ColorPickerPanel: the Colors tab - color code of the pixel under the mouse in 13 formats, one-click copy to the
clipboard, averaged sampling, copy history, and the WCAG contrast checker. Every setting and the history are
saved with QSettings.
Ways to copy (wired by the MainWindow): C key, right-click menu of the magnifier (every format), optional left
click in the magnifier, the zoomer color code and screen color picker hotkeys, or the Copy buttons of this tab.
"""
from ManyQt.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QCheckBox, QFrame, \
    QMenu, QPushButton, QScrollArea
from ManyQt.QtCore import Qt, QSettings, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtGui import QColor, QPixmap, QFont, QGuiApplication
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .colordetector import COLOR_FORMATS, formatColor, nearestColorName, contrastRatio, wcagRating
    from .colorswatches import ColorSwatchesWidget
except:
    from colordetector import COLOR_FORMATS, formatColor, nearestColorName, contrastRatio, wcagRating
    from colorswatches import ColorSwatchesWidget

PANEL_QSS = """
QWidget#colorContent { background: transparent; }
QLabel[role="title"] { color: #9AA3B8; font-size: 10px; font-weight: bold; letter-spacing: 1px; padding-top: 10px; }
QLabel[role="hint"] { color: #7C8498; font-size: 10px; }
QLabel[role="name"] { color: #9AA3B8; }
QLabel[role="mono"] { color: #E8EBF2; font-family: monospace; }
QLabel[role="big"] { color: #E8EBF2; font-size: 16px; font-weight: bold; font-family: monospace; }
QPushButton[role="small"] { padding: 2px 8px; }
"""  # type: str
PICK_SOURCES = [('zoomed', 'Zoomed image (what you see)'), ('original', 'Original screen pixel')]  # type: list
SAMPLE_SIZES = [(1, '1 pixel'), (3, '3 x 3 average'), (5, '5 x 5 average'), (9, '9 x 9 average')]  # type: list


class ColorPickerPanel(QScrollArea):
    """
    ColorPickerPanel class.
    """
    colorCopied = pyqtSignal(QColor, 'QString')  # type: pyqtSignal  # color, copied text
    optionsChanged = pyqtSignal()  # type: pyqtSignal  # format / pick source / sample size changed
    notify = pyqtSignal('QString')  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param settings: (QSettings | None) None = ScreenMagnifier / ColorPicker.
        :param colorCopied: callable | None
        :param args: any
        :param kwargs: any
        """
        settings = kwargs.pop('settings', None)  # type: QSettings | None
        colorCopied = kwargs.pop('colorCopied', None)  # type: callable | None
        super(ColorPickerPanel, self).__init__(*args, **kwargs)
        if callable(colorCopied):
            self.colorCopied.connect(colorCopied)
        self.__m_settings = settings if settings is not None else QSettings('ScreenMagnifier', 'ColorPicker')
        self.__m_color = QColor()  # type: QColor
        self.__m_liveSource = ''  # type: str  # 'magnifier', 'zoomer' or 'picker'
        self.__m_liveZone = ''  # type: str
        self.__m_reference = None  # type: QColor | None
        self.__m_values = {}  # type: dict  # format key -> value QLabel
        self.__m_loading = False  # type: bool
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(260)
        content = QWidget()  # type: QWidget
        content.setObjectName('colorContent')
        content.setStyleSheet(PANEL_QSS)
        self.__m_layout = QVBoxLayout(content)  # type: QVBoxLayout
        self.__m_layout.setContentsMargins(14, 6, 14, 14)
        self.__m_layout.setSpacing(6)
        self._build()
        self.__m_layout.addStretch(1)
        self.setWidget(content)
        self._load()
        self.setCurrentColor(QColor())

    # ---------- Building ----------
    @staticmethod
    def _label(text, role):
        """
        :param text: str | unicode | QString
        :param role: str | unicode | QString
        :return: QLabel
        """
        lbl = QLabel(text)  # type: QLabel
        lbl.setProperty('role', role)
        lbl.setWordWrap(role == 'hint')
        return lbl

    @staticmethod
    def _button(text, slot, tip=''):
        """
        :param text: str | unicode | QString
        :param slot: callable
        :param tip: str | unicode | QString
        :return: QPushButton
        """
        b = QPushButton(text)  # type: QPushButton
        b.setProperty('role', 'small')
        b.setFocusPolicy(Qt.NoFocus)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    def _build(self):
        """
        :return:
        """
        lay = self.__m_layout  # type: QVBoxLayout
        lay.addWidget(ColorPickerPanel._label(self.tr(u'LIVE COLOR'), 'title'))
        self.__m_sourceLabel = ColorPickerPanel._label('', 'hint')  # type: QLabel  # where the color comes from
        lay.addWidget(self.__m_sourceLabel)
        head = QHBoxLayout()  # type: QHBoxLayout
        self.__m_swatch = QLabel()  # type: QLabel
        self.__m_swatch.setFixedSize(52, 52)
        head.addWidget(self.__m_swatch)
        names = QVBoxLayout()  # type: QVBoxLayout
        self.__m_hex = ColorPickerPanel._label('', 'big')  # type: QLabel
        self.__m_hex.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.__m_name = ColorPickerPanel._label('', 'name')  # type: QLabel
        names.addWidget(self.__m_hex)
        names.addWidget(self.__m_name)
        self.__m_zoneLabel = ColorPickerPanel._label('', 'name')  # type: QLabel
        names.addWidget(self.__m_zoneLabel)
        head.addLayout(names, 1)
        head.addWidget(
            self._button(self.tr(u'Copy'), lambda: self.copyColor(), self.tr(u'Copy in the default format (C)')))
        lay.addLayout(head)
        grid = QGridLayout()  # type: QGridLayout
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        for row, (key, label) in enumerate(COLOR_FORMATS):
            value = ColorPickerPanel._label('-', 'mono')  # type: QLabel
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.__m_values[key] = value
            grid.addWidget(ColorPickerPanel._label(self.tr(label), 'name'), row, 0)
            grid.addWidget(value, row, 1)
            grid.addWidget(self._button(self.tr(u'Copy'), lambda checked=False, k=key: self.copyColor(fmt=k),
                                        self.tr(u'Copy as {}').format(self.tr(label))), row, 2)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addWidget(self._button(self.tr(u'Copy all formats'), self.copyAllFormats,
                                   self.tr(u'Copy every format, one per line')))
        lay.addWidget(ColorPickerPanel._label(self.tr(u'OPTIONS'), 'title'))
        lay.addWidget(QLabel(self.tr(u'Default format (C key, click, global hotkey)')))
        self.__m_format = QComboBox()  # type: QComboBox
        for key, label in COLOR_FORMATS:
            self.__m_format.addItem(self.tr(label), key)
        self.__m_format.currentIndexChanged.connect(lambda *a: (self._save(), self.setCurrentColor(self.__m_color)))
        lay.addWidget(self.__m_format)
        lay.addWidget(QLabel(self.tr(u'Pick from')))
        self.__m_source = QComboBox()  # type: QComboBox
        for key, label in PICK_SOURCES:
            self.__m_source.addItem(self.tr(label), key)
        self.__m_source.setToolTip(self.tr(u'Zoomed: the color as displayed after upscaling / sharpening. Original: '
                                           'the untouched screen pixel.'))
        self.__m_source.currentIndexChanged.connect(lambda *a: self._save())
        lay.addWidget(self.__m_source)
        lay.addWidget(QLabel(self.tr(u'Sample')))
        self.__m_sample = QComboBox()  # type: QComboBox
        for size, label in SAMPLE_SIZES:
            self.__m_sample.addItem(self.tr(label), size)
        self.__m_sample.setToolTip(self.tr(u'Average a small square: steadier on anti-aliased text and textures'))
        self.__m_sample.currentIndexChanged.connect(lambda *a: self._save())
        lay.addWidget(self.__m_sample)
        self.__m_copyOnClick = QCheckBox(self.tr(u'Copy on left click in the magnifier'))  # type: QCheckBox
        self.__m_copyOnClick.toggled.connect(lambda *a: self._save())
        lay.addWidget(self.__m_copyOnClick)
        lay.addWidget(ColorPickerPanel._label(self.tr(u'CONTRAST (WCAG)'), 'title'))
        lay.addWidget(self._button(self.tr(u'Set as reference'), self._setReference,
                                   self.tr(u'Then hover another color to see the contrast ratio')))
        self.__m_contrast = ColorPickerPanel._label(self.tr(u'Set a reference color first.'), 'hint')  # type: QLabel
        lay.addWidget(self.__m_contrast)
        lay.addWidget(ColorPickerPanel._label(self.tr(u'HISTORY'), 'title'))
        self.__m_history = ColorSwatchesWidget(maxColors=32, swatchSize=24, placeholderText=self.tr(
            'Copied colors appear here'), colorClicked=lambda c: self.copyColor(c))  # type: ColorSwatchesWidget
        self.__m_history.colorsChanged.connect(self._save)
        lay.addWidget(self.__m_history)
        row = QHBoxLayout()  # type: QHBoxLayout
        row.addWidget(self._button(self.tr(u'Copy history'), self.copyHistory,
                                   self.tr(u'Copy every color of the history, one per line')))
        row.addWidget(self._button(self.tr(u'Clear'), self.__m_history.clear))
        lay.addLayout(row)
        lay.addWidget(ColorPickerPanel._label(self.tr(
            u'These options apply to every way of copying: the magnifier eyedropper and C key, its right-click menu, '
            u'the zoomer color code and the screen color picker (shortcuts: Shortcuts tab). Click a history swatch '
            u'to copy it again, right-click to remove it.'), 'hint'))

    # ---------- Settings ----------
    def _load(self):
        """
        :return:
        """
        self.__m_loading = True  # type: bool
        s = self.__m_settings  # type: QSettings
        self.__m_format.setCurrentIndex(max(0, self.__m_format.findData(u'{}'.format(s.value('format', 'hex')))))
        self.__m_sample.setCurrentIndex(max(0, self.__m_sample.findData(int(s.value('sample', 1)))))
        self.__m_source.setCurrentIndex(max(0, self.__m_source.findData(u'{}'.format(s.value('pickSource', 'zoomed')))))
        self.__m_copyOnClick.setChecked(u'{}'.format(s.value('copyOnClick', False)).lower() in ('1', 'true', 'yes'))
        history = s.value('history', '') or ''
        if isinstance(history, (list, tuple)):
            history = ','.join(u'{}'.format(h) for h in history)
        self.__m_history.setColors([h for h in u'{}'.format(history).split(',') if QColor(h).isValid()])
        self.__m_loading = False  # type: bool

    @pyqtSlot()
    def _save(self):
        """
        :return:
        """
        if self.__m_loading:
            return
        s = self.__m_settings  # type: QSettings
        s.setValue('format', self.__m_format.currentData())
        s.setValue('sample', self.__m_sample.currentData())
        s.setValue('pickSource', self.__m_source.currentData())
        self.optionsChanged.emit()
        s.setValue('copyOnClick', self.__m_copyOnClick.isChecked())
        s.setValue('history', ','.join(u'{}'.format(c.name()) for c in self.__m_history.getColors()))

    # ---------- Helpers ----------
    def _setReference(self):
        """
        :return:
        """
        if self.__m_color.isValid():
            self.__m_reference = QColor(self.__m_color)  # type: QColor
            self._updateContrast()

    def _updateContrast(self):
        """
        :return:
        """
        ref, cur = self.__m_reference, self.__m_color
        if ref is None or not cur.isValid():
            return
        ratio = contrastRatio(ref, cur)  # type: float
        self.__m_contrast.setText(self.tr(u'{} on {}: {:.2f} : 1  ({})').format(
            formatColor(cur), formatColor(ref), ratio, wcagRating(ratio)))

    # ---------- Public API ----------
    def formatCode(self, color):
        """
        THE text of a color code everywhere (Colors tab, zoomer, eyedropper bubble): the default copy format, so
        the code shown is always the code copied.
        :param color: QColor
        :return: str | unicode | QString
        """
        return formatColor(color, self.getDefaultFormat())

    def colorName(self, color):
        """
        THE color name everywhere (Colors tab and zoomer).
        :param color: QColor
        :return: (str | unicode | QString) 'name' (exact) or 'close to name'.
        """
        name, de = nearestColorName(color)
        return name if de < 1.0 else self.tr(u'close to {}').format(name)

    def setLiveColor(self, color, source='', zone=''):
        """
        Show the live color: the one the user points at, wherever it comes from.
        :param color: QColor
        :param source: (str | unicode | QString) 'magnifier' (mouse), 'zoomer' (crosshair) or 'picker' (screen color picker).
        :param zone: (str | unicode | QString) Color zone the color is in ('' = none).
        :return:
        """
        self.__m_color = QColor(color) if color is not None else QColor()  # type: QColor
        self.__m_liveSource, self.__m_liveZone = u'{}'.format(source), u'{}'.format(zone)  # type: str, str
        pm = QPixmap(52, 52)  # type: QPixmap
        pm.fill(self.__m_color if self.__m_color.isValid() else QColor('#22252E'))
        self.__m_swatch.setPixmap(pm)
        valid = self.__m_color.isValid()  # type: bool
        self.__m_hex.setText(self.formatCode(self.__m_color) if valid else '-')
        self.__m_name.setText(self.colorName(self.__m_color) if valid else self.tr(
            'Point at a color: magnifier, zoomer or screen color picker'))
        self.__m_zoneLabel.setText(self.tr(u'zone: {}').format(zone) if valid and zone else '')
        exact = u'{}'.format(source) == 'picker' or self.getPickSource() == 'original'  # type: bool  # picker: pixel-exact
        where = {'magnifier': self.tr(u'from the magnifier (mouse)'), 'zoomer': self.tr(u'from the zoomer (crosshair)'),
                 'picker': self.tr(u'from the screen color picker')}.get(u'{}'.format(source), '')  # type: str
        self.__m_sourceLabel.setText(where and where + (self.tr(u'  \u00b7  exact screen pixel') if exact else
                                                        self.tr(u'  \u00b7  zoomed image (Pick from, below)')))
        for key, value in self.__m_values.items():
            value.setText(formatColor(self.__m_color, key) if valid else '-')
        self._updateContrast()

    @pyqtSlot(QColor)
    @pyqtSlot(Qt.GlobalColor)
    @pyqtSlot(int)
    @pyqtSlot(str)
    @pyqtSlot('QString')
    def setCurrentColor(self, color):
        """
        :param color: QColor | Qt.GlobalColor | int | str | QString (keeps the current source / zone).
        :return:
        """
        self.setLiveColor(color if isinstance(color, QColor) else QColor(color), self.__m_liveSource, self.__m_liveZone)

    def getLiveSource(self):
        """
        :return: (str | unicode | QString) 'magnifier', 'zoomer', 'picker' or ''.
        """
        return self.__m_liveSource

    def getLiveZone(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_liveZone

    def getCodeText(self):
        """
        :return: (str | unicode | QString) The code shown (and copied) for the live color.
        """
        return self.__m_hex.text()

    def getCurrentColor(self):
        """
        :return: QColor
        """
        return QColor(self.__m_color)

    def copyColor(self, color=None, fmt=None):
        """
        Copy a color code to the clipboard, add it to the history and announce it.
        :param color: (QColor | None) None = the current color.
        :param fmt: (str | None) COLOR_FORMATS key; None = the default format.
        :return: (str | unicode | QString) Copied text ('' when there is no color).
        """
        c = QColor(color) if color is not None else QColor(self.__m_color)  # type: QColor
        if not c.isValid():
            self.notify.emit(self.tr(u'Hover the magnifier to choose a color first.'))
            return ''
        text = formatColor(c, fmt or self.getDefaultFormat())  # type: str
        QGuiApplication.clipboard().setText(text)
        self.__m_history.addColor(c)
        self.notify.emit(self.tr(u'Copied {}').format(text))
        self.colorCopied.emit(c, text)
        return text

    @pyqtSlot()
    def copyAllFormats(self):
        """
        :return:
        """
        if self.__m_color.isValid():
            QGuiApplication.clipboard().setText('\n'.join(formatColor(self.__m_color, k) for k, _ in COLOR_FORMATS))
            self.__m_history.addColor(self.__m_color)
            self.notify.emit(self.tr(u'Copied every format of {}').format(formatColor(self.__m_color)))

    @pyqtSlot()
    def copyHistory(self):
        """
        :return:
        """
        colors = self.__m_history.getColors()  # type: list
        if colors:
            QGuiApplication.clipboard().setText('\n'.join(formatColor(c, self.getDefaultFormat()) for c in colors))
            self.notify.emit(self.tr(u'Copied {} colors').format(len(colors)))

    def buildCopyMenu(self, color, parent=None):
        """
        Context menu offering the color in every format (default format first, in bold).
        :param color: QColor
        :param parent: QWidget | None
        :return: QMenu
        """
        menu = QMenu(parent)  # type: QMenu
        title = menu.addAction(self.tr(u'{}  {}').format(formatColor(color), nearestColorName(color)[0]))
        title.setEnabled(False)
        menu.addSeparator()
        default = self.getDefaultFormat()  # type: str
        keys = [default] + [k for k, _ in COLOR_FORMATS if k != default]  # type: list
        labels = dict(COLOR_FORMATS)  # type: dict
        for key in keys:
            act = menu.addAction(self.tr(u'Copy {}    ({})').format(formatColor(color, key), self.tr(labels[key])))
            act.triggered.connect(lambda checked=False, k=key: self.copyColor(color, k))
            if key == default:
                font = QFont(act.font())  # type: QFont
                font.setBold(True)
                act.setFont(font)
        menu.addSeparator()
        menu.addAction(self.tr(u'Copy all formats'), lambda: (self.setCurrentColor(color), self.copyAllFormats()))
        menu.addAction(self.tr(u'Set as contrast reference'),
                       lambda: (self.setCurrentColor(color), self._setReference()))
        return menu

    def getDefaultFormat(self):
        """
        :return: (str | unicode | QString) COLOR_FORMATS key.
        """
        return u'{}'.format(self.__m_format.currentData() or 'hex')

    def getPickSource(self):
        """
        :return: (str | unicode | QString) 'zoomed' (color as displayed) or 'original' (screen pixel).
        """
        return u'{}'.format(self.__m_source.currentData() or 'zoomed')

    def getSampleSize(self):
        """
        :return: (int) 1, 3, 5 or 9.
        """
        return int(self.__m_sample.currentData() or 1)

    def isCopyOnClick(self):
        """
        :return: bool
        """
        return self.__m_copyOnClick.isChecked()

    def getHistory(self):
        """
        :return: (list[QColor]) Newest first.
        """
        return self.__m_history.getColors()

    # ---------- Properties ----------
    currentColor = pyqtProperty(QColor, fget=getCurrentColor, fset=setCurrentColor)  # type: pyqtProperty
