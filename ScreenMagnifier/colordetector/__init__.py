# coding=utf-8
"""
colordetector package: the Qt-free part (core.py) is always available - the headless server uses it, also where Qt is
not installed (e.g. Android); the Qt classes are available when a Qt binding is installed (None otherwise).
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .core import ColorAnalyzer, CSS_COLORS
except:
    from core import ColorAnalyzer, CSS_COLORS
try:
    from .colordetector import ColorDetector, colorInfo, nearestColorName, contrastRatio, wcagRating, maskToOverlay, \
        complementary, formatColor, sampleColor, refinePick, COLOR_FORMATS
except:
    try:
        from colordetector import ColorDetector, colorInfo, nearestColorName, contrastRatio, wcagRating, \
            maskToOverlay, complementary, formatColor, sampleColor, refinePick, COLOR_FORMATS
    except:  # No Qt binding: the Qt-free part only.
        ColorDetector = colorInfo = nearestColorName = contrastRatio = wcagRating = maskToOverlay = complementary = formatColor = sampleColor = refinePick = COLOR_FORMATS = None

__all__ = ['ColorAnalyzer', 'CSS_COLORS', 'ColorDetector', 'colorInfo', 'nearestColorName', 'contrastRatio',
           'wcagRating', 'maskToOverlay', 'complementary', 'formatColor', 'sampleColor', 'refinePick',
           'COLOR_FORMATS']  # type: list[str]
