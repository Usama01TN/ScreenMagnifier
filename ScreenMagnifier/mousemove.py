# -*- coding: utf-8 -*-
"""
Mouse movements like a real mouse, for games that capture the mouse (first-person and 3D games hide the pointer and
turn the view with the raw mouse movements, so moving the pointer's position has no effect there):
    sendRelativeMove(dx, dy) -> bool    Windows: SendInput (raw input sees it); Linux X11: XTest relative motion;
                                        macOS: Quartz mouse-moved event with deltas; Wayland: not possible (False).
    ButtonWatcher                       Is the right mouse button held? (pynput listener, nothing is swallowed)
    mouseCapture() -> str               'clipped' (Windows: the pointer is confined - a game), 'hidden' (the cursor
                                        is invisible: a game, or a video player resting) or '' (a normal pointer)
"""
from sys import platform
from os import environ
import ctypes

_X11 = []  # type: list  # [display] opened on first use
_QUARTZ = []  # type: list  # [library]


def _isWayland():
    """
    :return: (bool) A Wayland session (applications may not move the mouse there).
    """
    return platform.startswith('linux') and (environ.get('WAYLAND_DISPLAY') and not environ.get('DISPLAY') or
                                             environ.get('QT_QPA_PLATFORM', '').startswith('wayland'))


def canSendRelative():
    """
    :return: (bool) This system lets the application send relative mouse movements.
    """
    if platform == 'win32':
        return True
    if platform == 'darwin':
        return _quartz() is not None
    return not _isWayland() and _x11() is not None


def _x11():
    """
    :return: Xlib display | None
    """
    if not _X11:
        try:
            from Xlib import display as xdisplay
            from Xlib.ext import xtest  # noqa: F401  (the extension must exist)
            d = xdisplay.Display()
            _X11.append(d if d.has_extension('XTEST') else None)
        except Exception:
            _X11.append(None)
    return _X11[0]


def _quartz():
    """
    :return: ctypes library | None
    """
    if not _QUARTZ:
        try:
            lib = ctypes.cdll.LoadLibrary(
                '/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
            _QUARTZ.append(lib)
        except Exception:
            _QUARTZ.append(None)
    return _QUARTZ[0]


class _MouseInput(ctypes.Structure):
    """
    _MouseInput class: Windows MOUSEINPUT.
    """
    _fields_ = [('dx', ctypes.c_long), ('dy', ctypes.c_long), ('mouseData', ctypes.c_ulong),
                ('dwFlags', ctypes.c_ulong), ('time', ctypes.c_ulong), ('dwExtraInfo', ctypes.c_void_p)]


class _Input(ctypes.Structure):
    """
    _Input class: Windows INPUT (type + the mouse / keyboard / hardware union).
    """

    class _U(ctypes.Union):
        """
        _U class: the INPUT union (padded to its largest member).
        """
        _fields_ = [('mi', _MouseInput), ('pad', ctypes.c_byte * 32)]

    _anonymous_ = ('u',)
    _fields_ = [('type', ctypes.c_ulong), ('u', _U)]


class _Rect(ctypes.Structure):
    """
    _Rect class: Windows RECT.
    """
    _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long), ('right', ctypes.c_long), ('bottom', ctypes.c_long)]


class _CursorInfo(ctypes.Structure):
    """
    _CursorInfo class: Windows CURSORINFO.
    """
    _fields_ = [('cbSize', ctypes.c_ulong), ('flags', ctypes.c_ulong), ('hCursor', ctypes.c_void_p),
                ('x', ctypes.c_long), ('y', ctypes.c_long)]


def mouseCapture():
    """
    How the mouse pointer is held right now (asked to the system).
    :return: (str | unicode | QString)
        'clipped' (Windows: confined to a rect - games do that), 'hidden' (invisible cursor: a game, or
        a video player resting - tell them apart by moving it), '' (a normal, visible pointer) or '' when unknown.
    """
    try:
        if platform == 'win32':
            user32 = ctypes.windll.user32
            clip = _Rect()
            if user32.GetClipCursor(ctypes.byref(clip)):
                width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
                height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
                if clip.right - clip.left < width or clip.bottom - clip.top < height:
                    return 'clipped'
            info = _CursorInfo()
            info.cbSize = ctypes.sizeof(_CursorInfo)
            if user32.GetCursorInfo(ctypes.byref(info)) and not (info.flags & 1):  # CURSOR_SHOWING
                return 'hidden'
            return ''
        if platform == 'darwin':
            q = _quartz()
            if q is not None:
                q.CGCursorIsVisible.restype = ctypes.c_bool
                return '' if q.CGCursorIsVisible() else 'hidden'
            return ''
        d = _x11()
        if d is None or _isWayland():
            return ''
        if not getattr(d, '_sm_xfixes', False):
            d.xfixes_query_version()
            d._sm_xfixes = True
        image = d.xfixes_get_cursor_image(d.screen().root)
        pixels = list(image.cursor_image)  # ARGB
        return 'hidden' if pixels and not any((p >> 24) & 0xFF for p in pixels) else ''
    except Exception:
        return ''


class _CGPoint(ctypes.Structure):
    """
    _CGPoint class: macOS CGPoint.
    """
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]


def sendRelativeMove(dx, dy):
    """
    Move the mouse by (dx, dy) counts, as a physical mouse would.
    :param dx: int
    :param dy: int
    :return: (bool) Sent.
    """
    dx, dy = int(dx), int(dy)
    if not dx and not dy:
        return True
    try:
        if platform == 'win32':
            event = _Input(type=0)  # INPUT_MOUSE
            event.mi = _MouseInput(dx, dy, 0, 0x0001, 0, None)  # MOUSEEVENTF_MOVE (relative)
            return ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_Input)) == 1
        if platform == 'darwin':
            q = _quartz()
            if q is None:
                return False
            q.CGEventCreate.restype = ctypes.c_void_p
            q.CGEventGetLocation.restype = _CGPoint
            q.CGEventGetLocation.argtypes = [ctypes.c_void_p]
            q.CGEventCreateMouseEvent.restype = ctypes.c_void_p
            q.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, _CGPoint, ctypes.c_uint32]
            q.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
            q.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
            q.CFRelease.argtypes = [ctypes.c_void_p]
            probe = q.CGEventCreate(None)
            here = q.CGEventGetLocation(probe)
            q.CFRelease(probe)
            event = q.CGEventCreateMouseEvent(None, 5, _CGPoint(here.x + dx, here.y + dy), 0)  # kCGEventMouseMoved
            q.CGEventSetIntegerValueField(event, 4, dx)  # kCGMouseEventDeltaX
            q.CGEventSetIntegerValueField(event, 5, dy)  # kCGMouseEventDeltaY
            q.CGEventPost(0, event)  # kCGHIDEventTap
            q.CFRelease(event)
            return True
        d = _x11()
        if d is None or _isWayland():
            return False
        from Xlib.ext import xtest
        from Xlib import X
        xtest.fake_input(d, X.MotionNotify, detail=1, x=dx, y=dy)  # detail 1: relative motion
        d.sync()
        return True
    except Exception:
        return False


class ButtonWatcher(object):
    """
    ButtonWatcher class: tells whether the right mouse button is held (a pynput listener; clicks still reach the
    game). Start it only while needed.
    """

    def __init__(self):
        """
        """
        self.__m_listener = None
        self.__m_held = False  # type: bool

    def start(self):
        """
        :return: (bool) Watching.
        """
        if self.__m_listener is not None:
            return True
        try:
            from pynput import mouse
        except Exception:
            return False

        def onClick(x, y, button, pressed):
            """
            :param x: int
            :param y: int
            :param button: pynput.mouse.Button
            :param pressed: bool
            :return:
            """
            if button == mouse.Button.right:
                self.__m_held = bool(pressed)

        try:
            self.__m_listener = mouse.Listener(on_click=onClick)
            self.__m_listener.daemon = True
            self.__m_listener.start()
            return True
        except Exception:
            self.__m_listener = None
            return False

    def stop(self):
        """
        :return:
        """
        if self.__m_listener is not None:
            try:
                self.__m_listener.stop()
            except Exception:
                pass
        self.__m_listener = None
        self.__m_held = False  # type: bool

    def isHeld(self):
        """
        :return: (bool) The right mouse button is held.
        """
        return self.__m_held
