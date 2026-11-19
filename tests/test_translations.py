# coding=utf-8
"""
Tests of the interface languages (ScreenMagnifier/translations/<code>.json), on the installed package:
    pytest tests
"""
from ScreenMagnifier.support import qtBindingProblem
import ScreenMagnifier
from os.path import dirname, join
from pytest import fixture, mark
from os import environ, listdir
from re import findall
from json import load

FOLDER = join(dirname(ScreenMagnifier.__file__), 'translations')
LANGUAGES = sorted(f[:-5] for f in listdir(FOLDER) if f.endswith('.json'))  # Every shipped catalog.
EXPECTED = {'fr', 'ar', 'es', 'de', 'it', 'pt_BR', 'ru', 'tr', 'ja', 'ko', 'zh_CN'}
needsQt = mark.skipif(bool(qtBindingProblem()), reason='No Qt binding installed')


def catalog(code):
    with open(join(FOLDER, code + '.json'), encoding='utf-8') as f:
        return load(f)


def test_every_language_is_shipped():
    assert EXPECTED <= set(LANGUAGES), EXPECTED - set(LANGUAGES)


@mark.parametrize('code', LANGUAGES)
def test_catalog_is_complete_and_keeps_placeholders(code):
    data = catalog(code)
    assert data['language'] == code
    for source, text in data['strings'].items():
        assert text, 'untranslated: {!r}'.format(source)
        assert findall(r'\{[^{}]*\}', source) == findall(r'\{[^{}]*\}', text), (source, text)


@fixture(scope='module')
def app():
    environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from ManyQt.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@needsQt
@mark.parametrize('code', LANGUAGES)
def test_language_translates_through_qt(app, code):
    from ScreenMagnifier.translator import LanguageManager
    lm = LanguageManager(folder=FOLDER, language=code)  # type: LanguageManager
    sample = u'Copy all formats'
    assert app.translate('AnyContext', sample) == catalog(code)['strings'][sample]
    assert app.translate('AnyContext', u'\u2212') == u'\u2212'  # Unknown text keeps its source (never blank).
    assert lm.isRightToLeft() == (code == 'ar')
    lm.setLanguage('en')
    assert app.translate('AnyContext', sample) == sample


@needsQt
def test_automatic_language_is_an_available_one(app):
    from ScreenMagnifier.translator import LanguageManager
    lm = LanguageManager(folder=FOLDER)  # type: LanguageManager
    assert lm.resolve('auto') in dict(lm.availableLanguages())
    assert [c for c, n in lm.availableLanguages()][:1] == ['en']
    assert set(LANGUAGES) <= set(dict(lm.availableLanguages()))


@needsQt
def test_aliases_and_regional_fallbacks(app):
    from ScreenMagnifier.translator import LanguageManager
    lm = LanguageManager(folder=FOLDER)  # type: LanguageManager
    for name, code in (('jp', 'ja'), ('cn', 'zh_CN'), ('zh_TW', 'zh_CN'), ('zh-CN', 'zh_CN'), ('pt', 'pt_BR'),
                       ('pt_PT', 'pt_BR'), ('kr', 'ko'), ('de_AT', 'de'), ('fr_CA', 'fr'), ('xx', 'en')):
        assert lm.resolve(name) == code, (name, lm.resolve(name), code)
