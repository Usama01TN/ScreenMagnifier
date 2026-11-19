# coding=utf-8
"""
Capture docs/screenshot.png from the REAL running application (developer tool, Linux: Xvfb + Openbox + xdotool):
    xvfb-run -a -s "-screen 0 1920x1080x24" sh -c "openbox & sleep 1; python docs/make_screenshot.py"
The scene behind it is original pixel art drawn here (no third-party content). Shown: the magnifier (Pixel art
upscaler, color zones), the zoomer pinned on a zone with its live color code, and the Colors tab following it.
"""
from os.path import abspath, dirname, join
from subprocess import call
from sys import path, argv
from os import environ

HERE = dirname(abspath(__file__))  # type: str
environ['XDG_CONFIG_HOME'] = '/tmp/screenshot-config'  # A clean configuration, never the user's.
path.insert(0, join(HERE, '..'))
from ManyQt.QtGui import QImage, QPainter, QColor, QPixmap, QPolygon, QGuiApplication
from ManyQt.QtCore import Qt, QRect, QPoint, QTimer, QEventLoop, QSettings
from ManyQt.QtWidgets import QApplication, QLabel, QDockWidget

SCALE = 8  # type: int  # One scene pixel = 8 x 8 screen pixels.


def scene():
    """
    :return: (QImage) 240 x 135 pixel-art sunset landscape (1920 x 1080 at 8 x 8).
    """
    img = QImage(240, 135, QImage.Format_RGB32)  # type: QImage
    p = QPainter(img)  # type: QPainter
    sky = ['#1B1F4B', '#26286A', '#3A2E7E', '#5A358A', '#843D8C', '#B14C82', '#D9636F', '#EE8460', '#F7A85C',
           '#FBCB6B']
    for i, c in enumerate(sky):
        p.fillRect(QRect(0, i * 7, 240, 7), QColor(c))
    for x, y in ((12, 4), (40, 9), (71, 3), (150, 6), (183, 12), (122, 2), (98, 11), (214, 5), (231, 10)):
        p.fillRect(QRect(x, y, 1, 1), QColor('#FFF4D6'))
    p.setPen(Qt.NoPen)
    for rr, c in ((14, '#F7B65E'), (11, '#FBCB6B'), (8, '#FFE08A'), (6, '#FFF0B8')):
        p.setBrush(QColor(c))
        p.drawEllipse(QPoint(24, 62), rr, rr)  # low sun, left
    for pts, c in (([(0, 78), (20, 58), (34, 66), (58, 44), (80, 64), (100, 52), (126, 70), (0, 82)], '#3B2F6E'),
                   ([(56, 82), (92, 58), (114, 68), (150, 46), (176, 62), (204, 50), (240, 60), (240, 84), (56, 84)],
                    '#4A3A80'),
                   ([(0, 86), (40, 74), (80, 82), (120, 72), (160, 80), (200, 72), (240, 80), (240, 92), (0, 92)],
                    '#2D6B55')):
        p.setBrush(QColor(c))
        p.drawPolygon(QPolygon([QPoint(x, y) for x, y in pts]))
    p.fillRect(QRect(0, 90, 240, 45), QColor('#2E8B57'))
    for y, c in ((102, '#2A5F9E'), (105, '#3473B5'), (108, '#2A5F9E'), (111, '#23508A')):
        p.fillRect(QRect(0, y, 36, 3), QColor(c))  # pond
    for x in (6, 16, 26):
        p.fillRect(QRect(x, 105, 5, 1), QColor('#FBCB6B'))
    for x, h in ((7, 22), (17, 17), (88, 21), (97, 26)):
        p.setBrush(QColor('#1F5A3D'))
        p.drawPolygon(QPolygon([QPoint(x, 94 - h), QPoint(x - 6, 94), QPoint(x + 6, 94)]))
        p.fillRect(QRect(x - 1, 94, 2, 3), QColor('#5B3A29'))
    p.fillRect(QRect(44, 84, 30, 18), QColor('#F2E6C9'))  # cottage
    p.setBrush(QColor('#D9342B'))  # red roof (detected zone)
    p.drawPolygon(QPolygon([QPoint(40, 85), QPoint(59, 70), QPoint(78, 85)]))
    p.fillRect(QRect(66, 72, 4, 8), QColor('#7A4A35'))  # chimney
    p.fillRect(QRect(55, 91, 6, 11), QColor('#7A4A35'))  # door
    for x in (47, 65):
        p.fillRect(QRect(x, 88, 5, 5), QColor('#FFD45C'))  # lit windows
    p.fillRect(QRect(36, 102, 48, 3), QColor('#C9A66B'))  # path
    p.fillRect(QRect(44, 117, 34, 4), QColor('#11131F'))  # game-like HUD: health bar
    p.fillRect(QRect(45, 118, 24, 2), QColor('#E01020'))
    p.end()
    return img


def wait(ms):
    """
    :param ms: int
    :return:
    """
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    (getattr(loop, 'exec_', None) or getattr(loop, 'exec'))()


def main():
    """
    :return:
    """
    det = QSettings('ScreenMagnifier', 'Detection')
    for key, value in (('colorEnabled', True), ('targets', '#D9342B'), ('mask', False), ('rate', 10)):
        det.setValue(key, value)
    QSettings('ScreenMagnifier', 'Features').setValue('zonesInZoomer', True)
    zoomer = QSettings('ScreenMagnifier', 'GameOverlay')
    for key, value in (('colorReadout', True), ('placement', 1), ('zoom', 3.0), ('lensSize', 330)):
        zoomer.setValue(key, value)
    QSettings('ScreenMagnifier', 'ColorPicker').setValue('pickSource', 'original')
    app = QApplication(argv)  # type: QApplication
    from ScreenMagnifier.mainwindow import MainWindow
    from ScreenMagnifier.upscaler import Upscaler
    background = QLabel()
    background.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint)
    background.setPixmap(QPixmap.fromImage(scene().scaled(1920, 1080, Qt.IgnoreAspectRatio, Qt.FastTransformation)))
    background.setGeometry(0, 0, 1920, 1080)
    background.show()
    w = MainWindow()
    w.setGeometry(736, 36, 1150, 1010)  # right of the cottage: never over what it magnifies
    w.show()
    dock = w.findChild(QDockWidget, 'colorDock')
    dock.raise_()
    wait(300)
    try:
        w.resizeDocks([dock], [500], Qt.Horizontal)
    except:
        dock.resize(500, dock.height())
    wait(1200)
    w._MainWindow__m_upscaler.setMethod(Upscaler.PixelArt)
    w.onRegionSelected(QRect(37 * SCALE, 64 * SCALE, 34 * SCALE, 46 * SCALE))  # The cottage.
    xd = lambda *a: call(['xdotool'] + list(a))
    roof = (64 * SCALE + 4, 81 * SCALE + 4)  # roof edge: roof, chimney, wall and a window in the zoomer.
    xd('mousemove', u'{}'.format(roof[0]), u'{}'.format(roof[1]))
    wait(300)
    xd('key', 'ctrl+alt+z')  # Show the zoomer.
    wait(900)
    xd('key', 'ctrl+alt+x')  # Pin it on the roof.
    wait(400)
    xd('mousemove', '300', '1060')  # Away from the magnifier.
    wait(3500)
    out = join(HERE, 'screenshot.png')
    QGuiApplication.primaryScreen().grabWindow(0).save(out, 'PNG')
    panel = w.findChild(QDockWidget, 'colorDock').widget()
    print(u'Saved', out, '| live color:', panel.getLiveSource(), panel.getCodeText(), panel.getLiveZone())
    xd('key', 'ctrl+alt+z')
    w.quitApp()


if __name__ == '__main__':
    main()
