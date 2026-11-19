# -*- coding: utf-8 -*-
"""
Project support: donation links (toolbar / tray "Support" menu, README, PyPI page, GitHub Sponsor button) and the
startup check for a Qt binding (ManyQt runs on PyQt5, PyQt6, PySide2 or PySide6 - one must be installed).
"""
DONATION_LINKS = [
    ('ba9chich', 'https://ba9chich.com/fr/IninouUsama'),
    ('Ko-fi', 'https://ko-fi.com/usamatn'),
]  # type: list[tuple[str, str]]

INSTALL_HINT = """Screen Magnifier needs a Qt binding. Install one of them, e.g.:
    pip install "ScreenMagnifier[pyqt6]"     (or [pyqt5], [pyside6] - [all] = PyQt6 + OpenCV)"""  # type: str


def qtBindingProblem():
    """
    :return: (str | unicode | QString) '' when a Qt binding is usable, else a message explaining how to install one.
    """
    try:
        from ManyQt import QtWidgets  # noqa: F401
    except Exception as e:
        return u'{}\nDetails: {}'.format(INSTALL_HINT, e)
    return ''


def cleanEnvironment(env):
    """
    Undo what importing OpenCV (opencv-python, with its own Qt) changes in the environment: its Qt plugin and font
    folders and its library folder. A restarted instance inheriting them would load OpenCV's Qt plugins with the Qt of
    PyQt / PySide and fail to start ("Could not load the Qt platform plugin"). The values the process started with
    are restored (recorded by the package before OpenCV was imported), then whatever still points into OpenCV's
    folder is removed (source scripts, or OpenCV imported before the package).
    :param env: (dict) A copy of the environment.
    :return: (dict) The same dict, cleaned.
    """
    from os.path import dirname, abspath
    from sys import modules
    module = modules.get('cv2')
    folder = getattr(module, '__file__', None) if module is not None else None
    if not folder:
        return env
    keys = ('QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_FONTDIR', 'LD_LIBRARY_PATH')  # type: tuple
    package = modules.get((__package__ or '').split('.')[0]) if __package__ else None
    startup = getattr(package, 'STARTUP_ENVIRONMENT', None)  # type: dict | None
    if startup is not None:  # The values the process started with.
        for key in keys:
            if key in startup:
                env[key] = startup[key]
            else:
                env.pop(key, None)
    root = dirname(abspath(folder))  # type: str
    inside = lambda value: bool(value) and (value.startswith(root) or abspath(value).startswith(root))
    for key in keys[:2]:
        if inside(env.get(key, '')):
            env.pop(key)
    if env.get('LD_LIBRARY_PATH'):
        kept = [p for p in env['LD_LIBRARY_PATH'].split(':') if p and not inside(p)]  # type: list
        if kept:
            env['LD_LIBRARY_PATH'] = ':'.join(kept)
        else:
            env.pop('LD_LIBRARY_PATH')
    return env


def restartCommand(argv, extra=()):
    """
    Command that starts this application again, the way it was started: packaged executable, installed package
    (python -m ScreenMagnifier) or source script. One-time options (--lang, --wait-pid) are dropped.
    :param argv: (list[str | unicode | QString]) sys.argv.
    :param extra: (tuple[str | unicode | QString]) Options to add.
    :return: (tuple[list[str | unicode | QString], dict]) Command line and environment.
    """
    from os.path import dirname, abspath
    from os import environ
    import sys
    kept, skip = [], False  # type: list, bool
    for arg in argv[1:]:
        if skip:
            skip = False
        elif arg in ('--lang', '--wait-pid'):
            skip = True
        elif not arg.startswith(('--lang=', '--wait-pid=')):
            kept.append(arg)
    env = cleanEnvironment(dict(environ))  # type: dict
    if getattr(sys, 'frozen', False):
        command = [sys.executable]  # type: list[str]
    elif __package__:  # Imported as the ScreenMagnifier package: run it as a module (works for pip installs).
        command = [sys.executable, '-m', __package__.split('.')[0]]
        root = dirname(dirname(abspath(__file__)))  # type: str  # folder holding the package
        env['PYTHONPATH'] = root + (';' if sys.platform == 'win32' else ':') + env.get('PYTHONPATH', '') if \
            env.get('PYTHONPATH') else root
    else:
        command = [sys.executable, abspath(argv[0])]
    return command + kept + list(extra), env


def waitForExit(pid, timeout=8.0):
    """
    Wait until a process has exited (a restarted application waits for the previous one: global hotkeys and the
    tray icon are then free).
    :param pid: int
    :param timeout: (float | int) Seconds.
    :return: (bool) The process has exited.
    """
    from time import time, sleep
    from sys import platform
    end = time() + float(timeout)  # type: float
    if platform == 'win32':
        try:
            from ctypes import windll
            handle = windll.kernel32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
            if not handle:
                return True
            try:
                return windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000)) == 0
            finally:
                windll.kernel32.CloseHandle(handle)
        except:
            return False
    from os import kill
    while time() < end:
        try:
            kill(int(pid), 0)
        except OSError:
            return True
        sleep(0.05)
    return False
