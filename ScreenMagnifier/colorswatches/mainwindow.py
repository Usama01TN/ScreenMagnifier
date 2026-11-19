# coding=utf-8
"""
Demo window for ColorSwatchesWidget: add colors, click to copy, right-click to remove.
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QLabel, QPushButton, QApplication
from ManyQt.QtCore import pyqtSlot, Qt
from ManyQt.QtGui import QColor
from os.path import dirname
from random import randint
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .colorswatches import ColorSwatchesWidget
except:
    from colorswatches import ColorSwatchesWidget


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
        self.setWindowTitle(self.tr(u'ColorSwatches demo'))
        self.resize(420, 260)
        self.__m_swatches = ColorSwatchesWidget(colors=['#E01020', '#1E5AD7', '#2AA845', '#F2C12E'], maxColors=24,
                                                colorClicked=self.onColorClicked)  # type: ColorSwatchesWidget
        self.__m_info = QLabel(self.tr(u'Click a swatch to copy its HEX code, right-click to remove it.'))
        add = QPushButton(self.tr(u'Add a random color'))  # type: QPushButton
        add.clicked.connect(lambda: self.__m_swatches.addColor(QColor(randint(0, 255), randint(0, 255),
                                                                      randint(0, 255))))
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addWidget(add)
        layout.addWidget(self.__m_swatches)
        layout.addWidget(self.__m_info)
        layout.addStretch(1)
        self.setCentralWidget(wdg)

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
        color = color if isinstance(color, QColor) else QColor(color)  # type: QColor
        QApplication.clipboard().setText(u'{}'.format(color.name()).upper())
        self.__m_info.setText(self.tr(u'Copied {}').format(u'{}'.format(color.name()).upper()))
