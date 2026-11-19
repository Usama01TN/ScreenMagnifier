# coding=utf-8
"""
Demo window for FaceDetector: open a photo or follow the screen around the mouse, with boxes and landmarks.
"""
from ManyQt.QtWidgets import QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton, QComboBox, \
    QCheckBox, QFileDialog
from ManyQt.QtGui import QImage, QPainter, QColor, QPen, QPixmap, QCursor, QGuiApplication
from ManyQt.QtCore import Qt, QRect, QRectF, QPointF, QTimer, pyqtSlot
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .facedetector import FaceDetector
except:
    from facedetector import FaceDetector


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
        self.setWindowTitle(self.tr(u'FaceDetector demo'))
        self.resize(900, 640)
        self.__m_detector = FaceDetector(downloadFinished=self.onDownloaded,
                                         downloadProgress=lambda v: self.statusBar().showMessage(
                                             self.tr(u'Downloading model {} %').format(v)))  # type: FaceDetector
        self.__m_image = QImage()  # type: QImage
        self.__m_picture = QLabel(self.tr(u'Open a photo, or tick "Follow the mouse" and hover a face on screen.'))
        self.__m_picture.setAlignment(Qt.AlignCenter)
        self.__m_picture.setMinimumSize(320, 240)
        backend = QComboBox()  # type: QComboBox
        for data in ('auto', 'yunet', 'haar'):
            backend.addItem(data, data)
        backend.currentIndexChanged.connect(
            lambda i: (self.__m_detector.setBackend(backend.itemData(i)), self.detect()))
        openBtn = QPushButton(self.tr(u'Open photo...'))  # type: QPushButton
        openBtn.clicked.connect(self.openPhoto)
        self.__m_download = QPushButton(self.tr(u'Download YuNet model'))  # type: QPushButton
        self.__m_download.clicked.connect(self.__m_detector.downloadModel)
        self.__m_download.setVisible(FaceDetector.hasYuNetSupport() and not self.__m_detector.isModelReady())
        follow = QCheckBox(self.tr(u'Follow the mouse'))  # type: QCheckBox
        self.__m_timer = QTimer(self)  # type: QTimer
        self.__m_timer.timeout.connect(self.grabAroundCursor)
        follow.toggled.connect(lambda on: self.__m_timer.start(200) if on else self.__m_timer.stop())
        bar = QHBoxLayout()  # type: QHBoxLayout
        for w in (openBtn, follow, QLabel(self.tr(u'Backend')), backend, self.__m_download):
            bar.addWidget(w)
        bar.addStretch(1)
        wdg = QWidget()  # type: QWidget
        layout = QVBoxLayout(wdg)  # type: QVBoxLayout
        layout.addLayout(bar)
        layout.addWidget(self.__m_picture, 1)
        self.setCentralWidget(wdg)
        if not FaceDetector.isAvailable():
            self.statusBar().showMessage(self.tr(u'Install opencv-python and numpy to use the face detector.'))

    @pyqtSlot()
    def openPhoto(self):
        """
        :return:
        """
        res = QFileDialog.getOpenFileName(self, self.tr(u'Photo'), '', self.tr(u'Images (*.png *.jpg *.jpeg *.bmp)'))
        fileName = res[0] if isinstance(res, tuple) else res  # type: str
        if fileName:
            self.__m_image = QImage(fileName)  # type: QImage
            self.detect()

    @pyqtSlot()
    def grabAroundCursor(self):
        """
        :return:
        """
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        g = screen.geometry()  # type: QRect
        self.__m_image = screen.grabWindow(0, pos.x() - g.x() - 240, pos.y() - g.y() - 180, 480, 360).toImage()
        self.detect()

    @pyqtSlot()
    def detect(self):
        """
        :return: None
        """
        if self.__m_image.isNull():
            return
        r = self.__m_detector.detect(self.__m_image)  # type: dict
        pm = QPixmap.fromImage(self.__m_image)  # type: QPixmap
        p = QPainter(pm)  # type: QPainter
        p.setRenderHint(QPainter.Antialiasing, True)
        for f in r['faces']:
            p.setPen(QPen(QColor('#00E5FF'), 3))
            p.drawRect(QRectF(*f['rect']))
            p.drawText(QPointF(f['rect'][0], f['rect'][1] - 6), '{:.0f} %'.format(100 * f['score']))
            p.setBrush(QColor('#FF3B6B'))
            for x, y in f['landmarks']:
                p.drawEllipse(QPointF(x, y), 3, 3)
            p.setBrush(Qt.NoBrush)
        p.end()
        self.__m_picture.setPixmap(pm.scaled(self.__m_picture.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.statusBar().showMessage(self.tr(u'{} face(s) - backend {} - {:.1f} ms').format(
            len(r['faces']), r['backend'] or '-', r['timeMs']))

    @pyqtSlot(bool, 'QString')
    def onDownloaded(self, ok, message):
        """
        :param ok: bool
        :param message: str | unicode | QString
        :return:
        """
        self.__m_download.setVisible(not ok)
        self.statusBar().showMessage(self.tr(u'Model installed') if ok else u'{}'.format(message))
        self.detect()
