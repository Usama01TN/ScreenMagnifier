# coding=utf-8
"""
screengrabber package.
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .screengrabber import ScreenGrabber, winWindowAt, winGrabWindowRect, isBlankImage
except:
    from screengrabber import ScreenGrabber, winWindowAt, winGrabWindowRect, isBlankImage

__all__ = ['ScreenGrabber', 'winWindowAt', 'winGrabWindowRect', 'isBlankImage']  # type: list[str]
