# coding=utf-8
"""
colorswatches package.
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .colorswatches import ColorSwatchesWidget
except:
    from colorswatches import ColorSwatchesWidget

__all__ = ['ColorSwatchesWidget']  # type: list[str]
