# coding=utf-8
"""
PyInstaller entry of the release builds: the headless ScreenMagnifierServer, imported as a package.
"""
from ScreenMagnifier.server import run

if __name__ == '__main__':
    run()
