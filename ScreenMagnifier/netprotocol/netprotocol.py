# -*- coding: utf-8 -*-
"""
NetProtocol: dependency-free binary messaging over TCP (QtNetwork) for real-time image exchange.
Wire format of one message (wire.py, pure Python - also used by the Qt-free server):
    b'SMG1' | uint32 header length | uint32 payload length | header (UTF-8 JSON object) | payload (bytes)
(all integers big-endian). Images travel as encoded bytes (PNG / JPEG) in the payload, never as base64.
Messages larger than the limits, or a wrong magic, close the connection: a hostile or confused peer cannot make
the application allocate unbounded memory.
Classes:
    - FrameChannel : one connection (client side, or a server-side peer), send(header, payload) and
                     messageReceived(header, payload).
    - FrameServer  : listens and creates a FrameChannel per incoming connection.
"""
from ManyQt.QtCore import QObject, QBuffer, QByteArray, QIODevice, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtNetwork import QTcpServer, QTcpSocket, QHostAddress, QAbstractSocket
from ManyQt.QtGui import QImage
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:  # The wire format itself is pure Python (shared with the Qt-free server).
    from .wire import MAGIC, PREFIX_SIZE, MAX_HEADER, MAX_PAYLOAD, RAWZ_MAGIC, RAWG_MAGIC, DEFAULT_PORT, packMessage, \
        MessageParser, packRaw, unpackRaw
except:
    from wire import MAGIC, PREFIX_SIZE, MAX_HEADER, MAX_PAYLOAD, RAWZ_MAGIC, RAWG_MAGIC, DEFAULT_PORT, packMessage, \
        MessageParser, packRaw, unpackRaw

def encodeImage(image, fmt='PNG', quality=-1):
    """
    :param image: QImage
    :param fmt: (str | unicode | QString) 'PNG' (lossless), 'JPG' or 'RAWZ' (lossless and several times faster
        than PNG: raw RGB + fast zlib; exact colors, unlike JPEG's chroma sub-sampling).
    :param quality: (int) 0 .. 100 for JPEG, -1 = default.
    :return: bytes
    """
    if u'{}'.format(fmt).upper() == 'RAWZ':
        img = image.convertToFormat(QImage.Format_RGB888)  # type: QImage
        w, h, bpl = img.width(), img.height(), img.bytesPerLine()  # type: int, int, int
        ptr = img.constBits()
        n = img.sizeInBytes() if hasattr(img, 'sizeInBytes') else img.byteCount()  # type: int
        if hasattr(ptr, 'setsize'):
            ptr.setsize(n)
        raw = bytes(ptr)  # type: bytes
        rows = raw if bpl == w * 3 else b''.join(raw[y * bpl:y * bpl + w * 3] for y in range(h))  # type: bytes
        return packRaw(w, h, rows)
    data = QByteArray()  # type: QByteArray
    buf = QBuffer(data)  # type: QBuffer
    buf.open(QIODevice.WriteOnly)
    image.save(buf, u'{}'.format(fmt).upper(), int(quality))
    buf.close()
    return bytes(data.data())


def decodeImage(data):
    """
    :param data: (bytes) RAWZ / RAWG, PNG or JPEG bytes.
    :return: (QImage) Null image on failure.
    """
    image = QImage()  # type: QImage
    if data and bytes(data[:4]) in (RAWZ_MAGIC, RAWG_MAGIC):  # lossless raw colour / grayscale (bounded zlib)
        raw = unpackRaw(data)
        if raw is None:
            return image
        w, h, channels, rows = raw
        fmt = QImage.Format_Grayscale8 if channels == 1 else QImage.Format_RGB888
        return QImage(rows, w, h, w * channels, fmt).copy()
    if data:
        image.loadFromData(QByteArray(bytes(data)))
    return image


def hostAddress(host):
    """
    :param host: (str | unicode | QString) IP, 'localhost', '0.0.0.0' (all IPv4) or '::' (all).
    :return: QHostAddress
    """
    host = u'{}'.format(host).strip()  # type: str
    special = {'': QHostAddress.LocalHost, 'localhost': QHostAddress.LocalHost, '0.0.0.0': QHostAddress.AnyIPv4,
               '::': QHostAddress.Any, '*': QHostAddress.Any}  # type: dict
    return QHostAddress(special[host]) if host in special else QHostAddress(host)


class FrameChannel(QObject):
    """
    FrameChannel class: one framed-message connection.
    """
    messageReceived = pyqtSignal(object, object)  # type: pyqtSignal  # (dict header, bytes payload)
    connected = pyqtSignal()  # type: pyqtSignal
    disconnected = pyqtSignal()  # type: pyqtSignal
    errorOccurred = pyqtSignal('QString')  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param socket: (QTcpSocket | None) Existing connected socket (server side); None = client channel.
        :param messageReceived: callable | None
        :param connected: callable | None
        :param disconnected: callable | None
        :param errorOccurred: callable | None
        :param args: any
        :param kwargs: any
        """
        socket = kwargs.pop('socket', None)  # type: QTcpSocket | None
        messageReceived = kwargs.pop('messageReceived', None)  # type: callable | None
        connected = kwargs.pop('connected', None)  # type: callable | None
        disconnected = kwargs.pop('disconnected', None)  # type: callable | None
        errorOccurred = kwargs.pop('errorOccurred', None)  # type: callable | None
        super(FrameChannel, self).__init__(*args, **kwargs)
        for signal, slot in ((self.messageReceived, messageReceived), (self.connected, connected),
                             (self.disconnected, disconnected), (self.errorOccurred, errorOccurred)):
            if callable(slot):
                signal.connect(slot)
        self.__m_parser = MessageParser()  # type: MessageParser
        self.__m_bytesSent = 0  # type: int
        self.__m_bytesReceived = 0  # type: int
        self.__m_socket = socket if socket is not None else QTcpSocket(self)  # type: QTcpSocket
        self.__m_socket.setParent(self)
        self.__m_socket.readyRead.connect(self._onReadyRead)
        self.__m_socket.connected.connect(self._onConnected)
        self.__m_socket.disconnected.connect(self._onDisconnected)
        if hasattr(self.__m_socket, 'errorOccurred'):
            self.__m_socket.errorOccurred.connect(self._onError)
        else:
            self.__m_socket.error.connect(self._onError)
        if self.isConnected():
            self.__m_socket.setSocketOption(QAbstractSocket.LowDelayOption, 1)

    # ---------- Helpers ----------
    @pyqtSlot()
    def _onReadyRead(self):
        """
        :return:
        """
        data = self.__m_socket.readAll()  # type: QByteArray
        data = bytes(data.data())  # type: bytes
        self.__m_bytesReceived += len(data)
        try:
            messages = self.__m_parser.feed(data)  # type: list
        except Exception as e:
            self.errorOccurred.emit('Protocol error from {}: {}'.format(self.getPeer(), e))
            self.__m_socket.abort()
            return
        for header, payload in messages:
            self.messageReceived.emit(header, payload)

    @pyqtSlot()
    def _onConnected(self):
        """
        :return:
        """
        self.__m_socket.setSocketOption(QAbstractSocket.LowDelayOption, 1)  # TCP_NODELAY: low latency.
        self.connected.emit()

    @pyqtSlot()
    def _onDisconnected(self):
        """
        :return:
        """
        self.__m_parser = MessageParser()  # type: MessageParser
        self.disconnected.emit()

    def _onError(self, *args):
        """
        :param args: QAbstractSocket.SocketError
        :return:
        """
        if self.__m_socket.error() != QAbstractSocket.RemoteHostClosedError:
            self.errorOccurred.emit(u'{}'.format(self.__m_socket.errorString()))

    # ---------- Public API ----------
    @pyqtSlot('QString', int)
    @pyqtSlot(str, int)
    def connectToHost(self, host, port):
        """
        :param host: str | unicode | QString
        :param port: int
        :return:
        """
        self.__m_parser = MessageParser()  # type: MessageParser
        self.__m_socket.abort()
        self.__m_socket.connectToHost(u'{}'.format(host), int(port))

    @pyqtSlot()
    def close(self):
        """
        :return:
        """
        self.__m_socket.disconnectFromHost()

    def abort(self):
        """
        Close immediately, dropping unsent data.
        :return:
        """
        self.__m_socket.abort()

    def send(self, header, payload=b''):
        """
        :param header: (dict) JSON-serialisable header.
        :param payload: (bytes) Binary payload.
        :return: (bool) Queued for sending.
        """
        if not self.isConnected():
            return False
        try:
            data = packMessage(header, payload)  # type: bytes
        except Exception as e:
            self.errorOccurred.emit('Cannot send message: {}'.format(e))
            return False
        self.__m_socket.write(QByteArray(data))
        self.__m_bytesSent += len(data)
        return True

    def isConnected(self):
        """
        :return: bool
        """
        return self.__m_socket.state() == QAbstractSocket.ConnectedState

    def getState(self):
        """
        :return: (str | unicode | QString) 'disconnected', 'connecting' or 'connected'.
        """
        state = self.__m_socket.state()
        if state == QAbstractSocket.ConnectedState:
            return 'connected'
        if state in (QAbstractSocket.HostLookupState, QAbstractSocket.ConnectingState):
            return 'connecting'
        return 'disconnected'

    def getPeer(self):
        """
        :return: (str | unicode | QString) 'address:port' of the other side.
        """
        return '{}:{}'.format(self.__m_socket.peerAddress().toString(), self.__m_socket.peerPort())

    def getBytesToWrite(self):
        """
        :return: (int) Bytes queued but not yet sent (backpressure indicator).
        """
        return int(self.__m_socket.bytesToWrite())

    def getBytesSent(self):
        """
        :return: int
        """
        return self.__m_bytesSent

    def getBytesReceived(self):
        """
        :return: int
        """
        return self.__m_bytesReceived

    # ---------- Properties ----------
    bytesSent = pyqtProperty(int, fget=getBytesSent)  # type: pyqtProperty
    bytesReceived = pyqtProperty(int, fget=getBytesReceived)  # type: pyqtProperty


class FrameServer(QObject):
    """
    FrameServer class: accepts connections and wraps each one in a FrameChannel.
    """
    channelOpened = pyqtSignal(object)  # type: pyqtSignal  # FrameChannel
    channelClosed = pyqtSignal(object)  # type: pyqtSignal  # FrameChannel

    def __init__(self, *args, **kwargs):
        """
        :param maxChannels: (int) Further connections are refused.
        :param channelOpened: callable | None
        :param channelClosed: callable | None
        :param args: any
        :param kwargs: any
        """
        maxChannels = kwargs.pop('maxChannels', 8)  # type: int
        channelOpened = kwargs.pop('channelOpened', None)  # type: callable | None
        channelClosed = kwargs.pop('channelClosed', None)  # type: callable | None
        super(FrameServer, self).__init__(*args, **kwargs)
        if callable(channelOpened):
            self.channelOpened.connect(channelOpened)
        if callable(channelClosed):
            self.channelClosed.connect(channelClosed)
        self.__m_maxChannels = max(1, int(maxChannels))  # type: int
        self.__m_channels = []  # type: list[FrameChannel]
        self.__m_server = QTcpServer(self)  # type: QTcpServer
        self.__m_server.newConnection.connect(self._onNewConnection)

    # ---------- Helpers ----------
    @pyqtSlot()
    def _onNewConnection(self):
        """
        :return:
        """
        while self.__m_server.hasPendingConnections():
            socket = self.__m_server.nextPendingConnection()  # type: QTcpSocket
            if len(self.__m_channels) >= self.__m_maxChannels:
                socket.abort()
                continue
            channel = FrameChannel(socket=socket, parent=self)  # type: FrameChannel
            channel.disconnected.connect(lambda ch=channel: self._onClosed(ch))
            self.__m_channels.append(channel)
            self.channelOpened.emit(channel)

    def _onClosed(self, channel):
        """
        :param channel: FrameChannel
        :return:
        """
        if channel in self.__m_channels:
            self.__m_channels.remove(channel)
            self.channelClosed.emit(channel)
            channel.deleteLater()

    # ---------- Public API ----------
    def listen(self, host='127.0.0.1', port=DEFAULT_PORT):
        """
        :param host: (str | unicode | QString) '127.0.0.1' = this computer only, '0.0.0.0' = the network.
        :param port: (int) 0 = any free port (see getPort()).
        :return: bool
        """
        return bool(self.__m_server.listen(hostAddress(host), int(port)))

    @pyqtSlot()
    def close(self):
        """
        :return:
        """
        self.__m_server.close()
        for channel in list(self.__m_channels):
            channel.abort()

    def isListening(self):
        """
        :return: bool
        """
        return self.__m_server.isListening()

    def getPort(self):
        """
        :return: int
        """
        return int(self.__m_server.serverPort())

    def getErrorString(self):
        """
        :return: str | unicode | QString
        """
        return u'{}'.format(self.__m_server.errorString())

    def getChannels(self):
        """
        :return: list[FrameChannel]
        """
        return list(self.__m_channels)

    def getMaxChannels(self):
        """
        :return: int
        """
        return self.__m_maxChannels

    @pyqtSlot(int)
    def setMaxChannels(self, maxChannels):
        """
        :param maxChannels: int
        :return:
        """
        self.__m_maxChannels = max(1, int(maxChannels))  # type: int

    # ---------- Properties ----------
    maxChannels = pyqtProperty(int, fget=getMaxChannels, fset=setMaxChannels)  # type: pyqtProperty
