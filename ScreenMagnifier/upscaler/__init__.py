# coding=utf-8
"""
upscaler package: the Qt-free part (core.py) is always available - the headless server uses it, also where Qt is
not installed (e.g. Android); the Qt classes are available when a Qt binding is installed (None otherwise).
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .core import UpscaleEngine, METHOD_NAMES
except:
    from core import UpscaleEngine, METHOD_NAMES
try:
    from .upscaler import Upscaler
except:
    try:
        from upscaler import Upscaler
    except:  # No Qt binding: the Qt-free part only.
        Upscaler = None

__all__ = ['UpscaleEngine', 'METHOD_NAMES', 'Upscaler']  # type: list[str]
