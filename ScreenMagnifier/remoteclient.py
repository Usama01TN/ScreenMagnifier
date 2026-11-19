# -*- coding: utf-8 -*-
"""
RemoteClient: offloads upscaling and analysis to an AnalysisServer (server.py) in real time.
Flow control: per channel (e.g. 'view', 'lens') and per analysis source at most ONE request is in flight; a newer
frame replaces the waiting one ("latest frame wins"), so a slow network or server adds latency but never a
growing backlog. RemoteProcessor plugs into MagnifierViewWidget / ZoomOverlay as a normal processor: it never
blocks painting - until the server answers it shows the last server result (if recent) or a fast local scale.
"""
from ManyQt.QtCore import QObject, QTimer, QSize, QElapsedTimer, Qt, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtGui import QImage
from os.path import dirname
from zlib import adler32
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .netprotocol import FrameChannel, encodeImage, decodeImage, DEFAULT_PORT
except:
    from netprotocol import FrameChannel, encodeImage, decodeImage, DEFAULT_PORT

REQUEST_TIMEOUT_MS = 3000  # type: int  # An unanswered request is dropped after this (lost / server stuck).


def imageKey(image):
    """
    Cheap content fingerprint, so the same crop is never sent twice.
    :param image: QImage
    :return: int
    """
    ptr = image.constBits()
    n = image.sizeInBytes() if hasattr(image, 'sizeInBytes') else image.byteCount()  # type: int
    if hasattr(ptr, 'setsize'):
        ptr.setsize(n)
    return adler32(bytes(ptr)) ^ (image.width() << 16) ^ image.height()


def localScale(image, size):
    """
    Fallback processor while waiting for the server.
    :param image: QImage
    :param size: QSize
    :return: QImage
    """
    return image.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


class RemoteProcessor(object):
    """
    RemoteProcessor class: callable(QImage, QSize) -> QImage backed by a RemoteClient channel.
    """

    def __init__(self, client, channel, fallback=None, maxAgeMs=300):
        """
        :param client: RemoteClient
        :param channel: (str | unicode | QString) Channel name ('view', 'lens').
        :param fallback: (callable | None) Used when the server is unavailable (e.g. the local upscaler);
            None = smooth Qt scaling. While waiting for the server a cheap Qt scale is always used, so the
            expensive local processing is never duplicated.
        :param maxAgeMs: (int) How long an older server result may still be shown while waiting.
        """
        self.__m_client = client  # type: RemoteClient
        self.__m_channel = u'{}'.format(channel)  # type: str
        self.__m_fallback = fallback if callable(fallback) else localScale  # type: callable
        self.__m_maxAgeMs = int(maxAgeMs)  # type: int

    def __call__(self, image, size):
        """
        :param image: QImage
        :param size: QSize
        :return: QImage
        """
        return self.process(image, size)

    def process(self, image, size):
        """
        :param image: QImage
        :param size: QSize
        :return: QImage
        """
        client = self.__m_client  # type: RemoteClient
        if not client.isReady():
            return self.__m_fallback(image, size)
        key = (imageKey(image), size.width(), size.height())  # type: tuple
        exact = client.cachedResult(self.__m_channel, key)  # type: QImage | None
        if exact is not None:
            return exact
        client.submitUpscale(self.__m_channel, image, size, key)
        recent = client.recentResult(self.__m_channel, size, self.__m_maxAgeMs)  # type: QImage | None
        return recent if recent is not None else localScale(image, size)

    def getChannel(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_channel


class RemoteClient(QObject):
    """
    RemoteClient class.
    """
    stateChanged = pyqtSignal('QString')  # type: pyqtSignal
    upscaleReady = pyqtSignal('QString')  # type: pyqtSignal
    analysisReady = pyqtSignal('QString', object, object)  # type: pyqtSignal  # source, result dict, mask QImage
    errorOccurred = pyqtSignal('QString')  # type: pyqtSignal
    statsChanged = pyqtSignal()  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param host: str | unicode | QString
        :param port: int
        :param token: (str | unicode | QString) Shared secret expected by the server.
        :param autoReconnect: (bool) Reconnect every 3 s after an unexpected disconnection.
        :param uploadFormat: (str | unicode | QString) 'JPG' (default, fast) or 'PNG' (lossless, slow to encode).
        :param resultFormat: (str | unicode | QString) 'JPG' (default, fast) or 'PNG' (lossless).
        :param quality: (int) JPEG quality 1 .. 100 of the results.
        :param uploadQuality: (int) JPEG quality 1 .. 100 of uploaded frames (95: near lossless, far faster than PNG).
        :param method: (int) Upscaler method the server must use (Upscaler.Method value).
        :param sharpness: (float | int) Server-side sharpening 0 .. 2.
        :param stateChanged: callable | None
        :param errorOccurred: callable | None
        :param args: any
        :param kwargs: any
        """
        host = kwargs.pop('host', '127.0.0.1')  # type: str
        port = kwargs.pop('port', DEFAULT_PORT)  # type: int
        token = kwargs.pop('token', '')  # type: str
        autoReconnect = kwargs.pop('autoReconnect', True)  # type: bool
        uploadFormat = kwargs.pop('uploadFormat', 'JPG')  # type: str
        resultFormat = kwargs.pop('resultFormat', 'JPG')  # type: str
        quality = kwargs.pop('quality', 90)  # type: int
        uploadQuality = kwargs.pop('uploadQuality', 95)  # type: int
        method = kwargs.pop('method', 3)  # type: int
        sharpness = kwargs.pop('sharpness', 0.25)  # type: float
        stateChanged = kwargs.pop('stateChanged', None)  # type: callable | None
        errorOccurred = kwargs.pop('errorOccurred', None)  # type: callable | None
        super(RemoteClient, self).__init__(*args, **kwargs)
        if callable(stateChanged):
            self.stateChanged.connect(stateChanged)
        if callable(errorOccurred):
            self.errorOccurred.connect(errorOccurred)
        self.__m_host = u'{}'.format(host)  # type: str
        self.__m_port = int(port)  # type: int
        self.__m_token = token  # type: str
        self.__m_autoReconnect = bool(autoReconnect)  # type: bool
        self.__m_uploadFormat = 'JPG' if u'{}'.format(uploadFormat).upper() in ('JPG', 'JPEG') else 'PNG'  # type: str
        self.__m_resultFormat = 'PNG' if u'{}'.format(resultFormat).upper() == 'PNG' else 'JPG'  # type: str
        self.__m_quality = max(1, min(100, int(quality)))  # type: int
        self.__m_uploadQuality = max(1, min(100, int(uploadQuality)))  # type: int
        self.__m_method = int(method)  # type: int
        self.__m_sharpness = float(sharpness)  # type: float
        # State.
        self.__m_state = 'disconnected'  # type: str
        self.__m_wanted = False  # type: bool  # The user asked to be connected.
        self.__m_serverInfo = {}  # type: dict
        self.__m_nextId = 1  # type: int
        self.__m_inflight = {}  # type: dict  # id -> (kind, name, key, sentMs, size)
        self.__m_busy = {}  # type: dict  # (kind, name) -> id
        self.__m_pending = {}  # type: dict  # (kind, name) -> args of the newest waiting request
        self.__m_results = {}  # type: dict  # channel -> list of (key, QImage, size, receivedMs), newest last
        self.__m_latencyMs = -1.0  # type: float
        self.__m_counts = {}  # type: dict  # name -> results received (for fps)
        self.__m_clock = QElapsedTimer()  # type: QElapsedTimer
        self.__m_clock.start()
        self.__m_channel = FrameChannel(messageReceived=self._onMessage, connected=self._onConnected,
                                        disconnected=self._onDisconnected, errorOccurred=self._onError,
                                        parent=self)  # type: FrameChannel
        self.__m_reconnect = QTimer(self)  # type: QTimer
        self.__m_reconnect.setSingleShot(True)
        self.__m_reconnect.timeout.connect(self._reconnect)
        self.__m_pinger = QTimer(self)  # type: QTimer
        self.__m_pinger.timeout.connect(self._ping)

    # ---------- Helpers ----------
    def _setState(self, state):
        """
        :param state: (str | unicode | QString) disconnected | connecting | authenticating | ready | error
        :return:
        """
        if state != self.__m_state:
            self.__m_state = state  # type: str
            self.stateChanged.emit(state)

    def _now(self):
        """
        :return: (int) ms since the client was created.
        """
        return int(self.__m_clock.elapsed())

    def _reset(self):
        """
        Forget everything that belonged to the previous connection.
        :return:
        """
        self.__m_inflight, self.__m_busy, self.__m_pending = {}, {}, {}

    @pyqtSlot()
    def _onConnected(self):
        """
        :return:
        """
        self._setState('authenticating')
        self.__m_channel.send({'type': 'hello', 'token': self.__m_token, 'client': 'ScreenMagnifier',
                               'version': 1})

    @pyqtSlot()
    def _onDisconnected(self):
        """
        :return:
        """
        self.__m_pinger.stop()
        self._reset()
        if self.__m_state != 'error':
            self._setState('disconnected')
        if self.__m_wanted and self.__m_autoReconnect:
            self.__m_reconnect.start(3000)

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def _onError(self, message):
        """
        :param message: str | unicode | QString
        :return:
        """
        self.errorOccurred.emit(message)
        if self.__m_state in ('connecting', 'authenticating'):
            self._setState('error')
            if self.__m_wanted and self.__m_autoReconnect:
                self.__m_reconnect.start(3000)

    @pyqtSlot()
    def _reconnect(self):
        """
        :return:
        """
        if self.__m_wanted and self.__m_state != 'ready':
            self._setState('connecting')
            self.__m_channel.connectToHost(self.__m_host, self.__m_port)

    @pyqtSlot()
    def _ping(self):
        """
        Measure latency and expire lost requests.
        :return:
        """
        now = self._now()  # type: int
        for rid, item in list(self.__m_inflight.items()):
            if now - item[3] > REQUEST_TIMEOUT_MS:
                self._finish(rid)
        self.__m_channel.send({'type': 'ping', 't': now})
        self.statsChanged.emit()

    def _finish(self, rid):
        """
        A request is answered (or expired): free its slot and send the waiting one, if any.
        :param rid: int
        :return: (tuple | None) The in-flight record.
        """
        item = self.__m_inflight.pop(rid, None)
        if item is None:
            return None
        slot = (item[0], item[1])  # type: tuple
        if self.__m_busy.get(slot) == rid:
            del self.__m_busy[slot]
        waiting = self.__m_pending.pop(slot, None)
        if waiting is not None:
            if item[0] == 'upscale':
                self.submitUpscale(*waiting)
            else:
                self.requestAnalysis(*waiting)
        return item

    def _onMessage(self, header, payload):
        """
        :param header: dict
        :param payload: bytes
        :return:
        """
        kind = u'{}'.format(header.get('type', ''))  # type: str
        if kind == 'welcome':
            self.__m_serverInfo = dict(header)  # type: dict
            self._setState('ready')
            self.__m_pinger.start(2000)
            self._ping()
        elif kind == 'pong':
            try:
                self.__m_latencyMs = float(self._now() - int(header.get('t')))  # type: float
            except (TypeError, ValueError):
                pass
        elif kind == 'upscaled':
            item = self._finish(header.get('id'))
            image = decodeImage(payload)  # type: QImage
            if item is not None and not image.isNull():
                name = item[1]  # type: str
                results = self.__m_results.setdefault(name, [])  # type: list
                results.append((item[2], image, item[4], self._now()))
                del results[:-3]
                self.__m_counts[name] = self.__m_counts.get(name, 0) + 1
                self.upscaleReady.emit(name)
        elif kind == 'analysis':
            item = self._finish(header.get('id'))
            if item is not None:
                mask = decodeImage(payload) if header.get('hasMask') else QImage()  # type: QImage
                name = item[1]  # type: str
                self.__m_counts['analysis:' + name] = self.__m_counts.get('analysis:' + name, 0) + 1
                result = dict(header.get('result') or {})  # type: dict
                result['origin'] = header.get('origin')  # Screen position of the analysed frame (echoed).
                self.analysisReady.emit(name, result, mask)
        elif kind == 'error':
            if header.get('code') == 'auth':
                self.__m_wanted = False  # type: bool  # Do not hammer a server that refuses us.
                self._setState('error')
            else:
                self._finish(header.get('id'))
            self.errorOccurred.emit(u'Server: {}'.format(header.get('message', 'error')))

    def _send(self, kind, name, key, size, header, image, fmt, quality):
        """
        :param kind: str | unicode | QString
        :param name: str | unicode | QString
        :param key: tuple | None
        :param size: QSize | None
        :param header: dict
        :param image: QImage
        :param fmt: str | unicode | QString
        :param quality: (int) JPEG quality.
        :return: bool
        """
        rid = self.__m_nextId  # type: int
        self.__m_nextId += 1
        header['id'] = rid
        accepted = self.__m_serverInfo.get('formats') if self.__m_serverInfo else None  # older servers: all
        if accepted and fmt not in accepted:  # e.g. a phone server without a JPEG codec: lossless RAWZ instead
            fmt = 'RAWZ'  # type: str
        data = encodeImage(image, fmt, quality if fmt == 'JPG' else -1)  # type: bytes
        if not self.__m_channel.send(header, data):
            return False
        self.__m_inflight[rid] = (kind, name, key, self._now(), size)
        self.__m_busy[(kind, name)] = rid
        return True

    # ---------- Public API ----------
    @pyqtSlot()
    def connectToServer(self):
        """
        Connect with the current host / port / token (see setters).
        :return:
        """
        self.__m_wanted = True  # type: bool
        self.__m_reconnect.stop()
        self._reset()
        self._setState('connecting')
        self.__m_channel.connectToHost(self.__m_host, self.__m_port)

    @pyqtSlot()
    def disconnectFromServer(self):
        """
        :return:
        """
        self.__m_wanted = False  # type: bool
        self.__m_reconnect.stop()
        self.__m_pinger.stop()
        self.__m_channel.abort()
        self._reset()
        self._setState('disconnected')

    def isReady(self):
        """
        :return: (bool) Connected and authenticated.
        """
        return self.__m_state == 'ready'

    def getState(self):
        """
        :return: (str | unicode | QString) disconnected | connecting | authenticating | ready | error
        """
        return self.__m_state

    def getServerInfo(self):
        """
        :return: (dict) The server's welcome message (methods, faces, server name...).
        """
        return dict(self.__m_serverInfo)

    def processor(self, channel, fallback=None):
        """
        :param channel: (str | unicode | QString) e.g. 'view' or 'lens'.
        :param fallback: (callable | None) Local processor used while the server is unavailable.
        :return: RemoteProcessor
        """
        return RemoteProcessor(self, channel, fallback)

    def cachedResult(self, channel, key):
        """
        :param channel: str | unicode | QString
        :param key: tuple
        :return: (QImage | None) Server result for exactly this crop and size.
        """
        for k, image, size, t in reversed(self.__m_results.get(u'{}'.format(channel), [])):
            if k == key:
                return image
        return None

    def recentResult(self, channel, size, maxAgeMs):
        """
        :param channel: str | unicode | QString
        :param size: QSize
        :param maxAgeMs: int
        :return: (QImage | None) Newest server result of this size that is not older than maxAgeMs.
        """
        results = self.__m_results.get(u'{}'.format(channel), [])  # type: list
        if results:
            key, image, s, t = results[-1]
            if s == size and self._now() - t <= maxAgeMs:
                return image
        return None

    def submitUpscale(self, channel, image, size, key=None):
        """
        Queue an upscale request ("latest frame wins").
        :param channel: str | unicode | QString
        :param image: QImage
        :param size: QSize
        :param key: (tuple | None) Content key (imageKey, w, h).
        :return:
        """
        if not self.isReady():
            return
        slot = ('upscale', u'{}'.format(channel))  # type: tuple
        if slot in self.__m_busy:
            if self.__m_inflight.get(self.__m_busy[slot], (None, None, None))[2] != key:
                self.__m_pending[slot] = (channel, image, size, key)
            return
        header = {'type': 'upscale', 'channel': u'{}'.format(channel), 'width': size.width(), 'height': size.height(),
                  'method': self.__m_method, 'sharpness': self.__m_sharpness, 'format': self.__m_resultFormat,
                  'quality': self.__m_quality}  # type: dict
        self._send('upscale', u'{}'.format(channel), key, QSize(size), header, image, self.__m_uploadFormat,
                   self.__m_uploadQuality)

    def requestAnalysis(self, source, image, params):
        """
        Queue an analysis request ("latest frame wins").
        :param source: (str | unicode | QString) e.g. 'view' or 'lens'.
        :param image: QImage
        :param params: (dict) {'colors': {...}, 'faces': {...}} as in the AnalysisServer protocol.
        :return: None
        """
        if not self.isReady():
            return
        slot = ('analyze', u'{}'.format(source))  # type: tuple
        if slot in self.__m_busy:
            self.__m_pending[slot] = (source, image, params)
            return
        header = dict(params, type='analyze', source=u'{}'.format(source))  # type: dict
        self._send('analyze', u'{}'.format(source), None, None, header, image, 'RAWZ', -1)  # Lossless: exact colors.

    def getLatency(self):
        """
        :return: (float | int) Last measured round-trip time in ms, -1 if unknown.
        """
        return self.__m_latencyMs

    def takeCounts(self):
        """
        :return: (dict) Results received per channel since the previous call (for fps displays).
        """
        counts, self.__m_counts = self.__m_counts, {}
        return counts

    def getBytes(self):
        """
        :return: (tuple[int, int]) Total bytes sent, received.
        """
        return self.__m_channel.getBytesSent(), self.__m_channel.getBytesReceived()

    def getHost(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_host

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setHost(self, host):
        """
        :param host: str | unicode | QString
        :return:
        """
        self.__m_host = u'{}'.format(host).strip()  # type: str

    def getPort(self):
        """
        :return: int
        """
        return self.__m_port

    @pyqtSlot(int)
    def setPort(self, port):
        """
        :param port: int
        :return:
        """
        self.__m_port = int(port)  # type: int

    def getToken(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_token

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setToken(self, token):
        """
        :param token: str | unicode | QString
        :return:
        """
        self.__m_token = token  # type: str

    def isAutoReconnect(self):
        """
        :return: bool
        """
        return self.__m_autoReconnect

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setAutoReconnect(self, autoReconnect):
        """
        :param autoReconnect: bool
        :return:
        """
        self.__m_autoReconnect = bool(autoReconnect)  # type: bool

    def getUploadFormat(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_uploadFormat

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setUploadFormat(self, uploadFormat):
        """
        :param uploadFormat: (str | unicode | QString) 'PNG' or 'JPG'.
        :return:
        """
        self.__m_uploadFormat = 'JPG' if u'{}'.format(uploadFormat).upper() in ('JPG', 'JPEG') else 'PNG'  # type: str

    def getResultFormat(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_resultFormat

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setResultFormat(self, resultFormat):
        """
        :param resultFormat: (str | unicode | QString) 'JPG' or 'PNG'.
        :return:
        """
        self.__m_resultFormat = 'PNG' if u'{}'.format(resultFormat).upper() == 'PNG' else 'JPG'  # type: str

    def getQuality(self):
        """
        :return: int
        """
        return self.__m_quality

    @pyqtSlot(int)
    def setQuality(self, quality):
        """
        :param quality: int
        :return:
        """
        self.__m_quality = max(1, min(100, int(quality)))  # type: int

    def getUploadQuality(self):
        """
        :return: int
        """
        return self.__m_uploadQuality

    @pyqtSlot(int)
    def setUploadQuality(self, uploadQuality):
        """
        :param uploadQuality: int
        :return:
        """
        self.__m_uploadQuality = max(1, min(100, int(uploadQuality)))  # type: int

    def getMethod(self):
        """
        :return: int
        """
        return self.__m_method

    @pyqtSlot(int)
    def setMethod(self, method):
        """
        :param method: (int) Upscaler.Method value used by the server.
        :return:
        """
        self.__m_method = int(method)  # type: int
        self.__m_results = {}  # type: dict  # Old results were made with another method.

    def getSharpness(self):
        """
        :return: float | int
        """
        return self.__m_sharpness

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setSharpness(self, sharpness):
        """
        :param sharpness: float | int
        :return:
        """
        self.__m_sharpness = float(sharpness)  # type: float
        self.__m_results = {}  # type: dict

    # ---------- Properties ----------
    host = pyqtProperty('QString', fget=getHost, fset=setHost)  # type: pyqtProperty
    port = pyqtProperty(int, fget=getPort, fset=setPort)  # type: pyqtProperty
    token = pyqtProperty('QString', fget=getToken, fset=setToken)  # type: pyqtProperty
    autoReconnect = pyqtProperty(bool, fget=isAutoReconnect, fset=setAutoReconnect)  # type: pyqtProperty
    uploadFormat = pyqtProperty('QString', fget=getUploadFormat, fset=setUploadFormat)  # type: pyqtProperty
    resultFormat = pyqtProperty('QString', fget=getResultFormat, fset=setResultFormat)  # type: pyqtProperty
    quality = pyqtProperty(int, fget=getQuality, fset=setQuality)  # type: pyqtProperty
    uploadQuality = pyqtProperty(int, fget=getUploadQuality, fset=setUploadQuality)  # type: pyqtProperty
    method = pyqtProperty(int, fget=getMethod, fset=setMethod)  # type: pyqtProperty
    sharpness = pyqtProperty(float, fget=getSharpness, fset=setSharpness)  # type: pyqtProperty
