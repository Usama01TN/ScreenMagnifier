# -*- coding: utf-8 -*-
"""
ImageFilters: colour filters for QImage - adjustments (brightness, contrast, saturation) and effects (grayscale,
sepia, invert, high contrast, warm, night vision, thermal, outline, color-blindness help), blended by strength.
The work is done by the Qt-free core (core.py, NumPy); without NumPy, Invert and Grayscale still work (Qt).
"""
from ManyQt.QtCore import QObject, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtGui import QImage
from os.path import dirname
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .core import applyFilters, isIdentity, isAvailable, EFFECT_NAMES, NONE, GRAYSCALE, INVERT
except:
    from core import applyFilters, isIdentity, isAvailable, EFFECT_NAMES, NONE, GRAYSCALE, INVERT
if isAvailable():
    from numpy import frombuffer, uint8, ascontiguousarray


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


def arrayToQImage(arr):
    """
    :param arr: (ndarray) (H, W, 3) uint8 RGB.
    :return: (QImage) Owned copy.
    """
    arr = ascontiguousarray(arr)
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, w * 3, QImage.Format_RGB888).copy()


class ImageFilters(QObject):
    """
    ImageFilters class.
    """
    changed = pyqtSignal()  # type: pyqtSignal
    EFFECT_NAMES = EFFECT_NAMES  # type: list[str]  # index = effect number (English; translate with tr())

    def __init__(self, *args, **kwargs):
        """
        :param effect: (int) Effect number (see EFFECT_NAMES), 0 = none.
        :param brightness: (int) -100 .. 100.
        :param contrast: (int) -100 .. 100.
        :param saturation: (int) -100 .. 100.
        :param strength: (int) 0 .. 100: how much of the effect.
        :param changed: (callable | None) Called after any setting changes.
        :param args: any
        :param kwargs: any
        """
        effect = kwargs.pop('effect', NONE)  # type: int
        brightness = kwargs.pop('brightness', 0)  # type: int
        contrast = kwargs.pop('contrast', 0)  # type: int
        saturation = kwargs.pop('saturation', 0)  # type: int
        strength = kwargs.pop('strength', 100)  # type: int
        changed = kwargs.pop('changed', None)  # type: callable | None
        super(ImageFilters, self).__init__(*args, **kwargs)
        if callable(changed):
            self.changed.connect(changed)
        self.__m_effect = int(clamp(int(effect), 0, len(EFFECT_NAMES) - 1))  # type: int
        self.__m_brightness = int(clamp(int(brightness), -100, 100))  # type: int
        self.__m_contrast = int(clamp(int(contrast), -100, 100))  # type: int
        self.__m_saturation = int(clamp(int(saturation), -100, 100))  # type: int
        self.__m_strength = int(clamp(int(strength), 0, 100))  # type: int

    # ---------- Helpers ----------
    @staticmethod
    def isAvailable():
        """
        :return: (bool) Every effect is available (NumPy installed); else only Invert and Grayscale.
        """
        return isAvailable()

    def isActive(self):
        """
        :return: (bool) The settings change images.
        """
        return not isIdentity(self.__m_effect, self.__m_brightness, self.__m_contrast, self.__m_saturation,
                              self.__m_strength)

    def _set(self, name, value):
        """
        :param name: str | unicode | QString
        :param value: int
        :return:
        """
        attribute = '_ImageFilters__m_' + name  # type: str
        if getattr(self, attribute) != value:
            setattr(self, attribute, value)
            self.changed.emit()

    # ---------- Public API ----------
    def apply(self, image):
        """
        :param image: QImage
        :return: (QImage) The filtered image (the image itself when nothing changes it).
        """
        if image is None or image.isNull() or not self.isActive():
            return image
        if isAvailable():
            return arrayToQImage(applyFilters(qimageToArray(image), self.__m_effect, self.__m_brightness,
                                              self.__m_contrast, self.__m_saturation, self.__m_strength))
        if self.__m_effect == INVERT:  # without NumPy: what Qt does by itself
            out = image.convertToFormat(QImage.Format_RGB32)  # type: QImage
            out.invertPixels()
            return out
        if self.__m_effect == GRAYSCALE:
            return image.convertToFormat(QImage.Format_Grayscale8).convertToFormat(QImage.Format_RGB32)
        return image

    @pyqtSlot()
    def reset(self):
        """
        No effect, no adjustment.
        :return:
        """
        for name, value in (('effect', NONE), ('brightness', 0), ('contrast', 0), ('saturation', 0), ('strength', 100)):
            setattr(self, '_ImageFilters__m_' + name, value)
        self.changed.emit()

    def getEffect(self):
        """
        :return: int
        """
        return self.__m_effect

    @pyqtSlot(int)
    def setEffect(self, effect):
        """
        :param effect: (int) See EFFECT_NAMES.
        :return:
        """
        self._set('effect', int(clamp(int(effect), 0, len(EFFECT_NAMES) - 1)))

    def getBrightness(self):
        """
        :return: int
        """
        return self.__m_brightness

    @pyqtSlot(int)
    def setBrightness(self, brightness):
        """
        :param brightness: (int) -100 .. 100.
        :return:
        """
        self._set('brightness', int(clamp(int(brightness), -100, 100)))

    def getContrast(self):
        """
        :return: int
        """
        return self.__m_contrast

    @pyqtSlot(int)
    def setContrast(self, contrast):
        """
        :param contrast: (int) -100 .. 100.
        :return:
        """
        self._set('contrast', int(clamp(int(contrast), -100, 100)))

    def getSaturation(self):
        """
        :return: int
        """
        return self.__m_saturation

    @pyqtSlot(int)
    def setSaturation(self, saturation):
        """
        :param saturation: (int) -100 .. 100.
        :return:
        """
        self._set('saturation', int(clamp(int(saturation), -100, 100)))

    def getStrength(self):
        """
        :return: int
        """
        return self.__m_strength

    @pyqtSlot(int)
    def setStrength(self, strength):
        """
        :param strength: (int) 0 .. 100.
        :return:
        """
        self._set('strength', int(clamp(int(strength), 0, 100)))

    # ---------- Properties ----------
    effect = pyqtProperty(int, fget=getEffect, fset=setEffect, notify=changed)  # type: pyqtProperty
    brightness = pyqtProperty(int, fget=getBrightness, fset=setBrightness, notify=changed)  # type: pyqtProperty
    contrast = pyqtProperty(int, fget=getContrast, fset=setContrast, notify=changed)  # type: pyqtProperty
    saturation = pyqtProperty(int, fget=getSaturation, fset=setSaturation, notify=changed)  # type: pyqtProperty
    strength = pyqtProperty(int, fget=getStrength, fset=setStrength, notify=changed)  # type: pyqtProperty
