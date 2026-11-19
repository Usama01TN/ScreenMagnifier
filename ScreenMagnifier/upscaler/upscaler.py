# -*- coding: utf-8 -*-
"""
Upscaler: real-time upscaling engine for QImage frames.
Methods (each degrades gracefully when its optional dependency is missing):
    - Nearest     : Qt only. Pixel-perfect blocks, best for inspecting pixels.
    - Bilinear    : Qt only. Smooth, cheap.
    - Bicubic     : OpenCV. Sharper than bilinear.
    - Lanczos     : OpenCV. Sharpest classic interpolation (Lanczos-4).
    - PixelArt    : NumPy. Edge-aware Scale2x (EPX) passes, keeps lines and text edges crisp.
    - AIFast      : OpenCV-contrib dnn_superres + FSRCNN-small (bundled), ~10 ms for 200x150 -> x4.
    - AIQuality   : OpenCV-contrib dnn_superres + FSRCNN (bundled), better detail, ~2.5x slower.
An optional unsharp mask ("sharpness") can be applied after any smooth method (needs OpenCV).
"""
from ManyQt.QtCore import Qt, QObject, QElapsedTimer, pyqtSignal, pyqtSlot, pyqtProperty, Q_ENUMS, qVersion
from ManyQt.QtGui import QImage
from os.path import dirname, join
from enum import IntEnum
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:  # The algorithms are Qt-free (core.py), shared with the headless server.
    from .core import UpscaleEngine, METHOD_NAMES as CORE_NAMES, MODEL_FILES as CORE_MODELS, nearestResize, scale2x, \
        hasNumpy, hasCV2
except:
    from core import UpscaleEngine, METHOD_NAMES as CORE_NAMES, MODEL_FILES as CORE_MODELS, nearestResize, scale2x, \
        hasNumpy, hasCV2
if hasNumpy:
    from numpy import frombuffer, ascontiguousarray, ndarray, uint8
MODELS_DIR = join(dirname(__file__), 'models')  # type: str


def clamp(x, a, b):
    """
    :param x: float | int
    :param a: float | int
    :param b: float | int
    :return: float | int
    """
    return a if x < a else b if x > b else x


def qimageToArray(image):
    """
    Convert a QImage into an owned (H, W, 3) uint8 RGB NumPy array.
    :param image: QImage
    :return: ndarray
    """
    img = image.convertToFormat(QImage.Format_RGB888)  # type: QImage
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()  # type: int, int, int
    nBytes = img.sizeInBytes() if hasattr(img, 'sizeInBytes') else img.byteCount()  # type: int
    ptr = img.constBits()
    if hasattr(ptr, 'setsize'):  # PyQt (sip.voidptr). PySide returns a memoryview.
        ptr.setsize(nBytes)
    arr = frombuffer(ptr, uint8, count=nBytes).reshape(h, bpl)[:, :w * 3]  # type: ndarray
    return arr.reshape(h, w, 3).copy()


def arrayToQImage(arr):
    """
    Convert an (H, W, 3) uint8 RGB NumPy array into a QImage that owns its memory.
    :param arr: ndarray
    :return: QImage
    """
    arr = ascontiguousarray(arr, dtype=uint8)  # type: ndarray
    h, w = arr.shape[:2]  # type: int, int
    return QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()


class Upscaler(QObject):
    """
    Upscaler class: converts a QImage crop into a QImage of the requested size with the selected method.
    """

    class Method(IntEnum):
        """
        Method enumeration class.
        """
        Nearest = 0  # type: int
        Bilinear = 1  # type: int
        Bicubic = 2  # type: int
        Lanczos = 3  # type: int
        PixelArt = 4  # type: int
        AIFast = 5  # type: int
        AIQuality = 6  # type: int

    Nearest = Method.Nearest  # type: int
    Bilinear = Method.Bilinear  # type: int
    Bicubic = Method.Bicubic  # type: int
    Lanczos = Method.Lanczos  # type: int
    PixelArt = Method.PixelArt  # type: int
    AIFast = Method.AIFast  # type: int
    AIQuality = Method.AIQuality  # type: int
    METHOD_NAMES = dict(zip(map(Method, CORE_NAMES), CORE_NAMES.values()))  # type: dict  # names: core.py
    MODEL_FILES = dict(zip(map(Method, CORE_MODELS), CORE_MODELS.values()))  # type: dict
    methodChanged = pyqtSignal(int)  # type: pyqtSignal
    sharpnessChanged = pyqtSignal(float)  # type: pyqtSignal
    errorOccurred = pyqtSignal('QString')  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param method: (Upscaler.Method | int) Upscaling method, falls back to the best available one.
        :param sharpness: (float | int) Unsharp-mask amount 0.0 .. 2.0 applied after smooth methods.
        :param aiMinScale: (float | int) Below this scale factor the AI methods use Lanczos instead.
        :param modelsDir: (str | unicode | QString)Folder containing FSRCNN*_x{2,3,4}.pb files.
        :param errorOccurred: callable | None
        :param args: any
        :param kwargs: any
        """
        method = kwargs.pop('method', Upscaler.Lanczos)  # type: int
        sharpness = kwargs.pop('sharpness', 0.3)  # type: float
        aiMinScale = kwargs.pop('aiMinScale', 1.5)  # type: float
        modelsDir = kwargs.pop('modelsDir', MODELS_DIR)  # type: str
        errorOccurred = kwargs.pop('errorOccurred', None)  # type: callable | None
        super(Upscaler, self).__init__(*args, **kwargs)
        if callable(errorOccurred):
            self.errorOccurred.connect(errorOccurred)
        # Options.
        self.__m_modelsDir = u'{}'.format(modelsDir)  # type: str
        self.__m_sharpness = clamp(float(sharpness), 0.0, 2.0)  # type: float
        self.__m_aiMinScale = max(1.0, float(aiMinScale))  # type: float
        self.__m_engine = UpscaleEngine(modelsDir=self.__m_modelsDir, aiMinScale=self.__m_aiMinScale,
                                        onError=self.errorOccurred.emit)  # type: UpscaleEngine
        self.__m_method = self._resolve(method)  # type: Upscaler.Method
        # State.
        self.__m_lastTimeMs = 0.0  # type: float
        self.__m_clock = QElapsedTimer()  # type: QElapsedTimer

    # ---------- Helpers ----------
    @staticmethod
    def hasNumpy():
        """
        :return: bool
        """
        return hasNumpy

    @staticmethod
    def hasOpenCV():
        """
        :return: bool
        """
        return hasCV2 and hasNumpy

    @staticmethod
    def hasSuperRes():
        """
        :return: bool
        """
        return UpscaleEngine.hasSuperRes()

    def isMethodAvailable(self, method):
        """
        :param method: Upscaler.Method | int
        :return: bool
        """
        return self.__m_engine.isMethodAvailable(int(method))

    def availableMethods(self):
        """
        :return: (list[tuple[Upscaler.Method, str]]) Available methods with display names.
        """
        return [(Upscaler.Method(m), n) for m, n in self.__m_engine.availableMethods()]

    def _resolve(self, method):
        """
        Return the method itself if available, else the closest available fallback.
        :param method: Upscaler.Method | int
        :return: Upscaler.Method
        """
        return Upscaler.Method(self.__m_engine.resolve(int(method)))

    # ---------- Public API ----------
    def process(self, image, size):
        """
        Upscale (or downscale) image to exactly size using the current method.
        :param image: QImage
        :param size: QSize
        :return: QImage
        """
        if image is None or image.isNull() or size.isEmpty():
            return QImage()
        self.__m_clock.start()
        w, h = size.width(), size.height()  # type: int, int
        scale = max(w / float(image.width()), h / float(image.height()))  # type: float
        m = self.__m_method  # type: Upscaler.Method
        sharpen = self.__m_sharpness > 0.0 and scale > 1.0 and Upscaler.hasOpenCV() and m not in (
            Upscaler.Nearest, Upscaler.PixelArt)  # type: bool
        if m == Upscaler.Nearest or (m == Upscaler.Bilinear and not sharpen):
            mode = Qt.FastTransformation if m == Upscaler.Nearest else Qt.SmoothTransformation  # type: int
            out = image.scaled(size, Qt.IgnoreAspectRatio, mode)  # type: QImage
        else:
            up = self.__m_engine.upscale(qimageToArray(image), w, h, int(m),
                                         self.__m_sharpness if sharpen else 0.0)  # type: ndarray
            out = arrayToQImage(up)  # type: QImage
        self.__m_lastTimeMs = float(self.__m_clock.nsecsElapsed()) / 1e6  # type: float
        return out

    def getLastProcessTime(self):
        """
        :return: (float | int) Duration of the last process() call in ms.
        """
        return self.__m_lastTimeMs

    def getMethod(self):
        """
        :return: Upscaler.Method
        """
        return self.__m_method

    @pyqtSlot(Method)
    @pyqtSlot(int)
    def setMethod(self, method):
        """
        :param method: Upscaler.Method | int
        :return:
        """
        method = self._resolve(method)  # type: Upscaler.Method
        if method != self.__m_method:
            self.__m_method = method  # type: Upscaler.Method
            self.methodChanged.emit(int(method))

    def getMethodName(self):
        """
        :return: str | unicode | QString
        """
        return Upscaler.METHOD_NAMES[self.__m_method]

    def getSharpness(self):
        """
        :return: float | int
        """
        return self.__m_sharpness

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setSharpness(self, sharpness):
        """
        :param sharpness: (float | int) 0.0 .. 2.0
        :return:
        """
        sharpness = clamp(float(sharpness), 0.0, 2.0)  # type: float
        if sharpness != self.__m_sharpness:
            self.__m_sharpness = sharpness  # type: float
            self.sharpnessChanged.emit(sharpness)

    def getAiMinScale(self):
        """
        :return: float | int
        """
        return self.__m_aiMinScale

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setAiMinScale(self, aiMinScale):
        """
        :param aiMinScale: float | int
        :return:
        """
        self.__m_aiMinScale = max(1.0, float(aiMinScale))  # type: float
        self.__m_engine.setAiMinScale(self.__m_aiMinScale)

    def getModelsDir(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_modelsDir

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setModelsDir(self, modelsDir):
        """
        :param modelsDir: str | unicode | QString
        :return:
        """
        self.__m_modelsDir = u'{}'.format(modelsDir)  # type: str
        self.__m_engine.setModelsDir(self.__m_modelsDir)
        self.setMethod(self.__m_method)

    # ---------- Properties ----------
    Q_ENUMS('Method' if qVersion()[0] == '4' else Method)
    method = pyqtProperty(int, fget=getMethod, fset=setMethod, notify=methodChanged)  # type: pyqtProperty
    sharpness = pyqtProperty(float, fget=getSharpness, fset=setSharpness, notify=sharpnessChanged)  # type: pyqtProperty
    aiMinScale = pyqtProperty(float, fget=getAiMinScale, fset=setAiMinScale)  # type: pyqtProperty
    modelsDir = pyqtProperty('QString', fget=getModelsDir, fset=setModelsDir)  # type: pyqtProperty
