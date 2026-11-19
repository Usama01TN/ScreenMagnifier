# coding=utf-8
"""
facedetector package: the Qt-free part (core.py) is always available - the headless server uses it, also where Qt is
not installed (e.g. Android); the Qt classes are available when a Qt binding is installed (None otherwise).
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .core import FaceEngine
except:
    from core import FaceEngine
try:
    from .facedetector import FaceDetector
except:
    try:
        from facedetector import FaceDetector
    except:  # No Qt binding: the Qt-free part only.
        FaceDetector = None

__all__ = ['FaceEngine', 'FaceDetector']  # type: list[str]
