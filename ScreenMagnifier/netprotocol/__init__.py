# coding=utf-8
"""
netprotocol package: the Qt-free part (wire.py) is always available - the headless server uses it, also where Qt is
not installed (e.g. Android); the Qt classes are available when a Qt binding is installed (None otherwise).
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .wire import packMessage, MessageParser, DEFAULT_PORT, encodeArray, decodeArray, availableFormats
except:
    from wire import packMessage, MessageParser, DEFAULT_PORT, encodeArray, decodeArray, availableFormats
try:
    from .netprotocol import FrameChannel, FrameServer, encodeImage, decodeImage
except:
    try:
        from netprotocol import FrameChannel, FrameServer, encodeImage, decodeImage
    except:  # No Qt binding: the Qt-free part only.
        FrameChannel = FrameServer = encodeImage = decodeImage = None

__all__ = ['packMessage', 'MessageParser', 'DEFAULT_PORT', 'encodeArray', 'decodeArray', 'availableFormats',
           'FrameChannel', 'FrameServer', 'encodeImage', 'decodeImage']  # type: list[str]
