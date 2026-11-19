# coding=utf-8
"""
Demo window for Upscaler: the same tiny crop upscaled with every available method.
"""
from ManyQt.QtWidgets import QMainWindow, QGridLayout, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QSlider, QScrollArea
from ManyQt.QtGui import QImage, QPainter, QColor, QFont, QPixmap, QPen, QLinearGradient
from ManyQt.QtCore import Qt, QSize, QRectF, pyqtSlot
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .upscaler import Upscaler
except:
    from upscaler import Upscaler


def makeSample():
    """
    Build a small UI-like sample: text, thin lines, a gradient and an icon-ish circle.
    :return: QImage
    """
    img = QImage(96, 64, QImage.Format_RGB32)  # type: QImage
    img.fill(QColor('#F4F5F8'))
    p = QPainter(img)  # type: QPainter
    p.setRenderHint(QPainter.Antialiasing, True)
    g = QLinearGradient(0, 0, 96, 0)  # type: QLinearGradient
    g.setColorAt(0, QColor('#5227FF'))
    g.setColorAt(1, QColor('#FF3B6B'))
    p.fillRect(QRectF(0, 0, 96, 14), g)
    p.setPen(Qt.white)
    p.setFont(QFont('Sans Serif', 7, QFont.Bold))
    p.drawText(QRectF(4, 0, 90, 14), Qt.AlignVCenter, u'Magnify me')
    p.setPen(QColor('#22252E'))
    p.setFont(QFont('Sans Serif', 7))
    p.drawText(QRectF(4, 16, 90, 24), Qt.AlignLeft, u'Small text 123\nfine detail')
    p.setPen(QPen(QColor('#1E88E5'), 1))
    p.drawLine(4, 60, 60, 42)
    p.setBrush(QColor('#43A047'))
    p.drawEllipse(QRectF(70, 40, 18, 18))
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
        self.setWindowTitle(self.tr(u'Upscaler demo'))
        self.resize(1180, 760)
        self.__m_sample = makeSample()  # type: QImage
        self.__m_upscaler = Upscaler(sharpness=0.3, errorOccurred=self.onError)  # type: Upscaler
        self.__m_cells = []  # type: list
        grid = QWidget()  # type: QWidget
        layout = QGridLayout(grid)  # type: QGridLayout
        for i, (method, name) in enumerate(self.__m_upscaler.availableMethods()):
            title = QLabel(name)  # type: QLabel
            title.setStyleSheet('font-weight: bold;')
            image = QLabel()  # type: QLabel
            image.setAlignment(Qt.AlignCenter)
            layout.addWidget(title, (i // 3) * 2, i % 3)
            layout.addWidget(image, (i // 3) * 2 + 1, i % 3)
            self.__m_cells.append((method, title, image))
        scroll = QScrollArea()  # type: QScrollArea
        scroll.setWidget(grid)
        scroll.setWidgetResizable(True)
        self.__m_scaleLabel = QLabel()  # type: QLabel
        scale = QSlider(Qt.Horizontal)  # type: QSlider
        scale.setRange(2, 6)
        scale.setValue(4)
        scale.valueChanged.connect(self.setScale)
        sharp = QSlider(Qt.Horizontal)  # type: QSlider
        sharp.setRange(0, 200)
        sharp.setValue(30)
        sharp.valueChanged.connect(lambda v: (self.__m_upscaler.setSharpness(v / 100.0), self.render()))
        bar = QHBoxLayout()  # type: QHBoxLayout
        bar.addWidget(self.__m_scaleLabel)
        bar.addWidget(scale)
        bar.addWidget(QLabel(self.tr(u'Sharpness')))
        bar.addWidget(sharp)
        wdg = QWidget()  # type: QWidget
        v = QVBoxLayout(wdg)  # type: QVBoxLayout
        v.addLayout(bar)
        v.addWidget(scroll)
        self.setCentralWidget(wdg)
        self.__m_scale = 4  # type: int
        self.render()

    @pyqtSlot()
    def render(self):
        """
        :return:
        """
        self.__m_scaleLabel.setText(self.tr(u'Scale x{}').format(self.__m_scale))
        size = self.__m_sample.size() * self.__m_scale  # type: QSize
        for method, title, image in self.__m_cells:
            self.__m_upscaler.setMethod(method)
            out = self.__m_upscaler.process(self.__m_sample, size)  # type: QImage
            title.setText(
                u'{}  -  {:.1f} ms'.format(Upscaler.METHOD_NAMES[method], self.__m_upscaler.getLastProcessTime()))
            image.setPixmap(QPixmap.fromImage(out))

    @pyqtSlot(int)
    def setScale(self, scale):
        """
        :param scale: int
        :return:
        """
        self.__m_scale = int(scale)  # type: int
        self.render()

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def onError(self, message):
        """
        :param message: str | unicode | QString
        :return:
        """
        print(message)
