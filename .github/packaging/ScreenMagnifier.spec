# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec: one bundle, two programs sharing their libraries -
    ScreenMagnifier        (GUI application: launch_app.py -> ScreenMagnifier.main)
    ScreenMagnifierServer  (headless analysis server: launch_server.py -> ScreenMagnifier.server)
On macOS the bundle is ScreenMagnifier.app. Build with .github/packaging/build.py (it writes _buildinfo.py first).
Environment: SM_QT_API = pyqt6 (default) | pyqt5 | pyside6 | pyside2 - the only Qt binding bundled.
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from os.path import join, abspath
from os import environ
from sys import platform

ROOT = abspath(join(SPECPATH, '..', '..'))  # .github/packaging -> project
QT_API = environ.get('SM_QT_API', 'pyqt6').lower()
BINDING = {'pyqt6': 'PyQt6', 'pyqt5': 'PyQt5', 'pyside6': 'PySide6', 'pyside2': 'PySide2'}[QT_API]
QT_MODULES = ('QtCore', 'QtGui', 'QtWidgets', 'QtNetwork')  # the only Qt modules the application uses
# ManyQt imports the binding dynamically (by name), so PyInstaller cannot see it: declare it. Only ManyQt's own
# helpers and the used Qt wrappers (ManyQt.QtQuick etc. would drag QML / Quick into the bundle).
HIDDEN = collect_submodules('ManyQt', filter=lambda name: not name.split('.')[-1].startswith('Qt') or
                            name.split('.')[-1] in QT_MODULES) + ['{}.{}'.format(BINDING, m) for m in QT_MODULES]
# pynput picks its OS backend at run time (pynput.keyboard._win32 / _darwin / _xorg ...): bundle them all, or the
# global hotkeys and the screen color picker's click capture silently vanish from the release builds.
HIDDEN += collect_submodules('pynput')
DATAS = [(join(ROOT, 'ScreenMagnifier', 'upscaler', 'models'),
          join('ScreenMagnifier', 'upscaler', 'models')),  # FSRCNN networks
         (join(ROOT, 'ScreenMagnifier', 'resources'), join('ScreenMagnifier', 'resources')),  # icons
         (join(ROOT, 'ScreenMagnifier', 'translations'), join('ScreenMagnifier', 'translations'))]
ICON = join(ROOT, 'ScreenMagnifier', 'resources', 'icon.icns' if platform == 'darwin' else 'icon.ico')
try:
    import cv2  # noqa: F401
    DATAS += collect_data_files('cv2')  # Haar cascade used by the face detector
except:
    pass
EXCLUDES = [b for b in ('PyQt5', 'PyQt6', 'PySide2', 'PySide6') if b != BINDING] + ['tkinter'] + [
    '{}.{}'.format(BINDING, m) for m in ('QtQuick', 'QtQml', 'QtQuickWidgets', 'QtWebEngineCore', 'QtWebEngineWidgets',
                                         'QtWebEngineQuick', 'QtWebChannel', 'QtWebSockets', 'QtMultimedia',
                                         'QtMultimediaWidgets', 'QtPdf', 'QtPdfWidgets', 'Qt3DCore', 'QtCharts',
                                         'QtDataVisualization', 'QtBluetooth', 'QtSensors', 'QtPositioning', 'QtDesigner',
                                         'QtHelp', 'QtSql', 'QtTest', 'QtSvg', 'QtPrintSupport', 'QtOpenGLWidgets')]


def analysis(script):
    """
    :param script: str
    :return: Analysis
    """
    return Analysis([join(SPECPATH, script)], pathex=[ROOT], datas=DATAS, hiddenimports=HIDDEN, excludes=EXCLUDES)


app = analysis('launch_app.py')  # imports ScreenMagnifier.main: the package, like a pip install
srv = analysis('launch_server.py')
appExe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True, name='ScreenMagnifier', console=False,
             upx=False, icon=ICON)
srvExe = EXE(PYZ(srv.pure), srv.scripts, [], exclude_binaries=True, name='ScreenMagnifierServer', console=True,
             upx=False, icon=ICON)
coll = COLLECT(appExe, app.binaries, app.datas, srvExe, srv.binaries, srv.datas, upx=False, name='ScreenMagnifier')
if platform == 'darwin':
    app = BUNDLE(coll, name='ScreenMagnifier.app', bundle_identifier='io.github.screenmagnifier', icon=ICON,
                 info_plist={'CFBundleShortVersionString': environ.get('SM_VERSION', '0.0.0'),
                             'NSHighResolutionCapable': True})
