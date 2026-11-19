# -*- coding: utf-8 -*-
"""
Face detection on NumPy arrays - pure Python + NumPy + OpenCV, no Qt: used by the Qt FaceDetector and by the
headless server (which also runs without Qt, e.g. on Android).
    - YuNet (OpenCV >= 4.5.4, model downloaded on demand, SHA-256 verified): accurate, 5 landmarks, scores.
    - Haar cascade (bundled with OpenCV): no download, frontal faces.
"""
from os.path import dirname, join, isfile, getsize
from os import makedirs
from hashlib import sha256
from time import time
from math import exp
import sys

try:
    from os import replace
except:
    from os import remove, rename
    from os.path import exists


    def replace(src, dst):
        """
        Replace the destination file with the source file.
        """
        if exists(dst):
            remove(dst)
        rename(src, dst)
try:
    from urllib.request import Request, urlopen
except:  # Python 2.
    from urllib2 import Request, urlopen
try:
    from numpy import ndarray

    np = True  # type: bool
except Exception:
    np = False  # type: bool
try:
    from cv2 import CascadeClassifier, cvtColor, resize, createCLAHE, COLOR_RGB2GRAY, COLOR_RGB2BGR, INTER_AREA
    from cv2.data import haarcascades

    cv2 = True  # type: bool
except Exception:
    haarcascades = ''  # type: str
    cv2 = False  # type: bool
try:
    from cv2 import FaceDetectorYN  # OpenCV >= 4.5.4.
except Exception:
    FaceDetectorYN = None

MODELS_DIR = join(dirname(__file__), 'models')  # type: str
YUNET_FILE = 'face_detection_yunet_2023mar.onnx'  # type: str
YUNET_URL = 'https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/' + YUNET_FILE  # type: str
YUNET_SHA256 = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'  # type: str
YUNET_SIZE = 232589  # type: int
HAAR_FILE = 'haarcascade_frontalface_default.xml'  # type: str
HAAR_MAX_INPUT = 400  # type: int  # Haar cost grows fast with size: 400 px + scale step 1.2 keeps faces >= ~20 px.


def clamp(x, a, b):
    """
    :param x: float | int
    :param a: float | int
    :param b: float | int
    :return: float | int
    """
    return a if x < a else b if x > b else x


def modelDirs(dataDir=''):
    """
    :param dataDir: (str | unicode | QString) Writable per-user data folder ('' = none).
    :return: (list[str | unicode | QString]) Folders searched for the YuNet model, in order: package folder,
        user data folder (user data first in a packaged application, whose own folder is read-only or temporary).
    """
    dirs = [MODELS_DIR]  # type: list[str]
    if dataDir:
        dirs.insert(0 if getattr(sys, 'frozen', False) else 1, join(dataDir, 'models'))
    return dirs


def verifyModel(path):
    """
    :param path: str | unicode | QString
    :return: (bool) The file exists and its SHA-256 matches the official YuNet model.
    """
    try:
        if not isfile(path) or getsize(path) != YUNET_SIZE:
            return False
        with open(path, 'rb') as f:
            return sha256(f.read()).hexdigest() == YUNET_SHA256
    except Exception:
        return False


def downloadModel(target, progress=None):
    """
    Fetch, verify (SHA-256) and atomically install the YuNet model.
    :param target: (str | unicode | QString) Destination file.
    :param progress: (callable | None) f(percent).
    :return:
    :raise Exception: on a network error or a failed check (nothing is installed then).
    """
    request = Request(YUNET_URL, headers={'User-Agent': 'ScreenMagnifier'})
    data = bytearray()  # type: bytearray
    response = urlopen(request, timeout=30)
    try:
        total = int(response.headers.get('Content-Length') or YUNET_SIZE)  # type: int
        while True:
            chunk = response.read(16384)  # type: bytes
            if not chunk:
                break
            data.extend(chunk)
            if callable(progress):
                progress(int(clamp(100.0 * len(data) / max(1, total), 0, 100)))
    finally:
        response.close()
    if sha256(bytes(data)).hexdigest() != YUNET_SHA256:
        raise ValueError(u'Downloaded file failed the SHA-256 check ({} bytes)'.format(len(data)))
    makedirs(dirname(target), exist_ok=True)
    with open(target + '.part', 'wb') as f:
        f.write(bytes(data))
    replace(target + '.part', target)


class FaceEngine(object):
    """
    FaceEngine class: options are plain attributes (backend 'auto' / 'yunet' / 'haar', scoreThreshold,
    nmsThreshold, minFaceSize, maxInputSize); setModelPath() / resetModel() after changing the model.
    """

    def __init__(self, **options):
        """
        :param options: backend, scoreThreshold, nmsThreshold, minFaceSize, maxInputSize, haarMaxInput (Haar frames
            are downscaled to at most this, default 400: it is slower than YuNet), modelPath, dataDir,
            onError (callable f(message)).
        """
        self.backend = u'{}'.format(options.get('backend', 'auto'))  # type: str
        self.scoreThreshold = clamp(float(options.get('scoreThreshold', 0.6)), 0.1, 0.99)  # type: float
        self.nmsThreshold = clamp(float(options.get('nmsThreshold', 0.3)), 0.05, 0.95)  # type: float
        self.minFaceSize = max(8, int(options.get('minFaceSize', 20)))  # type: int
        self.maxInputSize = max(160, int(options.get('maxInputSize', 640)))  # type: int
        self.haarMaxInput = max(160, int(options.get('haarMaxInput', HAAR_MAX_INPUT)))  # type: int  # Haar is slower
        self.dataDir = u'{}'.format(options.get('dataDir', ''))  # type: str
        self.onError = options.get('onError')
        self.__m_modelPath = u'{}'.format(options.get('modelPath', ''))  # type: str
        self.__m_resolvedModel = None  # type: str | None  # Cached verified model path ('' = none).
        self.__m_yunet = None
        self.__m_yunetSize = (0, 0)  # type: tuple[int, int]
        self.__m_haar = None
        self.__m_clahe = None

    @staticmethod
    def isAvailable():
        """
        :return: (bool) Face detection is possible (NumPy + OpenCV).
        """
        return np and cv2

    @staticmethod
    def hasYuNetSupport():
        """
        :return: bool
        """
        return FaceEngine.isAvailable() and FaceDetectorYN is not None

    def getModelPath(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_modelPath

    def setModelPath(self, modelPath):
        """
        :param modelPath: (str | unicode | QString) '' = search modelDirs().
        :return:
        """
        self.__m_modelPath = u'{}'.format(modelPath)  # type: str
        self.resetModel()

    def resetModel(self):
        """
        Forget the cached model (after a download or a path change).
        :return:
        """
        self.__m_resolvedModel = None
        self.__m_yunet = None

    def findModel(self):
        """
        :return: (str | unicode | QString) Path of a verified YuNet model, '' if none is available.
        """
        if self.__m_resolvedModel is None:
            candidates = [self.__m_modelPath] if self.__m_modelPath else [join(d, YUNET_FILE) for d in
                                                                          modelDirs(self.dataDir)]
            self.__m_resolvedModel = next((p for p in candidates if verifyModel(p)), '')  # type: str
        return self.__m_resolvedModel

    def isModelReady(self):
        """
        :return: bool
        """
        return FaceEngine.hasYuNetSupport() and bool(self.findModel())

    def getActiveBackend(self):
        """
        :return: (str | unicode | QString) 'yunet', 'haar' or '' (nothing usable).
        """
        if not FaceEngine.isAvailable():
            return ''
        if self.backend in ('auto', 'yunet') and self.isModelReady():
            return 'yunet'
        return 'haar' if self.backend in ('auto', 'haar') or not self.isModelReady() else ''

    def _detectYuNet(self, arr, minSize):
        """
        :param arr: (ndarray) RGB frame.
        :param minSize: (int) Smallest face in this frame's pixels.
        :return: list[dict]
        """
        h, w = arr.shape[:2]
        if self.__m_yunet is None:
            self.__m_yunet = FaceDetectorYN.create(self.findModel(), '', (w, h), self.scoreThreshold,
                                                   self.nmsThreshold, 5000)
            self.__m_yunetSize = (w, h)  # type: tuple[int, int]
        elif self.__m_yunetSize != (w, h):
            self.__m_yunet.setInputSize((w, h))
            self.__m_yunetSize = (w, h)  # type: tuple[int, int]
        self.__m_yunet.setScoreThreshold(self.scoreThreshold)
        self.__m_yunet.setNMSThreshold(self.nmsThreshold)
        _, faces = self.__m_yunet.detect(cvtColor(arr, COLOR_RGB2BGR))
        out = []  # type: list
        for f in ([] if faces is None else faces):
            x, y, fw, fh = [float(v) for v in f[:4]]
            if min(fw, fh) < minSize:
                continue
            out.append({'rect': [x, y, fw, fh], 'score': round(float(f[14]), 3),
                        'landmarks': [[float(f[4 + 2 * k]), float(f[5 + 2 * k])] for k in range(5)]})
        return out

    def _detectHaar(self, arr, minSize):
        """
        :param arr: (ndarray) RGB frame.
        :param minSize: (int) Smallest face in this frame's pixels.
        :return: list[dict]
        """
        if self.__m_haar is None:
            self.__m_haar = CascadeClassifier(join(haarcascades, HAAR_FILE))
            if self.__m_haar.empty():
                raise RuntimeError(u'Haar cascade not found in {}'.format(haarcascades))
        if self.__m_clahe is None:  # local equalization: a large plain area (letterbox bars, a desktop around a
            self.__m_clahe = createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))  # video) no longer washes faces out
        gray = self.__m_clahe.apply(cvtColor(arr, COLOR_RGB2GRAY))  # type: ndarray
        neighbors = 2 + int(round(self.scoreThreshold * 5))  # type: int  # Stricter with higher confidence.
        rects, _, weights = self.__m_haar.detectMultiScale3(
            gray, scaleFactor=1.2, minNeighbors=neighbors, minSize=(minSize, minSize),
            outputRejectLevels=True)
        out = []  # type: list
        for k, (x, y, fw, fh) in enumerate([] if rects is None else rects):
            weight = float(weights[k]) if weights is not None and len(weights) > k else 4.0  # type: float
            out.append({'rect': [float(x), float(y), float(fw), float(fh)],
                        'score': round(1.0 - exp(-max(weight, 0.0) / 3.0), 3), 'landmarks': []})
        return out

    def detect(self, arr):
        """
        :param arr: (numpy.ndarray) (H, W, 3) uint8 RGB frame.
        :return: (dict) faces [{rect, score, landmarks}], backend, width, height, timeMs.
        """
        result = {'faces': [], 'backend': '', 'width': 0, 'height': 0, 'timeMs': 0.0}  # type: dict
        backend = self.getActiveBackend()  # type: str
        if not backend or arr is None or arr.size == 0:
            return result
        started = time()  # type: float
        h0, w0 = arr.shape[:2]
        limit = self.maxInputSize if backend == 'yunet' else min(self.maxInputSize, self.haarMaxInput)  # type: int
        scale = min(1.0, limit / float(max(w0, h0)))  # type: float
        if scale < 1.0:
            arr = resize(arr, (max(1, int(w0 * scale)), max(1, int(h0 * scale))), interpolation=INTER_AREA)
        try:
            minSize = max(8, int(round(self.minFaceSize * scale)))  # type: int  # minFaceSize is in frame px.
            faces = self._detectYuNet(arr, minSize) if backend == 'yunet' else self._detectHaar(arr,
                                                                                                minSize)  # type: list
        except Exception as e:
            if callable(self.onError):
                self.onError('Face detection ({}) failed: {}'.format(backend, e))
            if backend == 'yunet':
                self.__m_resolvedModel = ''  # type: str  # Fall back to Haar from now on.
                self.__m_yunet = None
            faces = []  # type: list
        inv = 1.0 / scale  # type: float
        for f in faces:
            f['rect'] = [round(v * inv, 1) for v in f['rect']]
            f['landmarks'] = [[round(x * inv, 1), round(y * inv, 1)] for x, y in f['landmarks']]
        result.update(faces=faces, backend=backend, width=w0, height=h0,
                      timeMs=round((time() - started) * 1000.0, 2))
        return result


def userDataDir(appName='Screen Magnifier'):
    """
    The per-user data folder of the application, as Qt's QStandardPaths.AppDataLocation names it (no organization
    name): the server, which has no Qt, finds the YuNet model downloaded by the application, and vice versa.
    :param appName: str | unicode | QString
    :return: str | unicode | QString
    """
    from os.path import expanduser
    from os import environ
    if sys.platform == 'win32':
        return join(environ.get('APPDATA') or expanduser('~'), appName)
    if sys.platform == 'darwin':
        return join(expanduser('~'), 'Library', 'Application Support', appName)
    return join(environ.get('XDG_DATA_HOME') or join(expanduser('~'), '.local', 'share'), appName)
