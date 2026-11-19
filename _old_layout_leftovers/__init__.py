# coding=utf-8
"""
Screen Magnifier root package: aggregates all components and the application window.
"""
from os.path import dirname
from sys import path

if dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .advancedoverlay import AdvancedOverlayController
    from .advancedpanel import AdvancedOverlayPanel
    from .magnifierview import MagnifierViewWidget
    from .regionselector import RegionSelector
    from .screengrabber import ScreenGrabber
    from .controlpanel import ControlPanel
    from .zoomoverlay import ZoomOverlay
    from .mainwindow import MainWindow
    from .hotkeys import GlobalHotkeys
    from .upscaler import Upscaler
except:
    from advancedoverlay import AdvancedOverlayController
    from advancedpanel import AdvancedOverlayPanel
    from magnifierview import MagnifierViewWidget
    from regionselector import RegionSelector
    from screengrabber import ScreenGrabber
    from controlpanel import ControlPanel
    from zoomoverlay import ZoomOverlay
    from mainwindow import MainWindow
    from hotkeys import GlobalHotkeys
    from upscaler import Upscaler

__all__ = ['Upscaler', 'ScreenGrabber', 'RegionSelector', 'MagnifierViewWidget', 'GlobalHotkeys', 'ZoomOverlay',
           'AdvancedOverlayController', 'AdvancedOverlayPanel', 'ControlPanel', 'MainWindow']  # type: list[str]
