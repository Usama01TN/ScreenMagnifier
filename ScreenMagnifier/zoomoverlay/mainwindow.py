# coding=utf-8
"""
Demo window for ZoomOverlay: a click-through lens over the screen center, the cursor or a corner.
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QComboBox, QSlider, QLabel
from ManyQt.QtGui import QImage, QPainter, QColor, QGuiApplication
from ManyQt.QtCore import Qt, QRect, QRectF, QTimer, pyqtSlot
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .zoomoverlay import ZoomOverlay
except:
    from zoomoverlay import ZoomOverlay


def grabGlobal(rect):
    """
    Minimal multiscreen grab of a global rect (the full version lives in the screengrabber package).
    :param rect: QRect
    :return: QImage
    """
    img = QImage(max(1, rect.width()), max(1, rect.height()), QImage.Format_RGB32)  # type: QImage
    img.fill(QColor(14, 15, 20))
    p = QPainter(img)  # type: QPainter
    for s in QGuiApplication.screens():
        inter = s.geometry().intersected(rect)  # type: QRect
        if inter.isEmpty():
            continue
        pm = s.grabWindow(0, inter.x() - s.geometry().x(), inter.y() - s.geometry().y(), inter.width(),
                          inter.height())
        p.drawPixmap(QRectF(inter.translated(-rect.topLeft())), pm, QRectF(0, 0, pm.width(), pm.height()))
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
        self.setWindowTitle(self.tr(u'ZoomOverlay demo'))
        self.resize(460, 200)
        self.__m_overlay = ZoomOverlay(zoom=3.0, target=ZoomOverlay.Cursor, placement=ZoomOverlay.TopRight,
                                       overlayToggled=self.onToggled)  # type: ZoomOverlay
        self.__m_timer = QTimer(self)  # type: QTimer
        self.__m_timer.timeout.connect(lambda: self.__m_overlay.setFrame(grabGlobal(self.__m_overlay.sourceRect())))
        toggle = QPushButton(self.tr(u'Show / hide lens'))  # type: QPushButton
        toggle.clicked.connect(self.__m_overlay.toggle)
        target = QComboBox()  # type: QComboBox
        target.addItems([self.tr(u'Screen centre'), self.tr(u'Pinned point'), self.tr(u'Mouse cursor')])
        target.setCurrentIndex(int(ZoomOverlay.Cursor))
        target.currentIndexChanged.connect(self.__m_overlay.setTarget)
        placement = QComboBox()  # type: QComboBox
        placement.addItems([self.tr(u'On target'), self.tr(u'Top-left'), self.tr(u'Top-right'), self.tr(u'Bottom-left'),
                            self.tr(u'Bottom-right')])
        placement.setCurrentIndex(int(ZoomOverlay.TopRight))
        placement.currentIndexChanged.connect(self.__m_overlay.setPlacement)
        zoom = QSlider(Qt.Horizontal)  # type: QSlider
        zoom.setRange(10, 160)
        zoom.setValue(30)
        zoom.valueChanged.connect(lambda v: self.__m_overlay.setZoom(v / 10.0))
        row = QHBoxLayout()  # type: QHBoxLayout
        row.addWidget(target)
        row.addWidget(placement)
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addWidget(toggle)
        layout.addLayout(row)
        layout.addWidget(QLabel(self.tr(u'Magnification')))
        layout.addWidget(zoom)
        self.setCentralWidget(wdg)

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def onToggled(self, shown):
        """
        :param shown: bool
        :return:
        """
        self.__m_timer.start(16) if shown else self.__m_timer.stop()

    def closeEvent(self, e):
        """
        :param e: QCloseEvent
        :return:
        """
        self.__m_overlay.hideOverlay()
        self.__m_overlay.close()
        super(MainWindow, self).closeEvent(e)
