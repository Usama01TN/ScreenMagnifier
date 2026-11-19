# coding=utf-8
"""
Demo window for RegionSelector.
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QLabel, QPushButton
from ManyQt.QtCore import Qt, QRect, QTimer, pyqtSlot
from os.path import dirname
from sys import path

if dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .regionselector import RegionSelector
except:
    from regionselector import RegionSelector


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
        self.setWindowTitle(self.tr('RegionSelector demo'))
        self.resize(520, 220)
        self.__m_selector = RegionSelector(borderColor='#4F8BFF', loupeZoom=8, regionSelected=self.onSelected,
                                           selectionCanceled=self.onCanceled)  # type: RegionSelector
        button = QPushButton(self.tr('Select a screen region...'))  # type: QPushButton
        button.setMinimumHeight(40)
        button.clicked.connect(self.select)
        self.__m_result = QLabel(self.tr('No region selected yet.'))  # type: QLabel
        self.__m_result.setAlignment(Qt.AlignCenter)
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addWidget(button)
        layout.addWidget(self.__m_result)
        self.setCentralWidget(wdg)

    @pyqtSlot()
    def select(self):
        """
        Hide this window, give the compositor time to remove it, then freeze the desktop.
        :return:
        """
        self.hide()
        QTimer.singleShot(250, self.__m_selector.start)

    @pyqtSlot(QRect)
    def onSelected(self, rect):
        """
        :param rect: QRect
        :return:
        """
        self.__m_result.setText(self.tr('Selected: x={}, y={}, {} x {}').format(
            rect.x(), rect.y(), rect.width(), rect.height()))
        self.show()

    @pyqtSlot()
    def onCanceled(self):
        """
        :return:
        """
        self.__m_result.setText(self.tr('Selection canceled.'))
        self.show()
