# coding=utf-8
"""
mousecatcher package.
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .mousecatcher import GlobalMouseCatcher
except:
    from mousecatcher import GlobalMouseCatcher

__all__ = ['GlobalMouseCatcher']  # type: list[str]
