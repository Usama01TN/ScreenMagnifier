# coding=utf-8
"""
translator package.
"""
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .translator import LanguageManager, CatalogTranslator, LANGUAGES
except:
    from translator import LanguageManager, CatalogTranslator, LANGUAGES

__all__ = ['LanguageManager', 'CatalogTranslator', 'LANGUAGES']  # type: list[str]
