# coding=utf-8
"""
ImageFilters demo: a test picture before / after, with the effect and the adjustment sliders.
"""
from ManyQt.QtWidgets import QMainWindow, QWidget, QGridLayout, QHBoxLayout, QVBoxLayout, QLabel, QSlider, QComboBox, \
    QPushButton
from ManyQt.QtGui import QImage, QPainter, QColor, QFont, QPixmap, QLinearGradient, QConicalGradient
from ManyQt.QtCore import Qt, QPointF, QRectF, pyqtSlot
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .imagefilters import ImageFilters
except:
    from imagefilters import ImageFilters


def testPicture():
    """
    :return: (QImage) Colour wheel, grey ramp, red / green and blue / yellow patches, text.
    """
    img = QImage(360, 240, QImage.Format_RGB32)  # type: QImage
    img.fill(QColor(236, 238, 242))
    p = QPainter(img)  # type: QPainter
    p.setRenderHint(QPainter.Antialiasing, True)
    wheel = QConicalGradient(QPointF(80, 90), 0)  # type: QConicalGradient
    for i, c in enumerate(('#FF0000', '#FFFF00', '#00FF00', '#00FFFF', '#0000FF', '#FF00FF', '#FF0000')):
        wheel.setColorAt(i / 6.0, QColor(c))
    p.setBrush(wheel)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(80, 90), 62, 62)
    ramp = QLinearGradient(0, 0, 360, 0)  # type: QLinearGradient
    ramp.setColorAt(0, QColor('black'))
    ramp.setColorAt(1, QColor('white'))
    p.fillRect(QRectF(0, 200, 360, 40), ramp)
    for i, c in enumerate(('#D03030', '#30A040', '#2E6BD8', '#E8C020')):
        p.fillRect(QRectF(170 + (i % 2) * 90, 30 + (i // 2) * 70, 80, 60), QColor(c))
    p.setPen(QColor(30, 32, 40))
    p.setFont(QFont('Sans', 13, QFont.Bold))
    p.drawText(QRectF(170, 172, 180, 24), Qt.AlignCenter, 'Screen Magnifier')
    p.end()
    return img


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
        self.setWindowTitle(u'ImageFilters demo')
        self.__m_source = testPicture()  # type: QImage
        self.__m_filters = ImageFilters(changed=self._render)  # type: ImageFilters
        central = QWidget(self)  # type: QWidget
        layout = QVBoxLayout(central)  # type: QVBoxLayout
        images = QHBoxLayout()  # type: QHBoxLayout
        self.__m_before = QLabel()  # type: QLabel
        self.__m_after = QLabel()  # type: QLabel
        for title, label in ((u'Before', self.__m_before), (u'After', self.__m_after)):
            box = QVBoxLayout()  # type: QVBoxLayout
            box.addWidget(QLabel(title))
            box.addWidget(label)
            images.addLayout(box)
        layout.addLayout(images)
        grid = QGridLayout()  # type: QGridLayout
        self.__m_effect = QComboBox()  # type: QComboBox
        self.__m_effect.addItems(ImageFilters.EFFECT_NAMES)
        self.__m_effect.currentIndexChanged.connect(self.__m_filters.setEffect)
        grid.addWidget(QLabel(u'Effect'), 0, 0)
        grid.addWidget(self.__m_effect, 0, 1)
        self.__m_sliders = []  # type: list[QSlider]
        for row, (name, lo, value, slot) in enumerate(((u'Strength', 0, 100, self.__m_filters.setStrength),
                                                       (u'Brightness', -100, 0, self.__m_filters.setBrightness),
                                                       (u'Contrast', -100, 0, self.__m_filters.setContrast),
                                                       (u'Saturation', -100, 0, self.__m_filters.setSaturation))):
            s = QSlider(Qt.Horizontal)  # type: QSlider
            s.setRange(lo, 100)
            s.setValue(value)
            s.valueChanged.connect(slot)
            grid.addWidget(QLabel(name), row + 1, 0)
            grid.addWidget(s, row + 1, 1)
            self.__m_sliders.append(s)
        reset = QPushButton(u'Reset')  # type: QPushButton
        reset.clicked.connect(self._reset)
        grid.addWidget(reset, 5, 1)
        layout.addLayout(grid)
        self.setCentralWidget(central)
        self.__m_before.setPixmap(QPixmap.fromImage(self.__m_source))
        self._render()

    @pyqtSlot()
    def _render(self):
        """
        :return:
        """
        self.__m_after.setPixmap(QPixmap.fromImage(self.__m_filters.apply(self.__m_source)))

    @pyqtSlot()
    def _reset(self):
        """
        :return:
        """
        self.__m_filters.reset()
        self.__m_effect.setCurrentIndex(0)
        for s, value in zip(self.__m_sliders, (100, 0, 0, 0)):
            s.setValue(value)

    def getFilters(self):
        """
        :return: ImageFilters
        """
        return self.__m_filters
