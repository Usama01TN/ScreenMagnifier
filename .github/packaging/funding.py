# coding=utf-8
"""
.github/FUNDING.yml in the workflow:
    --check        validate it as GitHub reads it (platform keys, usernames, at most 4 custom links) and check that the
                   same links are in the application's Support menu (ScreenMagnifier/support.py) and in the package
                   metadata (setup.py PROJECT_URLS) - a link changed in one place only fails the build.
    --notes FILE   write the "Support the project" section of a GitHub release (markdown).
"""
from ast import literal_eval, parse, Assign, Name
from os.path import abspath, dirname, join
from argparse import ArgumentParser
from yaml import safe_load
from sys import exit

ROOT = abspath(join(dirname(__file__), '..', '..'))  # type: str
PLATFORMS = {  # GitHub's FUNDING.yml keys -> profile URL (None: no single URL form)
    'github': 'https://github.com/sponsors/{}', 'patreon': 'https://www.patreon.com/{}',
    'open_collective': 'https://opencollective.com/{}', 'ko_fi': 'https://ko-fi.com/{}',
    'tidelift': None, 'community_bridge': 'https://crowdfunding.lfx.linuxfoundation.org/projects/{}',
    'liberapay': 'https://liberapay.com/{}', 'issuehunt': 'https://issuehunt.io/r/{}',
    'lfx_crowdfunding': 'https://crowdfunding.lfx.linuxfoundation.org/projects/{}', 'polar': 'https://polar.sh/{}',
    'buy_me_a_coffee': 'https://buymeacoffee.com/{}', 'thanks_dev': 'https://thanks.dev/{}', 'custom': None,
}  # type: dict
NAMES = {'ko_fi': 'Ko-fi', 'github': 'GitHub Sponsors', 'buy_me_a_coffee': 'Buy Me a Coffee'}  # type: dict


def fundingLinks(path):
    """
    :param path: str | unicode | QString
    :return: (list[tuple[str, str]]) (name, url) of every funding link, in file order.
    """
    data = safe_load(open(path, encoding='utf-8')) or {}
    if not isinstance(data, dict):
        raise ValueError(u'FUNDING.yml must be a mapping of platform: account')
    links = []  # type: list
    for key, value in data.items():
        if key not in PLATFORMS:
            raise ValueError(u'Unknown FUNDING.yml platform {!r} (GitHub ignores it)'.format(key))
        values = value if isinstance(value, list) else [value]
        if key == 'custom':
            if len(values) > 4:
                raise ValueError(u'FUNDING.yml: at most 4 custom links')
            for url in values:
                if not u'{}'.format(url).startswith(('https://', 'http://')):
                    raise ValueError(u'FUNDING.yml: custom link {!r} must be a full URL'.format(url))
                host = u'{}'.format(url).split('/')[2].replace('www.', '')
                links.append((host.split('.')[0], u'{}'.format(url)))
        else:
            for account in values:
                if not account or '/' in u'{}'.format(account) or ' ' in u'{}'.format(account):
                    raise ValueError(u'FUNDING.yml: {} needs a user name, not {!r}'.format(key, account))
                if PLATFORMS[key]:
                    links.append((NAMES.get(key, key.replace('_', ' ').title()), PLATFORMS[key].format(account)))
    return links


def constant(path, name):
    """
    :param path: (str | unicode | QString) Python file.
    :param name: (str | unicode | QString) Module-level constant.
    :return: any
    """
    for node in parse(open(path, encoding='utf-8').read()).body:
        if isinstance(node, Assign) and any(isinstance(t, Name) and t.id == name for t in node.targets):
            return literal_eval(node.value)
    raise KeyError('{} not found in {}'.format(name, path))


def main():
    """
    :return: int
    """
    parser = ArgumentParser(description=__doc__)  # type: ArgumentParser
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--notes', default='')
    args = parser.parse_args()
    links = fundingLinks(join(ROOT, '.github', 'FUNDING.yml'))  # type: list
    urls = sorted(url for name, url in links)  # type: list
    if args.check:
        app = sorted(url for name, url in constant(join(ROOT, 'ScreenMagnifier', 'support.py'), 'DONATION_LINKS'))
        meta = sorted(constant(join(ROOT, 'setup.py'), 'PROJECT_URLS').values())
        for where, found in (('ScreenMagnifier/support.py DONATION_LINKS', app), ('setup.py PROJECT_URLS', meta)):
            if found != urls:
                print('FUNDING.yml links {} differ from {} {}'.format(urls, where, found))
                return 1
        print('FUNDING.yml ok: {} - same links in the application and the package metadata'.format(
            ', '.join('{} {}'.format(n, u) for n, u in links)))
    if args.notes:
        with open(args.notes, 'w', encoding='utf-8') as f:
            f.write(u'## \u2665 Support the project\n\nIf ScreenMagnifier is useful to you, you can support its '
                    'development:\n\n' + ''.join('- {}: [{}]({})\n'.format(n, u.split('://', 1)[1], u)
                                                 for n, u in links) + '\n')
        print('release notes: ' + args.notes)
    return 0


if __name__ == '__main__':
    exit(main())
