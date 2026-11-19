# -*- coding: utf-8 -*-
"""
python -m ScreenMagnifier [--tray] [--selftest] [--version]
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .main import run
except:
    from main import run

if __name__ == '__main__':
    run()
