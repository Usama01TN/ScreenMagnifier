# coding=utf-8
"""
regionselector package.
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .regionselector import RegionSelector
except:
    from regionselector import RegionSelector

__all__ = ['RegionSelector']  # type: list[str]
