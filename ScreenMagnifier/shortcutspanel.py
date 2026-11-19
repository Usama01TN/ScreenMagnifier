# -*- coding: utf-8 -*-
"""
ShortcutsPanel: the Shortcuts tab - every keyboard shortcut of every feature, editable, with conflict detection.
Window shortcuts are saved by ShortcutStore, global hotkeys by the zoomer controller (they work in other applications
and games). Global hotkeys are suspended while one is recorded, so pressing the current keys does not trigger them.
"""
from ManyQt.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QPushButton, QScrollArea, QFrame
from ManyQt.QtCore import Qt
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .shortcuts import SHORTCUTS, ShortcutStore, defaultsOf
    from .shortcuteditor import ShortcutEditorWidget
except:
    from shortcuts import SHORTCUTS, ShortcutStore, defaultsOf
    from shortcuteditor import ShortcutEditorWidget

PANEL_QSS = """
QWidget#shortcutContent { background: transparent; }
QLabel[role="title"] { color: #9AA3B8; font-size: 10px; font-weight: bold; letter-spacing: 1px; padding-top: 10px; }
QLabel[role="hint"] { color: #7C8498; font-size: 10px; }
"""  # type: str


class ShortcutsPanel(QScrollArea):
    """
    ShortcutsPanel class.
    """

    def __init__(self, *args, **kwargs):
        """
        :param store: ShortcutStore
        :param controller: AdvancedOverlayController (global hotkeys).
        :param args: any
        :param kwargs: any
        """
        store = kwargs.pop('store', None)  # type: ShortcutStore
        controller = kwargs.pop('controller', None)
        super(ShortcutsPanel, self).__init__(*args, **kwargs)
        self.__m_store = store  # type: ShortcutStore
        self.__m_ctrl = controller
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(300)
        content = QWidget()  # type: QWidget
        content.setObjectName('shortcutContent')
        content.setStyleSheet(PANEL_QSS)
        lay = QVBoxLayout(content)  # type: QVBoxLayout
        lay.setContentsMargins(14, 6, 14, 14)
        lay.setSpacing(6)
        title = QLabel(self.tr(u'KEYBOARD SHORTCUTS'))  # type: QLabel
        title.setProperty('role', 'title')
        lay.addWidget(title)
        self.__m_global = QCheckBox(self.tr(u'Global hotkeys: work in other applications and games'))  # type: QCheckBox
        self.__m_global.setChecked(controller.isHotkeysEnabled())
        self.__m_global.toggled.connect(controller.setHotkeysEnabled)
        lay.addWidget(self.__m_global)
        self.__m_backend = QLabel()  # type: QLabel
        self.__m_backend.setProperty('role', 'hint')
        self.__m_backend.setWordWrap(True)
        lay.addWidget(self.__m_backend)
        self.__m_editor = ShortcutEditorWidget(actions=self._actions())  # type: ShortcutEditorWidget
        self.__m_editor.shortcutChanged.connect(self._onChanged)
        self.__m_editor.recordingChanged.connect(self._onRecording)
        lay.addWidget(self.__m_editor)
        reset = QPushButton(self.tr(u'Reset every shortcut to its default'))  # type: QPushButton
        reset.setFocusPolicy(Qt.NoFocus)
        reset.clicked.connect(self.__m_editor.resetAll)
        lay.addWidget(reset)
        hint = QLabel(self.tr(u'Click a field and press the new keys. "In the window" shortcuts work while this window '
                              u'is active; "everywhere" hotkeys work in any application or game. \u2713 registered, '
                              u'\u2717 refused (taken by another application).'))  # type: QLabel
        hint.setProperty('role', 'hint')
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)
        self.setWidget(content)
        store.changed.connect(lambda name: self.__m_editor.updateShortcut('window', name, store.get(name)))
        controller.getHotkeys().registrationChanged.connect(self.refreshStatus)
        controller.settingsChanged.connect(self.refreshStatus)
        self.refreshStatus()

    def _actions(self):
        """
        :return: (list[dict]) Registry entries with their current values, for the editor.
        """
        out = []  # type: list
        for scope, name, group, label, defaults in SHORTCUTS:
            values = self.__m_store.get(name) if scope == 'window' else [self.__m_ctrl.getHotkey(name)]  # type: list
            out.append({'name': name, 'scope': scope, 'group': self.tr(group), 'label': self.tr(label),
                        'defaults': list(defaults), 'values': values})
        return out

    def _onChanged(self, name, scope, slot, keys):
        """
        :param name: str | unicode | QString
        :param scope: str | unicode | QString
        :param slot: int
        :param keys: str | unicode | QString
        :return:
        """
        if u'{}'.format(scope) == 'global':
            self.__m_ctrl.setHotkey(u'{}'.format(name), u'{}'.format(keys))
        else:
            self.__m_store.set(u'{}'.format(name), int(slot), u'{}'.format(keys))

    def _onRecording(self, recording):
        """
        :param recording: bool
        :return:
        """
        self.__m_ctrl.getHotkeys().setEnabled(False if recording else self.__m_ctrl.isHotkeysEnabled())

    def refreshStatus(self):
        """
        :return:
        """
        hk = self.__m_ctrl.getHotkeys()
        self.__m_global.blockSignals(True)
        self.__m_global.setChecked(self.__m_ctrl.isHotkeysEnabled())
        self.__m_global.blockSignals(False)
        for scope, name, group, label, defaults in SHORTCUTS:
            if scope == 'global':
                self.__m_editor.updateShortcut('global', name, [self.__m_ctrl.getHotkey(name)])
                state = hk.getStatus(name)
                self.__m_editor.setStatus(name, state, {True: self.tr(u'Registered'), False: self.tr(
                    u'Could not register: invalid, or already used by another application')}.get(state, ''))
        backend = {'windows': 'Windows RegisterHotKey', 'pynput': 'pynput'}.get(hk.getBackendName(), 'none')
        self.__m_backend.setText(hk.getError() or self.tr(u'Global hotkeys backend: {}').format(backend))

    def getEditor(self):
        """
        :return: ShortcutEditorWidget
        """
        return self.__m_editor
