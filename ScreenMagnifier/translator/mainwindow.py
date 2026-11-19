# coding=utf-8
"""
Demo window for LanguageManager: pick a language, the texts are translated live (retranslate on languageChanged).
Uses the application's catalogs (../translations).
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QLabel, QComboBox, QPushButton
from ManyQt.QtCore import pyqtSlot
from os.path import dirname, join
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .translator import LanguageManager
except:
    from translator import LanguageManager


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
        self.resize(460, 280)
        self.__m_manager = LanguageManager(folder=join(dirname(__file__), '..', 'translations'),
                                           languageChanged=self.retranslate)  # type: LanguageManager
        self.__m_combo = QComboBox()  # type: QComboBox
        for code, name in self.__m_manager.availableLanguages():
            self.__m_combo.addItem(name, code)
        self.__m_combo.currentIndexChanged.connect(lambda i: self.__m_manager.setLanguage(self.__m_combo.itemData(i)))
        self.__m_labels = [QLabel() for _ in range(3)]  # type: list
        self.__m_button = QPushButton()  # type: QPushButton
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addWidget(self.__m_combo)
        for label in self.__m_labels:
            layout.addWidget(label)
        layout.addWidget(self.__m_button)
        layout.addStretch(1)
        self.setCentralWidget(wdg)
        self.retranslate()

    @pyqtSlot()
    @pyqtSlot('QString')
    @pyqtSlot(str)
    def retranslate(self, *args):
        """
        Live switching: every text is set again from its English source.
        :param args: any
        :return:
        """
        self.setWindowTitle(self.tr(u'Translator demo'))
        for label, text in zip(self.__m_labels, (u'Select a region', u'Freeze / unfreeze', u'Screen color picker')):
            label.setText(self.tr(text))
        self.__m_button.setText(self.tr(u'Copy all formats'))
