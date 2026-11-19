# coding=utf-8
"""
Demo window for ColorDetector: click the scene to add target colors, tune the tolerance, see regions, mask,
palette and color information.
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QSlider, QPushButton, QComboBox
from ManyQt.QtGui import QImage, QPainter, QColor, QFont, QPen, QLinearGradient
from ManyQt.QtCore import Qt, QRect, QRectF, QPointF, pyqtSignal, pyqtSlot
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .colordetector import ColorDetector, colorInfo, maskToOverlay
except:
    from colordetector import ColorDetector, colorInfo, maskToOverlay


def makeScene():
    """
    :return: (QImage) A UI-like scene with several reds, blues and greens.
    """
    img = QImage(640, 400, QImage.Format_RGB32)  # type: QImage
    g = QLinearGradient(0, 0, 640, 400)  # type: QLinearGradient
    g.setColorAt(0, QColor('#1B2A3A'))
    g.setColorAt(1, QColor('#2E4A2E'))
    p = QPainter(img)  # type: QPainter
    p.fillRect(img.rect(), g)
    for rect, color in ((QRect(40, 40, 90, 60), '#E01020'), (QRect(200, 70, 40, 40), '#F03030'),
                        (QRect(470, 300, 120, 50), '#C81414'), (QRect(330, 180, 110, 80), '#1E5AD7'),
                        (QRect(60, 250, 70, 110), '#2AA845'), (QRect(520, 60, 60, 60), '#F2C12E')):
        p.fillRect(rect, QColor(color))
    p.setPen(QColor('#FFFFFF'))
    p.setFont(QFont('Sans Serif', 14, QFont.Bold))
    p.drawText(QRect(160, 330, 300, 40), Qt.AlignCenter, u'Click a color to detect it')
    p.end()
    return img


class SceneView(QWidget):
    """
    SceneView class: the scene with the detection result painted over it.
    """
    colorClicked = pyqtSignal(QColor)  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param args: any
        :param kwargs: any
        """
        super(SceneView, self).__init__(*args, **kwargs)
        self.__m_image = QImage()  # type: QImage
        self.__m_result = {}  # type: dict
        self.__m_overlay = QImage()  # type: QImage
        self.setMinimumSize(320, 200)

    def setScene(self, image, result, overlay):
        """
        :param image: QImage
        :param result: dict
        :param overlay: QImage
        :return:
        """
        self.__m_image, self.__m_result, self.__m_overlay = image, result, overlay
        self.update()

    def _target(self):
        """
        :return: (QRectF) Where the scene is drawn (aspect ratio kept).
        """
        if self.__m_image.isNull():
            return QRectF()
        s = min(self.width() / float(self.__m_image.width()), self.height() / float(self.__m_image.height()))
        w, h = self.__m_image.width() * s, self.__m_image.height() * s  # type: float, float
        return QRectF((self.width() - w) / 2.0, (self.height() - h) / 2.0, w, h)

    def mousePressEvent(self, e):
        """
        :param e: QMouseEvent
        :return:
        """
        t = self._target()  # type: QRectF
        if t.contains(QPointF(e.pos())):
            x = int((e.pos().x() - t.left()) * self.__m_image.width() / t.width())  # type: int
            y = int((e.pos().y() - t.top()) * self.__m_image.height() / t.height())  # type: int
            self.colorClicked.emit(QColor(self.__m_image.pixel(x, y)))

    def paintEvent(self, event):
        """
        :param event: QPaintEvent
        :return:
        """
        p = QPainter(self)  # type: QPainter
        p.fillRect(self.rect(), QColor('#15161C'))
        t = self._target()  # type: QRectF
        if not t.isNull():
            p.drawImage(t, self.__m_image)
            if not self.__m_overlay.isNull():
                p.drawImage(t, self.__m_overlay)
            s = t.width() / float(self.__m_image.width())  # type: float
            p.setRenderHint(QPainter.Antialiasing, True)
            for d in self.__m_result.get('detections', []):
                x, y, w, h = d['rect']
                p.setPen(QPen(QColor(d['color']), 2))
                p.drawRect(QRectF(t.left() + x * s, t.top() + y * s, w * s, h * s))
                p.setPen(Qt.white)
                p.drawText(QPointF(t.left() + x * s, t.top() + y * s - 4), d['name'])
        p.end()


class MainWindow(QMainWindow):
    """
    MainWindow class.
    """

    def __init__(self, *args, **kwargs):
        """
        :param args: any
        :param kwargs: any
        """
        super(MainWindow, self).__init__(*args, **kwargs)
        self.setWindowTitle(self.tr(u'ColorDetector demo'))
        self.resize(980, 640)
        self.__m_scene = makeScene()  # type: QImage
        self.__m_detector = ColorDetector(targetColors=['#E01020'], tolerance=20,
                                          targetsChanged=self.analyse)  # type: ColorDetector
        self.__m_view = SceneView()  # type: SceneView
        self.__m_view.colorClicked.connect(self.onColorClicked)
        self.__m_info = QLabel()  # type: QLabel
        self.__m_info.setWordWrap(True)
        self.__m_mode = QComboBox()  # type: QComboBox
        self.__m_mode.addItems(['isolate', 'tint', 'none'])
        self.__m_mode.currentIndexChanged.connect(lambda *a: self.analyse())
        tol = QSlider(Qt.Horizontal)  # type: QSlider
        tol.setRange(1, 60)
        tol.setValue(20)
        tol.valueChanged.connect(lambda v: (self.__m_detector.setTolerance(v), self.analyse()))
        clear = QPushButton(self.tr(u'Clear targets'))  # type: QPushButton
        clear.clicked.connect(self.__m_detector.clearTargetColors)
        bar = QHBoxLayout()  # type: QHBoxLayout
        bar.addWidget(QLabel(self.tr(u'Tolerance (delta E)')))
        bar.addWidget(tol)
        bar.addWidget(QLabel(self.tr(u'Mask')))
        bar.addWidget(self.__m_mode)
        bar.addWidget(clear)
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addLayout(bar)
        layout.addWidget(self.__m_view, 1)
        layout.addWidget(self.__m_info)
        self.setCentralWidget(wdg)
        self.analyse()

    @pyqtSlot()
    def analyse(self):
        """
        :return:
        """
        r = self.__m_detector.analyze(self.__m_scene)  # type: dict
        mode = self.__m_mode.currentText()  # type: str
        overlay = maskToOverlay(r.get('labelMask'), self.__m_detector.getTargetColors(), 0.6, mode) \
            if mode != 'none' else QImage()  # type: QImage
        self.__m_view.setScene(self.__m_scene, r, overlay)
        self.__m_info.setText(self.tr(u'Targets: {}   |   regions: {}   |   palette: {}   |   {:.1f} ms').format(
            ', '.join(c['name'] for c in r['coverage']) or '-', len(r['detections']),
            ', '.join('{} {:.0f}%'.format(p['name'], 100 * p['fraction']) for p in r['palette']), r['timeMs']))

    @pyqtSlot(QColor)
    @pyqtSlot(Qt.GlobalColor)
    @pyqtSlot(int)
    @pyqtSlot(str)
    @pyqtSlot('QString')
    def onColorClicked(self, color):
        """
        :param color: QColor | Qt.GlobalColor | int | str | QString
        :return:
        """
        info = colorInfo(color)  # type: dict
        self.statusBar().showMessage('{hex}  {name}  RGB {rgb}  HSV {hsv}  Lab {lab}'.format(**info))
        self.__m_detector.addTargetColor(color)
