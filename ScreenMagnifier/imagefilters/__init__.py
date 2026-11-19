# coding=utf-8
"""
imagefilters package: the Qt-free part (core.py) is always available; the Qt class ImageFilters is available when a
Qt binding is installed (None otherwise).
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .core import applyFilters, EFFECT_NAMES
except:
    from core import applyFilters, EFFECT_NAMES
try:
    from .imagefilters import ImageFilters
except:
    try:
        from imagefilters import ImageFilters
    except:  # No Qt binding: the Qt-free part only.
        ImageFilters = None

__all__ = ['applyFilters', 'EFFECT_NAMES', 'ImageFilters']  # type: list[str]
