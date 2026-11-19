# coding=utf-8
"""
Demo window for MagnifierViewWidget, fed with a synthetic image.
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QCheckBox, QPushButton, QLabel
from ManyQt.QtGui import QImage, QPainter, QColor, QFont, QPen, QLinearGradient
from ManyQt.QtCore import Qt, QPoint, QRectF, pyqtSlot
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .magnifierview import MagnifierViewWidget
except:
    from magnifierview import MagnifierViewWidget


def makeSample():
    """
    :return: QImage
    """
    img = QImage(240, 160, QImage.Format_RGB32)  # type: QImage
    img.fill(QColor('#F4F5F8'))
    p = QPainter(img)  # type: QPainter
    p.setRenderHint(QPainter.Antialiasing, True)
    g = QLinearGradient(0, 0, 240, 0)  # type: QLinearGradient
    g.setColorAt(0, QColor('#5227FF'))
    g.setColorAt(1, QColor('#FF3B6B'))
    p.fillRect(QRectF(0, 0, 240, 22), g)
    p.setPen(Qt.white)
    p.setFont(QFont('Sans Serif', 9, QFont.Bold))
    p.drawText(QRectF(8, 0, 230, 22), Qt.AlignVCenter, 'MagnifierViewWidget')
    p.setPen(QColor('#22252E'))
    p.setFont(QFont('Sans Serif', 8))
    p.drawText(QRectF(8, 30, 230, 60), Qt.AlignLeft, 'Wheel: zoom at cursor\nDrag: pan\nDouble-click: fit')
    for i in range(8):
        p.fillRect(8 + i * 12, 100, 10, 10, QColor.fromHsv(i * 45, 200, 230))
    p.setPen(QPen(QColor('#1E88E5'), 1))
    p.drawLine(8, 150, 230, 118)
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
        self.setWindowTitle(self.tr(u'MagnifierView demo'))
        self.resize(900, 620)
        self.__m_view = MagnifierViewWidget(
            zoom=4.0, showGrid=True, showCrosshair=False, pixelHovered=self.onPixel)  # type: MagnifierViewWidget
        self.__m_view.setFrame(makeSample())
        self.__m_info = QLabel()  # type: QLabel
        bar = QHBoxLayout()  # type: QHBoxLayout
        for text, slot, on in ((self.tr(u'Grid'), self.__m_view.setShowGrid, True),
                               (self.tr(u'Crosshair'), self.__m_view.setShowCrosshair, False),
                               (self.tr(u'Invert'), self.__m_view.setInvertColors, False)):
            box = QCheckBox(text)  # type: QCheckBox
            box.setChecked(on)
            box.toggled.connect(slot)
            bar.addWidget(box)
        for text, slot in (
                ('-', self.__m_view.zoomOut), ('+', self.__m_view.zoomIn), (self.tr(u'Fit'), self.__m_view.fitToView)):
            btn = QPushButton(text)  # type: QPushButton
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        bar.addStretch(1)
        bar.addWidget(self.__m_info)
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addLayout(bar)
        layout.addWidget(self.__m_view, 1)
        self.setCentralWidget(wdg)

    @pyqtSlot(QPoint, QColor)
    def onPixel(self, pos, color):
        """
        :param pos: QPoint
        :param color: QColor
        :return:
        """
        self.__m_info.setText('' if pos.x() < 0 else '({}, {})  {}'.format(pos.x(), pos.y(), color.name().upper()))
