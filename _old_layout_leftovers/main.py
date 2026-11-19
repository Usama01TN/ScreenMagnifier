# coding=utf-8
"""
Screen Magnifier entry point.
Usage: python main.py [--tray]   (--tray starts hidden in the system tray, ready for gaming).
"""
from os.path import dirname
from sys import path

if dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .mainwindow import MainWindow
except:
    from mainwindow import MainWindow

if __name__ == '__main__':
    from ManyQt.QtWidgets import QApplication
    from ManyQt.QtCore import Qt
    from sys import argv, exit

    for attr in ('AA_EnableHighDpiScaling', 'AA_UseHighDpiPixmaps'):  # Qt5 only, always on in Qt6.
        if hasattr(Qt, attr):
            QApplication.setAttribute(getattr(Qt, attr), True)
    a = QApplication(argv)  # type: QApplication
    a.setApplicationName('Screen Magnifier')
    w = MainWindow()  # type: MainWindow
    if '--tray' in argv and w.hasTray():
        pass  # Start hidden in the tray: only the global hotkeys / advanced zoom are active.
    else:
        w.show()
    exit(a.exec_())
