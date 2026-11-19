# coding=utf-8
"""
zoomoverlay package.
"""
from os.path import dirname
from sys import path

if dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .zoomoverlay import ZoomOverlay
except:
    from zoomoverlay import ZoomOverlay

__all__ = ['ZoomOverlay']  # type: list[str]
