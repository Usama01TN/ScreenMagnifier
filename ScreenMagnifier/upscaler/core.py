# -*- coding: utf-8 -*-
"""
Upscaling algorithms on NumPy arrays - pure Python + NumPy, OpenCV optional, no Qt: used by the Qt Upscaler and
by the headless server (which also runs without Qt, e.g. on Android).
Methods (same numbers as Upscaler.Method):
    0 Nearest   NumPy               1 Bilinear  OpenCV, else NumPy        2 Bicubic   OpenCV
    3 Lanczos   OpenCV              4 PixelArt  NumPy (Scale2x / EPX)     5 AIFast    OpenCV contrib (FSRCNN-small)
    6 AIQuality OpenCV contrib (FSRCNN)
An unavailable method falls back to the closest available one.
"""
from os.path import dirname, join, isfile

try:
    from numpy import arange, where, empty, ascontiguousarray, uint8, uint32, pad, float32, clip, ndarray, minimum

    hasNumpy = True  # type: bool
except:
    hasNumpy = False  # type: bool
try:
    from cv2 import GaussianBlur, addWeighted, resize, INTER_LINEAR, INTER_LANCZOS4, INTER_AREA, INTER_CUBIC, \
        INTER_NEAREST

    hasCV2 = True  # type: bool
except:
    hasCV2 = False  # type: bool
try:
    from cv2 import dnn_superres  # opencv-contrib-python only: must not disable the classic OpenCV methods.
except:
    dnn_superres = None

NEAREST, BILINEAR, BICUBIC, LANCZOS, PIXEL_ART, AI_FAST, AI_QUALITY = range(7)
METHOD_NAMES = {
    NEAREST: 'Nearest (pixel-perfect)',
    BILINEAR: 'Bilinear (smooth)',
    BICUBIC: 'Bicubic',
    LANCZOS: 'Lanczos (sharp)',
    PIXEL_ART: 'Pixel art (Scale2x)',
    AI_FAST: 'AI super-res - fast',
    AI_QUALITY: 'AI super-res - quality',
}  # type: dict[int, str]
MODEL_FILES = {AI_FAST: 'FSRCNN-small_x{}.pb', AI_QUALITY: 'FSRCNN_x{}.pb'}  # type: dict
MODELS_DIR = join(dirname(__file__), 'models')  # type: str
FALLBACKS = {
    AI_QUALITY: [AI_QUALITY, AI_FAST, LANCZOS, BILINEAR],
    AI_FAST: [AI_FAST, LANCZOS, BILINEAR],
    LANCZOS: [LANCZOS, BICUBIC, BILINEAR],
    BICUBIC: [BICUBIC, BILINEAR],
    PIXEL_ART: [PIXEL_ART, NEAREST],
}  # type: dict


def clamp(x, a, b):
    """
    :param x: float | int
    :param a: float | int
    :param b: float | int
    :return: float | int
    """
    return a if x < a else b if x > b else x


def nearestResize(arr, w, h):
    """
    Pure NumPy nearest-neighbor resize.
    :param arr: ndarray
    :param w: int
    :param h: int
    :return: ndarray
    """
    sh, sw = arr.shape[:2]  # type: int, int
    rows = (arange(h) * sh // h).clip(0, sh - 1)
    cols = (arange(w) * sw // w).clip(0, sw - 1)
    return arr[rows[:, None], cols[None, :]]


def bilinearResize(arr, w, h):
    """
    Pure NumPy bilinear resize (pixel centres aligned like OpenCV): Bilinear without OpenCV.
    :param arr: (ndarray) (H, W, C) uint8.
    :param w: int
    :param h: int
    :return: ndarray
    """
    sh, sw = arr.shape[:2]  # type: int, int
    ys = clip((arange(h, dtype=float32) + 0.5) * (sh / float(h)) - 0.5, 0, sh - 1)
    xs = clip((arange(w, dtype=float32) + 0.5) * (sw / float(w)) - 0.5, 0, sw - 1)
    y0, x0 = ys.astype(int), xs.astype(int)
    y1, x1 = minimum(y0 + 1, sh - 1), minimum(x0 + 1, sw - 1)
    fy, fx = (ys - y0)[:, None, None], (xs - x0)[None, :, None]
    a = arr.astype(float32)
    top = a[y0][:, x0] * (1 - fx) + a[y0][:, x1] * fx
    bottom = a[y1][:, x0] * (1 - fx) + a[y1][:, x1] * fx
    return clip(top * (1 - fy) + bottom * fy + 0.5, 0, 255).astype(uint8)


def scale2x(arr):
    """
    One Scale2x / EPX pass: doubles the image while keeping diagonal edges crisp.
    :param arr: (ndarray) (H, W, 3) uint8.
    :return: ndarray
    """
    a = arr.astype(uint32)
    p = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
    pd = pad(p, 1, mode='edge')
    b, d, f, hh = pd[:-2, 1:-1], pd[1:-1, :-2], pd[1:-1, 2:], pd[2:, 1:-1]
    cond = (b != hh) & (d != f)
    out = empty((p.shape[0] * 2, p.shape[1] * 2), uint32)
    out[0::2, 0::2] = where(cond & (d == b), d, p)
    out[0::2, 1::2] = where(cond & (b == f), f, p)
    out[1::2, 0::2] = where(cond & (d == hh), d, p)
    out[1::2, 1::2] = where(cond & (hh == f), f, p)
    rgb = empty(out.shape + (3,), uint8)
    rgb[..., 0] = (out >> 16) & 0xFF
    rgb[..., 1] = (out >> 8) & 0xFF
    rgb[..., 2] = out & 0xFF
    return rgb


class UpscaleEngine(object):
    """
    UpscaleEngine class: resizes NumPy RGB arrays with the requested method (no Qt).
    """

    def __init__(self, *args, **kwargs):
        """
        :param modelsDir: (str | unicode | QString) Folder of the FSRCNN networks.
        :param aiMinScale: (float | int) Below this factor the AI methods use Lanczos (faster, same quality).
        :param onError: (callable | None) f(message) when a network cannot be loaded.
        :param args: any
        :param kwargs: any
        """
        self.__m_modelsDir = kwargs.pop('modelsDir', MODELS_DIR)  # type: str
        self.__m_aiMinScale = float(kwargs.pop('aiMinScale', 1.5))  # type: float
        self.__m_onError = kwargs.pop('onError', None)
        super(UpscaleEngine, self).__init__(*args, **kwargs)
        self.__m_models = {}  # type: dict

    # ---------- Availability ----------
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
        return bool(hasCV2)

    @staticmethod
    def hasSuperRes():
        """
        :return: bool
        """
        return bool(hasCV2) and dnn_superres is not None

    def isMethodAvailable(self, method):
        """
        :param method: int
        :return: bool
        """
        method = int(method)  # type: int
        if method == NEAREST:
            return True
        if method in (BILINEAR, PIXEL_ART):
            return UpscaleEngine.hasNumpy() or method == BILINEAR
        if method in (BICUBIC, LANCZOS):
            return UpscaleEngine.hasOpenCV()
        if not UpscaleEngine.hasSuperRes():
            return False
        return all(isfile(join(self.__m_modelsDir, MODEL_FILES[method].format(s))) for s in (2, 3, 4))

    def availableMethods(self):
        """
        :return: (list[tuple[int, str | unicode | QString]]) Available methods with their (English) names.
        """
        return [(m, METHOD_NAMES[m]) for m in sorted(METHOD_NAMES) if self.isMethodAvailable(m)]

    def resolve(self, method):
        """
        :param method: int
        :return: (int) The method itself if available, else the closest available fallback.
        """
        for m in FALLBACKS.get(int(method), [int(method)]):
            if self.isMethodAvailable(m):
                return m
        return BILINEAR

    # ---------- Processing ----------
    def _model(self, method, scale):
        """
        :param method: int
        :param scale: int
        :return: dnn_superres.DnnSuperResImpl | None
        """
        key = (int(method), int(scale))  # type: tuple
        if key not in self.__m_models:
            sr = None
            try:
                sr = dnn_superres.DnnSuperResImpl_create()
                sr.readModel(join(self.__m_modelsDir, MODEL_FILES[method].format(scale)))
                sr.setModel('fsrcnn', int(scale))
            except Exception as e:
                sr = None
                if callable(self.__m_onError):
                    self.__m_onError(u'Could not load super-resolution model: {}'.format(e))
            self.__m_models[key] = sr
        return self.__m_models[key]

    def _superRes(self, arr, w, h, scale, method):
        """
        :param arr: ndarray
        :param w: int
        :param h: int
        :param scale: float | int
        :param method: int
        :return: ndarray
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
        return resize(up, (w, h), interpolation=INTER_AREA if up.shape[1] > w else INTER_CUBIC)

    @staticmethod
    def _pixelArt(arr, w, h):
        """
        :param arr: ndarray
        :param w: int
        :param h: int
        :return: ndarray
        """
        passes = 0  # type: int
        while passes < 3 and arr.shape[1] * 2 <= w and arr.shape[0] * 2 <= h:
            arr = scale2x(arr)
            passes += 1
        if arr.shape[1] == w and arr.shape[0] == h:
            return arr
        return resize(arr, (w, h), interpolation=INTER_NEAREST) if hasCV2 else nearestResize(arr, w, h)

    @staticmethod
    def _sharpen(arr, scale, amount):
        """
        Unsharp mask whose radius follows the upscale factor.
        :param arr: ndarray
        :param scale: float | int
        :param amount: float | int
        :return: ndarray
        """
        return addWeighted(arr, 1.0 + amount, GaussianBlur(arr, (0, 0), clamp(0.5 * scale, 0.8, 4.0)), -amount, 0)

    def upscale(self, arr, w, h, method=BILINEAR, sharpness=0.0):
        """
        Resize to exactly w x h with a method (resolved to an available one).
        :param arr: (ndarray) (H, W, 3) uint8 RGB.
        :param w: int
        :param h: int
        :param method: int
        :param sharpness: (float | int) Unsharp-mask amount (OpenCV; not for Nearest / PixelArt).
        :return: (ndarray) (h, w, 3) uint8 RGB.
        """
        m = self.resolve(method)  # type: int
        scale = max(w / float(arr.shape[1]), h / float(arr.shape[0]))  # type: float
        if m == NEAREST:
            up = resize(arr, (w, h), interpolation=INTER_NEAREST) if hasCV2 else nearestResize(arr, w, h)
        elif m == PIXEL_ART:
            up = UpscaleEngine._pixelArt(arr, w, h)
        elif not hasCV2:
            up = bilinearResize(arr, w, h)
        elif scale <= 1.0:
            up = resize(arr, (w, h), interpolation=INTER_AREA)
        elif m in (AI_FAST, AI_QUALITY):
            up = self._superRes(arr, w, h, scale, m)
        else:
            up = resize(arr, (w, h),
                        interpolation={BILINEAR: INTER_LINEAR, BICUBIC: INTER_CUBIC}.get(m, INTER_LANCZOS4))
        if sharpness > 0.0 and scale > 1.0 and hasCV2 and m not in (NEAREST, PIXEL_ART):
            up = UpscaleEngine._sharpen(up, scale, float(sharpness))
        return up

    # ---------- Options ----------
    def getModelsDir(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_modelsDir

    def setModelsDir(self, modelsDir):
        """
        :param modelsDir: str | unicode | QString
        :return:
        """
        self.__m_modelsDir = modelsDir  # type: str
        self.__m_models = {}  # type: dict

    def getAiMinScale(self):
        """
        :return: float | int
        """
        return self.__m_aiMinScale

    def setAiMinScale(self, aiMinScale):
        """
        :param aiMinScale: float | int
        :return:
        """
        self.__m_aiMinScale = float(aiMinScale)  # type: float
