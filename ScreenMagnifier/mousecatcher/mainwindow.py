# coding=utf-8
"""
Demo window for GlobalMouseCatcher: click anywhere on the screen, the clicks are reported and swallowed.
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QPushButton, QListWidget, QLabel
from ManyQt.QtCore import QPoint, pyqtSlot
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .mousecatcher import GlobalMouseCatcher
except:
    from mousecatcher import GlobalMouseCatcher


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
        self.setWindowTitle(self.tr(u'GlobalMouseCatcher demo'))
        self.resize(460, 340)
        self.__m_catcher = GlobalMouseCatcher(clicked=self.onClicked, wheelTurned=lambda d: self.log('wheel {}'.format(d)),
                                              keyPressed=self.onKey)  # type: GlobalMouseCatcher
        button = QPushButton(self.tr(u'Start catching (right-click or Esc stops)'))  # type: QPushButton
        button.clicked.connect(self.start)
        self.__m_log = QListWidget()  # type: QListWidget
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addWidget(button)
        layout.addWidget(QLabel(self.tr(u'Backend: {}').format(self.__m_catcher.getBackendName())))
        layout.addWidget(self.__m_log)
        self.setCentralWidget(wdg)

    def log(self, text):
        """
        :param text: str | unicode | QString
        :return:
        """
        self.__m_log.insertItem(0, u'{}'.format(text))

    @pyqtSlot()
    def start(self):
        """
        :return:
        """
        if not self.__m_catcher.start():
            self.log(self.__m_catcher.getError())

    @pyqtSlot(QPoint, int)
    def onClicked(self, pos, button):
        """
        :param pos: QPoint
        :param button: int
        :return:
        """
        self.log('button {} at ({}, {})'.format(button, pos.x(), pos.y()))
        if button == 2:
            self.__m_catcher.stop()

    @pyqtSlot(int)
    def onKey(self, key):
        """
        :param key: int
        :return:
        """
        self.log('key {}'.format(key))
        if key == 0x01000000:  # Qt.Key_Escape
            self.__m_catcher.stop()
