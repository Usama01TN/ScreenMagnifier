# coding=utf-8
"""
Screen Magnifier entry point.
Usage: ScreenMagnifier | python -m ScreenMagnifier | python ScreenMagnifier/main.py  [--tray] [--selftest] [--version]
    --tray      start hidden in the system tray, ready for gaming.
    --selftest  build the whole application headless, exercise upscaling / detection, print a report, exit
                (0 = ok); used by the release workflow on every built binary.
"""
from os.path import dirname
from os import environ
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:  # Version of the package (pip install), overridden by release builds below.
    from . import __version__ as VERSION
except:
    VERSION = 'dev'  # type: str
try:  # Written by .github/packaging/build.py in release builds: version and the bundled Qt binding.
    from ._buildinfo import QT_API as BUILD_QT_API, VERSION
except:
    try:
        from _buildinfo import QT_API as BUILD_QT_API, VERSION
    except:
        BUILD_QT_API = ''  # type: str
if BUILD_QT_API:
    environ.setdefault('QT_API', BUILD_QT_API)

try:
    from .support import qtBindingProblem
except:
    from support import qtBindingProblem


def mainWindowClass():
    """
    Imported on demand, after the Qt binding check (a missing binding gets a clear message, not a traceback).
    :return: type
    """
    try:
        from .mainwindow import MainWindow
    except:
        from mainwindow import MainWindow
    return MainWindow


def selfTest(app, window):
    """
    :param app: QApplication
    :param window: MainWindow
    :return: (int) Exit code: 0 when every mandatory part works.
    """
    from ManyQt.QtGui import QImage, QColor
    from ManyQt.QtCore import QSize
    from sys import argv, platform
    try:
        from .colordetector import ColorDetector
        from .facedetector import FaceDetector
        from .upscaler import Upscaler
    except:
        from colordetector import ColorDetector
        from facedetector import FaceDetector
        from upscaler import Upscaler
    img = QImage(64, 48, QImage.Format_RGB32)  # type: QImage
    img.fill(QColor('#3A7BD5'))
    up = Upscaler()  # type: Upscaler
    out = up.process(img, QSize(256, 192))  # type: QImage
    colors = ColorDetector(targetColors=['#3A7BD5']).analyze(img) if ColorDetector.isAvailable() else {}
    faces = FaceDetector()  # type: FaceDetector
    try:
        from .hotkeys import GlobalHotkeys
    except:
        from hotkeys import GlobalHotkeys
    try:
        from pynput import mouse  # noqa: F401  (screen color picker click capture on Windows / macOS)
        mouseHook = True  # type: bool
    except:
        mouseHook = False  # type: bool
    report = {'version': VERSION, 'qtApi': environ.get('QT_API', 'auto'), 'window': window is not None,
              'upscaled': [out.width(), out.height()], 'upscaleMethods': [n for m, n in up.availableMethods()],
              'colorDetection': ColorDetector.isAvailable(), 'colorRegions': len(colors.get('detections', [])),
              'faceBackend': faces.getActiveBackend() or 'unavailable',
              'hotkeyBackend': GlobalHotkeys.detectBackend() or 'none', 'mouseHook': mouseHook,
              'languages': [c for c, n in window.getLanguageManager().availableLanguages()],
              'language': window.getLanguageManager().getLanguage()}  # type: dict
    print('SELFTEST ' + u'{}'.format(report))
    if '--selftest-report' in argv:  # Windowed Windows builds have no stdout: also write the report to a file.
        with open(argv[argv.index('--selftest-report') + 1], 'w') as f:
            f.write('SELFTEST ' + u'{}'.format(report))
    ok = out.width() == 256 and (not ColorDetector.isAvailable() or report['colorRegions'] == 1)  # type: bool
    ok = ok and len(report['languages']) >= 5  # the translation catalogs are bundled
    if platform in ('win32', 'darwin'):  # Global input must be bundled (Linux headless CI has no X display for it).
        ok = ok and report['hotkeyBackend'] != 'none' and mouseHook
    return 0 if ok else 1

def run():
    """
    Application entry point: the ScreenMagnifier command, python -m ScreenMagnifier or python main.py.
    :return:
    """
    from sys import argv, exit, stderr, platform
    if '--version' in argv:
        print(VERSION)
        exit(0)
    problem = qtBindingProblem()  # type: str
    if problem:
        stderr.write(problem + '\n')
        exit(1)
    if platform == 'win32':  # Own taskbar entry and icon (not python.exe's) when started from Python / pip.
        try:
            from ctypes import windll
            windll.shell32.SetCurrentProcessExplicitAppUserModelID(u'UsamaTN.ScreenMagnifier')
        except:
            pass
    if '--wait-pid' in argv:  # Restarted by the previous instance (e.g. new language): let it release everything.
        try:
            from .support import waitForExit
        except:
            from support import waitForExit
        waitForExit(int(argv[argv.index('--wait-pid') + 1]))
    from ManyQt.QtWidgets import QApplication
    from ManyQt.QtCore import Qt
    MainWindow = mainWindowClass()
    try:
        from .translator import LanguageManager
    except:
        from translator import LanguageManager
    from ManyQt.QtCore import QSettings
    from os.path import dirname, join

    for attr in ('AA_EnableHighDpiScaling', 'AA_UseHighDpiPixmaps'):  # Qt5 only, always on in Qt6.
        if hasattr(Qt, attr):
            QApplication.setAttribute(getattr(Qt, attr), True)
    if '--selftest' in argv:
        environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    a = QApplication(argv)  # type: QApplication
    a.setApplicationName('Screen Magnifier')
    language = u'{}'.format(QSettings('ScreenMagnifier', 'General').value('language', 'auto'))  # type: str
    if '--lang' in argv:  # one-time override: python -m ScreenMagnifier --lang fr
        language = argv[argv.index('--lang') + 1]
    languages = LanguageManager(folder=join(dirname(__file__), 'translations'), language=language,
                                parent=a)  # type: LanguageManager  # before any window: every tr() is translated
    w = MainWindow(languageManager=languages)  # type: MainWindow
    if '--selftest' in argv:
        code = selfTest(a, w)  # type: int
        w.quitApp()
        exit(code)
    if '--tray' in argv and w.hasTray():
        pass  # Start hidden in the tray: only the global hotkeys / advanced zoom are active.
    else:
        w.show()
    exit(a.exec_())


if __name__ == '__main__':
    run()
