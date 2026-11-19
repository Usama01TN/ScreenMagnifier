# coding=utf-8
"""
Demo window for NetProtocol: a loopback server and client exchanging images; shows round trip and throughput.
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QLabel, QPushButton, QComboBox
from ManyQt.QtGui import QImage, QPainter, QColor, QFont
from ManyQt.QtCore import Qt, QTimer, QElapsedTimer, pyqtSlot
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .netprotocol import FrameServer, FrameChannel, encodeImage, decodeImage
except:
    from netprotocol import FrameServer, FrameChannel, encodeImage, decodeImage


class MainWindow(QMainWindow):
    """
    MainWindow class.
    """

    def __init__(self, *args, **kwargs):
        """
        :param args: any
        :param kwargs: any
        """
        super(MainWindow, self).__init__(*args, **kwargs)
        self.setWindowTitle(self.tr(u'NetProtocol demo'))
        self.resize(560, 300)
        self.__m_server = FrameServer(channelOpened=self.onChannel)  # type: FrameServer
        self.__m_server.listen('127.0.0.1', 0)
        self.__m_client = FrameChannel(messageReceived=self.onEcho)  # type: FrameChannel
        self.__m_client.connectToHost('127.0.0.1', self.__m_server.getPort())
        self.__m_clock = QElapsedTimer()  # type: QElapsedTimer
        self.__m_clock.start()
        self.__m_count = 0  # type: int
        self.__m_bytes = 0  # type: int
        self.__m_size = QComboBox()  # type: QComboBox
        self.__m_size.addItems(['320x200', '1280x720', '1920x1080'])
        self.__m_info = QLabel(self.tr(u'Press Start'))  # type: QLabel
        self.__m_info.setAlignment(Qt.AlignCenter)
        start = QPushButton(self.tr(u'Start / stop'))  # type: QPushButton
        self.__m_timer = QTimer(self)  # type: QTimer
        self.__m_timer.timeout.connect(self.sendFrame)
        start.clicked.connect(lambda: self.__m_timer.stop() if self.__m_timer.isActive() else self.__m_timer.start(30))
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addWidget(QLabel(self.tr(u'Loopback server on port {}').format(self.__m_server.getPort())))
        layout.addWidget(self.__m_size)
        layout.addWidget(start)
        layout.addWidget(self.__m_info, 1)
        self.setCentralWidget(wdg)

    def onChannel(self, channel):
        """
        :param channel: FrameChannel
        :return:
        """
        channel.messageReceived.connect(lambda h, p, ch=channel: ch.send(dict(h, type='echo'), p))

    @pyqtSlot()
    def sendFrame(self):
        """
        :return:
        """
        w, h = [int(v) for v in self.__m_size.currentText().split('x')]
        img = QImage(w, h, QImage.Format_RGB32)  # type: QImage
        img.fill(QColor.fromHsv(self.__m_count * 5 % 360, 160, 200))
        p = QPainter(img)  # type: QPainter
        p.setFont(QFont('Sans Serif', 24))
        p.drawText(img.rect(), Qt.AlignCenter, 'frame {}'.format(self.__m_count))
        p.end()
        self.__m_client.send({'type': 'frame', 'id': self.__m_count, 'sent': self.__m_clock.elapsed()},
                             encodeImage(img, 'JPG', 90))

    def onEcho(self, header, payload):
        """
        :param header: dict
        :param payload: bytes
        :return:
        """
        self.__m_count += 1
        self.__m_bytes += len(payload)
        rtt = self.__m_clock.elapsed() - int(header.get('sent', 0))  # type: int
        secs = max(0.001, self.__m_clock.elapsed() / 1000.0)  # type: float
        self.__m_info.setText(self.tr(u'frame {}  {}x{}\nround trip {} ms\n{:.0f} KB per frame, {:.1f} MB/s').format(
            header.get('id'), decodeImage(payload).width(), decodeImage(payload).height(), rtt,
            len(payload) / 1024.0, self.__m_bytes / 1048576.0 / secs))
