# -*- coding: utf-8 -*-
"""
CatalogTranslator, LanguageManager: application languages from JSON catalogs.
- Works with every Qt binding and needs no Qt tool (no lupdate / lrelease): a QTranslator subclass answers the
  application's tr() calls from a dictionary, so the existing self.tr(u'...') calls are translated unchanged.
- Catalog <folder>/<code>.json: {"language": "fr", "name": "Fran\u00e7ais", "direction": "ltr" | "rtl",
  "strings": {"English source text": "translation", ...}}. Empty or missing translations fall back to English.
- Lookup by source text: PyQt and PySide compute different tr() contexts for subclasses; the text is the same.
- LanguageManager: available languages, 'auto' (system language), installs the catalog and Qt's own translations
  (qtbase_<code>.qm: standard dialogs), sets the layout direction (right-to-left for Arabic) and the default locale.
"""
from ManyQt.QtCore import QObject, QTranslator, QLocale, QLibraryInfo, Qt, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtWidgets import QApplication
from os.path import isdir, isfile, join, splitext
from os import listdir
from io import open as iopen
import json

LANGUAGES = {  # code -> (English name, native name, right-to-left)
    'en': ('English', 'English', False),
    'fr': ('French', 'Fran\u00e7ais', False),
    'ar': ('Arabic', '\u0627\u0644\u0639\u0631\u0628\u064a\u0629', True),
    'es': ('Spanish', 'Espa\u00f1ol', False),
    'de': ('German', 'Deutsch', False),
    'it': ('Italian', 'Italiano', False),
    'pt_BR': ('Portuguese (Brazil)', 'Portugu\u00eas (Brasil)', False),
    'ru': ('Russian', '\u0420\u0443\u0441\u0441\u043a\u0438\u0439', False),
    'tr': ('Turkish', 'T\u00fcrk\u00e7e', False),
    'ja': ('Japanese', '\u65e5\u672c\u8a9e', False),
    'ko': ('Korean', '\ud55c\uad6d\uc5b4', False),
    'zh_CN': ('Chinese (Simplified)', '\u7b80\u4f53\u4e2d\u6587', False),
}  # type: dict
ALIASES = {'jp': 'ja', 'cn': 'zh_CN', 'zh': 'zh_CN', 'pt': 'pt_BR', 'br': 'pt_BR', 'kr': 'ko'}  # type: dict  # common names


def loadCatalog(path):
    """
    :param path: (str | unicode | QString) JSON catalog.
    :return: (dict) {'language', 'name', 'direction', 'strings'} - strings without empty translations.
    """
    with iopen(path, encoding='utf-8') as f:
        data = json.load(f)
    data['strings'] = {k: v for k, v in (data.get('strings') or {}).items() if hasattr(v, 'encode') and v}
    return data


def qtTranslationsPath():
    """
    :return: (str | unicode | QString) Folder of Qt's own .qm translations ('' if unknown).
    """
    try:
        if hasattr(QLibraryInfo, 'path'):  # Qt 6
            return u'{}'.format(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
        return u'{}'.format(QLibraryInfo.location(QLibraryInfo.TranslationsPath))  # Qt 5
    except Exception:
        return ''


class CatalogTranslator(QTranslator):
    """
    CatalogTranslator class: a QTranslator answering from a {source: translation} dictionary.
    """

    def __init__(self, *args, **kwargs):
        """
        :param strings: (dict) {English source: translation}.
        :param args: any
        :param kwargs: any
        """
        strings = kwargs.pop('strings', {})  # type: dict
        super(CatalogTranslator, self).__init__(*args, **kwargs)
        self.__m_strings = dict(strings or {})  # type: dict

    def translate(self, context, sourceText, disambiguation=None, n=-1):
        """
        :param context: str | unicode | QString
        :param sourceText: str | unicode | QString
        :param disambiguation: str | None
        :param n: int
        :return: (str | None) Translation; None when unknown - a NULL string, so Qt keeps the source text (an empty
            string would count as a translation and blank the text, e.g. toolbar buttons labelled '-' or '+').
        """
        return self.__m_strings.get(sourceText) if sourceText else None

    def isEmpty(self):
        """
        :return: bool
        """
        return not self.__m_strings

    def getStrings(self):
        """
        :return: dict
        """
        return dict(self.__m_strings)

    @pyqtSlot(object)
    def setStrings(self, strings):
        """
        :param strings: dict
        :return:
        """
        self.__m_strings = dict(strings or {})  # type: dict

    # ---------- Properties ----------
    strings = pyqtProperty(object, fget=getStrings, fset=setStrings)  # type: pyqtProperty


class LanguageManager(QObject):
    """
    LanguageManager class.
    """
    languageChanged = pyqtSignal('QString')  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param folder: (str | unicode | QString) Folder of the <code>.json catalogs.
        :param language: (str | None) Language to apply now: a code, 'auto' (system language) or None (none yet).
        :param languageChanged: callable | None
        :param args: any
        :param kwargs: any
        """
        folder = kwargs.pop('folder', '')  # type: str
        language = kwargs.pop('language', None)  # type: str | None
        languageChanged = kwargs.pop('languageChanged', None)  # type: callable | None
        super(LanguageManager, self).__init__(*args, **kwargs)
        if callable(languageChanged):
            self.languageChanged.connect(languageChanged)
        self.__m_folder = u'{}'.format(folder)  # type: str
        self.__m_language = 'en'  # type: str
        self.__m_requested = 'en'  # type: str
        self.__m_installed = []  # type: list  # translators installed by this manager
        if language is not None:
            self.setLanguage(language)

    # ---------- Helpers ----------
    def _catalogPath(self, code):
        """
        :param code: str | unicode | QString
        :return: str | unicode | QString
        """
        return join(self.__m_folder, '{}.json'.format(code))

    def catalog(self, code):
        """
        :param code: str | unicode | QString
        :return: (dict) Catalog of a language ({} for English or unknown).
        """
        path = self._catalogPath(code)  # type: str
        return loadCatalog(path) if code != 'en' and isfile(path) else {}

    # ---------- Public API ----------
    def availableLanguages(self):
        """
        :return: (list[tuple[str, str]]) (code, native name), English first.
        """
        codes = ['en']  # type: list
        if isdir(self.__m_folder):
            codes += sorted(splitext(f)[0] for f in listdir(self.__m_folder) if f.endswith('.json'))
        return [(c, self.nativeName(c)) for c in codes]

    def nativeName(self, code):
        """
        :param code: str | unicode | QString
        :return: str | unicode | QString
        """
        if code in LANGUAGES:
            return LANGUAGES[code][1]
        return u'{}'.format(self.catalog(code).get('name', code))

    def match(self, name):
        """
        Best available language for a locale name: exact ('pt_BR'), alias ('jp', 'cn'), language ('de' for 'de_AT'),
        then a regional variant of the language ('pt_BR' for 'pt_PT', 'zh_CN' for 'zh_TW').
        :param name: str | unicode | QString
        :return: (str | unicode | QString) Code, '' if none.
        """
        available = [c for c, n in self.availableLanguages()]  # type: list
        name = name.replace('-', '_')  # type: str
        lang = name.split('_')[0].lower()  # type: str
        region = name.split('_')[1].upper() if '_' in name else ''  # type: str
        for candidate in ('{}_{}'.format(lang, region) if region else '', ALIASES.get(name.lower(), ''), lang,
                          ALIASES.get(lang, '')):
            if candidate and candidate in available:
                return candidate
        return next((c for c in available if c.split('_')[0] == lang), '')

    def systemLanguage(self):
        """
        :return: (str | unicode | QString) The system language if a catalog matches it, else 'en'.
        """
        return self.match(u'{}'.format(QLocale.system().name())) or 'en'

    def resolve(self, code):
        """
        :param code: (str | unicode | QString) Code or 'auto'.
        :return: (str | unicode | QString) An available language code.
        """
        if u'{}'.format(code or 'auto').lower() == 'auto':
            return self.systemLanguage()
        return self.match(code) or 'en'

    def isRightToLeft(self, code=None):
        """
        :param code: (str | None) None = current language.
        :return: bool
        """
        code = self.__m_language if code is None else self.resolve(code)  # type: str
        if code in LANGUAGES:
            return LANGUAGES[code][2]
        return self.catalog(code).get('direction') == 'rtl'

    def translateIn(self, code, text):
        """
        Translate one text into a given language (e.g. to ask "restart?" in the language just chosen).
        :param code: str | unicode | QString
        :param text: str | unicode | QString
        :return: str | unicode | QString
        """
        return self.catalog(self.resolve(code)).get('strings', {}).get(text) or text

    def getLanguage(self):
        """
        :return: (str | unicode | QString) Current language code.
        """
        return self.__m_language

    def getRequestedLanguage(self):
        """
        :return: (str | unicode | QString) As requested: a code or 'auto'.
        """
        return self.__m_requested

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setLanguage(self, language):
        """
        Install a language for the whole application. Widgets built afterwards are translated; the application
        restarts its window to switch an open interface.
        :param language: (str | unicode | QString) Code ('fr', 'ar'...) or 'auto'.
        :return:
        """
        app = QApplication.instance()
        self.__m_requested = u'{}'.format(language or 'auto')  # type: str
        if self.__m_requested.lower() == 'auto':
            self.__m_requested = 'auto'  # type: str
        code = self.resolve(self.__m_requested)  # type: str
        for t in self.__m_installed:
            app.removeTranslator(t)
        self.__m_installed = []  # type: list
        if code != 'en':
            strings = self.catalog(code).get('strings', {})  # type: dict
            translator = CatalogTranslator(strings=strings, parent=self)  # type: CatalogTranslator
            app.installTranslator(translator)
            self.__m_installed.append(translator)
            qt = QTranslator(self)  # type: QTranslator  # Qt's own dialogs and buttons
            if qt.load(QLocale(code), 'qtbase', '_', qtTranslationsPath()):  # regional fallbacks by Qt
                app.installTranslator(qt)
                self.__m_installed.append(qt)
        app.setLayoutDirection(Qt.RightToLeft if self.isRightToLeft(code) else Qt.LeftToRight)
        QLocale.setDefault(QLocale(code))
        changed = code != self.__m_language  # type: bool
        self.__m_language = code  # type: str
        if changed:
            self.languageChanged.emit(code)

    def getFolder(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_folder

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setFolder(self, folder):
        """
        :param folder: str | unicode | QString
        :return:
        """
        self.__m_folder = u'{}'.format(folder)  # type: str

    # ---------- Properties ----------
    language = pyqtProperty('QString', fget=getLanguage, fset=setLanguage, notify=languageChanged)  # type: pyqtProperty
    folder = pyqtProperty('QString', fget=getFolder, fset=setFolder)  # type: pyqtProperty
