# coding=utf-8
"""
Demo window for ShortcutEditorWidget: window shortcuts with an alternate key, global hotkeys, conflicts.
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QLabel, QPushButton, QScrollArea
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .shortcuteditor import ShortcutEditorWidget
except:
    from shortcuteditor import ShortcutEditorWidget

DEMO_ACTIONS = [
    {'name': 'open', 'label': 'Open a file', 'group': 'File', 'scope': 'window', 'defaults': ['Ctrl+O', '']},
    {'name': 'save', 'label': 'Save', 'group': 'File', 'scope': 'window', 'defaults': ['Ctrl+S', 'F2']},
    {'name': 'zoomIn', 'label': 'Zoom in', 'group': 'View', 'scope': 'window', 'defaults': ['+', '=']},
    {'name': 'show', 'label': 'Show / hide everywhere', 'group': 'Global', 'scope': 'global',
     'defaults': ['Ctrl+Alt+Z']},
]  # type: list


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
        self.setWindowTitle(self.tr(u'ShortcutEditor demo'))
        self.resize(560, 460)
        self.__m_info = QLabel(self.tr(u'Record a shortcut - try Ctrl+S on "Open" to see a conflict.'))
        self.__m_editor = ShortcutEditorWidget(
            actions=DEMO_ACTIONS, shortcutChanged=lambda n, s, i, k: self.__m_info.setText(
                u'{} ({}) slot {} -> {}'.format(n, s, i, k or 'none')))  # type: ShortcutEditorWidget
        reset = QPushButton(self.tr(u'Reset all'))  # type: QPushButton
        reset.clicked.connect(self.__m_editor.resetAll)
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addWidget(self.__m_editor)
        layout.addWidget(reset)
        layout.addWidget(self.__m_info)
        layout.addStretch(1)
        scroll = QScrollArea()  # type: QScrollArea
        scroll.setWidgetResizable(True)
        scroll.setWidget(wdg)
        self.setCentralWidget(scroll)
