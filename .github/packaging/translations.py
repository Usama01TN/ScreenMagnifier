# coding=utf-8
"""
Translations of ScreenMagnifier (ScreenMagnifier/translations/<code>.json) - developer and CI tool:
    --list            print every translatable English text of the application
    --update          add the new texts to every catalog (empty: English until translated), drop obsolete ones
    --check           fail if a catalog misses a translation, changes a {} placeholder or an icon prefix
    --new CODE NAME   start a catalog for a new language (e.g. --new it Italiano), then --update and translate
Translatable texts: literal self.tr(u'...') arguments, the constant lists shown through self.tr(variable) (listed in
CONSTANTS) and the upscaler method names - not the component demo windows (<component>/main.py, mainwindow.py).
"""
from ast import walk, parse, Call, Attribute, AnnAssign, Constant, ClassDef, Assign, Name, Dict
from os.path import abspath, dirname, join, isfile
from json import dumps, load as jLoad
from collections import OrderedDict
from argparse import ArgumentParser
from io import open as iopen
from os import listdir
from re import findall
from glob import glob
from sys import exit

ROOT = abspath(join(dirname(__file__), '..', '..'))  # type: str
PACKAGE = join(ROOT, 'ScreenMagnifier')  # type: str
FOLDER = join(PACKAGE, 'translations')  # type: str
CONSTANTS = {  # file -> {constant: tuple indexes holding display texts (None: every string)}
    'shortcuts.py': {'SHORTCUTS': (2, 3)},
    'colordetector/colordetector.py': {'COLOR_FORMATS': (1,)},
    'colorpanel.py': {'PICK_SOURCES': (1,), 'SAMPLE_SIZES': (1,)},
    'advancedpanel.py': {'TARGET_NAMES': None, 'PLACEMENT_NAMES': None, 'SHAPE_NAMES': None},
    'detectionpanel.py': {'FACE_MODES': (1,), 'FACE_BACKENDS': (1,), 'MATCH_MODES': (1,), 'MASK_MODES': (1,),
                          'POINTER_FOLLOW': (1,), 'POINTER_CHOOSE': (1,), 'POINTER_MOTION': (1,),
                          'POINTER_HOLD': (1,)},
    'serverpanel.py': {'QUALITY': (1,)},
    'mainwindow.py': {'PLACEHOLDER': None, 'RESTART_QUESTION': None},
    'upscaler/core.py': {'METHOD_NAMES': None},  # the names live in the Qt-free core
    'imagefilters/core.py': {'EFFECT_NAMES': None},
}  # type: dict


def strings(node):
    """
    :param node: ast node
    :return: (list[str | unicode | QString]) Every string constant inside.
    """
    return [n.value for n in walk(node) if isinstance(n, Constant) and isinstance(n.value, str)]


def sources():
    """
    :return: (list[str | unicode | QString]) Every translatable text, in source order, without duplicates.
    """
    found = OrderedDict()  # type: OrderedDict
    for path in sorted(glob(join(PACKAGE, '**', '*.py'), recursive=True)):
        rel = path[len(PACKAGE) + 1:].replace('\\', '/')
        if '/' in rel and rel.split('/')[-1] in ('main.py', 'mainwindow.py'):
            continue  # component demo windows: for developers, not translated
        tree = parse(iopen(path, encoding='utf-8').read())
        for node in walk(tree):
            if isinstance(node, Call) and isinstance(node.func, Attribute) and node.func.attr == 'tr' and \
                    node.args and isinstance(node.args[0], Constant) and isinstance(node.args[0].value, str):
                found[node.args[0].value] = rel
            targets = CONSTANTS.get(rel, {})
            if targets and isinstance(node, (Assign, AnnAssign)):
                names = [t.id for t in (node.targets if isinstance(node, Assign) else [node.target])
                         if isinstance(t, Name)]
                for name in names:
                    if name in targets:
                        value = node.value
                        if isinstance(value, Dict):  # METHOD_NAMES = {Method.X: 'text'}: the values
                            texts = [s for v in value.values for s in strings(v)]
                        elif targets[name] is None:
                            texts = strings(value)
                        else:
                            texts = [t.value for e in value.elts for i, t in enumerate(e.elts)
                                     if i in targets[name] and isinstance(t, Constant) and isinstance(t.value, str)]
                        for t in texts:
                            found[t] = rel
            if isinstance(node, ClassDef):  # class-level METHOD_NAMES
                for item in node.body:
                    if isinstance(item, Assign) and any(isinstance(
                            t, Name) and t.id in targets for t in item.targets) and isinstance(item.value, Dict):
                        for v in item.value.values:
                            for t in strings(v):
                                found[t] = rel
    return [t for t in found if any(ch.isalpha() for ch in t)]


def placeholders(text):
    """
    :param text: str | unicode | QString
    :return: (list[str | unicode | QString]) {} placeholders in order.
    """
    return findall(r'\{[^{}]*\}', text)


def prefix(text):
    """
    :param text: str | unicode | QString
    :return: (str | unicode | QString) Leading icon / symbol characters (kept by translations).
    """
    out = ''  # type: str
    for ch in text:
        if ch.isalnum() or ch in '(-"\'{':  # '{' starts a placeholder (checked separately), not an icon
            break
        out += ch
    return out.strip()


def catalogs():
    """
    :return: (list[str | unicode | QString]) Catalog paths.
    """
    return sorted(join(FOLDER, f) for f in listdir(
        FOLDER) if f.endswith('.json')) if isfile(join(FOLDER, '..', '__init__.py')) else []


def load(path):
    """
    :param path: str | unicode | QString
    :return: dict
    """
    with iopen(path, encoding='utf-8') as f:
        return jLoad(f, object_pairs_hook=OrderedDict)


def save(path, data):
    """
    :param path: str | unicode | QString
    :param data: dict
    :return:
    """
    with iopen(path, 'w', encoding='utf-8', newline='\r\n') as f:  # CRLF, like every text file of the project.
        f.write(dumps(data, ensure_ascii=False, indent=2) + '\n')


def main():
    """
    :return: int
    """
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--new', nargs=2, metavar=('CODE', 'NAME'))
    args = parser.parse_args()
    texts = sources()  # type: list
    if args.list:
        print(dumps(texts, ensure_ascii=False, indent=1))
    if args.new:
        path = join(FOLDER, args.new[0] + '.json')
        if not isfile(path):
            save(path, OrderedDict([('language', args.new[0]), ('name', args.new[1]), ('direction', 'ltr'),
                                    ('strings', OrderedDict())]))
        args.update = True
    if args.update:
        for path in catalogs():
            data = load(path)
            old = data.get('strings') or {}
            data['strings'] = OrderedDict((t, old.get(t, '')) for t in texts)
            save(path, data)
            print(u'{}: {} texts, {} to translate'.format(
                path[len(ROOT) + 1:], len(texts), sum(1 for t in texts if not data['strings'][t])))
    if args.check:
        bad = 0  # type: int
        for path in catalogs():
            data, problems = load(path), []
            table = data.get(u'strings') or {}
            missing = [t for t in texts if not table.get(t)]
            problems += [u'missing: {!r}'.format(t) for t in missing]
            for t, tr in table.items():
                if tr and placeholders(t) != placeholders(tr):
                    problems.append(u'placeholders {} -> {}: {!r}'.format(placeholders(t), placeholders(tr), tr))
                if tr and prefix(t) and not tr.lstrip().startswith(prefix(t)):
                    problems.append(u'icon prefix {!r} lost: {!r}'.format(prefix(t), tr))
            obsolete = [t for t in table if t not in texts]
            name = path[len(ROOT) + 1:]
            if problems:
                bad += 1
                print(u'{}: {} problem(s)\n  '.format(name, len(problems)) + '\n  '.join(problems[:40]))
            else:
                print(u'{}: ok - {} texts translated{}'.format(
                    name, len(texts), ' ({} obsolete)'.format(len(obsolete)) if obsolete else ''))
        return 1 if bad else 0
    return 0


if __name__ == '__main__':
    exit(main())
