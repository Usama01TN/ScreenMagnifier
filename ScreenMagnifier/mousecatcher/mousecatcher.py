# -*- coding: utf-8 -*-
"""
GlobalMouseCatcher: catches mouse clicks ANYWHERE on the screen (over any application or game) and swallows them,
while the cursor keeps moving normally - e.g. for a screen color picker.
Backends:
    - qtgrab : Qt pointer + keyboard grab on a 1 px window (Linux / X11). Also reports keys (Esc, arrows).
    - pynput : system mouse hook (Windows low-level hook, macOS Quartz event tap - needs the Accessibility
               permission). Only button / wheel events are suppressed, movements pass through.
    - auto   : pynput on Windows / macOS, qtgrab elsewhere.
Signals: clicked(QPoint global position, int button 1 left / 2 right / 3 middle), wheelTurned(int delta, 120 per
notch), keyPressed(int Qt key, qtgrab only).
"""
from ManyQt.QtCore import Qt, QPoint, QObject, QThread, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtWidgets import QWidget, QApplication
from ManyQt.QtGui import QCursor
from sys import platform

WM_BUTTONS = {0x0201: 1, 0x0204: 2, 0x0207: 3}  # type: dict  # Windows WM_*BUTTONDOWN -> button
WM_BUTTONS_UP = (0x0202, 0x0205, 0x0208)  # type: tuple
WM_MOUSEWHEEL = 0x020A  # type: int
CG_BUTTONS = {1: 1, 3: 2, 25: 3}  # type: dict  # macOS kCGEvent*MouseDown -> button
CG_BUTTONS_UP = (2, 4, 26)  # type: tuple
CG_SCROLL = 22  # type: int


class _GrabWindow(QWidget):
    """
    _GrabWindow class: 1 px window owning the pointer / keyboard grab.
    """

    def __init__(self, catcher):
        """
        :param catcher: GlobalMouseCatcher
        """
        super(_GrabWindow, self).__init__()
        self.__m_catcher = catcher  # type: GlobalMouseCatcher
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint  # type: int
        if platform.startswith('linux'):
            flags |= Qt.X11BypassWindowManagerHint
        self.setWindowFlags(flags)
        self.setGeometry(0, 0, 1, 1)

    def mousePressEvent(self, e):
        """
        :param e: QMouseEvent
        :return:
        """
        button = {Qt.LeftButton: 1, Qt.RightButton: 2, Qt.MiddleButton: 3}.get(e.button(), 0)  # type: int
        pos = e.globalPosition().toPoint() if hasattr(e, 'globalPosition') else e.globalPos()  # type: QPoint
        if button:
            self.__m_catcher.clicked.emit(pos, button)

    def wheelEvent(self, e):
        """
        :param e: QWheelEvent
        :return:
        """
        self.__m_catcher.wheelTurned.emit(int(e.angleDelta().y()))

    def keyPressEvent(self, e):
        """
        :param e: QKeyEvent
        :return:
        """
        self.__m_catcher.keyPressed.emit(int(e.key()))


class GlobalMouseCatcher(QObject):
    """
    GlobalMouseCatcher class.
    """
    clicked = pyqtSignal(QPoint, int)  # type: pyqtSignal
    wheelTurned = pyqtSignal(int)  # type: pyqtSignal
    keyPressed = pyqtSignal(int)  # type: pyqtSignal
    activeChanged = pyqtSignal(bool)  # type: pyqtSignal
    _hookButton = pyqtSignal(int)  # type: pyqtSignal  # hook thread -> GUI thread
    _hookWheel = pyqtSignal(int)  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param backend: (str | unicode | QString) 'auto', 'qtgrab' or 'pynput'.
        :param cursorShape: (Qt.CursorShape) Cursor while catching (qtgrab).
        :param clicked: callable | None
        :param wheelTurned: callable | None
        :param keyPressed: callable | None
        :param args: any
        :param kwargs: any
        """
        backend = kwargs.pop('backend', 'auto')  # type: str
        cursorShape = kwargs.pop('cursorShape', Qt.CrossCursor)  # type: int
        clicked = kwargs.pop('clicked', None)  # type: callable | None
        wheelTurned = kwargs.pop('wheelTurned', None)  # type: callable | None
        keyPressed = kwargs.pop('keyPressed', None)  # type: callable | None
        super(GlobalMouseCatcher, self).__init__(*args, **kwargs)
        for signal, slot in ((self.clicked, clicked), (self.wheelTurned, wheelTurned), (self.keyPressed, keyPressed)):
            if callable(slot):
                signal.connect(slot)
        self.__m_backend = u'{}'.format(backend) if u'{}'.format(backend) in ('auto', 'qtgrab', 'pynput') else 'auto'  # type: str
        self.__m_cursorShape = cursorShape  # type: int
        self.__m_active = False  # type: bool
        self.__m_error = ''  # type: str
        self.__m_window = None  # type: _GrabWindow | None
        self.__m_listener = None
        self._hookButton.connect(lambda b: self.clicked.emit(QCursor.pos(), b), Qt.QueuedConnection)
        self._hookWheel.connect(self.wheelTurned.emit, Qt.QueuedConnection)

    # ---------- Helpers ----------
    def getBackendName(self):
        """
        :return: (str | unicode | QString) Backend used by start(): 'qtgrab' or 'pynput'.
        """
        if self.__m_backend != 'auto':
            return self.__m_backend
        return 'pynput' if platform in ('win32', 'darwin') else 'qtgrab'

    def winFilter(self, msg, data):
        """
        Windows low-level hook filter (pynput win32_event_filter): report and swallow buttons / wheel.
        :param msg: (int) WM_* message.
        :param data: MSLLHOOKSTRUCT
        :return: bool
        """
        if msg in WM_BUTTONS:
            self._hookButton.emit(WM_BUTTONS[msg])
        elif msg == WM_MOUSEWHEEL:
            delta = (int(data.mouseData) >> 16) & 0xFFFF  # type: int
            self._hookWheel.emit(delta - 0x10000 if delta >= 0x8000 else delta)
        elif msg not in WM_BUTTONS_UP:
            return True  # Movements pass through untouched.
        if self.__m_listener is not None:
            self.__m_listener.suppress_event()  # Raises inside pynput: the event never reaches other apps.
        return False

    def macIntercept(self, eventType, event):
        """
        macOS event tap (pynput darwin_intercept): report and swallow buttons / wheel.
        :param eventType: (int) kCGEvent* type.
        :param event: CGEventRef
        :return: (CGEventRef | None) None swallows the event.
        """
        if eventType in CG_BUTTONS:
            self._hookButton.emit(CG_BUTTONS[eventType])
            return None
        if eventType in CG_BUTTONS_UP:
            return None
        if eventType == CG_SCROLL:
            try:
                from Quartz import CGEventGetIntegerValueField, kCGScrollWheelEventDeltaAxis1
                self._hookWheel.emit(int(CGEventGetIntegerValueField(event, kCGScrollWheelEventDeltaAxis1)) * 120)
            except:
                pass
            return None
        return event

    def _grab(self):
        """
        X11 maps a new window asynchronously and refuses to grab for a window that is not viewable yet: retry until
        the window system confirms both grabs (up to ~1 s).
        :return: (bool) Pointer and keyboard grabbed.
        """
        for _ in range(40):
            QApplication.processEvents()
            handle = self.__m_window.windowHandle()
            if handle is not None and self.__m_window.isVisible():
                if handle.setMouseGrabEnabled(True) and handle.setKeyboardGrabEnabled(True):
                    return True
            QThread.msleep(25)
        return False

    # ---------- Public API ----------
    @pyqtSlot()
    def start(self):
        """
        :return: (bool) Catching.
        """
        if self.__m_active:
            return True
        self.__m_error = u''  # type: str
        try:
            if self.getBackendName() == 'pynput':
                from pynput import mouse
                self.__m_listener = mouse.Listener(
                    win32_event_filter=self.winFilter, darwin_intercept=self.macIntercept)
                self.__m_listener.daemon = True
                self.__m_listener.start()
            else:
                self.__m_window = _GrabWindow(self)  # type: _GrabWindow
                self.__m_window.show()
                if not self._grab():
                    raise RuntimeError(u'The pointer grab was refused (another application holds it)')
                self.__m_window.grabMouse(QCursor(self.__m_cursorShape))  # Qt-side routing of the grabbed events.
                self.__m_window.grabKeyboard()
        except Exception as e:
            self.__m_error = u'Global mouse capture unavailable: {}'.format(e)  # type: str
            self.stop()
            return False
        self.__m_active = True  # type: bool
        self.activeChanged.emit(True)
        return True

    @pyqtSlot()
    def stop(self):
        """
        :return:
        """
        if self.__m_listener is not None:
            try:
                self.__m_listener.stop()
            except:
                pass
            self.__m_listener = None
        if self.__m_window is not None:
            self.__m_window.releaseKeyboard()
            self.__m_window.releaseMouse()
            self.__m_window.close()
            self.__m_window.deleteLater()
            self.__m_window = None
        if self.__m_active:
            self.__m_active = False  # type: bool
            self.activeChanged.emit(False)

    def isActive(self):
        """
        :return: bool
        """
        return self.__m_active

    def getError(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_error

    def getBackend(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_backend

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setBackend(self, backend):
        """
        :param backend: (str | unicode | QString) 'auto', 'qtgrab' or 'pynput' (used at the next start()).
        :return:
        """
        self.__m_backend = u'{}'.format(backend) if u'{}'.format(backend) in ('auto', 'qtgrab', 'pynput') else 'auto'  # type: str

    # ---------- Properties ----------
    backend = pyqtProperty('QString', fget=getBackend, fset=setBackend)  # type: pyqtProperty
    active = pyqtProperty(bool, fget=isActive, notify=activeChanged)  # type: pyqtProperty
