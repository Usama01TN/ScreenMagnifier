# -*- coding: utf-8 -*-
"""
ShortcutEditorWidget: edit the keyboard shortcuts of an application.
- Actions are grouped (e.g. "Magnifier", "Zoomer", "Colors") and can be filtered by name or key.
- Two scopes: 'window' (active while the application window has focus, primary + alternate shortcut) and 'global'
  (system-wide hotkeys, one shortcut, with a registration status).
- Conflicts are flagged live: the same key twice in one scope is an error (red); a window shortcut equal to a global
  hotkey is a warning (orange: the global hotkey takes the key everywhere).
- Click a field and press the keys to record; per-row reset / clear, resetAll().
- recordingChanged(bool) lets the owner suspend global hotkeys while one is being recorded.
"""
from ManyQt.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton, QKeySequenceEdit
from ManyQt.QtCore import Qt, QEvent, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtGui import QKeySequence

STYLE = """
QLabel[role="group"] { color: #9AA3B8; font-size: 10px; font-weight: bold; letter-spacing: 1px; padding-top: 10px; }
QLabel[role="scope"] { color: #7C8498; font-size: 9px; }
QLabel[role="ok"] { color: #4CC38A; } QLabel[role="bad"] { color: #F2555A; } QLabel[role="hint"] { color: #7C8498; }
QKeySequenceEdit[conflict="error"] QLineEdit { border: 1px solid #F2555A; }
QKeySequenceEdit[conflict="warning"] QLineEdit { border: 1px solid #F0A030; }
QPushButton[role="small"] { padding: 2px 6px; }
"""  # type: str


def normalize(sequence):
    """
    :param sequence: (str | QKeySequence) Any spelling ('ctrl+alt+p', QKeySequence...).
    :return: (str | unicode | QString) First chord in Qt portable text ('Ctrl+Alt+P'), '' for none.
    """
    seq = QKeySequence(sequence) if not isinstance(sequence, QKeySequence) else sequence  # type: QKeySequence
    if seq.isEmpty():
        return ''
    return u'{}'.format(seq.toString(QKeySequence.PortableText)).split(', ')[0]


class ShortcutEditorWidget(QWidget):
    """
    ShortcutEditorWidget class.
    """
    shortcutChanged = pyqtSignal('QString', 'QString', int, 'QString')  # type: pyqtSignal  # name, scope, slot, keys
    recordingChanged = pyqtSignal(bool)  # type: pyqtSignal
    conflictsChanged = pyqtSignal(int)  # type: pyqtSignal  # number of errors

    def __init__(self, *args, **kwargs):
        """
        :param actions: (list[dict]) {'name', 'label', 'group', 'scope': 'window' | 'global', 'defaults': [str, ...],
            'values': [str, ...]} - window actions have 2 slots (primary, alternate), global ones 1.
        :param filterText: (str | unicode | QString) Initial filter.
        :param shortcutChanged: callable | None
        :param recordingChanged: callable | None
        :param args: any
        :param kwargs: any
        """
        actions = kwargs.pop('actions', [])  # type: list
        filterText = kwargs.pop('filterText', '')  # type: str
        shortcutChanged = kwargs.pop('shortcutChanged', None)  # type: callable | None
        recordingChanged = kwargs.pop('recordingChanged', None)  # type: callable | None
        super(ShortcutEditorWidget, self).__init__(*args, **kwargs)
        for signal, slot in ((self.shortcutChanged, shortcutChanged), (self.recordingChanged, recordingChanged)):
            if callable(slot):
                signal.connect(slot)
        self.__m_actions = []  # type: list
        self.__m_rows = {}  # type: dict  # (scope, name) -> {'edits': [...], 'status': QLabel, 'widgets': [...]}
        self.__m_groups = {}  # type: dict  # group -> header QLabel
        self.__m_filterText = u'{}'.format(filterText)  # type: str
        self.__m_recording = False  # type: bool
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)  # type: QVBoxLayout
        layout.setContentsMargins(0, 0, 0, 0)
        self.__m_filter = QLineEdit(self.__m_filterText)  # type: QLineEdit
        self.__m_filter.setPlaceholderText(self.tr(u'Search a feature or a key...'))
        self.__m_filter.setClearButtonEnabled(True)
        self.__m_filter.textChanged.connect(self.setFilterText)
        layout.addWidget(self.__m_filter)
        self.__m_grid = QGridLayout()  # type: QGridLayout
        self.__m_grid.setHorizontalSpacing(6)
        self.__m_grid.setVerticalSpacing(3)
        self.__m_grid.setColumnStretch(0, 1)
        layout.addLayout(self.__m_grid)
        self.__m_summary = QLabel()  # type: QLabel
        self.__m_summary.setProperty('role', 'hint')
        self.__m_summary.setWordWrap(True)
        layout.addWidget(self.__m_summary)
        self.setActions(actions)

    # ---------- Building ----------
    def _recorder(self, scope, name, slot):
        """
        :param scope: str | unicode | QString
        :param name: str | unicode | QString
        :param slot: int
        :return: QKeySequenceEdit
        """
        edit = QKeySequenceEdit()  # type: QKeySequenceEdit
        edit.setMinimumWidth(96)
        edit.installEventFilter(self)
        for inner in edit.findChildren(QLineEdit):  # Focus goes to an internal line edit.
            inner.installEventFilter(self)
        edit.editingFinished.connect(lambda s=scope, n=name, i=slot, e=edit: self._recorded(s, n, i, e))
        return edit

    def _button(self, text, tip, slot):
        """
        :param text: str | unicode | QString
        :param tip: str | unicode | QString
        :param slot: callable
        :return: QPushButton
        """
        b = QPushButton(text)  # type: QPushButton
        b.setProperty('role', 'small')
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(slot)
        return b

    def _build(self):
        """
        :return:
        """
        while self.__m_grid.count():
            item = self.__m_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.__m_rows, self.__m_groups = {}, {}
        row = 0  # type: int
        for a in self.__m_actions:
            group = u'{}'.format(a.get('group', ''))  # type: str
            if group not in self.__m_groups:
                header = QLabel(group.upper())  # type: QLabel
                header.setProperty('role', 'group')
                self.__m_grid.addWidget(header, row, 0, 1, 5)
                self.__m_groups[group] = header
                row += 1
            scope, name = u'{}'.format(a.get('scope', 'window')), u'{}'.format(a['name'])  # type: str, str
            label = QLabel(u'{}'.format(a.get('label', name)))  # type: QLabel
            label.setWordWrap(True)
            scopeLabel = QLabel(self.tr(u'everywhere') if scope == 'global' else self.tr(u'in the window'))  # type: QLabel
            scopeLabel.setProperty('role', 'scope')
            left = QWidget()  # type: QWidget
            box = QVBoxLayout(left)  # type: QVBoxLayout
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(0)
            box.addWidget(label)
            box.addWidget(scopeLabel)
            slots = 1 if scope == 'global' else 2  # type: int
            edits = [self._recorder(scope, name, i) for i in range(slots)]  # type: list
            values = list(a.get('values', [])) + [''] * slots  # type: list
            for i, e in enumerate(edits):
                e.setKeySequence(QKeySequence(values[i]))
                e.setToolTip(self.tr(u'Click, then press the keys. Default: {}').format(
                    ' / '.join(d for d in a.get('defaults', []) if d) or self.tr(u'none')))
            status = QLabel()  # type: QLabel
            status.setFixedWidth(14)
            reset = self._button('\u21ba', self.tr(u'Back to the default'), lambda c=False, s=scope, n=name: self.resetShortcut(s, n))
            clear = self._button('\u2715', self.tr(u'Remove the shortcut(s)'), lambda c=False, s=scope, n=name: self.clearShortcut(s, n))
            self.__m_grid.addWidget(left, row, 0)
            self.__m_grid.addWidget(edits[0], row, 1)
            if slots > 1:
                self.__m_grid.addWidget(edits[1], row, 2)
            self.__m_grid.addWidget(status, row, 3)
            tools = QWidget()  # type: QWidget
            t = QVBoxLayout(tools)  # type: QVBoxLayout
            t.setContentsMargins(0, 0, 0, 0)
            t.setSpacing(2)
            t.addWidget(reset)
            t.addWidget(clear)
            self.__m_grid.addWidget(tools, row, 4)
            self.__m_rows[(scope, name)] = {'action': a, 'edits': edits, 'status': status,
                                            'widgets': [left] + edits + [status, tools], 'group': group}
            row += 1
        self._applyFilter()
        self._checkConflicts()

    # ---------- Logic ----------
    def _recorded(self, scope, name, slot, edit):
        """
        :param scope: str | unicode | QString
        :param name: str | unicode | QString
        :param slot: int
        :param edit: QKeySequenceEdit
        :return:
        """
        seq = normalize(edit.keySequence())  # type: str  # One chord only.
        edit.blockSignals(True)
        edit.setKeySequence(QKeySequence(seq))
        edit.blockSignals(False)
        edit.clearFocus()
        self._store(scope, name, slot, seq)

    def _store(self, scope, name, slot, seq):
        """
        :param scope: str | unicode | QString
        :param name: str | unicode | QString
        :param slot: int
        :param seq: str | unicode | QString
        :return:
        """
        a = self.__m_rows[(scope, name)]['action']  # type: dict
        values = (list(a.get('values', [])) + ['', ''])[:len(self.__m_rows[(scope, name)]['edits'])]  # type: list
        if values[slot] == seq:
            self._checkConflicts()
            return
        values[slot] = seq
        a['values'] = values
        self._checkConflicts()
        self.shortcutChanged.emit(name, scope, slot, seq)

    def _checkConflicts(self):
        """
        Mark every key used twice: same scope = error, window vs global = warning.
        :return:
        """
        uses = {}  # type: dict  # key -> [(scope, name, label)]
        for (scope, name), r in self.__m_rows.items():
            for v in r['action'].get('values', []):
                if v:
                    uses.setdefault(normalize(v), []).append((scope, name, r['action'].get('label', name)))
        errors = warnings = 0  # type: int
        for (scope, name), r in self.__m_rows.items():
            for e in r['edits']:
                key = normalize(e.keySequence())  # type: str
                others = [u for u in uses.get(key, []) if (u[0], u[1]) != (scope, name)] if key else []  # type: list
                level = ''  # type: str
                if any(o[0] == scope for o in others):
                    level = 'error'
                elif others:
                    level = 'warning'
                e.setProperty('conflict', level)
                e.setToolTip(self.tr(u'{} is also used by: {}').format(key, ', '.join(o[2] for o in others)) if others
                             else self.tr(u'Click, then press the keys. Default: {}').format(
                    ' / '.join(d for d in r['action'].get('defaults', []) if d) or self.tr(u'none')))
                e.style().unpolish(e)
                e.style().polish(e)
                for inner in e.findChildren(QLineEdit):
                    inner.style().unpolish(inner)
                    inner.style().polish(inner)
                errors += level == 'error'
                warnings += level == 'warning'
        self.__m_summary.setText(
            (self.tr(u'{} conflict(s): the same keys are used twice in one scope (red).').format(errors // 2 or errors)
             if errors else self.tr(u'No conflicts.')) +
            (self.tr(u' Orange: a window shortcut equal to a global hotkey - the global hotkey takes it.')
             if warnings else ''))
        self.conflictsChanged.emit(errors)

    def _applyFilter(self):
        """
        :return:
        """
        text = self.__m_filterText.strip().lower()  # type: str
        shown = {}  # type: dict
        for (scope, name), r in self.__m_rows.items():
            a = r['action']  # type: dict
            haystack = ' '.join([u'{}'.format(a.get('label', '')), u'{}'.format(a.get('group', '')), name] + list(a.get('values', [])))
            visible = not text or text in haystack.lower()  # type: bool
            for w in r['widgets']:
                w.setVisible(visible)
            shown[r['group']] = shown.get(r['group'], False) or visible
        for group, header in self.__m_groups.items():
            header.setVisible(shown.get(group, False))

    # ---------- Qt overrides ----------
    def eventFilter(self, obj, e):
        """
        :param obj: QObject
        :param e: QEvent
        :return: bool
        """
        if e.type() in (QEvent.FocusIn, QEvent.FocusOut) and (
                isinstance(obj, QKeySequenceEdit) or isinstance(obj.parent(), QKeySequenceEdit)):
            recording = e.type() == QEvent.FocusIn  # type: bool
            if recording != self.__m_recording:
                self.__m_recording = recording  # type: bool
                self.recordingChanged.emit(recording)
        return super(ShortcutEditorWidget, self).eventFilter(obj, e)

    # ---------- Public API ----------
    def getActions(self):
        """
        :return: (list[dict]) With the current values.
        """
        return [dict(a) for a in self.__m_actions]

    @pyqtSlot(list)
    def setActions(self, actions):
        """
        :param actions: list[dict]
        :return:
        """
        self.__m_actions = [dict(a, values=list(a.get('values', a.get('defaults', [])))) for a in (actions or [])]
        self._build()

    def valuesOf(self, scope, name):
        """
        :param scope: str | unicode | QString
        :param name: str | unicode | QString
        :return: (list[str | unicode | QString]) Values (primary, alternate...).
        """
        r = self.__m_rows.get((u'{}'.format(scope), u'{}'.format(name)))
        return list(r['action'].get('values', [])) if r else []

    def updateShortcut(self, scope, name, values):
        """
        Show values set elsewhere (no shortcutChanged).
        :param scope: str | unicode | QString
        :param name: str | unicode | QString
        :param values: list[str | unicode | QString]
        :return:
        """
        r = self.__m_rows.get((u'{}'.format(scope), u'{}'.format(name)))
        if r is None:
            return
        r['action']['values'] = list(values)
        for i, e in enumerate(r['edits']):
            if not e.hasFocus():
                e.blockSignals(True)
                e.setKeySequence(QKeySequence((list(values) + ['', ''])[i]))
                e.blockSignals(False)
        self._checkConflicts()

    def resetShortcut(self, scope, name):
        """
        :param scope: str | unicode | QString
        :param name: str | unicode | QString
        :return:
        """
        r = self.__m_rows.get((u'{}'.format(scope), u'{}'.format(name)))
        if r is None:
            return
        defaults = list(r['action'].get('defaults', [])) + ['', '']  # type: list
        for i, e in enumerate(r['edits']):
            e.blockSignals(True)
            e.setKeySequence(QKeySequence(defaults[i]))
            e.blockSignals(False)
            self._store(u'{}'.format(scope), u'{}'.format(name), i, normalize(defaults[i]))

    def clearShortcut(self, scope, name):
        """
        :param scope: str | unicode | QString
        :param name: str | unicode | QString
        :return:
        """
        r = self.__m_rows.get((u'{}'.format(scope), u'{}'.format(name)))
        if r is None:
            return
        for i, e in enumerate(r['edits']):
            e.blockSignals(True)
            e.clear()
            e.blockSignals(False)
            self._store(u'{}'.format(scope), u'{}'.format(name), i, '')

    @pyqtSlot()
    def resetAll(self):
        """
        :return:
        """
        for scope, name in list(self.__m_rows):
            self.resetShortcut(scope, name)

    def setStatus(self, name, state, tip=''):
        """
        Registration status of a global hotkey.
        :param name: str | unicode | QString
        :param state: (bool | None) True registered, False refused, None unknown / unbound.
        :param tip: str | unicode | QString
        :return: None
        """
        r = self.__m_rows.get(('global', u'{}'.format(name)))
        if r is None:
            return
        s = r['status']  # type: QLabel
        s.setText({True: '\u2713', False: '\u2717'}.get(state, ''))
        s.setProperty('role', {True: 'ok', False: 'bad'}.get(state, 'hint'))
        s.setToolTip(tip)
        s.style().unpolish(s)
        s.style().polish(s)

    def conflictCount(self):
        """
        :return: (int) Number of shortcut fields in a same-scope conflict.
        """
        return sum(1 for r in self.__m_rows.values() for e in r['edits'] if e.property('conflict') == 'error')

    def isRecording(self):
        """
        :return: bool
        """
        return self.__m_recording

    def getFilterText(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_filterText

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setFilterText(self, filterText):
        """
        :param filterText: str | unicode | QString
        :return:
        """
        self.__m_filterText = filterText  # type: str
        if self.__m_filter.text() != self.__m_filterText:
            self.__m_filter.setText(self.__m_filterText)
        self._applyFilter()

    # ---------- Properties ----------
    actions = pyqtProperty(list, fget=getActions, fset=setActions)  # type: pyqtProperty
    filterText = pyqtProperty('QString', fget=getFilterText, fset=setFilterText)  # type: pyqtProperty
