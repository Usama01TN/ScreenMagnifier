# coding=utf-8
"""
shortcuteditor package.
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .shortcuteditor import ShortcutEditorWidget
except:
    from shortcuteditor import ShortcutEditorWidget

__all__ = ['ShortcutEditorWidget']  # type: list[str]
