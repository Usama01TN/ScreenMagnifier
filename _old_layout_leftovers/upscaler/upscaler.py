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
from os.path import dirname, join, isfile
from enum import IntEnum

try:
    from numpy import arange, frombuffer, where, empty, ascontiguousarray, ndarray, uint8, uint32, pad

    np = True  # type: bool
except:
    np = False  # type: bool
try:
    from cv2 import dnn_superres, GaussianBlur, addWeighted, resize, INTER_LINEAR, INTER_LANCZOS4, INTER_AREA, \
        INTER_CUBIC, INTER_NEAREST

    cv2 = True  # type: bool
except Exception:
    dnn_superres = False
    cv2 = False  # type: bool

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
    :return: numpy.ndarray
    """
    img = image.convertToFormat(QImage.Format_RGB888)  # type: QImage
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()  # type: int, int, int
    nbytes = img.sizeInBytes() if hasattr(img, 'sizeInBytes') else img.byteCount()  # type: int
    ptr = img.constBits()
    if hasattr(ptr, 'setsize'):  # PyQt (sip.voidptr). PySide returns a memoryview.
        ptr.setsize(nbytes)
    arr = frombuffer(ptr, uint8, count=nbytes).reshape(h, bpl)[:, :w * 3]  # type: ndarray
    return arr.reshape(h, w, 3).copy()


def arrayToQImage(arr):
    """
    Convert an (H, W, 3) uint8 RGB NumPy array into a QImage that owns its memory.
    :param arr: numpy.ndarray
    :return: QImage
    """
    arr = ascontiguousarray(arr, dtype=uint8)  # type: ndarray
    h, w = arr.shape[:2]  # type: int, int
    return QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def nearestResize(arr, w, h):
    """
    Pure NumPy nearest-neighbour resize (used when OpenCV is missing).
    :param arr: numpy.ndarray
    :param w: int
    :param h: int
    :return: numpy.ndarray
    """
    sh, sw = arr.shape[:2]  # type: int, int
    rows = (arange(h) * sh // h).clip(0, sh - 1)  # type: ndarray
    cols = (arange(w) * sw // w).clip(0, sw - 1)  # type: ndarray
    return arr[rows[:, None], cols[None, :]]


def scale2x(arr):
    """
    One Scale2x / EPX pass: doubles the image while keeping diagonal edges crisp.
    :param arr: (numpy.ndarray) (H, W, 3) uint8.
    :return: numpy.ndarray
    """
    a = arr.astype(uint32)  # type: ndarray
    p = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]  # type: ndarray
    pd = pad(p, 1, mode='edge')  # type: ndarray
    b, d, f, hh = pd[:-2, 1:-1], pd[1:-1, :-2], pd[1:-1, 2:], pd[2:, 1:-1]
    cond = (b != hh) & (d != f)  # type: ndarray
    out = empty((p.shape[0] * 2, p.shape[1] * 2), uint32)  # type: ndarray
    out[0::2, 0::2] = where(cond & (d == b), d, p)
    out[0::2, 1::2] = where(cond & (b == f), f, p)
    out[1::2, 0::2] = where(cond & (d == hh), d, p)
    out[1::2, 1::2] = where(cond & (hh == f), f, p)
    rgb = empty(out.shape + (3,), uint8)  # type: ndarray
    rgb[..., 0] = (out >> 16) & 0xFF
    rgb[..., 1] = (out >> 8) & 0xFF
    rgb[..., 2] = out & 0xFF
    return rgb


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
    METHOD_NAMES = {
        Method.Nearest: 'Nearest (pixel-perfect)',
        Method.Bilinear: 'Bilinear (smooth)',
        Method.Bicubic: 'Bicubic',
        Method.Lanczos: 'Lanczos (sharp)',
        Method.PixelArt: 'Pixel art (Scale2x)',
        Method.AIFast: 'AI super-res - fast',
        Method.AIQuality: 'AI super-res - quality',
    }  # type: dict
    MODEL_FILES = {Method.AIFast: 'FSRCNN-small_x{}.pb', Method.AIQuality: 'FSRCNN_x{}.pb'}  # type: dict
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
        self.__m_method = self._resolve(method)  # type: Upscaler.Method
        self.__m_sharpness = clamp(float(sharpness), 0.0, 2.0)  # type: float
        self.__m_aiMinScale = max(1.0, float(aiMinScale))  # type: float
        # State.
        self.__m_models = {}  # type: dict  # (method, scale) -> DnnSuperResImpl | None
        self.__m_lastTimeMs = 0.0  # type: float
        self.__m_clock = QElapsedTimer()  # type: QElapsedTimer

    # ---------- Helpers ----------
    @staticmethod
    def hasNumpy():
        """
        :return: bool
        """
        return np

    @staticmethod
    def hasOpenCV():
        """
        :return: bool
        """
        return cv2 and np

    @staticmethod
    def hasSuperRes():
        """
        :return: bool
        """
        return Upscaler.hasOpenCV() and dnn_superres

    def isMethodAvailable(self, method):
        """
        :param method: Upscaler.Method | int
        :return: bool
        """
        method = Upscaler.Method(int(method))  # type: Upscaler.Method
        if method in (Upscaler.Nearest, Upscaler.Bilinear):
            return True
        if method == Upscaler.PixelArt:
            return Upscaler.hasNumpy()
        if method in (Upscaler.Bicubic, Upscaler.Lanczos):
            return Upscaler.hasOpenCV()
        if not Upscaler.hasSuperRes():
            return False
        pattern = Upscaler.MODEL_FILES[method]  # type: str
        return all(isfile(join(self.__m_modelsDir, pattern.format(s))) for s in (2, 3, 4))

    def availableMethods(self):
        """
        :return: (list[tuple[Upscaler.Method, str]]) Available methods with display names.
        """
        return [(m, Upscaler.METHOD_NAMES[m]) for m in Upscaler.Method if self.isMethodAvailable(m)]

    def _resolve(self, method):
        """
        Return the method itself if available, else the closest available fallback.
        :param method: Upscaler.Method | int
        :return: Upscaler.Method
        """
        method = Upscaler.Method(int(method))  # type: Upscaler.Method
        chain = {
            Upscaler.AIQuality: [Upscaler.AIQuality, Upscaler.AIFast, Upscaler.Lanczos, Upscaler.Bilinear],
            Upscaler.AIFast: [Upscaler.AIFast, Upscaler.Lanczos, Upscaler.Bilinear],
            Upscaler.Lanczos: [Upscaler.Lanczos, Upscaler.Bicubic, Upscaler.Bilinear],
            Upscaler.Bicubic: [Upscaler.Bicubic, Upscaler.Bilinear],
            Upscaler.PixelArt: [Upscaler.PixelArt, Upscaler.Nearest],
        }.get(method, [method])  # type: list
        for m in chain:
            if self.isMethodAvailable(m):
                return m
        return Upscaler.Bilinear

    def _model(self, method, scale):
        """
        Lazily load (and cache) a super-resolution network.
        :param method: Upscaler.Method
        :param scale: (int) 2, 3 or 4.
        :return: dnn_superres.DnnSuperResImpl | None
        """
        key = (int(method), int(scale))  # type: tuple
        if key not in self.__m_models:
            sr = None
            try:
                sr = dnn_superres.DnnSuperResImpl_create()
                sr.readModel(join(self.__m_modelsDir, Upscaler.MODEL_FILES[method].format(scale)))
                sr.setModel('fsrcnn', int(scale))
            except Exception as e:
                sr = None
                self.errorOccurred.emit('Could not load super-resolution model: {}'.format(e))
            self.__m_models[key] = sr
        return self.__m_models[key]

    def _superRes(self, arr, w, h, scale, method):
        """
        :param arr: (numpy.ndarray) RGB source.
        :param w: int
        :param h: int
        :param scale: (float | int) Requested scale factor.
        :param method: Upscaler.Method
        :return: numpy.ndarray
        """
        if scale < self.__m_aiMinScale:
            return resize(arr, (w, h), interpolation=INTER_LANCZOS4)
        k = 2 if scale < 2.5 else 3 if scale < 3.5 else 4  # type: int
        sr = self._model(method, k)
        if sr is None:
            return resize(arr, (w, h), interpolation=INTER_LANCZOS4)
        up = sr.upsample(ascontiguousarray(arr[..., ::-1]))[..., ::-1]  # Network expects BGR.
        if up.shape[1] == w and up.shape[0] == h:
            return up
        interp = INTER_AREA if up.shape[1] > w else INTER_CUBIC  # type: int
        return resize(up, (w, h), interpolation=interp)

    @staticmethod
    def _pixelArt(arr, w, h):
        """
        :param arr: numpy.ndarray
        :param w: int
        :param h: int
        :return: numpy.ndarray
        """
        passes = 0  # type: int
        while passes < 3 and arr.shape[1] * 2 <= w and arr.shape[0] * 2 <= h:
            arr = scale2x(arr)  # type: ndarray
            passes += 1
        if arr.shape[1] == w and arr.shape[0] == h:
            return arr
        if cv2:
            return resize(arr, (w, h), interpolation=INTER_NEAREST)
        return nearestResize(arr, w, h)

    def _sharpen(self, arr, scale):
        """
        Unsharp mask whose radius follows the upscale factor.
        :param arr: numpy.ndarray
        :param scale: float | int
        :return: numpy.ndarray
        """
        sigma = clamp(0.5 * scale, 0.8, 4.0)  # type: float
        blur = GaussianBlur(arr, (0, 0), sigma)  # type: ndarray
        a = self.__m_sharpness  # type: float
        return addWeighted(arr, 1.0 + a, blur, -a, 0)

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
        sharpen = self.__m_sharpness > 0.0 and scale > 1.0 and Upscaler.hasOpenCV() and \
            m not in (Upscaler.Nearest, Upscaler.PixelArt)  # type: bool
        if m == Upscaler.Nearest or (m == Upscaler.Bilinear and not sharpen):
            mode = Qt.FastTransformation if m == Upscaler.Nearest else Qt.SmoothTransformation  # type: int
            out = image.scaled(size, Qt.IgnoreAspectRatio, mode)  # type: QImage
        else:
            arr = qimageToArray(image)  # type: ndarray
            if m == Upscaler.PixelArt:
                up = Upscaler._pixelArt(arr, w, h)  # type: ndarray
            elif scale <= 1.0:
                up = resize(arr, (w, h), interpolation=INTER_AREA)  # type: ndarray
            elif m in (Upscaler.AIFast, Upscaler.AIQuality):
                up = self._superRes(arr, w, h, scale, m)  # type: ndarray
            else:
                interp = {Upscaler.Bilinear: INTER_LINEAR, Upscaler.Bicubic: INTER_CUBIC}.get(
                    m, INTER_LANCZOS4)  # type: int
                up = resize(arr, (w, h), interpolation=interp)  # type: ndarray
            if sharpen:
                up = self._sharpen(up, scale)  # type: ndarray
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
        self.__m_models = {}  # type: dict
        self.setMethod(self.__m_method)

    # ---------- Properties ----------
    Q_ENUMS('Method' if qVersion()[0] == '4' else Method)
    method = pyqtProperty(int, fget=getMethod, fset=setMethod, notify=methodChanged)  # type: pyqtProperty
    sharpness = pyqtProperty(float, fget=getSharpness, fset=setSharpness, notify=sharpnessChanged)  # type: pyqtProperty
    aiMinScale = pyqtProperty(float, fget=getAiMinScale, fset=setAiMinScale)  # type: pyqtProperty
    modelsDir = pyqtProperty('QString', fget=getModelsDir, fset=setModelsDir)  # type: pyqtProperty
