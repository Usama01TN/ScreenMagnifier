# -*- coding: utf-8 -*-
"""
GlobalHotkeys: system-wide keyboard shortcuts that fire even while another application (e.g. a game) has the
keyboard focus.
Backends:
    - windows : Win32 RegisterHotKey on a dedicated message-loop thread. No dependency. The combination is
                consumed, so the focused application does not receive it.
    - pynput  : pynput.keyboard.GlobalHotKeys (Linux X11, macOS with Accessibility permission). The focused
                application still receives the keys.
Key sequences use Qt's portable text form, e.g. 'Ctrl+Alt+Z', 'Ctrl+Alt+=', 'Ctrl+Shift+F9', 'Num+5'.
"""
from ManyQt.QtCore import QObject, pyqtSignal, pyqtSlot, pyqtProperty
from threading import Thread, Event
from sys import platform

MODIFIERS = {'ctrl': 'Ctrl', 'control': 'Ctrl', 'alt': 'Alt', 'option': 'Alt', 'shift': 'Shift', 'meta': 'Meta',
             'win': 'Meta', 'super': 'Meta', 'cmd': 'Meta', 'num': 'Num', 'keypad': 'Num'}  # type: dict[str, str]
KEY_ALIASES = {'escape': 'Esc', 'esc': 'Esc', 'insert': 'Ins', 'ins': 'Ins', 'delete': 'Del', 'del': 'Del',
               'pageup': 'PgUp', 'pgup': 'PgUp', 'pagedown': 'PgDown', 'pgdown': 'PgDown', 'return': 'Return',
               'enter': 'Enter', 'space': 'Space', 'tab': 'Tab', 'backspace': 'Backspace', 'home': 'Home',
               'end': 'End', 'up': 'Up', 'down': 'Down', 'left': 'Left', 'right': 'Right', 'pause': 'Pause',
               'print': 'Print', 'printscreen': 'Print', 'scrolllock': 'ScrollLock', 'numlock': 'NumLock',
               'plus': '+', 'minus': '-'}  # type: dict[str, str]
# Win32 virtual-key codes.
VK_NAMED = {'Up': 0x26, 'Down': 0x28, 'Left': 0x25, 'Right': 0x27, 'Space': 0x20, 'Tab': 0x09, 'Esc': 0x1B,
            'Return': 0x0D, 'Enter': 0x0D, 'Ins': 0x2D, 'Del': 0x2E, 'Home': 0x24, 'End': 0x23, 'PgUp': 0x21,
            'PgDown': 0x22, 'Backspace': 0x08, 'Pause': 0x13, 'Print': 0x2C, 'ScrollLock': 0x91,
            'NumLock': 0x90, '=': 0xBB, '+': 0xBB, '-': 0xBD, ',': 0xBC, '.': 0xBE, '/': 0xBF, ';': 0xBA,
            '`': 0xC0, '[': 0xDB, '\\': 0xDC, ']': 0xDD, "'": 0xDE}  # type: dict[str, int]
VK_KEYPAD = {'+': 0x6B, '-': 0x6D, '*': 0x6A, '/': 0x6F, '.': 0x6E, 'Enter': 0x0D}  # type: dict[str, int]
MOD_FLAGS = {'Alt': 0x0001, 'Ctrl': 0x0002, 'Shift': 0x0004, 'Meta': 0x0008}  # type: dict[str, int]
MOD_NOREPEAT = 0x4000  # type: int
# pynput tokens.
PYNPUT_MODS = {'Ctrl': '<ctrl>', 'Alt': '<alt>', 'Shift': '<shift>', 'Meta': '<cmd>'}  # type: dict
PYNPUT_NAMED = {'Up': '<up>', 'Down': '<down>', 'Left': '<left>', 'Right': '<right>', 'Space': '<space>',
                'Tab': '<tab>', 'Esc': '<esc>', 'Return': '<enter>', 'Enter': '<enter>', 'Ins': '<insert>',
                'Del': '<delete>', 'Home': '<home>', 'End': '<end>', 'PgUp': '<page_up>',
                'PgDown': '<page_down>', 'Backspace': '<backspace>', 'Pause': '<pause>',
                'Print': '<print_screen>', 'ScrollLock': '<scroll_lock>', 'NumLock': '<num_lock>',
                '+': '='}  # type: dict[str, str]


def parseSequence(sequence):
    """
    Parse 'Ctrl+Alt+Z' (Qt portable text, first chord only) into its modifiers and key.
    :param sequence: str | unicode | QString
    :return: (tuple[frozenset, str]) Canonical modifiers and key.
    :raise ValueError: on empty or unknown sequences.
    """
    text = u'{}'.format(sequence).split(',')[0].strip()  # type: str
    if not text:
        raise ValueError(u'Empty key sequence')
    if text.endswith('++') or text == '+':
        parts, key = [p for p in text[:-2].split('+') if p], '+'
    else:
        parts = text.split('+')  # type: list
        key = parts.pop()  # type: str
    mods = set()  # type: set
    for p in parts:
        m = MODIFIERS.get(p.strip().lower())
        if m is None:
            raise ValueError(u'Unknown modifier: {}'.format(p))
        mods.add(m)
    key = key.strip()  # type: str
    low = key.lower()  # type: str
    if low in KEY_ALIASES:
        key = KEY_ALIASES[low]  # type: str
    elif len(key) == 1:
        key = key.upper()  # type: str
    elif low.startswith('f') and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
        key = 'F{}'.format(int(low[1:]))  # type: str
    else:
        raise ValueError(u'Unknown key: {}'.format(key))
    return frozenset(mods), key


def toVirtualKey(mods, key):
    """
    :param mods: frozenset
    :param key: str | unicode | QString
    :return: (tuple[int, int]) RegisterHotKey modifier flags and virtual-key code.
    """
    flags = 0  # type: int
    for m in mods:
        flags |= MOD_FLAGS.get(m, 0)
    if 'Num' in mods and (key.isdigit() or key in VK_KEYPAD):
        vk = 0x60 + int(key) if key.isdigit() else VK_KEYPAD[key]  # type: int
    elif len(key) == 1 and (key.isalpha() or key.isdigit()):
        vk = ord(key)  # type: int
    elif key.startswith('F') and key[1:].isdigit():
        vk = 0x6F + int(key[1:])  # type: int
    elif key in VK_NAMED:
        vk = VK_NAMED[key]  # type: int
    else:
        raise ValueError(u'No virtual-key code for {}'.format(key))
    return flags | MOD_NOREPEAT, vk


def toPynput(mods, key):
    """
    :param mods: frozenset
    :param key: str | unicode | QString
    :return: (str | unicode | QString)pynput hotkey string such as '<ctrl>+<alt>+z'.
    """
    tokens = [PYNPUT_MODS[m] for m in ('Ctrl', 'Alt', 'Shift', 'Meta') if m in mods]  # type: list
    if key.startswith('F') and key[1:].isdigit():
        tokens.append('<{}>'.format(key.lower()))
    elif key in PYNPUT_NAMED:
        tokens.append(PYNPUT_NAMED[key])
    else:
        tokens.append(key.lower())
    return '+'.join(tokens)


class _WindowsBackend(object):
    """
    RegisterHotKey on a private thread that runs its own Win32 message loop.
    """

    def __init__(self, bindings, callback):
        """
        :param bindings: (dict) name -> (modifiers, key).
        :param callback: (callable) f(name), called from the hotkey thread.
        :return:
        """
        self.status = {}  # type: dict
        self.__m_bindings = bindings  # type: dict
        self.__m_callback = callback  # type: callable
        self.__m_threadId = 0  # type: int
        self.__m_ready = Event()  # type: Event
        self.__m_thread = Thread(target=self._run, name='GlobalHotkeys')  # type: Thread
        self.__m_thread.daemon = True
        self.__m_thread.start()
        self.__m_ready.wait(2.0)

    def _run(self):
        """
        :return:
        """
        from ctypes import c_int, byref, windll, POINTER
        from ctypes.wintypes import HWND, UINT, MSG
        user32 = windll.user32
        kernel32 = windll.kernel32
        user32.RegisterHotKey.argtypes = [HWND, c_int, UINT, UINT]
        user32.UnregisterHotKey.argtypes = [HWND, c_int]
        user32.GetMessageW.argtypes = [POINTER(MSG), HWND, UINT, UINT]
        user32.PeekMessageW.argtypes = [POINTER(MSG), HWND, UINT, UINT, UINT]
        WM_HOTKEY, WM_USER, PM_NOREMOVE = 0x0312, 0x0400, 0x0000
        msg = MSG()
        user32.PeekMessageW(byref(msg), None, WM_USER, WM_USER, PM_NOREMOVE)  # Create the queue.
        self.__m_threadId = kernel32.GetCurrentThreadId()  # type: int
        ids = {}  # type: dict
        for i, (name, (mods, key)) in enumerate(sorted(self.__m_bindings.items()), 1):
            try:
                flags, vk = toVirtualKey(mods, key)
                ok = bool(user32.RegisterHotKey(None, i, flags, vk))  # type: bool
            except ValueError:
                ok = False  # type: bool
            self.status[name] = ok
            if ok:
                ids[i] = name
        self.__m_ready.set()
        while user32.GetMessageW(byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                self.__m_callback(ids[msg.wParam])
        for i in ids:
            user32.UnregisterHotKey(None, i)

    def stop(self):
        """
        :return:
        """
        if self.__m_threadId:
            from ctypes import windll
            WM_QUIT = 0x0012  # type: int
            windll.user32.PostThreadMessageW(self.__m_threadId, WM_QUIT, 0, 0)
            self.__m_thread.join(1.0)


class _PynputBackend(object):
    """
    pynput.keyboard.GlobalHotKeys wrapper.
    """

    def __init__(self, bindings, callback):
        """
        :param bindings: (dict) name -> (modifiers, key).
        :param callback: (callable) f(name), called from the listener thread.
        """
        from pynput import keyboard
        self.status = {}  # type: dict
        mapping = {}  # type: dict
        for name, (mods, key) in bindings.items():
            combo = toPynput(mods, key)  # type: str
            try:
                keyboard.HotKey.parse(combo)
                mapping[combo] = (lambda n=name: callback(n))
                self.status[name] = True
            except Exception:
                self.status[name] = False
        self.__m_listener = keyboard.GlobalHotKeys(mapping)
        self.__m_listener.daemon = True
        self.__m_listener.start()

    def stop(self):
        """
        :return:
        """
        self.__m_listener.stop()


class GlobalHotkeys(QObject):
    """
    GlobalHotkeys class: name -> key sequence bindings, activated(name) when one is pressed anywhere.
    """
    activated = pyqtSignal('QString')  # type: pyqtSignal
    registrationChanged = pyqtSignal()  # type: pyqtSignal
    enabledChanged = pyqtSignal(bool)  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param bindings: (dict[str, str]) name -> key sequence, e.g. {'toggle': 'Ctrl+Alt+Z'}.
        :param enabled: bool
        :param backend: (str | unicode | QString)'auto' | 'windows' | 'pynput'
        :param activated: callable | None
        :param args: any
        :param kwargs: any
        """
        bindings = kwargs.pop('bindings', {})  # type: dict
        enabled = kwargs.pop('enabled', True)  # type: bool
        backend = kwargs.pop('backend', 'auto')  # type: str
        activated = kwargs.pop('activated', None)  # type: callable | None
        super(GlobalHotkeys, self).__init__(*args, **kwargs)
        if callable(activated):
            self.activated.connect(activated)
        self.__m_bindings = dict(bindings)  # type: dict
        self.__m_enabled = bool(enabled)  # type: bool
        self.__m_backendName = GlobalHotkeys.detectBackend() if backend == 'auto' else u'{}'.format(backend)  # type: str
        self.__m_backend = None  # type: _WindowsBackend | _PynputBackend | None
        self.__m_status = {}  # type: dict
        self.__m_error = ''  # type: str
        self._apply()

    # ---------- Helpers ----------
    @staticmethod
    def detectBackend():
        """
        :return: (str | unicode | QString)'windows', 'pynput' or '' when no backend can work here.
        """
        if platform == 'win32':
            return 'windows'
        try:
            from pynput import keyboard  # noqa: F401  (fails without an X server / permission)
            return 'pynput'
        except:
            return ''

    def _emit(self, name):
        """
        Called from the backend thread; the queued signal delivers it in the GUI thread.
        :param name: str | unicode | QString
        :return:
        """
        self.activated.emit(name)

    def _apply(self):
        """
        (Re)register every binding with the backend.
        :return:
        """
        if self.__m_backend is not None:
            try:
                self.__m_backend.stop()
            except Exception:
                pass
            self.__m_backend = None
        self.__m_status = {}  # type: dict
        self.__m_error = ''  # type: str
        parsed = {}  # type: dict
        for name, seq in self.__m_bindings.items():
            try:
                parsed[name] = parseSequence(seq)
            except ValueError:
                self.__m_status[name] = False
        if self.__m_enabled and parsed:
            try:
                if self.__m_backendName == 'windows':
                    self.__m_backend = _WindowsBackend(parsed, self._emit)
                elif self.__m_backendName == 'pynput':
                    self.__m_backend = _PynputBackend(parsed, self._emit)
                else:
                    self.__m_error = 'No global hotkey backend: install pynput (pip install pynput).'  # type: str
                if self.__m_backend is not None:
                    self.__m_status.update(self.__m_backend.status)
            except Exception as e:
                self.__m_backend = None
                self.__m_error = 'Global hotkeys unavailable: {}'.format(e)  # type: str
        self.registrationChanged.emit()

    # ---------- Public API ----------
    def getStatus(self, name):
        """
        :param name: str | unicode | QString
        :return: (bool | None) True registered, False failed (invalid or taken by another app), None inactive.
        """
        return self.__m_status.get(name)

    def getError(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_error

    def getBackendName(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_backendName

    def getBindings(self):
        """
        :return: dict[str, str]
        """
        return dict(self.__m_bindings)

    def setBindings(self, bindings):
        """
        :param bindings: dict[str, str]
        :return:
        """
        self.__m_bindings = dict(bindings)  # type: dict
        self._apply()

    def setBinding(self, name, sequence):
        """
        :param name: str | unicode | QString
        :param sequence: (str | unicode | QString)Empty string removes the binding.
        :return:
        """
        if sequence:
            self.__m_bindings[u'{}'.format(name)] = u'{}'.format(sequence)
        else:
            self.__m_bindings.pop(u'{}'.format(name), None)
        self._apply()

    def isEnabled(self):
        """
        :return: bool
        """
        return self.__m_enabled

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setEnabled(self, enabled):
        """
        :param enabled: bool
        :return:
        """
        enabled = bool(enabled)  # type: bool
        if enabled != self.__m_enabled:
            self.__m_enabled = enabled  # type: bool
            self._apply()
            self.enabledChanged.emit(enabled)

    @pyqtSlot()
    def shutdown(self):
        """
        Unregister everything (call before quitting).
        :return:
        """
        if self.__m_backend is not None:
            try:
                self.__m_backend.stop()
            except Exception:
                pass
            self.__m_backend = None

    # ---------- Properties ----------
    enabled = pyqtProperty(bool, fget=isEnabled, fset=setEnabled, notify=enabledChanged)  # type: pyqtProperty
