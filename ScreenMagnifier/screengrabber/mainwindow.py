# coding=utf-8
"""
Demo window for ScreenGrabber: live capture around the mouse cursor (or a fixed region).
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QCheckBox, QSpinBox
from ManyQt.QtCore import Qt, QRect, QSize, pyqtSlot
from ManyQt.QtGui import QImage, QPixmap
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .screengrabber import ScreenGrabber
except:
    from screengrabber import ScreenGrabber


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
        self.setWindowTitle(self.tr(u'ScreenGrabber demo'))
        self.resize(760, 520)
        self.__m_image = QLabel(self.tr(u'Waiting for frames...'))  # type: QLabel
        self.__m_image.setAlignment(Qt.AlignCenter)
        self.__m_image.setMinimumSize(320, 240)
        self.__m_info = QLabel()  # type: QLabel
        follow = QCheckBox(self.tr(u'Follow cursor'))  # type: QCheckBox
        follow.setChecked(True)
        fps = QSpinBox()  # type: QSpinBox
        fps.setRange(1, 120)
        fps.setValue(30)
        fps.setSuffix(' fps')
        self.__m_grabber = ScreenGrabber(fps=30, followCursor=True, followSize=QSize(360, 240),
                                         region=QRect(0, 0, 360, 240), ignoreWidgets=[self],
                                         frameReady=self.onFrame, captureFailed=self.onFailed,
                                         autoStart=True)  # type: ScreenGrabber
        follow.toggled.connect(self.__m_grabber.setFollowCursor)
        fps.valueChanged.connect(self.__m_grabber.setFps)
        bar = QHBoxLayout()  # type: QHBoxLayout
        bar.addWidget(follow)
        bar.addWidget(fps)
        bar.addStretch(1)
        bar.addWidget(self.__m_info)
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addLayout(bar)
        layout.addWidget(self.__m_image, 1)
        self.setCentralWidget(wdg)

    @pyqtSlot(QImage)
    def onFrame(self, image):
        """
        :param image: QImage
        :return:
        """
        self.__m_image.setPixmap(QPixmap.fromImage(image).scaled(
            self.__m_image.size(), Qt.KeepAspectRatio, Qt.FastTransformation))
        r = self.__m_grabber.getCaptureRect()  # type: QRect
        self.__m_info.setText(u'{}x{} @ ({}, {})  grab {:.1f} ms'.format(
            image.width(), image.height(), r.x(), r.y(), self.__m_grabber.getLastGrabTime()))

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def onFailed(self, message):
        """
        :param message: str | unicode | QString
        :return:
        """
        self.__m_image.setText(message)
