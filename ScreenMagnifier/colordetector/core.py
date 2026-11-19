# -*- coding: utf-8 -*-
"""
Color analysis on NumPy arrays - pure Python + NumPy, OpenCV optional, no Qt: used by the Qt ColorDetector and by
the headless server (which also runs without Qt, e.g. on Android).
    - Color maths: sRGB -> CIE Lab, delta E, CSS color names (static table, same names and order as Qt).
    - ColorAnalyzer: target color regions (Similar shades: same hue at any lightness, with hysteresis against
      look-alikes; Exact: delta E), grouped fragments, coverage, dominant palette, label mask.
Colors are (r, g, b) tuples or '#RRGGBB' strings.
"""
from math import ceil, sqrt, cos, radians
from time import time

try:
    from numpy import array, zeros, where, cbrt, bincount, argsort, ascontiguousarray, ndarray, float32, uint8, \
        int32, ones, full, minimum, maximum
    from numpy import sqrt as npsqrt

    np = True  # type: bool
except:
    np = False  # type: bool
try:
    from cv2 import connectedComponents, dilate, boxFilter, blur, cvtColor, COLOR_RGB2Lab

    cv2 = True  # type: bool
except:
    cv2 = False  # type: bool
scipy = False  # type: bool  # SciPy replaces OpenCV for regions (e.g. Android: Termux / Pydroid have SciPy).
if not cv2:
    try:
        from scipy.ndimage import label as _label, binary_dilation as _dilation, uniform_filter as _uniform

        scipy = True  # type: bool
    except:
        pass


def _components(mask):
    """
    :param mask: (ndarray) uint8 0/1.
    :return: (tuple[int, ndarray]) Number of labels (background included) and the 8-connected label image.
    """
    if cv2:
        return connectedComponents(mask, connectivity=8)[:2]
    labels, n = _label(mask, structure=ones((3, 3), int32))
    return n + 1, labels


def _neighbours(mask):
    """
    :param mask: (ndarray) uint8 0/1.
    :return: (ndarray) Matching pixels in each 3 x 3 window (self included).
    """
    if cv2:
        return boxFilter(mask, -1, (3, 3), normalize=False)
    return (_uniform(mask.astype(float32), 3, mode='constant') * 9.0 + 0.5).astype(int32)


def _grow(mask, radius):
    """
    :param mask: (ndarray) uint8 0/1.
    :param radius: (int) Square dilation radius.
    :return: (ndarray) uint8 0/1.
    """
    if cv2:
        return dilate(mask, ones((2 * radius + 1, 2 * radius + 1), uint8))
    return _dilation(mask > 0, structure=ones((2 * radius + 1, 2 * radius + 1), bool)).astype(uint8)


SIMILAR, EXACT = 0, 1  # match modes (ColorDetector.Similar / ColorDetector.Exact)

CSS_COLORS = [  # (name, RRGGBB): the CSS / SVG color names, in Qt's order (ties keep the first)
    ('aliceblue', 'F0F8FF'), ('antiquewhite', 'FAEBD7'), ('aqua', '00FFFF'), ('aquamarine', '7FFFD4'),
    ('azure', 'F0FFFF'), ('beige', 'F5F5DC'), ('bisque', 'FFE4C4'), ('black', '000000'),
    ('blanchedalmond', 'FFEBCD'), ('blue', '0000FF'), ('blueviolet', '8A2BE2'), ('brown', 'A52A2A'),
    ('burlywood', 'DEB887'), ('cadetblue', '5F9EA0'), ('chartreuse', '7FFF00'), ('chocolate', 'D2691E'),
    ('coral', 'FF7F50'), ('cornflowerblue', '6495ED'), ('cornsilk', 'FFF8DC'), ('crimson', 'DC143C'),
    ('darkblue', '00008B'), ('darkcyan', '008B8B'), ('darkgoldenrod', 'B8860B'), ('darkgray', 'A9A9A9'),
    ('darkgreen', '006400'), ('darkkhaki', 'BDB76B'), ('darkmagenta', '8B008B'), ('darkolivegreen', '556B2F'),
    ('darkorange', 'FF8C00'), ('darkorchid', '9932CC'), ('darkred', '8B0000'), ('darksalmon', 'E9967A'),
    ('darkseagreen', '8FBC8F'), ('darkslateblue', '483D8B'), ('darkslategray', '2F4F4F'),
    ('darkturquoise', '00CED1'), ('darkviolet', '9400D3'), ('deeppink', 'FF1493'), ('deepskyblue', '00BFFF'),
    ('dimgray', '696969'), ('dodgerblue', '1E90FF'), ('firebrick', 'B22222'), ('floralwhite', 'FFFAF0'),
    ('forestgreen', '228B22'), ('fuchsia', 'FF00FF'), ('gainsboro', 'DCDCDC'), ('ghostwhite', 'F8F8FF'),
    ('gold', 'FFD700'), ('goldenrod', 'DAA520'), ('gray', '808080'), ('green', '008000'),
    ('greenyellow', 'ADFF2F'), ('honeydew', 'F0FFF0'), ('hotpink', 'FF69B4'), ('indianred', 'CD5C5C'),
    ('indigo', '4B0082'), ('ivory', 'FFFFF0'), ('khaki', 'F0E68C'), ('lavender', 'E6E6FA'),
    ('lavenderblush', 'FFF0F5'), ('lawngreen', '7CFC00'), ('lemonchiffon', 'FFFACD'), ('lightblue', 'ADD8E6'),
    ('lightcoral', 'F08080'), ('lightcyan', 'E0FFFF'), ('lightgoldenrodyellow', 'FAFAD2'), ('lightgray', 'D3D3D3'),
    ('lightgreen', '90EE90'), ('lightpink', 'FFB6C1'), ('lightsalmon', 'FFA07A'), ('lightseagreen', '20B2AA'),
    ('lightskyblue', '87CEFA'), ('lightslategray', '778899'), ('lightsteelblue', 'B0C4DE'),
    ('lightyellow', 'FFFFE0'), ('lime', '00FF00'), ('limegreen', '32CD32'), ('linen', 'FAF0E6'),
    ('maroon', '800000'), ('mediumaquamarine', '66CDAA'), ('mediumblue', '0000CD'), ('mediumorchid', 'BA55D3'),
    ('mediumpurple', '9370DB'), ('mediumseagreen', '3CB371'), ('mediumslateblue', '7B68EE'),
    ('mediumspringgreen', '00FA9A'), ('mediumturquoise', '48D1CC'), ('mediumvioletred', 'C71585'),
    ('midnightblue', '191970'), ('mintcream', 'F5FFFA'), ('mistyrose', 'FFE4E1'), ('moccasin', 'FFE4B5'),
    ('navajowhite', 'FFDEAD'), ('navy', '000080'), ('oldlace', 'FDF5E6'), ('olive', '808000'),
    ('olivedrab', '6B8E23'), ('orange', 'FFA500'), ('orangered', 'FF4500'), ('orchid', 'DA70D6'),
    ('palegoldenrod', 'EEE8AA'), ('palegreen', '98FB98'), ('paleturquoise', 'AFEEEE'), ('palevioletred', 'DB7093'),
    ('papayawhip', 'FFEFD5'), ('peachpuff', 'FFDAB9'), ('peru', 'CD853F'), ('pink', 'FFC0CB'), ('plum', 'DDA0DD'),
    ('powderblue', 'B0E0E6'), ('purple', '800080'), ('red', 'FF0000'), ('rosybrown', 'BC8F8F'),
    ('royalblue', '4169E1'), ('saddlebrown', '8B4513'), ('salmon', 'FA8072'), ('sandybrown', 'F4A460'),
    ('seagreen', '2E8B57'), ('seashell', 'FFF5EE'), ('sienna', 'A0522D'), ('silver', 'C0C0C0'),
    ('skyblue', '87CEEB'), ('slateblue', '6A5ACD'), ('slategray', '708090'), ('snow', 'FFFAFA'),
    ('springgreen', '00FF7F'), ('steelblue', '4682B4'), ('tan', 'D2B48C'), ('teal', '008080'),
    ('thistle', 'D8BFD8'), ('tomato', 'FF6347'), ('turquoise', '40E0D0'), ('violet', 'EE82EE'),
    ('wheat', 'F5DEB3'), ('white', 'FFFFFF'), ('whitesmoke', 'F5F5F5'), ('yellow', 'FFFF00'),
    ('yellowgreen', '9ACD32'),
]  # type: list[tuple[str, str]]
_SRGB_TO_XYZ = ((0.4124564, 0.3575761, 0.1804375),
                (0.2126729, 0.7151522, 0.0721750),
                (0.0193339, 0.1191920, 0.9503041))  # type: tuple
_WHITE = (0.95047, 1.0, 1.08883)  # type: tuple  # D65 reference white.
CHROMATIC_MIN = 12.0  # type: float  # Lab chroma under which a target counts as gray / white / black.
STRONG_FACTOR = 0.6  # type: float  # Strong evidence (hysteresis seeds): >= 60 % chroma and half the hue window.
CHROMA_FACTOR = 0.45  # type: float  # Similar mode: a pixel needs >= 45 % of the target chroma (shadows of the
#                                      same color keep ~55-65 %, dull look-alikes such as brown for red do not).
_NAME_TABLE = []  # type: list  # Lazily built [(name, (L, a, b))] for nearestColorName().
_LINEAR_LUT = []  # type: list  # Lazily built 256-entry sRGB -> linear table (ndarray).


def parseColor(color):
    """
    :param color: ((r, g, b) | '#RRGGBB' | '#RGB' | CSS name) A colour.
    :return: (tuple[int, int, int]) (r, g, b).
    """
    if isinstance(color, (tuple, list)):
        return int(color[0]), int(color[1]), int(color[2])
    text = u'{}'.format(color).strip()  # type: str
    if not text.startswith('#'):
        for name, code in CSS_COLORS:
            if name == text.lower():
                text = '#' + code
                break
    text = text.lstrip('#')
    if len(text) == 3:
        text = ''.join(ch * 2 for ch in text)
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def hexName(color):
    """
    :param color: (r, g, b) | str
    :return: (str | unicode | QString) '#RRGGBB'.
    """
    return '#{:02X}{:02X}{:02X}'.format(*parseColor(color))


def clamp(x, a, b):
    """
    :param x: float | int
    :param a: float | int
    :param b: float | int
    :return: float | int
    """
    return a if x < a else b if x > b else x


def _linear(c):
    """
    sRGB channel (0 .. 1) -> linear light.
    :param c: float
    :return: float | int
    """
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgbToLab(r, g, b):
    """
    :param r: (int) 0 .. 255
    :param g: (int) 0 .. 255
    :param b: (int) 0 .. 255
    :return: (tuple[float, float, float]) CIE L*a*b* (D65).
    """
    lr, lg, lb = _linear(r / 255.0), _linear(g / 255.0), _linear(b / 255.0)
    xyz = [(m[0] * lr + m[1] * lg + m[2] * lb) / w for m, w in zip(_SRGB_TO_XYZ, _WHITE)]  # type: list
    f = [v ** (1.0 / 3.0) if v > 0.008856 else 7.787 * v + 16.0 / 116.0 for v in xyz]  # type: list
    return 116.0 * f[1] - 16.0, 500.0 * (f[0] - f[1]), 200.0 * (f[1] - f[2])


def deltaE(lab1, lab2):
    """
    :param lab1: tuple[float, float, float]
    :param lab2: tuple[float, float, float]
    :return: (float | int) CIE76 color difference (about 2.3 = just noticeable).
    """
    return sqrt(sum((p - q) ** 2 for p, q in zip(lab1, lab2)))


def nearestColorName(color):
    """
    :param color: (r, g, b) | str
    :return: (tuple[str, float]) Nearest CSS / SVG color name and its delta E.
    """
    if not _NAME_TABLE:
        for name, code in CSS_COLORS:
            _NAME_TABLE.append((name, rgbToLab(*parseColor('#' + code))))
    lab = rgbToLab(*parseColor(color))
    best = min(_NAME_TABLE, key=lambda item: deltaE(lab, item[1]))
    return best[0], deltaE(lab, best[1])


def labArray(arr):
    """
    Vectorised sRGB -> CIE Lab (OpenCV float conversion when available: about 3x faster, < 0.2 delta E).
    :param arr: (ndarray) (H, W, 3) uint8 RGB.
    :return: (ndarray) (H, W, 3) float32 Lab.
    """
    if cv2:
        rgb = arr.astype(float32)  # type: ndarray
        rgb *= 1.0 / 255.0
        return cvtColor(rgb, COLOR_RGB2Lab)
    if not _LINEAR_LUT:
        _LINEAR_LUT.append(array([_linear(i / 255.0) for i in range(256)], float32))
    lin = _LINEAR_LUT[0][arr]  # type: ndarray
    xyz = lin.dot(array(_SRGB_TO_XYZ, float32).T) / array(_WHITE, float32)  # type: ndarray
    f = where(xyz > 0.008856, cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)  # type: ndarray
    out = zeros(arr.shape, float32)  # type: ndarray
    out[..., 0] = 116.0 * f[..., 1] - 16.0
    out[..., 1] = 500.0 * (f[..., 0] - f[..., 1])
    out[..., 2] = 200.0 * (f[..., 1] - f[..., 2])
    return out


class ColorAnalyzer(object):
    """
    ColorAnalyzer class: options are plain attributes (set them, then analyze()).
    """

    def __init__(self, **options):
        """
        :param options: targets ([(r, g, b) | str]), tolerance, matchMode (SIMILAR / EXACT), groupDistance, minArea,
            maxRegions, paletteSize, returnMask, maxPixels - the ColorDetector options.
        """
        self.targets = []  # type: list
        self.tolerance = 15.0  # type: float
        self.matchMode = SIMILAR  # type: int
        self.groupDistance = 5  # type: int
        self.minArea = 12  # type: int
        self.maxRegions = 24  # type: int
        self.paletteSize = 6  # type: int
        self.returnMask = True  # type: bool
        self.maxPixels = 1280 * 800  # type: int
        self.configure(**options)

    def configure(self, **options):
        """
        :param options: see __init__ (unknown names are ignored, values are clamped).
        :return:
        """
        if 'targets' in options:
            self.targets = [parseColor(c) for c in options['targets']][:254]  # type: list
        if 'tolerance' in options:
            self.tolerance = clamp(float(options['tolerance']), 1.0, 100.0)  # type: float
        if 'matchMode' in options:
            self.matchMode = EXACT if int(options['matchMode']) == EXACT else SIMILAR  # type: int
        if 'groupDistance' in options:
            self.groupDistance = max(0, int(options['groupDistance']))  # type: int
        if 'minArea' in options:
            self.minArea = max(1, int(options['minArea']))  # type: int
        if 'maxRegions' in options:
            self.maxRegions = max(1, int(options['maxRegions']))  # type: int
        if 'paletteSize' in options:
            self.paletteSize = max(0, int(options['paletteSize']))  # type: int
        if 'returnMask' in options:
            self.returnMask = bool(options['returnMask'])  # type: bool
        if 'maxPixels' in options:
            self.maxPixels = max(4096, int(options['maxPixels']))  # type: int

    def _palette(self, arr):
        """
        :param arr: (ndarray) RGB pixels.
        :return: list[dict]
        """
        flat = arr.reshape(-1, 3)  # type: ndarray
        step = max(1, int(flat.shape[0] // 65536))  # type: int
        px = flat[::step].astype(int32)  # type: ndarray
        bins = (px[:, 0] >> 4) * 256 + (px[:, 1] >> 4) * 16 + (px[:, 2] >> 4)  # type: ndarray
        counts = bincount(bins, minlength=4096)  # type: ndarray
        sums = [bincount(bins, weights=px[:, k], minlength=4096) for k in range(3)]  # type: list
        total = float(px.shape[0])  # type: float
        groups = []  # type: list  # [lab, (r, g, b), count]
        for b in argsort(counts)[::-1][:64]:
            if counts[b] == 0:
                break
            rgb = tuple(int(round(sums[k][b] / counts[b])) for k in range(3))  # type: tuple
            lb = rgbToLab(*rgb)
            for grp in groups:
                if deltaE(grp[0], lb) < 12.0:
                    grp[2] += int(counts[b])
                    break
            else:
                groups.append([lb, rgb, int(counts[b])])
        groups.sort(key=lambda g: -g[2])
        out, byName = [], {}  # type: list, dict  # Groups sharing a color name are merged (gradients).
        for lb, rgb, count in [g for g in groups if g[2] / total >= 0.003]:
            name = nearestColorName(rgb)[0]  # type: str
            if name in byName:
                byName[name]['fraction'] = round(byName[name]['fraction'] + count / total, 4)
                continue
            byName[name] = {'color': hexName(rgb), 'fraction': round(count / total, 4), 'name': name}
            out.append(byName[name])
        out.sort(key=lambda c: -c['fraction'])  # Merging changed the shares: sort again.
        return out[:self.paletteSize]

    def _match(self, lab, chroma, ab, abChroma, target):
        """
        Pixels matching one target.
        :param lab: (ndarray) (H, W, 3) Lab frame.
        :param chroma: (ndarray) (H, W) Lab chroma of the frame.
        :param ab: (ndarray) (H, W, 2) a/b plane smoothed 3 x 3: hue direction with ~3x less noise (blending
            with a neutral background shrinks the vector but keeps its direction, so thin text keeps its hue).
        :param abChroma: (ndarray) (H, W) length of the smoothed a/b vector.
        :param target: (tuple) (r, g, b)
        :return: (tuple[ndarray, ndarray | None]) Weak mask (all matches) and strong mask (hysteresis seeds, None
            when every match counts as strong: Exact mode, gray targets), uint8 0/1.
        """
        tl = rgbToLab(*target)
        tol = self.tolerance  # type: float
        L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
        if self.matchMode == EXACT:
            dl, da, db = L - tl[0], A - tl[1], B - tl[2]
            return (dl * dl + da * da + db * db <= tol * tol).astype(uint8), None
        ct = sqrt(tl[1] * tl[1] + tl[2] * tl[2])  # type: float
        if ct < CHROMATIC_MIN:
            # Gray / white / black target: hue is meaningless, match low chroma and close lightness.
            return ((chroma <= max(8.0, 0.6 * tol)) & (abs(L - tl[0]) <= 1.2 * tol)).astype(uint8), None
        # Chromatic target: same hue (angle in the a/b plane) and enough chroma, ANY lightness, so shading,
        # shadows and highlights of the same color match. cos(angle) test avoids a per-pixel atan2.
        cosTol = cos(radians(min(tol, 89.0)))  # type: float
        dot = ab[..., 0] * tl[1] + ab[..., 1] * tl[2]  # type: ndarray
        bright = L >= 3.0  # type: ndarray
        weak = (chroma >= max(8.0, CHROMA_FACTOR * ct)) & (dot >= abChroma * (ct * cosTol)) & bright  # type: ndarray
        strong = weak & (chroma >= STRONG_FACTOR * ct) & (dot >= abChroma * (ct * cos(radians(min(tol, 89.0) / 2.0))))
        return weak.astype(uint8), strong.astype(uint8)

    def _regions(self, mask, step, strong=None):
        """
        Regions of a mask: fragments closer than groupDistance are merged (text line, noisy object = one box) and
        scattered specks (noise, isolated look-alike pixels) are dropped. A pixel with at least 2 matching
        neighbors is "core" (true for every pixel of a 1 px stroke or line, rarely for noise); only matches
        within groupDistance of a core pixel are kept.
        :param mask: (ndarray) uint8 0/1, all matches.
        :param step: (int) Sub-sampling step of the frame (coordinates are scaled back).
        :param strong: (ndarray | None) Strong matches: a group (built from all matches, so anti-aliased pixels
            bridge the letters of a text line) is kept only if it holds >= 3 strong pixels (hysteresis), so
            borderline look-alike pixels (e.g. noisy brown for a red target) never form regions on their own.
        :return: (tuple[list, ndarray]) Regions (pixels, [x, y, w, h], [cx, cy]) in frame pixels, cleaned mask.
        """
        out = []  # type: list
        count = int(mask.sum())  # type: int
        if not cv2 and not scipy:  # NumPy only: one box per target color
            if count * step * step >= self.minArea:
                ys, xs = where(mask > 0)
                x0, y0 = int(xs.min()), int(ys.min())
                out.append((count, [x0 * step, y0 * step, (int(xs.max()) - x0 + 1) * step,
                                    (int(ys.max()) - y0 + 1) * step],
                            [float(xs.mean()) * step, float(ys.mean()) * step]))
            return out, mask
        core = mask & (_neighbours(mask) >= 3).astype(uint8)  # type: ndarray  # self + 2 neighbors
        gap = max(1, int(round(self.groupDistance / float(step))))  # type: int
        grouped = _grow(core, gap)  # type: ndarray
        n, labels = _components(grouped)
        keep = bincount(labels[core > 0], minlength=n) > 0  # type: ndarray  # groups with core pixels
        if strong is not None:  # Hysteresis: a group must contain strong evidence, not only borderline pixels.
            keep &= bincount(labels[(strong & mask) > 0], minlength=n) >= 3
        keep[0] = False
        mask = mask & keep[labels].astype(uint8)  # type: ndarray  # Specks / look-alike-only groups are dropped.
        ys, xs = where(mask > 0)
        ls = labels[ys, xs]  # type: ndarray  # Group of every matching pixel (dilation pixels are not counted).
        pixels = bincount(ls, minlength=n)  # type: ndarray
        sx, sy = bincount(ls, weights=xs, minlength=n), bincount(ls, weights=ys, minlength=n)
        x0, y0 = full(n, mask.shape[1], int32), full(n, mask.shape[0], int32)
        x1, y1 = full(n, -1, int32), full(n, -1, int32)
        minimum.at(x0, ls, xs)
        minimum.at(y0, ls, ys)
        maximum.at(x1, ls, xs)
        maximum.at(y1, ls, ys)
        for k in range(1, n):
            area = int(pixels[k]) * step * step  # type: int
            if area >= self.minArea:
                out.append((area, [int(x0[k]) * step, int(y0[k]) * step, int(x1[k] - x0[k] + 1) * step,
                                   int(y1[k] - y0[k] + 1) * step],
                            [float(sx[k] / pixels[k]) * step, float(sy[k] / pixels[k]) * step]))
        return out, mask

    def analyze(self, arr):
        """
        :param arr: (numpy.ndarray) (H, W, 3) uint8 RGB frame.
        :return: (dict) width, height, scale, detections, coverage, palette, labelMask ((H, W) uint8 array of
            target index + 1, or None), timeMs.
        """
        result = {'width': 0, 'height': 0, 'scale': 1, 'detections': [], 'coverage': [], 'palette': [],
                  'labelMask': None, 'timeMs': 0.0}  # type: dict
        if not np or arr is None or arr.size == 0:
            return result
        started = time()  # type: float
        h0, w0 = arr.shape[:2]
        step = max(1, int(ceil(sqrt(w0 * h0 / float(self.maxPixels)))))  # type: int
        if step > 1:
            arr = arr[::step, ::step]  # type: ndarray
        h, w = arr.shape[:2]
        label = zeros((h, w), uint8)  # type: ndarray
        if self.targets:
            lab = labArray(arr)  # type: ndarray
            chroma = npsqrt(lab[..., 1] * lab[..., 1] + lab[..., 2] * lab[..., 2])  # type: ndarray
            if cv2:
                ab = blur(ascontiguousarray(lab[..., 1:3]), (3, 3))  # type: ndarray
            elif scipy:
                ab = _uniform(lab[..., 1:3], (3, 3, 1), mode='nearest')  # type: ndarray
            else:
                ab = lab[..., 1:3]  # type: ndarray
            abChroma = npsqrt(ab[..., 0] * ab[..., 0] + ab[..., 1] * ab[..., 1])  # type: ndarray
            for i, target in enumerate(self.targets[:254]):
                weak, strong = self._match(lab, chroma, ab, abChroma, target)
                regions, mask = self._regions(weak, step, strong)
                count = int(mask.sum())  # type: int
                code = hexName(target)  # type: str
                name = nearestColorName(target)[0]  # type: str
                result['coverage'].append({'target': i, 'color': code, 'name': name,
                                           'fraction': round(count / float(w * h), 5)})
                if not count:
                    continue
                label[(mask > 0) & (label == 0)] = i + 1
                regions.sort(key=lambda rg: -rg[0])
                for area, rect, centre in regions[:self.maxRegions]:
                    result['detections'].append({'target': i, 'color': code, 'name': name, 'rect': rect,
                                                 'center': [round(centre[0], 1), round(centre[1], 1)],
                                                 'pixels': int(area)})
            if self.returnMask:
                result['labelMask'] = ascontiguousarray(label)
        if self.paletteSize:
            result['palette'] = self._palette(arr)
        result.update(width=w0, height=h0, scale=step, timeMs=round((time() - started) * 1000.0, 2))
        return result
