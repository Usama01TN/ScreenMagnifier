# coding=utf-8
"""
hotkeys package.
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .hotkeys import GlobalHotkeys
except:
    from hotkeys import GlobalHotkeys

__all__ = ['GlobalHotkeys']  # type: list[str]
