# coding=utf-8
"""
Screen Magnifier root package: aggregates all components and the application window.
Components are imported on first use (PEP 562): `from ScreenMagnifier import Upscaler` works as before, and the
ScreenMagnifier command can explain a missing Qt binding instead of failing while importing the package.
"""
__version__ = '1.11.0'  # Single version source (pyproject.toml reads it; release tags override it).
STARTUP_ENVIRONMENT = dict(__import__('os').environ)  # type: dict  # before anything imports OpenCV (see
# support.cleanEnvironment: a restarted instance gets these values back, not OpenCV's Qt plugin folders).
from importlib import import_module
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

EXPORTS = {
    'LanguageManager': 'translator',
    'AdvancedOverlayController': 'advancedoverlay',
    'AdvancedOverlayPanel': 'advancedpanel',
    'MagnifierViewWidget': 'magnifierview',
    'RegionSelector': 'regionselector',
    'ScreenGrabber': 'screengrabber',
    'ControlPanel': 'controlpanel',
    'ZoomOverlay': 'zoomoverlay',
    'MainWindow': 'mainwindow',
    'GlobalHotkeys': 'hotkeys',
    'Upscaler': 'upscaler',
    'ColorDetector': 'colordetector',
    'FaceDetector': 'facedetector',
    'FrameChannel': 'netprotocol',
    'AnalysisController': 'analysiscontroller',
    'AnalysisServer': 'analysisserver',
    'RemoteClient': 'remoteclient',
    'DetectionPanel': 'detectionpanel',
    'ServerPanel': 'serverpanel',
    'ColorPickerPanel': 'colorpanel',
    'ColorSwatchesWidget': 'colorswatches',
    'GlobalMouseCatcher': 'mousecatcher',
    'ShortcutEditorWidget': 'shortcuteditor',
}  # type: dict  # exported name -> module of this package

__all__ = list(EXPORTS)  # type: list[str]


def __getattr__(name):
    """
    :param name: str | unicode | QString
    :return: any
    """
    module = EXPORTS.get(name)
    if module is None:
        raise AttributeError(u'Module {!r} has no attribute {!r}'.format(__name__, name))
    try:
        value = getattr(import_module('.' + module, __name__), name)
    except:
        if __package__:
            raise
        value = getattr(import_module(module), name)
    globals()[name] = value  # Cached: later accesses do not come back here.
    return value


def __dir__():
    """
    :return: list[str | unicode | QString]
    """
    return sorted(list(globals()) + __all__)
