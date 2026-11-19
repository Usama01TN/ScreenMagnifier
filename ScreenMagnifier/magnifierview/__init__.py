# coding=utf-8
"""
magnifierview package.
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .magnifierview import MagnifierViewWidget
except:
    from magnifierview import MagnifierViewWidget

__all__ = ['MagnifierViewWidget']  # type: list[str]
