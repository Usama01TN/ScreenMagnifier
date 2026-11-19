# coding=utf-8
"""
Windows self-test for the in-game scope: run `python wincheck.py` and read (or send) the report.
Checks:
    1. Hiding a plain window from screen capture.
    2. Hiding a per-pixel-alpha window (WA_TranslucentBackground, what the lens used before).
    3. Hiding the real ZoomOverlay lens.
    4. Direct window capture (PrintWindow) of the window under the screen center.
"""
from sys import path, platform
from os.path import dirname

if dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .zoomoverlay.zoomoverlay import winSetCaptureExcluded, ZoomOverlay
    from .screengrabber import winWindowAt, winGrabWindowRect, isBlankImage
except:
    from zoomoverlay.zoomoverlay import winSetCaptureExcluded, ZoomOverlay
    from screengrabber import winWindowAt, winGrabWindowRect, isBlankImage


def runChecks():
    """
    :return: (list[str | unicode | QString]) Report lines.
    """
    from ManyQt.QtGui import QGuiApplication
    from ManyQt.QtWidgets import QWidget
    from ManyQt.QtCore import Qt, QRect
    from sys import getwindowsversion
    lines = ['Platform: {}  Windows build: {}'.format(
        platform, getwindowsversion().build if platform == 'win32' else '-')]  # type: list[str]
    plain = QWidget()  # type: QWidget
    plain.resize(200, 120)
    plain.show()
    lines.append(u'1. plain window        : {}'.format(winSetCaptureExcluded(plain, forceLayered=False)))
    translucent = QWidget()  # type: QWidget
    translucent.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
    translucent.setAttribute(Qt.WA_TranslucentBackground, True)
    translucent.resize(200, 120)
    translucent.show()
    lines.append(u'2. per-pixel alpha     : {}'.format(winSetCaptureExcluded(translucent, forceLayered=False)))
    lens = ZoomOverlay()  # type: ZoomOverlay
    lens.show()
    lines.append(u'3. ZoomOverlay lens    : {}'.format(winSetCaptureExcluded(lens)))
    centre = QGuiApplication.primaryScreen().geometry().center()
    hwnd = winWindowAt(centre)
    if hwnd:
        img, dpr = winGrabWindowRect(hwnd, QRect(centre.x() - 50, centre.y() - 50, 100, 100))
        lines.append(u'4. window capture      : hwnd=0x{:x} image={}x{} blank={}'.format(
            hwnd, img.width(), img.height(), isBlankImage(img)))
    else:
        lines.append(u'4. window capture      : no application window under the screen centre')
    for w in (plain, translucent, lens):
        w.close()
    return lines


if __name__ == '__main__':
    from ManyQt.QtWidgets import QApplication
    from sys import argv

    a = QApplication(argv)  # type: QApplication
    print('\n'.join(runChecks()))
