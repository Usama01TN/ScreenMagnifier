# -*- coding: utf-8 -*-
"""
DetectionPanel: the Detection tab - color detection, palette and the optional AI face detection (color codes,
copying and contrast are in the Colors tab). Bound to an AnalysisController; every setting is saved with QSettings.
"""
from ManyQt.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QSlider, QComboBox, QFrame, \
    QCheckBox, QPushButton, QScrollArea, QListWidget, QListWidgetItem, QColorDialog
from ManyQt.QtCore import Qt, QPoint, QRectF, QSettings, QSize, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtGui import QColor, QPainter, QPixmap, QIcon
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .facepointer import FacePointer, FOLLOW_POINTER, FOLLOW_ZOOMER, CHOOSE_LARGEST, CHOOSE_NEAREST, \
        MOTION_POINTER, MOTION_VIEW, MOTION_AUTO, HOLD_ALWAYS, HOLD_RIGHT_BUTTON
    from .colordetector import ColorDetector, nearestColorName
    from .analysiscontroller import AnalysisController
    from .facedetector import FaceDetector
except:
    from facepointer import FacePointer, FOLLOW_POINTER, FOLLOW_ZOOMER, CHOOSE_LARGEST, CHOOSE_NEAREST, \
        MOTION_POINTER, MOTION_VIEW, MOTION_AUTO, HOLD_ALWAYS, HOLD_RIGHT_BUTTON
    from colordetector import ColorDetector, nearestColorName
    from analysiscontroller import AnalysisController
    from facedetector import FaceDetector

PANEL_QSS = """
QWidget#detectionContent { background: transparent; }
QLabel[role="title"] { color: #9AA3B8; font-size: 10px; font-weight: bold; letter-spacing: 1px; padding-top: 10px; }
QLabel[role="value"] { color: #E8EBF2; font-weight: bold; }
QLabel[role="hint"] { color: #7C8498; font-size: 10px; }
QLabel[role="mono"] { color: #E8EBF2; font-family: monospace; }
QListWidget { background: #22252E; color: #E8EBF2; border: 1px solid #3A3F50; border-radius: 6px; }
QPushButton[role="small"] { padding: 3px 6px; }
"""  # type: str
FACE_MODES = [('box', 'Boxes'), ('landmarks', 'Boxes + landmarks'), ('blur', 'Privacy blur')]  # type: list
FACE_BACKENDS = [('auto', 'Auto (YuNet if installed)'), ('yunet', 'YuNet (DNN, accurate)'),
                 ('haar', 'Haar cascade (no download)')]  # type: list
MATCH_MODES = [(0, 'Similar shades (lighting, shadows, anti-aliasing)'), (1, 'Exact color')]  # type: list
ENGINE_VERSION = 2  # type: int  # 2: tolerance = hue degrees in Similar mode (was delta E): saved values reset.
MASK_MODES = [('isolate', 'Isolate matches (dim the rest)'), ('tint', 'Tint matches')]  # type: list


def swatch(color, size=14):
    """
    :param color: QColor | str
    :param size: int
    :return: QIcon
    """
    pm = QPixmap(size, size)  # type: QPixmap
    pm.fill(Qt.transparent)
    p = QPainter(pm)  # type: QPainter
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QColor(255, 255, 255, 120))
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), 3, 3)
    p.end()
    return QIcon(pm)


POINTER_FOLLOW = [(FOLLOW_POINTER, 'The mouse pointer'),
                  (FOLLOW_ZOOMER, 'Only the zoomer (the pointer stays still)')]  # type: list[tuple[int, str]]
POINTER_CHOOSE = [(CHOOSE_LARGEST, 'The largest face'), (CHOOSE_NEAREST, 'The face nearest the pointer')]  # type: list
POINTER_MOTION = [(MOTION_AUTO, 'Automatic (turn the view when the game captures the mouse)'),
                  (MOTION_POINTER, 'Move the pointer to the face (films, games with a pointer)'),
                  (MOTION_VIEW, 'Turn the view to the face (games that capture the mouse)')]  # type: list
POINTER_HOLD = [(HOLD_ALWAYS, 'Always'), (HOLD_RIGHT_BUTTON, 'While the right mouse button is held')]  # type: list


class PaletteBar(QWidget):
    """
    PaletteBar class: horizontal bar of the dominant colors, each segment as wide as its share.
    """

    def __init__(self, *args, **kwargs):
        """
        :param args: any
        :param kwargs: any
        """
        super(PaletteBar, self).__init__(*args, **kwargs)
        self.__m_palette = []  # type: list
        self.setMinimumHeight(26)

    @pyqtSlot(list)
    def setColors(self, colors):
        """
        :param colors: (list[dict]) [{'color': '#RRGGBB', 'fraction': f, 'name': str}]
        :return:
        """
        self.__m_palette = list(colors or [])  # type: list
        self.setToolTip('\n'.join('{}  {}  {:.1f} %'.format(p['color'], p['name'], 100 * p['fraction'])
                                  for p in self.__m_palette))
        self.update()

    def getColors(self):
        """
        :return: list[dict]
        """
        return list(self.__m_palette)

    def sizeHint(self):
        """
        :return: QSize
        """
        return QSize(220, 26)

    def paintEvent(self, event):
        """
        :param event: QPaintEvent
        :return:
        """
        p = QPainter(self)  # type: QPainter
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)  # type: QRectF
        p.setPen(QColor('#3A3F50'))
        p.setBrush(QColor('#22252E'))
        p.drawRoundedRect(r, 5, 5)
        total = sum(c['fraction'] for c in self.__m_palette) or 1.0  # type: float
        x = r.left() + 1  # type: float
        p.setPen(Qt.NoPen)
        for c in self.__m_palette:
            w = (r.width() - 2) * c['fraction'] / total  # type: float
            p.setBrush(QColor(c['color']))
            p.drawRect(QRectF(x, r.top() + 1, w, r.height() - 2))
            x += w
        p.end()

    # ---------- Properties ----------
    colors = pyqtProperty(list, fget=getColors, fset=setColors)  # type: pyqtProperty


class DetectionPanel(QScrollArea):
    """
    DetectionPanel class.
    """
    notify = pyqtSignal('QString')  # type: pyqtSignal  # Message for the status bar / tray.

    def __init__(self, *args, **kwargs):
        """
        :param controller: AnalysisController
        :param settings: (QSettings | None) None = ScreenMagnifier / Detection.
        :param features: (FeatureSettings | None) Where the zones are shown (magnifier / zoomer).
        :param args: any
        :param kwargs: any
        """
        controller = kwargs.pop('controller', None)  # type: AnalysisController
        settings = kwargs.pop('settings', None)  # type: QSettings | None
        features = kwargs.pop('features', None)  # type: FeatureSettings | None
        facePointer = kwargs.pop('facePointer', None)  # type: FacePointer | None
        hotkeyText = kwargs.pop('hotkeyText', None)  # type: callable | None
        super(DetectionPanel, self).__init__(*args, **kwargs)
        self.__m_pointer = facePointer  # type: FacePointer | None
        self.__m_hotkeyText = hotkeyText if callable(hotkeyText) else (lambda name: '')  # type: callable
        self.__m_pointerSettings = QSettings('ScreenMagnifier', 'FacePointer')  # type: QSettings
        self.__m_features = features  # type: FeatureSettings | None
        self.__m_ctrl = controller  # type: AnalysisController
        self.__m_colors = controller.getColorDetector()  # type: ColorDetector
        self.__m_faces = controller.getFaceDetector()  # type: FaceDetector
        self.__m_settings = settings if settings is not None else QSettings('ScreenMagnifier', 'Detection')
        self.__m_notifyOn = True  # type: bool
        self.__m_loading = False  # type: bool  # No saving while the saved values are being restored.
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(260)
        content = QWidget()  # type: QWidget
        content.setObjectName('detectionContent')
        content.setStyleSheet(PANEL_QSS)
        self.__m_layout = QVBoxLayout(content)  # type: QVBoxLayout
        self.__m_layout.setContentsMargins(14, 6, 14, 14)
        self.__m_layout.setSpacing(6)
        self._buildColors()
        self._buildFaces()
        if facePointer is not None:
            self._buildFacePointer()
        self._buildAnalysis()
        self.__m_layout.addStretch(1)
        self.setWidget(content)
        self._load()
        self._syncWhere()
        if features is not None:
            features.changed.connect(self._syncWhere)
        controller.resultsReady.connect(self._onResults)
        controller.colorAppeared.connect(self._onAppeared)
        self.__m_colors.targetsChanged.connect(self._refreshTargets)
        self.__m_faces.downloadProgress.connect(lambda v: self.__m_modelState.setText(
            self.tr(u'Downloading YuNet model... {} %').format(v)))
        self.__m_faces.downloadFinished.connect(self._onDownloaded)
        self.__m_faces.errorOccurred.connect(self.notify.emit)
        self._refreshTargets()
        self._refreshModelState()

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

    def _title(self, text, value=None):
        """
        :param text: str | unicode | QString
        :param value: QLabel | None
        :return:
        """
        row = QHBoxLayout()  # type: QHBoxLayout
        row.addWidget(DetectionPanel._label(text.upper(), 'title'))
        row.addStretch(1)
        if value is not None:
            value.setProperty('role', 'value')
            row.addWidget(value)
        self.__m_layout.addLayout(row)

    def _check(self, text, slot):
        """
        :param text: str | unicode | QString
        :param slot: callable
        :return: QCheckBox
        """
        box = QCheckBox(text)  # type: QCheckBox
        box.toggled.connect(slot)
        self.__m_layout.addWidget(box)
        return box

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
        :param items: (list[tuple[str, str]]) (data, text)
        :param slot: callable f(data)
        :return: QComboBox
        """
        c = QComboBox()  # type: QComboBox
        for data, text in items:
            c.addItem(self.tr(text), data)
        c.currentIndexChanged.connect(lambda i, cb=c: slot(cb.itemData(i)))
        self.__m_layout.addWidget(c)
        return c

    def _buildColors(self):
        """
        :return:
        """
        ctrl = self.__m_ctrl  # type: AnalysisController
        self._title(self.tr(u'Color detection'))
        if not ColorDetector.isAvailable():
            self.__m_layout.addWidget(DetectionPanel._label(self.tr(u'Install numpy to enable color detection.'),
                                                            'hint'))
        self.__m_colorOn = self._check(self.tr(u'Detect target colors'), self._setColorEnabled)  # type: QCheckBox
        self.__m_colorOn.setEnabled(ColorDetector.isAvailable())
        self.__m_targets = QListWidget()  # type: QListWidget
        self.__m_targets.setMaximumHeight(110)
        self.__m_layout.addWidget(self.__m_targets)
        row = QGridLayout()  # type: QGridLayout  # 2 x 2: fits a narrow panel in every language
        buttons = []  # type: list
        for text, tip, slot in ((self.tr(u'Add...'), self.tr(u'Choose a color'), self._addDialog),
                                (self.tr(u'Remove'), self.tr(u'Remove the selected color'), self._removeSelected),
                                (self.tr(u'Clear'), self.tr(u'Remove every target color'),
                                 self.__m_colors.clearTargetColors)):
            b = QPushButton(text)  # type: QPushButton
            b.setProperty('role', 'small')
            b.setToolTip(tip)
            b.clicked.connect(slot)
            buttons.append(b)
        self.__m_pick = QPushButton(self.tr(u'Pick'))  # type: QPushButton
        self.__m_pick.setProperty('role', 'small')
        self.__m_pick.setCheckable(True)
        self.__m_pick.setToolTip(self.tr(u'Click a pixel in the magnifier to add its color'))
        buttons.insert(1, self.__m_pick)
        for i, b in enumerate(buttons):
            row.addWidget(b, i // 2, i % 2)
        self.__m_layout.addLayout(row)
        self._title(self.tr(u'Match'))
        self.__m_match = self._combo(MATCH_MODES, lambda m: (self.__m_colors.setMatchMode(m), self._save()))
        self.__m_tolValue = QLabel()  # type: QLabel
        self._title(self.tr(u'Tolerance'), self.__m_tolValue)
        self.__m_tol = self._slider(1, 60, lambda v: (self.__m_colors.setTolerance(v), self._save()))  # type: QSlider
        self.__m_groupValue = QLabel()  # type: QLabel
        self._title(self.tr(u'Group nearby'), self.__m_groupValue)
        self.__m_group = self._slider(
            0, 20, lambda v: (self.__m_colors.setGroupDistance(v), self._save()))  # type: QSlider
        self.__m_group.setToolTip(self.tr(u'Fragments closer than this form one box (letters of a text line)'))
        self.__m_areaValue = QLabel()  # type: QLabel
        self._title(self.tr(u'Smallest region'), self.__m_areaValue)
        self.__m_area = self._slider(1, 400, lambda v: (self.__m_colors.setMinArea(v), self._save()))  # type: QSlider
        self.__m_boxes = self._check(self.tr(u'Boxes around regions'),
                                     lambda on: (ctrl.setShowBoxes(on), self._save()))  # type: QCheckBox
        self.__m_mask = self._check(self.tr(u'Highlight mask'), lambda on: (ctrl.setShowMask(on), self._save()))
        self.__m_maskMode = self._combo(MASK_MODES, lambda m: (ctrl.setMaskMode(m), self._save()))  # type: QComboBox
        self.__m_notify = self._check(self.tr(u'Notify when a target color appears'), self._setNotify)
        self._title(self.tr(u'Show the zones in'))
        self.__m_inView = self._check(self.tr(u'the magnifier'), lambda on: self._setWhere('zonesInMagnifier', on))
        self.__m_inLens = self._check(self.tr(u'the zoomer (also in the Zoomer tab)'),
                                      lambda on: self._setWhere('zonesInZoomer', on))
        self._title(self.tr(u'Dominant colors'))
        self.__m_palette = PaletteBar()  # type: PaletteBar
        self.__m_layout.addWidget(self.__m_palette)
        self.__m_paletteNames = DetectionPanel._label('', 'hint')  # type: QLabel
        self.__m_layout.addWidget(self.__m_paletteNames)

    def _buildFaces(self):
        """
        :return:
        """
        ctrl = self.__m_ctrl  # type: AnalysisController
        self._title(self.tr(u'Face detection (AI, optional)'))
        if not FaceDetector.isAvailable():
            self.__m_layout.addWidget(DetectionPanel._label(
                self.tr(u'Install opencv-python (and numpy) to enable face detection.'), 'hint'))
        self.__m_faceOn = self._check(self.tr(u'Detect faces'), self._setFaceEnabled)  # type: QCheckBox
        self.__m_faceOn.setEnabled(FaceDetector.isAvailable())
        self.__m_backend = self._combo(FACE_BACKENDS, lambda b: (self.__m_faces.setBackend(b),
                                                                 self._refreshModelState(), self._save()))
        row = QHBoxLayout()  # type: QHBoxLayout
        self.__m_modelState = DetectionPanel._label('', 'hint')  # type: QLabel
        self.__m_download = QPushButton(self.tr(u'Download model'))  # type: QPushButton
        self.__m_download.setProperty('role', 'small')
        self.__m_download.setToolTip(self.tr(u'YuNet, 232 KB, MIT license, from the official OpenCV model zoo'))
        self.__m_download.clicked.connect(self._download)
        row.addWidget(self.__m_modelState, 1)
        row.addWidget(self.__m_download)
        self.__m_layout.addLayout(row)
        self.__m_scoreValue = QLabel()  # type: QLabel
        self._title(self.tr(u'Confidence'), self.__m_scoreValue)
        self.__m_score = self._slider(10, 99, lambda v: (self.__m_faces.setScoreThreshold(v / 100.0),
                                                         self.__m_ctrl.reanalyse(), self._save()))  # type: QSlider
        self.__m_faceMode = self._combo(FACE_MODES, lambda m: (ctrl.setFaceMode(m), self._save()))  # type: QComboBox
        self.__m_faceInfo = DetectionPanel._label('', 'hint')  # type: QLabel
        self.__m_layout.addWidget(self.__m_faceInfo)

    def _buildFacePointer(self):
        """
        FACE POINTER: the pointer (or the zoomer) glides to the faces on the screen, e.g. while watching a film.
        :return:
        """
        fp = self.__m_pointer  # type: FacePointer
        s = self.__m_pointerSettings  # type: QSettings
        fp.setFollow(int(s.value('follow', FOLLOW_POINTER)))
        fp.setChoose(int(s.value('choose', CHOOSE_LARGEST)))
        fp.setSmoothness(int(s.value('smoothness', 40)))
        fp.setPauseSeconds(float(s.value('pauseSeconds', 3.0)))
        fp.setScanRate(int(s.value('scanRate', 5)))
        fp.setMotion(int(s.value('motion', MOTION_AUTO)))
        fp.setHold(int(s.value('hold', HOLD_ALWAYS)))
        fp.setAssistArea(int(s.value('assistArea', 35)))
        fp.setStrength(int(s.value('strength', 60)))
        self._title(self.tr(u'Face pointer (films, offline games)'))
        self.__m_pointerOn = self._check(self.tr(u'Follow the faces on the screen'), fp.setEnabled)  # type: QCheckBox
        self.__m_pointerOn.setEnabled(FacePointer.isAvailable())
        fp.enabledChanged.connect(self._refreshFacePointer)
        fp.statusChanged.connect(self._refreshFacePointer)
        self._title(self.tr(u'How to move'))
        self.__m_pointerMotion = self._combo(POINTER_MOTION, lambda v: (fp.setMotion(v), self._savePointer(),
                                                                        self._refreshFacePointer()))
        self._title(self.tr(u'When'))
        self.__m_pointerHold = self._combo(POINTER_HOLD, lambda v: (fp.setHold(v), self._savePointer()))
        self.__m_followBox = QWidget()  # type: QWidget  # only when the pointer moves (not the game's view)
        followLayout = QVBoxLayout(self.__m_followBox)  # type: QVBoxLayout
        followLayout.setContentsMargins(0, 0, 0, 0)
        followLayout.addWidget(DetectionPanel._label(self.tr(u'What follows the face').upper(), 'title'))
        self.__m_pointerFollow = self._combo(POINTER_FOLLOW, lambda v: (fp.setFollow(v), self._savePointer()))
        followLayout.addWidget(self.__m_pointerFollow)
        self.__m_layout.addWidget(self.__m_followBox)
        self._title(self.tr(u'Which face'))
        self.__m_pointerChoose = self._combo(POINTER_CHOOSE, lambda v: (fp.setChoose(v), self._savePointer()))
        self.__m_pointerValues = {}  # type: dict
        self.__m_pointerSliders = {}  # type: dict
        self.__m_pointerRows = {}  # type: dict  # name -> row widget (shown for the motion it applies to)
        for name, title, lo, hi in (('assistArea', self.tr(u'Assist area around the crosshair'), 10, 100),
                                    ('strength', self.tr(u'Strength'), 10, 100),
                                    ('smoothness', self.tr(u'Smoothness'), 0, 100),
                                    ('pauseSeconds', self.tr(u'Give the mouse back for'), 1, 10),
                                    ('scanRate', self.tr(u'Scans per second'), 1, 15)):
            row = QWidget()  # type: QWidget
            column = QVBoxLayout(row)  # type: QVBoxLayout
            column.setContentsMargins(0, 0, 0, 0)
            head = QHBoxLayout()  # type: QHBoxLayout
            head.addWidget(DetectionPanel._label(title.upper(), 'title'))
            head.addStretch(1)
            value = QLabel()  # type: QLabel
            value.setProperty('role', 'value')
            head.addWidget(value)
            column.addLayout(head)
            slider = QSlider(Qt.Horizontal)  # type: QSlider
            slider.setRange(lo, hi)
            setter = getattr(fp, 'set' + name[0].upper() + name[1:])
            slider.valueChanged.connect(lambda v, f=setter: (f(v), self._savePointer(), self._refreshFacePointer()))
            column.addWidget(slider)
            self.__m_layout.addWidget(row)
            self.__m_pointerRows[name] = row
            self.__m_pointerValues[name] = value
            self.__m_pointerSliders[name] = slider
        self.__m_pointerStatus = DetectionPanel._label('', 'hint')  # type: QLabel
        self.__m_layout.addWidget(self.__m_pointerStatus)
        self.__m_gameHint = DetectionPanel._label(self.tr(
            u'Offline games that capture the mouse: the view turns until the face is at the crosshair (the screen '
            'centre), about 30 times per second; the game\'s mouse sensitivity is measured from the picture while it '
            'assists. Only faces inside the assist area '
            'count, and a portrait of the game\'s interface is ignored. "While the right mouse button is held" never '
            'fights your own aiming. Run the game in borderless / windowed mode. Realistic faces work best.'),
            'hint')  # type: QLabel
        self.__m_layout.addWidget(self.__m_gameHint)
        self.__m_filmHint = DetectionPanel._label(self.tr(
            u'Faces are found anywhere on the screen of the pointer (the zoomer lens and this window are ignored), '
            'with the face detection settings above. Move the mouse yourself to take the control back. Video '
            'players show their controls when the pointer moves: choose "Only the zoomer" to keep it still. The YuNet '
            'model (Download model, above) finds smaller faces, faster.'),
            'hint')  # type: QLabel
        self.__m_layout.addWidget(self.__m_filmHint)
        for combo, value in ((self.__m_pointerFollow, fp.getFollow()), (self.__m_pointerChoose, fp.getChoose()),
                             (self.__m_pointerMotion, fp.getMotion()), (self.__m_pointerHold, fp.getHold())):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)
        for name, slider in self.__m_pointerSliders.items():
            slider.blockSignals(True)
            slider.setValue(int(getattr(fp, 'get' + name[0].upper() + name[1:])()))
            slider.blockSignals(False)
        self._refreshFacePointer()

    def _savePointer(self):
        """
        :return:
        """
        fp = self.__m_pointer  # type: FacePointer
        s = self.__m_pointerSettings  # type: QSettings
        for key, value in (('follow', fp.getFollow()), ('choose', fp.getChoose()), ('smoothness', fp.getSmoothness()),
                           ('pauseSeconds', fp.getPauseSeconds()), ('scanRate', fp.getScanRate()),
                           ('motion', fp.getMotion()), ('hold', fp.getHold()), ('assistArea', fp.getAssistArea()),
                           ('strength', fp.getStrength())):
            s.setValue(key, value)

    @pyqtSlot()
    def _refreshFacePointer(self, *args):
        """
        :return:
        """
        fp = self.__m_pointer  # type: FacePointer
        self.__m_pointerOn.blockSignals(True)
        self.__m_pointerOn.setChecked(fp.isEnabled())
        self.__m_pointerOn.blockSignals(False)
        key = self.__m_hotkeyText('facePointer')  # type: str
        self.__m_pointerOn.setText(self.tr(u'Follow the faces on the screen') + (u' ({})'.format(key) if key else u''))
        motion = fp.getMotion()  # type: int
        game, film = motion != MOTION_POINTER, motion != MOTION_VIEW  # type: bool, bool  # (Automatic: both)
        view = fp.isTurningView()  # type: bool
        self.__m_followBox.setVisible(film)
        self.__m_pointerHold.setEnabled(game)
        for name in ('assistArea', 'strength'):
            self.__m_pointerRows[name].setVisible(game)
        for name in ('pauseSeconds', 'scanRate'):
            self.__m_pointerRows[name].setVisible(film)
        self.__m_gameHint.setVisible(game)
        self.__m_filmHint.setVisible(film)
        self.__m_pointerValues['assistArea'].setText(u'{} %'.format(fp.getAssistArea()))
        self.__m_pointerValues['strength'].setText(u'{} %'.format(fp.getStrength()))
        self.__m_pointerValues['smoothness'].setText(u'{} %'.format(fp.getSmoothness()))
        self.__m_pointerValues['pauseSeconds'].setText(self.tr(u'{} s').format(int(fp.getPauseSeconds())))
        self.__m_pointerValues['scanRate'].setText(self.tr(u'{} / s').format(fp.getScanRate()))
        status, d = fp.getStatus(), fp.getStatusDetail()  # type: str, dict
        role = 'hint'  # type: str
        if status == 'unavailable':
            text = self.tr(u'Install opencv-python (and numpy) to enable face detection.')  # type: str
        elif status == 'off':
            text = self.tr(u'Off.')
        elif status == 'searching':
            text = self.tr(u'Looking for faces\u2026')
        elif status == 'following' and view and d.get('auto'):
            text, role = self.tr(u'\u2713 This game captures the mouse: the view turns to a face ({} in the assist '
                                 'area, {:.0f} ms).').format(d.get('faces', 1), d.get('timeMs', 0.0)), 'ok'
        elif status == 'following' and view:
            text, role = self.tr(u'\u2713 Turning the view to a face ({} in the assist area, {:.0f} ms)').format(
                d.get('faces', 1), d.get('timeMs', 0.0)), 'ok'
        elif status == 'blank':
            text, role = self.tr(u'\u26a0 The game\'s picture cannot be captured (black): run it in borderless / '
                                 'windowed mode. On Windows, "pip install dxcam" captures more games.'), 'warn'
        elif status == 'noReaction':
            text, role = self.tr(u'\u26a0 The game does not receive the mouse movements. Click into the game; if '
                                 'it runs as administrator, run Screen Magnifier as administrator too.'), 'warn'
        elif status == 'following':
            text, role = self.tr(u'\u2713 Following a face ({} on the screen, {:.0f} ms)').format(
                d.get('faces', 1), d.get('timeMs', 0.0)), 'ok'
        elif status == 'waiting':
            text = self.tr(u'Hold the right mouse button to assist.')
        elif status == 'static':
            text = self.tr(u'A face that does not move with the view (a portrait of the game\'s interface) is '
                           'ignored for a few seconds.')
        elif status == 'blocked' and view:
            text, role = self.tr(u'\u26a0 This system does not let applications send mouse movements (Wayland, or '
                                 'macOS without the Accessibility permission).'), 'warn'
        elif status == 'paused':
            text = self.tr(u'Paused: you moved the mouse. It starts again {} s after you stop.').format(
                int(fp.getPauseSeconds()))
        elif status == 'blocked':
            text, role = self.tr(u'\u26a0 This system does not let applications move the pointer (Wayland, or macOS '
                                 'without the Accessibility permission): choose "Only the zoomer".'), 'warn'
        else:
            text, role = self.tr(u'Face detection failed: {}').format(d.get('message', '')), 'warn'
        self.__m_pointerStatus.setText(text)
        self.__m_pointerStatus.setProperty('role', role)
        self.__m_pointerStatus.style().unpolish(self.__m_pointerStatus)
        self.__m_pointerStatus.style().polish(self.__m_pointerStatus)

    def _buildAnalysis(self):
        """
        :return:
        """
        self.__m_rateValue = QLabel()  # type: QLabel
        self._title(self.tr(u'Analysis rate'), self.__m_rateValue)
        self.__m_rate = self._slider(1, 30, lambda v: (self.__m_ctrl.setRateHz(v), self._save()))  # type: QSlider
        self.__m_engine = DetectionPanel._label('', 'hint')  # type: QLabel
        self.__m_layout.addWidget(self.__m_engine)

    # ---------- Settings ----------
    def _load(self):
        """
        :return:
        """
        self.__m_loading = True  # type: bool
        s = self.__m_settings  # type: QSettings
        get = lambda key, default, cast: cast(s.value(key, default))
        flag = lambda v: u'{}'.format(v).lower() in ('1', 'true', 'yes')
        targets = s.value('targets', []) or []  # type: list
        if hasattr(targets, 'encode'):
            targets = [t for t in targets.split(',') if t]  # type: list
        if int(s.value('engineVersion', 1)) < ENGINE_VERSION:  # Tolerance changed meaning: start from defaults.
            for key in ('tolerance', 'matchMode', 'groupDistance'):
                s.remove(key)
            s.setValue('engineVersion', ENGINE_VERSION)
        widgets = (self.__m_match, self.__m_group, self.__m_tol, self.__m_area, self.__m_boxes, self.__m_mask,
                   self.__m_maskMode, self.__m_notify, self.__m_backend, self.__m_score, self.__m_faceMode,
                   self.__m_rate)
        for w in widgets:
            w.blockSignals(True)
        self.__m_colors.setTargetColors([QColor(u'{}'.format(t)) for t in targets if QColor(u'{}'.format(t)).isValid()])
        self.__m_match.setCurrentIndex(max(0, self.__m_match.findData(get('matchMode', 0, int))))
        self.__m_group.setValue(get('groupDistance', 5, int))
        self.__m_tol.setValue(get('tolerance', 15, int))
        self.__m_area.setValue(get('minArea', 12, int))
        self.__m_boxes.setChecked(get('boxes', True, flag))
        self.__m_mask.setChecked(get('mask', True, flag))
        self.__m_maskMode.setCurrentIndex(max(0, self.__m_maskMode.findData(get('maskMode', 'isolate', str))))
        self.__m_notify.setChecked(get('notify', True, flag))
        self.__m_backend.setCurrentIndex(max(0, self.__m_backend.findData(get('faceBackend', 'auto', str))))
        self.__m_score.setValue(get('faceScore', 60, int))
        self.__m_faceMode.setCurrentIndex(max(0, self.__m_faceMode.findData(get('faceMode', 'box', str))))
        self.__m_rate.setValue(get('rate', 8, int))
        for w in widgets:
            w.blockSignals(False)
        ctrl = self.__m_ctrl  # type: AnalysisController
        self.__m_colors.setMatchMode(self.__m_match.currentData())
        self.__m_colors.setGroupDistance(self.__m_group.value())
        self.__m_colors.setTolerance(self.__m_tol.value())
        self.__m_colors.setMinArea(self.__m_area.value())
        ctrl.setShowBoxes(self.__m_boxes.isChecked())
        ctrl.setShowMask(self.__m_mask.isChecked())
        ctrl.setMaskMode(self.__m_maskMode.currentData())
        ctrl.setFaceMode(self.__m_faceMode.currentData())
        ctrl.setRateHz(self.__m_rate.value())
        self.__m_faces.setBackend(self.__m_backend.currentData())
        self.__m_faces.setScoreThreshold(self.__m_score.value() / 100.0)
        self.__m_notifyOn = self.__m_notify.isChecked()  # type: bool
        colorOn = get('colorEnabled', False, flag) and ColorDetector.isAvailable()  # type: bool
        faceOn = get('faceEnabled', False, flag) and FaceDetector.isAvailable()  # type: bool
        self.__m_colorOn.setChecked(colorOn)
        self.__m_faceOn.setChecked(faceOn)
        self.__m_loading = False  # type: bool
        self._updateLabels()

    def _save(self):
        """
        :return: None
        """
        if self.__m_loading:
            return
        s = self.__m_settings  # type: QSettings
        s.setValue('targets', ','.join(u'{}'.format(c.name()) for c in self.__m_colors.getTargetColors()))
        for key, value in (('matchMode', self.__m_match.currentData()), ('groupDistance', self.__m_group.value()),
                           ('tolerance', self.__m_tol.value()), ('minArea', self.__m_area.value()),
                           ('boxes', self.__m_boxes.isChecked()), ('mask', self.__m_mask.isChecked()),
                           ('maskMode', self.__m_maskMode.currentData()), ('notify', self.__m_notify.isChecked()),
                           ('faceBackend', self.__m_backend.currentData()),
                           ('faceScore', self.__m_score.value()), ('faceMode', self.__m_faceMode.currentData()),
                           ('rate', self.__m_rate.value()), ('colorEnabled', self.__m_colorOn.isChecked()),
                           ('faceEnabled', self.__m_faceOn.isChecked())):
            s.setValue(key, value)
        self._updateLabels()

    def _updateLabels(self):
        """
        :return:
        """
        exact = self.__m_match.currentData() == 1  # type: bool
        self.__m_tolValue.setText(
            (self.tr(u'Delta E {}') if exact else self.tr(u'{} deg hue')).format(self.__m_tol.value()))
        self.__m_groupValue.setText(self.tr(u'{} px').format(self.__m_group.value()))
        self.__m_areaValue.setText(self.tr(u'{} px').format(self.__m_area.value()))
        self.__m_scoreValue.setText('{} %'.format(self.__m_score.value()))
        self.__m_rateValue.setText(self.tr(u'{} / s').format(self.__m_rate.value()))
        self.__m_maskMode.setEnabled(self.__m_mask.isChecked())

    # ---------- Slots ----------
    def _setColorEnabled(self, on):
        """
        :param on: bool
        :return:
        """
        self.__m_ctrl.setColorEnabled(on)
        self._save()

    def _setFaceEnabled(self, on):
        """
        :param on: bool
        :return:
        """
        self.__m_ctrl.setFaceEnabled(on)
        self._refreshModelState()
        self._save()

    def _setNotify(self, on):
        """
        :param on: bool
        :return:
        """
        self.__m_notifyOn = bool(on)  # type: bool
        self._save()

    def _setWhere(self, name, on):
        """
        :param name: (str | unicode | QString) 'zonesInMagnifier' or 'zonesInZoomer' (FeatureSettings).
        :param on: bool
        :return:
        """
        if self.__m_features is not None:
            self.__m_features.set(name, bool(on))

    def _syncWhere(self, *args):
        """
        :param args: any
        :return:
        """
        f = self.__m_features
        for box, name in ((self.__m_inView, 'zonesInMagnifier'), (self.__m_inLens, 'zonesInZoomer')):
            box.blockSignals(True)
            box.setChecked(f is not None and f.get(name))
            box.setEnabled(f is not None)
            box.blockSignals(False)

    def _addDialog(self):
        """
        :return:
        """
        color = QColorDialog.getColor(QColor('#E01020'), self, self.tr(u'Target color'))  # type: QColor
        if color.isValid():
            self.__m_colors.addTargetColor(color)

    def _removeSelected(self):
        """
        :return:
        """
        row = self.__m_targets.currentRow()  # type: int
        if row >= 0:
            self.__m_colors.removeTargetColor(row)

    def _refreshTargets(self):
        """
        :return:
        """
        coverage = {c['target']: c['fraction'] for c in
                    self.__m_ctrl.getLastResult('view').get('colors', {}).get('coverage', [])}  # type: dict
        self.__m_targets.clear()
        for i, c in enumerate(self.__m_colors.getTargetColors()):
            text = '{}  {}'.format(nearestColorName(c)[0], u'{}'.format(c.name()).upper())  # type: str
            if i in coverage:
                text += '   {:.1f} %'.format(100.0 * coverage[i])
            self.__m_targets.addItem(QListWidgetItem(swatch(c), text))
        self._save()

    def _onResults(self, source, result):
        """
        :param source: str | unicode | QString
        :param result: dict
        :return:
        """
        if u'{}'.format(source) != 'view':
            return
        colors = result.get('colors') or {}  # type: dict
        faces = result.get('faces') or {}  # type: dict
        palette = colors.get('palette', [])  # type: list
        self.__m_palette.setColors(palette)
        self.__m_paletteNames.setText(', '.join('{} {:.0f}%'.format(p['name'], 100 * p['fraction'])
                                                for p in palette[:4]))
        for i, c in enumerate(colors.get('coverage', [])):
            item = self.__m_targets.item(c['target'])  # type: QListWidgetItem
            if item is not None:
                item.setText('{}  {}   {:.1f} %'.format(c['name'], c['color'], 100.0 * c['fraction']))
        if self.__m_ctrl.isFaceEnabled():
            self.__m_faceInfo.setText(self.tr(u'{} face(s)  -  {}  -  {:.0f} ms').format(
                len(faces.get('faces', [])), faces.get('backend', '-') or '-', faces.get('timeMs', 0)))
        where = self.tr(u'server') if self.__m_ctrl.isRemoteActive() else self.tr(u'this computer')  # type: str
        self.__m_engine.setText(self.tr(u'Analysed on {}: colors {:.0f} ms, faces {:.0f} ms').format(
            where, colors.get('timeMs', 0), faces.get('timeMs', 0)))

    def _onAppeared(self, source, name):
        """
        :param source: str | unicode | QString
        :param name: str | unicode | QString
        :return:
        """
        if self.__m_notifyOn:
            where = self.tr(u'zoom lens') if u'{}'.format(source) == 'lens' else self.tr(u'magnifier')  # type: str
            self.notify.emit(self.tr(u'Target color "{}" detected in the {}').format(name, where))

    def _refreshModelState(self):
        """
        :return:
        """
        fd = self.__m_faces  # type: FaceDetector
        if not FaceDetector.isAvailable():
            text = self.tr(u'OpenCV not installed')  # type: str
        elif fd.isModelReady():
            text = self.tr(u'YuNet model installed')  # type: str
        elif not FaceDetector.hasYuNetSupport():
            text = self.tr(u'This OpenCV has no YuNet support: Haar is used')  # type: str
        else:
            text = self.tr(u'YuNet model not installed: Haar is used')  # type: str
        active = fd.getActiveBackend()  # type: str
        if active:
            text += self.tr(u'  (active: {})').format(active)
        self.__m_modelState.setText(text)
        self.__m_download.setVisible(FaceDetector.hasYuNetSupport() and not fd.isModelReady())
        self.__m_download.setEnabled(not fd.isDownloading())

    def _download(self):
        """
        :return:
        """
        self.__m_download.setEnabled(False)
        self.__m_faces.downloadModel()

    def _onDownloaded(self, ok, message):
        """
        :param ok: bool
        :param message: str | unicode | QString
        :return:
        """
        self._refreshModelState()
        self.__m_ctrl.reanalyse()
        self.notify.emit(self.tr(u'YuNet face model installed.') if ok else u'{}'.format(message))

    # ---------- Public API ----------
    @pyqtSlot(QPoint, QColor)
    def onPixelClicked(self, pos, color):
        """
        In pick mode, a click in the magnifier adds the clicked color as a target.
        :param pos: QPoint
        :param color: QColor
        :return:
        """
        if self.__m_pick.isChecked() and color.isValid():
            self.__m_colors.addTargetColor(color)
            self.__m_pick.setChecked(False)
            if not self.__m_colorOn.isChecked():
                self.__m_colorOn.setChecked(True)
            self.notify.emit(self.tr(u'Target color {} added').format(u'{}'.format(color.name()).upper()))

    def isPicking(self):
        """
        :return: bool
        """
        return self.__m_pick.isChecked()
