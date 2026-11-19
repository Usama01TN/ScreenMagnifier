# coding=utf-8
"""
upscaler package.
"""
from os.path import dirname
from sys import path

if dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .upscaler import Upscaler
except:
    from upscaler import Upscaler

__all__ = ['Upscaler']  # type: list[str]
