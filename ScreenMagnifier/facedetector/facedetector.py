# -*- coding: utf-8 -*-
"""
FaceDetector: optional AI face detection for QImage frames.
Backends:
    - yunet : OpenCV FaceDetectorYN + YuNet ONNX model (MIT license, 232 KB): accurate, rotated / small faces,
              confidence score and 5 landmarks (eyes, nose, mouth corners). The model is downloaded on demand
              from the official opencv_zoo repository and verified with SHA-256 before use.
    - haar  : OpenCV Haar cascade shipped with opencv-python: no download, frontal faces only, no landmarks.
    - auto  : YuNet when its model is available, otherwise Haar.
Results are plain Python data (JSON safe) so they can be sent over a network.
"""
from ManyQt.QtCore import QObject, QStandardPaths, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtGui import QImage
from os import makedirs, access, W_OK
from os.path import dirname, join
from threading import Thread
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:  # Detection, model search, verification and download are Qt-free (core.py), shared with the server.
    from .core import FaceEngine, MODELS_DIR, YUNET_FILE, YUNET_URL, YUNET_SHA256, YUNET_SIZE, HAAR_FILE, \
        HAAR_MAX_INPUT, clamp, verifyModel, downloadModel, modelDirs as _modelDirs, np, cv2
except:
    from core import FaceEngine, MODELS_DIR, YUNET_FILE, YUNET_URL, YUNET_SHA256, YUNET_SIZE, HAAR_FILE, \
        HAAR_MAX_INPUT, clamp, verifyModel, downloadModel, modelDirs as _modelDirs, np, cv2
if np:
    from numpy import frombuffer, uint8, ndarray


def qimageToArray(image):
    """
    :param image: QImage
    :return: (ndarray) Owned (H, W, 3) uint8 RGB array.
    """
    img = image.convertToFormat(QImage.Format_RGB888)  # type: QImage
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()  # type: int, int, int
    nbytes = img.sizeInBytes() if hasattr(img, 'sizeInBytes') else img.byteCount()  # type: int
    ptr = img.constBits()
    if hasattr(ptr, 'setsize'):
        ptr.setsize(nbytes)
    return frombuffer(ptr, uint8, count=nbytes).reshape(h, bpl)[:, :w * 3].reshape(h, w, 3).copy()


def appDataDir():
    """
    :return: (str | unicode | QString) The writable per-user data folder of the application.
    """
    location = QStandardPaths.AppDataLocation if hasattr(QStandardPaths, 'AppDataLocation') else \
        QStandardPaths.DataLocation  # (AppDataLocation first: on Windows it is the folder the server uses too)
    return u'{}'.format(QStandardPaths.writableLocation(location))


def modelDirs():
    """
    :return: (list[str | unicode | QString]) Folders searched for the YuNet model (package folder, user data folder).
    """
    return _modelDirs(appDataDir())


class FaceDetector(QObject):
    """
    FaceDetector class.
    """
    downloadProgress = pyqtSignal(int)  # type: pyqtSignal
    downloadFinished = pyqtSignal(bool, 'QString')  # type: pyqtSignal
    errorOccurred = pyqtSignal('QString')  # type: pyqtSignal
    backendChanged = pyqtSignal('QString')  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param backend: (str | unicode | QString) 'auto', 'yunet' or 'haar'.
        :param scoreThreshold: (float | int) 0.1 . 0.99 minimum confidence.
        :param nmsThreshold: (float | int) YuNet non-maximum suppression threshold.
        :param minFaceSize: (int) Smallest face (px, in the analysed frame).
        :param maxInputSize: (int) Frames are downscaled so their longest side is at most this (speed).
        :param modelPath: (str | unicode | QString) YuNet model file; '' = search the default folders.
        :param downloadProgress: callable | None
        :param downloadFinished: callable | None
        :param errorOccurred: callable | None
        :param args: any
        :param kwargs: any
        """
        backend = kwargs.pop('backend', 'auto')  # type: str
        scoreThreshold = kwargs.pop('scoreThreshold', 0.6)  # type: float
        nmsThreshold = kwargs.pop('nmsThreshold', 0.3)  # type: float
        minFaceSize = kwargs.pop('minFaceSize', 20)  # type: int
        maxInputSize = kwargs.pop('maxInputSize', 640)  # type: int
        modelPath = kwargs.pop('modelPath', '')  # type: str
        downloadProgress = kwargs.pop('downloadProgress', None)  # type: callable | None
        downloadFinished = kwargs.pop('downloadFinished', None)  # type: callable | None
        errorOccurred = kwargs.pop('errorOccurred', None)  # type: callable | None
        super(FaceDetector, self).__init__(*args, **kwargs)
        for signal, slot in ((self.downloadProgress, downloadProgress), (self.downloadFinished, downloadFinished),
                             (self.errorOccurred, errorOccurred)):
            if callable(slot):
                signal.connect(slot)
        self.__m_engine = FaceEngine(backend=u'{}'.format(backend) if u'{}'.format(backend) in ('auto', 'yunet', 'haar') else 'auto',
                                     scoreThreshold=scoreThreshold, nmsThreshold=nmsThreshold,
                                     minFaceSize=minFaceSize, maxInputSize=maxInputSize, modelPath=u'{}'.format(modelPath),
                                     dataDir=appDataDir(), onError=self.errorOccurred.emit)  # type: FaceEngine
        self.__m_downloading = False  # type: bool

    # ---------- Helpers ----------
    @staticmethod
    def isAvailable():
        """
        :return: (bool) OpenCV and NumPy are installed.
        """
        return FaceEngine.isAvailable()

    @staticmethod
    def hasYuNetSupport():
        """
        :return: (bool) This OpenCV build has FaceDetectorYN (4.5.4+).
        """
        return FaceEngine.hasYuNetSupport()

    def findModel(self):
        """
        :return: (str | unicode | QString) Path of a verified YuNet model, '' if none is available.
        """
        return self.__m_engine.findModel()

    def isModelReady(self):
        """
        :return: bool
        """
        return self.__m_engine.isModelReady()

    def getActiveBackend(self):
        """
        :return: (str | unicode | QString) 'yunet', 'haar' or '' (nothing usable).
        """
        return self.__m_engine.getActiveBackend()

    def _download(self, target):
        """
        Worker thread: fetch, verify and atomically install the YuNet model.
        :param target: str | unicode | QString
        :return:
        """
        try:
            downloadModel(target, self.downloadProgress.emit)
            self.__m_engine.resetModel()
            self.__m_downloading = False  # type: bool
            self.downloadFinished.emit(True, target)
        except Exception as e:
            self.__m_downloading = False  # type: bool
            self.downloadFinished.emit(False, u'YuNet model download failed: {}'.format(e))

    # ---------- Public API ----------
    def detect(self, image):
        """
        :param image: QImage
        :return: (dict) faces [{rect, score, landmarks}], backend, width, height, timeMs.
        """
        if image is None or image.isNull() or not self.__m_engine.getActiveBackend():
            return {'faces': [], 'backend': '', 'width': 0, 'height': 0, 'timeMs': 0.0}
        return self.__m_engine.detect(qimageToArray(image))

    @pyqtSlot()
    def downloadModel(self):
        """
        Download the YuNet model in the background (downloadProgress / downloadFinished report the result).
        :return:
        """
        if self.__m_downloading:
            return
        folder = modelDirs()[-1]  # type: str
        for d in modelDirs():  # First folder that exists (or can be created) and is writable.
            try:
                makedirs(d, exist_ok=True)
                if access(d, W_OK):
                    folder = d  # type: str
                    break
            except Exception:
                continue
        self.__m_downloading = True  # type: bool
        worker = Thread(target=self._download, args=(join(folder, YUNET_FILE),), name='YuNetDownload')
        worker.daemon = True
        worker.start()

    def isDownloading(self):
        """
        :return: bool
        """
        return self.__m_downloading

    def getBackend(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_engine.backend

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setBackend(self, backend):
        """
        :param backend: (str | unicode | QString) 'auto', 'yunet' or 'haar'.
        :return:
        """
        backend = u'{}'.format(backend) if u'{}'.format(backend) in ('auto', 'yunet', 'haar') else 'auto'  # type str
        if backend != self.__m_engine.backend:
            self.__m_engine.backend = backend  # type str
            self.backendChanged.emit(backend)

    def getScoreThreshold(self):
        """
        :return: float | int
        """
        return self.__m_engine.scoreThreshold

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setScoreThreshold(self, scoreThreshold):
        """
        :param scoreThreshold: float
        :return:
        """
        self.__m_engine.scoreThreshold = clamp(float(scoreThreshold), 0.1, 0.99)  # type float

    def getNmsThreshold(self):
        """
        :return: float | int
        """
        return self.__m_engine.nmsThreshold

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setNmsThreshold(self, nmsThreshold):
        """
        :param nmsThreshold: float | int
        :return:
        """
        self.__m_engine.nmsThreshold = clamp(float(nmsThreshold), 0.05, 0.95)  # type float

    def getMinFaceSize(self):
        """
        :return: int
        """
        return self.__m_engine.minFaceSize

    @pyqtSlot(int)
    def setMinFaceSize(self, minFaceSize):
        """
        :param minFaceSize: int
        :return:
        """
        self.__m_engine.minFaceSize = max(8, int(minFaceSize))  # type int

    def getMaxInputSize(self):
        """
        :return: int
        """
        return self.__m_engine.maxInputSize

    @pyqtSlot(int)
    def setMaxInputSize(self, maxInputSize):
        """
        :param maxInputSize: int
        :return:
        """
        self.__m_engine.maxInputSize = max(160, int(maxInputSize))  # type int

    def getModelPath(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_engine.getModelPath()

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setModelPath(self, modelPath):
        """
        :param modelPath: (str | unicode | QString) '' = search the default folders.
        :return:
        """
        self.__m_engine.setModelPath(u'{}'.format(modelPath))

    # ---------- Properties ----------
    backend = pyqtProperty('QString', fget=getBackend, fset=setBackend, notify=backendChanged)  # type: pyqtProperty
    scoreThreshold = pyqtProperty(float, fget=getScoreThreshold, fset=setScoreThreshold)  # type: pyqtProperty
    nmsThreshold = pyqtProperty(float, fget=getNmsThreshold, fset=setNmsThreshold)  # type: pyqtProperty
    minFaceSize = pyqtProperty(int, fget=getMinFaceSize, fset=setMinFaceSize)  # type: pyqtProperty
    maxInputSize = pyqtProperty(int, fget=getMaxInputSize, fset=setMaxInputSize)  # type: pyqtProperty
    modelPath = pyqtProperty('QString', fget=getModelPath, fset=setModelPath)  # type: pyqtProperty
