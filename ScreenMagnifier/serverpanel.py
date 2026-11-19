# -*- coding: utf-8 -*-
"""
ServerPanel: the Server tab - connect to an analysis server, choose what to offload (upscaling of the magnifier
and of the zoomer, color / face analysis), transfer quality, live statistics, and a button to start a
server on this computer. Every setting is saved with QSettings (the token included, in the user's settings).
"""
from ManyQt.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel, QComboBox, QCheckBox, QPushButton, QFrame, \
    QScrollArea, QLineEdit, QSpinBox
from ManyQt.QtCore import Qt, QSettings, QTimer, QProcess, QElapsedTimer, pyqtSignal, pyqtSlot
from sys import path, executable, platform
from os.path import dirname, join, isfile
import sys

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .analysiscontroller import AnalysisController
    from .remoteclient import RemoteClient
    from .netprotocol import DEFAULT_PORT
except:
    from analysiscontroller import AnalysisController
    from remoteclient import RemoteClient
    from netprotocol import DEFAULT_PORT

PANEL_QSS = """
QWidget#serverContent { background: transparent; }
QLabel[role="title"] { color: #9AA3B8; font-size: 10px; font-weight: bold; letter-spacing: 1px; padding-top: 10px; }
QLabel[role="hint"] { color: #7C8498; font-size: 10px; }
QLabel[role="mono"] { color: #E8EBF2; font-family: monospace; }
QLineEdit, QSpinBox { background: #2A2E3A; color: #E8EBF2; border: 1px solid #3A3F50; border-radius: 6px;
                      padding: 4px 6px; }
QPushButton[role="primary"] { background: #3A4BD8; border-color: #4F8BFF; font-weight: bold; padding: 7px; }
"""  # type: str
STATE_TEXT = {'disconnected': ('#7C8498', 'Disconnected'), 'connecting': ('#FFB86B', 'Connecting...'),
              'authenticating': ('#FFB86B', 'Authenticating...'), 'ready': ('#43C16A', 'Connected'),
              'error': ('#FF5A6E', 'Error')}  # type: dict
QUALITY = [('fast', 'Fast (JPEG 85)'), ('balanced', 'Balanced (JPEG 92-95, near lossless)'),
           ('lossless', 'Lossless (PNG: exact pixels, slower)')]  # type: list


class ServerPanel(QScrollArea):
    """
    ServerPanel class.
    """
    offloadChanged = pyqtSignal()  # type: pyqtSignal
    notify = pyqtSignal('QString')  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param client: RemoteClient
        :param analysis: AnalysisController
        :param upscaler: (Upscaler) Local upscaler whose method / sharpness the server mirrors by default.
        :param settings: (QSettings | None) None = ScreenMagnifier / Server.
        :param args: any
        :param kwargs: any
        """
        client = kwargs.pop('client', None)  # type: RemoteClient
        analysis = kwargs.pop('analysis', None)  # type: AnalysisController
        upscaler = kwargs.pop('upscaler', None)
        settings = kwargs.pop('settings', None)  # type: QSettings | None
        super(ServerPanel, self).__init__(*args, **kwargs)
        self.__m_client = client  # type: RemoteClient
        self.__m_analysis = analysis  # type: AnalysisController
        self.__m_upscaler = upscaler
        self.__m_settings = settings if settings is not None else QSettings('ScreenMagnifier', 'Server')
        self.__m_process = None  # type: QProcess | None
        self.__m_lastBytes = (0, 0)  # type: tuple
        self.__m_savedMethod = -1  # type: int  # Server method chosen by the user (-1 = mirror Settings).
        self.__m_clock = QElapsedTimer()  # type: QElapsedTimer
        self.__m_clock.start()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(260)
        content = QWidget()  # type: QWidget
        content.setObjectName('serverContent')
        content.setStyleSheet(PANEL_QSS)
        self.__m_layout = QVBoxLayout(content)  # type: QVBoxLayout
        self.__m_layout.setContentsMargins(14, 6, 14, 14)
        self.__m_layout.setSpacing(6)
        self._build()
        self.__m_layout.addStretch(1)
        self.setWidget(content)
        self._load()
        client.stateChanged.connect(self._onState)
        client.errorOccurred.connect(self._onError)
        if upscaler is not None:
            upscaler.methodChanged.connect(lambda *a: self._syncMethod())
            upscaler.sharpnessChanged.connect(lambda *a: self._syncMethod())
        self.__m_stats = QTimer(self)  # type: QTimer
        self.__m_stats.timeout.connect(self._updateStats)
        self.__m_stats.start(1000)
        self._onState(client.getState())
        if self.__m_autoConnect.isChecked():
            QTimer.singleShot(500, self._connect)

    # ---------- Building ----------
    @staticmethod
    def _label(text, role):
        """
        :param text: str | unicode | QString
        :param role: str | unicode | QString
        :return: QLabel
        """
        lbl = QLabel(text)  # type: QLabel
        lbl.setProperty('role', role)
        lbl.setWordWrap(role == 'hint')
        return lbl

    def _build(self):
        """
        :return:
        """
        lay = self.__m_layout  # type: QVBoxLayout
        lay.addWidget(ServerPanel._label(self.tr(u'CONNECTION'), 'title'))
        grid = QGridLayout()  # type: QGridLayout
        self.__m_host = QLineEdit()  # type: QLineEdit
        self.__m_host.setPlaceholderText('192.168.1.20')
        self.__m_port = QSpinBox()  # type: QSpinBox
        self.__m_port.setRange(1, 65535)
        self.__m_token = QLineEdit()  # type: QLineEdit
        self.__m_token.setEchoMode(QLineEdit.Password)
        self.__m_token.setPlaceholderText(self.tr(u'shared secret (recommended)'))
        for row, (text, w) in enumerate(((self.tr(u'Host'), self.__m_host), (self.tr(u'Port'), self.__m_port),
                                         (self.tr(u'Token'), self.__m_token))):
            grid.addWidget(QLabel(text), row, 0)
            grid.addWidget(w, row, 1)
        lay.addLayout(grid)
        self.__m_connect = QPushButton()  # type: QPushButton
        self.__m_connect.setProperty('role', 'primary')
        self.__m_connect.clicked.connect(self._toggleConnection)
        lay.addWidget(self.__m_connect)
        self.__m_state = QLabel()  # type: QLabel
        lay.addWidget(self.__m_state)
        self.__m_autoConnect = QCheckBox(self.tr(u'Connect automatically at startup'))  # type: QCheckBox
        self.__m_autoConnect.toggled.connect(lambda *a: self._save())
        lay.addWidget(self.__m_autoConnect)
        lay.addWidget(ServerPanel._label(self.tr(u'OFFLOAD TO THE SERVER'), 'title'))
        self.__m_offView = QCheckBox(self.tr(u'Upscaling of the magnifier'))  # type: QCheckBox
        self.__m_offLens = QCheckBox(self.tr(u'Upscaling of the zoomer'))  # type: QCheckBox
        self.__m_offAnalysis = QCheckBox(self.tr(u'Color and face analysis'))  # type: QCheckBox
        for box in (self.__m_offView, self.__m_offLens, self.__m_offAnalysis):
            box.toggled.connect(self._onOffload)
            lay.addWidget(box)
        lay.addWidget(QLabel(self.tr(u'Server upscaling method')))
        self.__m_method = QComboBox()  # type: QComboBox
        self.__m_method.currentIndexChanged.connect(lambda *a: (self._syncMethod(), self._save()))
        lay.addWidget(self.__m_method)
        lay.addWidget(QLabel(self.tr(u'Image quality')))
        self.__m_quality = QComboBox()  # type: QComboBox
        for data, text in QUALITY:
            self.__m_quality.addItem(self.tr(text), data)
        self.__m_quality.currentIndexChanged.connect(lambda *a: (self._applyQuality(), self._save()))
        lay.addWidget(self.__m_quality)
        lay.addWidget(ServerPanel._label(self.tr(u'STATISTICS'), 'title'))
        self.__m_statsLabel = ServerPanel._label('-', 'mono')  # type: QLabel
        lay.addWidget(self.__m_statsLabel)
        lay.addWidget(ServerPanel._label(self.tr(u'SERVER ON THIS COMPUTER'), 'title'))
        self.__m_local = QPushButton(self.tr(u'Start local server'))  # type: QPushButton
        self.__m_local.clicked.connect(self._toggleLocalServer)
        lay.addWidget(self.__m_local)
        self.__m_localState = ServerPanel._label('', 'hint')  # type: QLabel
        lay.addWidget(self.__m_localState)
        lay.addWidget(ServerPanel._label(self.tr(
            u'The server pays off on a stronger computer: run "python server.py --host 0.0.0.0 --token SECRET" '
            u'there, then enter its address and the same token here. Use a token whenever the server listens on '
            u'the network.'), 'hint'))

    # ---------- Settings ----------
    def _load(self):
        """
        :return:
        """
        s = self.__m_settings  # type: QSettings
        flag = lambda v: u'{}'.format(v).lower() in ('1', 'true', 'yes')
        self.__m_host.setText(u'{}'.format(s.value('host', '127.0.0.1')))
        self.__m_port.setValue(int(s.value('port', DEFAULT_PORT)))
        self.__m_token.setText(u'{}'.format(s.value('token', '') or ''))
        for box, key, default in ((self.__m_autoConnect, 'autoConnect', False), (self.__m_offView, 'offView', True),
                                  (self.__m_offLens, 'offLens', True), (self.__m_offAnalysis, 'offAnalysis', True)):
            box.blockSignals(True)
            box.setChecked(flag(s.value(key, default)))
            box.blockSignals(False)
        self.__m_quality.blockSignals(True)
        self.__m_quality.setCurrentIndex(max(0, self.__m_quality.findData(u'{}'.format(s.value('quality', 'balanced')))))
        self.__m_quality.blockSignals(False)
        self.__m_savedMethod = int(s.value('method', -1))  # type: int
        self._fillMethods()
        self._applyQuality()
        self.__m_analysis.setUseRemote(self.__m_offAnalysis.isChecked())

    def _save(self):
        """
        :return:
        """
        s = self.__m_settings  # type: QSettings
        for key, value in (('host', self.__m_host.text().strip()), ('port', self.__m_port.value()),
                           ('token', self.__m_token.text()), ('autoConnect', self.__m_autoConnect.isChecked()),
                           ('offView', self.__m_offView.isChecked()), ('offLens', self.__m_offLens.isChecked()),
                           ('offAnalysis', self.__m_offAnalysis.isChecked()),
                           ('quality', self.__m_quality.currentData()),
                           ('method', self.__m_method.currentData() if self.__m_method.count() else -1)):
            s.setValue(key, value)

    def _fillMethods(self):
        """
        Same as the Settings tab, or any method the server offers (it may have AI models this computer has not).
        :return:
        """
        self.__m_method.blockSignals(True)
        self.__m_method.clear()
        self.__m_method.addItem(self.tr(u'Same as the Settings tab'), -1)
        for m, name in self.__m_client.getServerInfo().get('methods', []):
            self.__m_method.addItem(self.tr(u'Server: {}').format(name), int(m))
        self.__m_method.setCurrentIndex(max(0, self.__m_method.findData(self.__m_savedMethod)))
        self.__m_method.blockSignals(False)
        self._syncMethod()

    def _syncMethod(self):
        """
        :return:
        """
        data = self.__m_method.currentData()  # type: int
        if data is None or int(data) < 0:
            if self.__m_upscaler is not None:
                self.__m_client.setMethod(int(self.__m_upscaler.getMethod()))
                self.__m_client.setSharpness(float(self.__m_upscaler.getSharpness()))
        else:
            self.__m_client.setMethod(int(data))
            self.__m_savedMethod = int(data)  # type: int
        self.offloadChanged.emit()

    def _applyQuality(self):
        """
        :return:
        """
        q = self.__m_quality.currentData()  # type: str
        lossless = q == 'lossless'  # type: bool
        self.__m_client.setResultFormat('PNG' if lossless else 'JPG')
        self.__m_client.setUploadFormat('PNG' if lossless else 'JPG')
        self.__m_client.setQuality(85 if q == 'fast' else 92)
        self.__m_client.setUploadQuality(85 if q == 'fast' else 95)

    # ---------- Slots ----------
    @pyqtSlot()
    def _toggleConnection(self):
        """
        :return:
        """
        if self.__m_client.getState() in ('ready', 'connecting', 'authenticating'):
            self.__m_client.disconnectFromServer()
        else:
            self._connect()

    @pyqtSlot()
    def _connect(self):
        """
        :return:
        """
        self._save()
        c = self.__m_client  # type: RemoteClient
        c.setHost(self.__m_host.text().strip() or '127.0.0.1')
        c.setPort(self.__m_port.value())
        c.setToken(self.__m_token.text())
        c.connectToServer()

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def _onState(self, state):
        """
        :param state: str | unicode | QString
        :return:
        """
        color, text = STATE_TEXT.get(u'{}'.format(state), ('#7C8498', u'{}'.format(state)))
        info = self.__m_client.getServerInfo()  # type: dict
        if u'{}'.format(state) == 'ready' and info:
            text += self.tr(u' to {}').format(info.get('server', '?'))
            self._fillMethods()
        self.__m_state.setText('<span style="color:{}">&#9679;</span> {}'.format(color, self.tr(text)))
        busy = u'{}'.format(state) in ('ready', 'connecting', 'authenticating')  # type: bool
        self.__m_connect.setText(self.tr(u'Disconnect') if busy else self.tr(u'Connect'))
        for w in (self.__m_host, self.__m_port, self.__m_token):
            w.setEnabled(not busy)
        self.offloadChanged.emit()

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def _onError(self, message):
        """
        :param message: str | unicode | QString
        :return:
        """
        self.__m_state.setToolTip(self.tr(message))
        self.notify.emit(self.tr(message))

    @pyqtSlot()
    def _onOffload(self):
        """
        :return:
        """
        self.__m_analysis.setUseRemote(self.__m_offAnalysis.isChecked())
        self._save()
        self.offloadChanged.emit()

    @pyqtSlot()
    def _updateStats(self):
        """
        :return:
        """
        c = self.__m_client  # type: RemoteClient
        secs = max(0.001, self.__m_clock.restart() / 1000.0)  # type: float
        counts = c.takeCounts()  # type: dict
        sent, received = c.getBytes()
        up = (sent - self.__m_lastBytes[0]) / 1024.0 / secs  # type: float
        down = (received - self.__m_lastBytes[1]) / 1024.0 / secs  # type: float
        self.__m_lastBytes = (sent, received)  # type: tuple
        if not c.isReady():
            self.__m_statsLabel.setText('-')
            return
        self.__m_statsLabel.setText(
            'latency   {:.0f} ms\nmagnifier {:.0f} fps\nlens      {:.0f} fps\nanalysis  {:.0f} / s\n'
            'upload    {:.0f} KB/s\ndownload  {:.0f} KB/s'.format(
                max(0.0, c.getLatency()), counts.get('view', 0) / secs, counts.get('lens', 0) / secs,
                                          (counts.get('analysis:view', 0) + counts.get('analysis:lens', 0)) / secs, up,
                down))

    @pyqtSlot()
    def _toggleLocalServer(self):
        """
        :return:
        """
        if self.__m_process is not None and self.__m_process.state() != QProcess.NotRunning:
            self.stopLocalServer()
            return
        self._save()
        proc = QProcess(self)  # type: QProcess
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.setWorkingDirectory(dirname(__file__))
        proc.readyRead.connect(lambda: self.__m_localState.setText(
            u'{}'.format(bytes(proc.readAll().data()).decode('utf-8', 'replace')).strip().splitlines()[-1][-160:]))
        proc.finished.connect(lambda *a: (self.__m_local.setText(self.tr(u'Start local server')),
                                          self.__m_localState.setText(self.tr(u'Local server stopped.'))))
        args = ['--port', u'{}'.format(self.__m_port.value())]  # type: list
        if self.__m_token.text():
            args += ['--token', self.__m_token.text()]
        bundled = join(dirname(executable), 'ScreenMagnifierServer' + ('.exe' if platform == 'win32' else ''))
        if getattr(sys, 'frozen', False) and isfile(bundled):  # Packaged release: the bundled server binary.
            proc.start(bundled, args)
        else:
            proc.start(executable, [join(dirname(__file__), 'server.py')] + args)
        self.__m_process = proc  # type: QProcess
        self.__m_local.setText(self.tr(u'Stop local server'))
        self.__m_localState.setText(self.tr(u'Starting...'))
        if self.__m_host.text().strip() in ('', '127.0.0.1', 'localhost'):
            QTimer.singleShot(2500, self._connect)

    # ---------- Public API ----------
    @pyqtSlot()
    def stopLocalServer(self):
        """
        :return:
        """
        if self.__m_process is not None and self.__m_process.state() != QProcess.NotRunning:
            self.__m_process.terminate()
            if not self.__m_process.waitForFinished(2000):
                self.__m_process.kill()

    def isOffloadView(self):
        """
        :return: (bool) Upscale the magnifier on the server right now.
        """
        return self.__m_offView.isChecked() and self.__m_client.isReady()

    def isOffloadLens(self):
        """
        :return: (bool) Upscale the zoomer on the server right now.
        """
        return self.__m_offLens.isChecked() and self.__m_client.isReady()
