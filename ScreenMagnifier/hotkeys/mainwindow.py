# coding=utf-8
"""
Demo window for GlobalHotkeys: press the shortcuts while another application has the focus.
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QLabel, QListWidget
from ManyQt.QtCore import QDateTime, pyqtSlot
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .hotkeys import GlobalHotkeys
except:
    from hotkeys import GlobalHotkeys


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
        self.setWindowTitle(self.tr(u'GlobalHotkeys demo'))
        self.resize(520, 360)
        self.__m_hotkeys = GlobalHotkeys(bindings={'hello': 'Ctrl+Alt+H', 'world': 'Ctrl+Alt+F9'},
                                         activated=self.onActivated, parent=self)  # type: GlobalHotkeys
        info = QLabel()  # type: QLabel
        lines = ['Backend: {}'.format(self.__m_hotkeys.getBackendName() or 'none')]  # type: list
        for name, seq in sorted(self.__m_hotkeys.getBindings().items()):
            lines.append('{}  =  {}   [{}]'.format(name, seq, {True: 'registered', False: 'FAILED'}.get(
                self.__m_hotkeys.getStatus(name), 'inactive')))
        if self.__m_hotkeys.getError():
            lines.append(self.__m_hotkeys.getError())
        info.setText('\n'.join(lines))
        self.__m_log = QListWidget()  # type: QListWidget
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addWidget(info)
        layout.addWidget(self.__m_log)
        self.setCentralWidget(wdg)

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def onActivated(self, name):
        """
        :param name: str | unicode | QString
        :return:
        """
        self.__m_log.insertItem(0, '{}  {}'.format(QDateTime.currentDateTime().toString('HH:mm:ss.zzz'), name))
