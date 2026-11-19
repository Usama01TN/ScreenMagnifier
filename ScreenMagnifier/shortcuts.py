# -*- coding: utf-8 -*-
"""
Keyboard shortcuts of every feature - the single registry used by the window actions, the zoomer's global hotkeys
and the Shortcuts tab.
Scopes:
    window : active while the Screen Magnifier window has focus; a primary and an alternate shortcut.
    global : system-wide hotkeys (also in other applications and games), one shortcut each; saved by the zoomer
             controller (AdvancedOverlayController.setHotkey()).
"""
from ManyQt.QtCore import QObject, QSettings, pyqtSignal, pyqtSlot

SHORTCUTS = [  # (scope, name, group, label, defaults)
    ('window', 'selectRegion', 'Magnifier', 'Select a region', ('Ctrl+R', '')),
    ('window', 'followCursor', 'Magnifier', 'Follow the mouse cursor', ('F', '')),
    ('window', 'freeze', 'Magnifier', 'Freeze / unfreeze', ('Space', '')),
    ('window', 'viewZoomIn', 'Magnifier', 'Zoom in', ('+', '=')),
    ('window', 'viewZoomOut', 'Magnifier', 'Zoom out', ('-', '')),
    ('window', 'viewFit', 'Magnifier', 'Fit the region', ('0', '')),
    ('window', 'saveSnapshot', 'Magnifier', 'Save the zoomed image', ('Ctrl+S', '')),
    ('window', 'copySnapshot', 'Magnifier', 'Copy the zoomed image', ('Ctrl+C', '')),
    ('global', 'toggle', 'Zoomer', 'Show / hide the zoomer', ('Ctrl+Alt+Z',)),
    ('global', 'zoomIn', 'Zoomer', 'Zoomer: zoom in', ('Ctrl+Alt+=',)),
    ('global', 'zoomOut', 'Zoomer', 'Zoomer: zoom out', ('Ctrl+Alt+-',)),
    ('global', 'pinTarget', 'Zoomer', 'Pin the zoomer target at the mouse', ('Ctrl+Alt+X',)),
    ('global', 'cycleTarget', 'Zoomer', 'Cycle the zoomer target', ('Ctrl+Alt+C',)),
    ('global', 'copyZoomerColor', 'Colors', 'Copy the zoomer color code', ('Ctrl+Alt+K',)),
    ('global', 'screenPicker', 'Colors', 'Screen color picker: start / copy', ('Ctrl+Alt+P',)),
    ('global', 'facePointer', 'Faces', 'Face pointer: on / off', ('Ctrl+Alt+F',)),
    ('window', 'screenPickerWindow', 'Colors', 'Screen color picker', ('Ctrl+Shift+P', '')),
    ('window', 'eyedropper', 'Colors', 'Eyedropper on the magnifier on / off', ('I', '')),
    ('window', 'stopEyedropper', 'Colors', 'Stop the eyedropper', ('Esc', '')),
    ('window', 'copyHoveredColor', 'Colors', 'Copy the color under the mouse', ('C', '')),
    ('window', 'pinOnTop', 'Window', 'Keep the window on top', ('T', '')),
    ('window', 'toggleSidePanel', 'Window', 'Show / hide the side panel', ('Ctrl+,', '')),
    ('window', 'quit', 'Window', 'Quit', ('Ctrl+Q', '')),
]  # type: list[tuple]

HOTKEY_ACTIONS = [(name, label, defaults[0]) for scope, name, group, label, defaults in SHORTCUTS
                  if scope == 'global']  # type: list[tuple[str, str, str]]  # For the zoomer controller.


def shortcutInfo(scope, name):
    """
    :param scope: str | unicode | QString
    :param name: str | unicode | QString
    :return: (tuple | None) Registry entry.
    """
    return next((s for s in SHORTCUTS if s[0] == scope and s[1] == name), None)


def defaultsOf(scope, name):
    """
    :param scope: str | unicode | QString
    :param name: str | unicode | QString
    :return: (list[str | unicode | QString]) Default sequences.
    """
    info = shortcutInfo(scope, name)
    return list(info[4]) if info else []


class ShortcutStore(QObject):
    """
    ShortcutStore class: saved window shortcuts (primary | alternate) of every registry action.
    """
    changed = pyqtSignal('QString')  # type: pyqtSignal  # window shortcut name

    def __init__(self, *args, **kwargs):
        """
        :param settings: (QSettings | None) None = ScreenMagnifier / Shortcuts.
        :param args: any
        :param kwargs: any
        """
        settings = kwargs.pop('settings', None)  # type: QSettings | None
        super(ShortcutStore, self).__init__(*args, **kwargs)
        self.__m_settings = settings if settings is not None else QSettings('ScreenMagnifier', 'Shortcuts')

    def get(self, name):
        """
        :param name: str | unicode | QString
        :return: (list[str | unicode | QString]) [primary, alternate] ('' = none).
        """
        defaults = (defaultsOf('window', name) + ['', ''])[:2]  # type: list
        saved = self.__m_settings.value('window/' + u'{}'.format(name), None)
        if saved is None:
            return defaults
        return (u'{}'.format(saved).split('|') + ['', ''])[:2]

    def sequences(self, name):
        """
        :param name: str | unicode | QString
        :return: (list[str | unicode | QString]) Non-empty sequences, for QAction.setShortcuts().
        """
        return [s for s in self.get(name) if s]

    def set(self, name, slot, sequence):
        """
        :param name: str | unicode | QString
        :param slot: (int) 0 primary, 1 alternate.
        :param sequence: (str | unicode | QString) Qt portable text, '' = none.
        :return:
        """
        values = self.get(name)  # type: list
        values[int(slot)] = u'{}'.format(sequence)
        if values == (defaultsOf('window', name) + ['', ''])[:2]:
            self.__m_settings.remove('window/' + u'{}'.format(name))  # Default: nothing saved, future defaults apply.
        else:
            self.__m_settings.setValue('window/' + u'{}'.format(name), '|'.join(values))
        self.changed.emit(u'{}'.format(name))

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def reset(self, name):
        """
        :param name: str | unicode | QString
        :return:
        """
        self.__m_settings.remove('window/' + u'{}'.format(name))
        self.changed.emit(u'{}'.format(name))
