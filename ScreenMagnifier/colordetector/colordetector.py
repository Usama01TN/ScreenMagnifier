# -*- coding: utf-8 -*-
"""
ColorDetector: real-time color detection and color analysis for QImage frames.
Features:
    - Target colors: find every region of one of the target colors; regions (rect, center, pixel count) and
      coverage per target. Two match modes:
        * Similar (default): same hue (angle in Lab's a/b plane, tolerance in degrees) with enough chroma, at
          ANY lightness - shading, shadows, highlights and anti-aliased text of the same color all match.
          Gray / white / black targets match low-chroma pixels of close lightness instead.
        * Exact: CIE76 delta E distance (tolerance in delta E), for checking one precise UI color.
      Thin strokes (1 px text, lines) are kept; fragments closer than groupDistance are merged into one region.
    - Highlight mask: label image (0 = no match, k = target k - 1) and helpers to turn it into an overlay that
      either isolates the matches (dims everything else) or tints them with a contrasting color.
    - Dominant palette: stable (histogram based, no random k-means flicker) list of the main colors.
    - Color information: HEX, RGB, HSV, HSL, CMYK, CIE Lab and the nearest CSS / SVG color name.
    - Contrast: WCAG 2.x contrast ratio and AA / AAA rating between two colors.
    - Color codes: formatColor() in 13 formats (HEX, CSS rgb / hsl / lab, CMYK, QColor...) and sampleColor()
      (averaged N x N pick) for color pickers.
Results are plain Python data (JSON safe) except 'labelMask' (QImage), so they can be sent over a network.
Requires NumPy; OpenCV is optional (connected components = one rect per region instead of one per target).
"""
from ManyQt.QtCore import QObject, QElapsedTimer, pyqtSignal, pyqtSlot, pyqtProperty, Q_ENUMS, qVersion, Qt
from ManyQt.QtGui import QImage, QColor
from math import sqrt, cos, radians
from os.path import dirname
from enum import IntEnum
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:  # The analysis itself is Qt-free (core.py), shared with the headless server.
    from .core import ColorAnalyzer, rgbToLab, deltaE, labArray, clamp, CHROMATIC_MIN, STRONG_FACTOR, CHROMA_FACTOR, \
        nearestColorName as _nearestName, _linear, np, cv2
except:
    from core import ColorAnalyzer, rgbToLab, deltaE, labArray, clamp, CHROMATIC_MIN, STRONG_FACTOR, CHROMA_FACTOR, \
        nearestColorName as _nearestName, _linear, np, cv2
if np:
    from numpy import frombuffer, ascontiguousarray, uint8, ndarray, zeros


def toColor(color):
    """
    :param color: QColor | Qt.GlobalColor | int | str | unicode | QString
    :return: QColor
    """
    return QColor(color)


def colorToLab(color):
    """
    :param color: QColor | Qt.GlobalColor | int | str | unicode | QString
    :return: tuple[float, float, float]
    """
    c = toColor(color)  # type: QColor
    return rgbToLab(c.red(), c.green(), c.blue())


def nearestColorName(color):
    """
    :param color: QColor | Qt.GlobalColor | int | str | unicode | QString
    :return: (tuple[str, float]) Nearest CSS / SVG color name and its delta E.
    """
    c = toColor(color)  # type: QColor
    return _nearestName((c.red(), c.green(), c.blue()))


def relativeLuminance(color):
    """
    :param color: QColor | Qt.GlobalColor | int | str | unicode | QString
    :return: (float | int) WCAG relative luminance 0 .. 1.
    """
    c = toColor(color)  # type: QColor
    return 0.2126 * _linear(c.redF()) + 0.7152 * _linear(c.greenF()) + 0.0722 * _linear(c.blueF())


def contrastRatio(color1, color2):
    """
    :param color1: QColor | Qt.GlobalColor | int | str | unicode | QString
    :param color2: QColor | Qt.GlobalColor | int | str | unicode | QString
    :return: (float | int) WCAG contrast ratio 1 .. 21.
    """
    l1, l2 = relativeLuminance(color1), relativeLuminance(color2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def wcagRating(ratio):
    """
    :param ratio: float
    :return: (str | unicode | QString) 'AAA', 'AA', 'AA large' or 'Fail' for normal text.
    """
    return 'AAA' if ratio >= 7.0 else 'AA' if ratio >= 4.5 else 'AA large' if ratio >= 3.0 else 'Fail'


def colorInfo(color):
    """
    Everything about one color.
    :param color: QColor | Qt.GlobalColor | int | str | unicode | QString
    :return: (dict) hex, rgb, hsv, hsl, cmyk, lab, name, nameDeltaE.
    """
    c = toColor(color)  # type: QColor
    h, s, v, _ = c.getHsvF()
    hh, ss, ll, _ = c.getHslF()
    cc, mm, yy, kk, _ = c.getCmykF()
    name, de = nearestColorName(c)
    return {
        'hex': u'{}'.format(c.name()).upper(),
        'rgb': [c.red(), c.green(), c.blue()],
        'hsv': [int(round(max(h, 0.0) * 360)), int(round(s * 100)), int(round(v * 100))],
        'hsl': [int(round(max(hh, 0.0) * 360)), int(round(ss * 100)), int(round(ll * 100))],
        'cmyk': [int(round(x * 100)) for x in (cc, mm, yy, kk)],
        'lab': [round(x, 1) for x in colorToLab(c)],
        'name': name,
        'nameDeltaE': round(de, 1),
    }


COLOR_FORMATS = [
    ('hex', 'HEX'), ('hexLower', 'hex (lower case)'), ('hexBare', 'HEX without #'), ('rgb', 'CSS rgb()'),
    ('rgbTuple', 'RGB numbers'), ('rgbFloat', 'RGB 0..1'), ('hsl', 'CSS hsl()'), ('hsv', 'HSV'),
    ('cmyk', 'CMYK'), ('lab', 'CSS lab()'), ('qcolor', 'QColor(...)'), ('int', '0xRRGGBB'), ('name', 'Nearest name'),
]  # type: list[tuple[str, str]]  # (key, label), in menu order.


def formatColor(color, fmt='hex'):
    """
    Color code in a given format, ready for the clipboard.
    :param color: QColor | Qt.GlobalColor | int | str | unicode | QString
    :param fmt: (str | unicode | QString) One of the COLOR_FORMATS keys.
    :return: str | unicode | QString
    """
    c = toColor(color)  # type: QColor
    r, g, b = c.red(), c.green(), c.blue()  # type: int, int, int
    fmt = u'{}'.format(fmt)  # type: str
    if fmt == 'hexLower':
        return '#{:02x}{:02x}{:02x}'.format(r, g, b)
    if fmt == 'hexBare':
        return '{:02X}{:02X}{:02X}'.format(r, g, b)
    if fmt == 'rgb':
        return 'rgb({}, {}, {})'.format(r, g, b)
    if fmt == 'rgbTuple':
        return '{}, {}, {}'.format(r, g, b)
    if fmt == 'rgbFloat':
        return '{:.3f}, {:.3f}, {:.3f}'.format(r / 255.0, g / 255.0, b / 255.0)
    if fmt in ('hsl', 'hsv', 'cmyk', 'lab', 'name'):
        info = colorInfo(c)  # type: dict
        if fmt == 'hsl':
            return 'hsl({}, {}%, {}%)'.format(*info['hsl'])
        if fmt == 'hsv':
            return 'hsv({}, {}%, {}%)'.format(*info['hsv'])
        if fmt == 'cmyk':
            return 'cmyk({}%, {}%, {}%, {}%)'.format(*info['cmyk'])
        if fmt == 'lab':
            return 'lab({}% {} {})'.format(*info['lab'])
        return info['name']
    if fmt == 'qcolor':
        return 'QColor({}, {}, {})'.format(r, g, b)
    if fmt == 'int':
        return '0x{:02X}{:02X}{:02X}'.format(r, g, b)
    return '#{:02X}{:02X}{:02X}'.format(r, g, b)


def sampleColor(image, x, y, size=1):
    """
    Average color of a size x size square centred on a pixel (clipped to the image): steadier than one pixel on
    anti-aliased text, gradients and noisy textures. Pure Qt, no NumPy needed.
    :param image: QImage
    :param x: int
    :param y: int
    :param size: (int) 1, 3, 5, 9...
    :return: (QColor) Invalid when the pixel is outside the image.
    """
    if image is None or image.isNull() or not (0 <= x < image.width() and 0 <= y < image.height()):
        return QColor()
    half = max(0, int(size) // 2)  # type: int
    x0, x1 = max(0, x - half), min(image.width() - 1, x + half)  # type: int, int
    y0, y1 = max(0, y - half), min(image.height() - 1, y + half)  # type: int, int
    tr = tg = tb = n = 0  # type: int
    for yy in range(y0, y1 + 1):
        for xx in range(x0, x1 + 1):
            c = QColor(image.pixel(xx, yy))  # type: QColor
            tr, tg, tb, n = tr + c.red(), tg + c.green(), tb + c.blue(), n + 1
    return QColor(int(round(tr / float(n))), int(round(tg / float(n))), int(round(tb / float(n))))


def refinePick(image, x, y, radius=3):
    """
    Robust target color for a click: on thin text or icon edges the clicked pixel is often an anti-aliased blend
    (e.g. pale red on white), and in noisy images single pixels are off. Averages the same-family pixels of a
    (2r+1)^2 neighborhood that have at least 60 % of the strongest Chroma there: pale edges are left out, noise
    averages away, and the result is the object's typical color. Gray / white / black clicks average similar pixels.
    :param image: QImage
    :param x: int
    :param y: int
    :param radius: int
    :return: (QColor) Invalid when (x, y) is outside the image.
    """
    if image is None or image.isNull() or not (0 <= x < image.width() and 0 <= y < image.height()):
        return QColor()
    c0 = QColor(image.pixel(x, y))  # type: QColor
    l0 = colorToLab(c0)
    c0Chroma = sqrt(l0[1] ** 2 + l0[2] ** 2)  # type: float
    picks = []  # type: list  # (chroma, QColor)
    for yy in range(max(0, y - radius), min(image.height(), y + radius + 1)):
        for xx in range(max(0, x - radius), min(image.width(), x + radius + 1)):
            c = QColor(image.pixel(xx, yy))  # type: QColor
            lab = colorToLab(c)
            chroma = sqrt(lab[1] ** 2 + lab[2] ** 2)  # type: float
            if c0Chroma < 6.0:  # Really gray / white / black: keep similar pixels only.
                if deltaE(lab, l0) <= 12.0:
                    picks.append((0.0, c))
            elif lab[1] * l0[1] + lab[2] * l0[2] >= chroma * c0Chroma * cos(radians(45.0)):
                # Same color family (blending with white / black shifts the Lab hue: wide window).
                picks.append((chroma, c))
    if not picks:
        return c0
    strongest = max(p[0] for p in picks)  # type: float
    best = [c for chroma, c in picks if chroma >= 0.6 * strongest] or [c0]  # type: list
    n = float(len(best))  # type: float
    return QColor(int(round(sum(c.red() for c in best) / n)), int(round(sum(c.green() for c in best) / n)),
                  int(round(sum(c.blue() for c in best) / n)))


def complementary(color):
    """
    :param color: QColor | Qt.GlobalColor | int | str | unicode | QString
    :return: (QColor) Vivid complementary color, used to tint matches so they stand out.
    """
    h = toColor(color).hsvHue()  # type: int
    return QColor.fromHsv(((h if h >= 0 else 0) + 180) % 360, 255, 255)


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


def grayToArray(image):
    """
    :param image: (QImage) Format_Grayscale8 label image.
    :return: (ndarray) Owned (H, W) uint8 array.
    """
    img = image.convertToFormat(QImage.Format_Grayscale8)  # type: QImage
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()  # type: int, int, int
    nbytes = img.sizeInBytes() if hasattr(img, 'sizeInBytes') else img.byteCount()  # type: int
    ptr = img.constBits()
    if hasattr(ptr, 'setsize'):
        ptr.setsize(nbytes)
    return frombuffer(ptr, uint8, count=nbytes).reshape(h, bpl)[:, :w].copy()


def maskToOverlay(labelMask, colors, alpha=0.6, mode='isolate'):
    """
    Turn a label mask into an ARGB overlay of the mask size (draw it scaled over the analysed frame).
    :param labelMask: (QImage) Grayscale8, 0 = no match, k = target k - 1.
    :param colors: (list[QColor | str]) Target colors, in target order.
    :param alpha: (float | int) 0 .. 1 overlay strength.
    :param mode: (str | unicode | QString) 'isolate' dims everything that does not match, 'tint' paints the
        matches with a vivid complementary color.
    :return: QImage
    """
    if labelMask is None or labelMask.isNull() or not np:
        return QImage()
    lab = grayToArray(labelMask)  # type: ndarray
    h, w = lab.shape
    lut = zeros((256, 4), uint8)  # type: ndarray  # B, G, R, A = Format_ARGB32 memory order (little-endian).
    a = int(round(clamp(float(alpha), 0.0, 1.0) * 255))  # type: int
    if u'{}'.format(mode) == 'tint':
        for i, color in enumerate(list(colors)[:255]):
            c = complementary(color)  # type: QColor
            lut[i + 1] = (c.blue(), c.green(), c.red(), a)
    else:
        lut[0] = (16, 12, 12, a)
    rgba = ascontiguousarray(lut[lab])  # type: ndarray
    return QImage(rgba.data, w, h, w * 4, QImage.Format_ARGB32).copy()


class ColorDetector(QObject):
    """
    ColorDetector class.
    """

    class MatchMode(IntEnum):
        """
        MatchMode enumeration class.
        """
        Similar = 0  # type: int
        Exact = 1  # type: int

    Similar = MatchMode.Similar  # type: int
    Exact = MatchMode.Exact  # type: int
    targetsChanged = pyqtSignal()  # type: pyqtSignal
    settingsChanged = pyqtSignal()  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param targetColors: (list[QColor | str]) Colors to detect.
        :param tolerance: (float | int) 1 .. 100: hue degrees (Similar mode) or delta E (Exact mode).
        :param matchMode: (ColorDetector.MatchMode | int) Similar (any shade of the hue) or Exact.
        :param groupDistance: (int) Fragments closer than this (px) form one region, 0 = no grouping.
        :param minArea: (int) Smallest region (pixels) that is reported.
        :param maxRegions: (int) Maximum regions reported per target.
        :param paletteSize: (int) Dominant colors to compute, 0 disables the palette.
        :param returnMask: (bool) Include the label mask (QImage) in the results.
        :param maxPixels: (int) Bigger frames are sub-sampled to stay real time.
        :param targetsChanged: callable | None
        :param settingsChanged: callable | None
        :param args: any
        :param kwargs: any
        """
        targetColors = kwargs.pop('targetColors', [])  # type: list
        tolerance = kwargs.pop('tolerance', 15.0)  # type: float
        matchMode = kwargs.pop('matchMode', ColorDetector.Similar)  # type: int
        groupDistance = kwargs.pop('groupDistance', 5)  # type: int  # Joins the letters / words of a text line.
        minArea = kwargs.pop('minArea', 12)  # type: int
        maxRegions = kwargs.pop('maxRegions', 24)  # type: int
        paletteSize = kwargs.pop('paletteSize', 6)  # type: int
        returnMask = kwargs.pop('returnMask', True)  # type: bool
        maxPixels = kwargs.pop('maxPixels', 1280 * 800)  # type: int  # Full resolution keeps 1 px strokes.
        targetsChanged = kwargs.pop('targetsChanged', None)  # type: callable | None
        settingsChanged = kwargs.pop('settingsChanged', None)  # type: callable | None
        super(ColorDetector, self).__init__(*args, **kwargs)
        if callable(targetsChanged):
            self.targetsChanged.connect(targetsChanged)
        if callable(settingsChanged):
            self.settingsChanged.connect(settingsChanged)
        self.__m_targets = [toColor(c) for c in targetColors]  # type: list[QColor]
        self.__m_tolerance = clamp(float(tolerance), 1.0, 100.0)  # type: float
        self.__m_matchMode = ColorDetector.MatchMode(int(matchMode))  # type: ColorDetector.MatchMode
        self.__m_groupDistance = max(0, int(groupDistance))  # type: int
        self.__m_minArea = max(1, int(minArea))  # type: int
        self.__m_maxRegions = max(1, int(maxRegions))  # type: int
        self.__m_paletteSize = max(0, int(paletteSize))  # type: int
        self.__m_returnMask = bool(returnMask)  # type: bool
        self.__m_maxPixels = max(4096, int(maxPixels))  # type: int
        self.__m_clock = QElapsedTimer()  # type: QElapsedTimer
        self.__m_analyzer = ColorAnalyzer()  # type: ColorAnalyzer  # the Qt-free pipeline (core.py)

    # ---------- Helpers ----------
    @staticmethod
    def isAvailable():
        """
        :return: (bool) NumPy is installed.
        """
        return np

    @staticmethod
    def hasRegions():
        """
        :return: (bool) OpenCV is installed (one rect per region instead of one per target).
        """
        return np and cv2

    # ---------- Public API ----------
    def analyze(self, image):
        """
        :param image: QImage
        :return: (dict) width, height, scale, detections, coverage, palette, labelMask (QImage | None), timeMs.
        """
        result = {'width': 0, 'height': 0, 'scale': 1, 'detections': [], 'coverage': [], 'palette': [],
                  'labelMask': None, 'timeMs': 0.0}  # type: dict
        if not np or image is None or image.isNull():
            return result
        self.__m_clock.start()
        self.__m_analyzer.configure(targets=[(c.red(), c.green(), c.blue()) for c in self.__m_targets],
                                    tolerance=self.__m_tolerance, matchMode=int(self.__m_matchMode),
                                    groupDistance=self.__m_groupDistance, minArea=self.__m_minArea,
                                    maxRegions=self.__m_maxRegions, paletteSize=self.__m_paletteSize,
                                    returnMask=self.__m_returnMask, maxPixels=self.__m_maxPixels)
        result = self.__m_analyzer.analyze(qimageToArray(image))  # type: dict
        label = result.get('labelMask')
        if label is not None:
            h, w = label.shape[:2]
            result['labelMask'] = QImage(label.data, w, h, w, QImage.Format_Grayscale8).copy()
        result['timeMs'] = round(self.__m_clock.nsecsElapsed() / 1e6, 2)
        return result

    def getTargetColors(self):
        """
        :return: list[QColor]
        """
        return [QColor(c) for c in self.__m_targets]

    @pyqtSlot(list)
    def setTargetColors(self, targetColors):
        """
        :param targetColors: list[QColor | str]
        :return:
        """
        self.__m_targets = [toColor(c) for c in targetColors]  # type: list[QColor]
        self.targetsChanged.emit()

    @pyqtSlot(QColor)
    @pyqtSlot(Qt.GlobalColor)
    @pyqtSlot(int)
    @pyqtSlot(str)
    @pyqtSlot('QString')
    def addTargetColor(self, color):
        """
        :param color: QColor | Qt.GlobalColor | int | str | unicode | QString
        :return:
        """
        c = toColor(color)  # type: QColor
        if c.isValid() and all(t.rgb() != c.rgb() for t in self.__m_targets):
            self.__m_targets.append(c)
            self.targetsChanged.emit()

    @pyqtSlot(int)
    def removeTargetColor(self, index):
        """
        :param index: int
        :return:
        """
        if 0 <= int(index) < len(self.__m_targets):
            del self.__m_targets[int(index)]
            self.targetsChanged.emit()

    @pyqtSlot()
    def clearTargetColors(self):
        """
        :return:
        """
        if self.__m_targets:
            self.__m_targets = []  # type: list[QColor]
            self.targetsChanged.emit()

    def getTolerance(self):
        """
        :return: float | int
        """
        return self.__m_tolerance

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setTolerance(self, tolerance):
        """
        :param tolerance: (float | int) delta E, 1 .. 100.
        :return:
        """
        self.__m_tolerance = clamp(float(tolerance), 1.0, 100.0)  # type: float
        self.settingsChanged.emit()

    def getMatchMode(self):
        """
        :return: ColorDetector.MatchMode
        """
        return self.__m_matchMode

    @pyqtSlot(MatchMode)
    @pyqtSlot(int)
    def setMatchMode(self, matchMode):
        """
        :param matchMode: (ColorDetector.MatchMode | int) Similar or Exact.
        :return:
        """
        self.__m_matchMode = ColorDetector.MatchMode(int(matchMode))  # type: ColorDetector.MatchMode
        self.settingsChanged.emit()

    def getGroupDistance(self):
        """
        :return: int
        """
        return self.__m_groupDistance

    @pyqtSlot(int)
    def setGroupDistance(self, groupDistance):
        """
        :param groupDistance: (int) px, 0 = no grouping.
        :return:
        """
        self.__m_groupDistance = max(0, int(groupDistance))  # type: int
        self.settingsChanged.emit()

    def getMinArea(self):
        """
        :return: int
        """
        return self.__m_minArea

    @pyqtSlot(int)
    def setMinArea(self, minArea):
        """
        :param minArea: int
        :return:
        """
        self.__m_minArea = max(1, int(minArea))  # type: int
        self.settingsChanged.emit()

    def getMaxRegions(self):
        """
        :return: int
        """
        return self.__m_maxRegions

    @pyqtSlot(int)
    def setMaxRegions(self, maxRegions):
        """
        :param maxRegions: int
        :return:
        """
        self.__m_maxRegions = max(1, int(maxRegions))  # type: int
        self.settingsChanged.emit()

    def getPaletteSize(self):
        """
        :return: int
        """
        return self.__m_paletteSize

    @pyqtSlot(int)
    def setPaletteSize(self, paletteSize):
        """
        :param paletteSize: (int) 0 disables the palette.
        :return:
        """
        self.__m_paletteSize = max(0, int(paletteSize))  # type: int
        self.settingsChanged.emit()

    def isReturnMask(self):
        """
        :return: bool
        """
        return self.__m_returnMask

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setReturnMask(self, returnMask):
        """
        :param returnMask: bool
        :return:
        """
        self.__m_returnMask = bool(returnMask)  # type: bool
        self.settingsChanged.emit()

    def getMaxPixels(self):
        """
        :return: int
        """
        return self.__m_maxPixels

    @pyqtSlot(int)
    def setMaxPixels(self, maxPixels):
        """
        :param maxPixels: int
        :return:
        """
        self.__m_maxPixels = max(4096, int(maxPixels))  # type: int
        self.settingsChanged.emit()

    # ---------- Properties ----------
    targetColors = pyqtProperty(
        list, fget=getTargetColors, fset=setTargetColors, notify=targetsChanged)  # type: pyqtProperty
    Q_ENUMS('MatchMode' if qVersion()[0] == '4' else MatchMode)
    tolerance = pyqtProperty(float, fget=getTolerance, fset=setTolerance)  # type: pyqtProperty
    matchMode = pyqtProperty(int, fget=getMatchMode, fset=setMatchMode)  # type: pyqtProperty
    groupDistance = pyqtProperty(int, fget=getGroupDistance, fset=setGroupDistance)  # type: pyqtProperty
    minArea = pyqtProperty(int, fget=getMinArea, fset=setMinArea)  # type: pyqtProperty
    maxRegions = pyqtProperty(int, fget=getMaxRegions, fset=setMaxRegions)  # type: pyqtProperty
    paletteSize = pyqtProperty(int, fget=getPaletteSize, fset=setPaletteSize)  # type: pyqtProperty
    returnMask = pyqtProperty(bool, fget=isReturnMask, fset=setReturnMask)  # type: pyqtProperty
    maxPixels = pyqtProperty(int, fget=getMaxPixels, fset=setMaxPixels)  # type: pyqtProperty
