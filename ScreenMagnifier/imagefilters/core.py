# -*- coding: utf-8 -*-
"""
Image filters on NumPy arrays - pure Python + NumPy, no Qt (usable by the application and the headless server).
    applyFilters(arr, effect, brightness, contrast, saturation, strength) -> filtered copy
Adjustments (-100 .. 100, 0 = unchanged): brightness, contrast, saturation; applied first.
Effects (then blended with the adjusted image by strength 0 .. 100):
    NONE, GRAYSCALE, SEPIA, INVERT, HIGH_CONTRAST (auto levels + steep curve), WARM (less blue light),
    NIGHT_VISION, THERMAL (false colours by brightness), OUTLINE (edges over a dimmed image),
    PROTAN / DEUTAN / TRITAN (colour-blindness help: colours a red-, green- or blue-weak viewer would confuse are
    moved apart - see _CORRECTION for how the matrices were made and measured).
Arrays are (H, W, 3) uint8 RGB; every function returns a new uint8 array.
"""
try:
    from numpy import array, clip, dot, float32, uint8, empty, linspace, interp, percentile, sqrt, repeat, stack, \
        zeros_like
    numpy = True  # type: bool
except:
    numpy = False  # type: bool

NONE, GRAYSCALE, SEPIA, INVERT, HIGH_CONTRAST, WARM, NIGHT_VISION, THERMAL, OUTLINE, PROTAN, DEUTAN, TRITAN = range(12)
EFFECT_NAMES = [
    'None', 'Grayscale', 'Sepia', 'Invert', 'High contrast', 'Warm (less blue light)', 'Night vision',
    'Thermal (false colors)', 'Outline (edges)', 'Color-blind help: red-weak', 'Color-blind help: green-weak',
    'Color-blind help: blue-weak']  # type: list[str]  # index = effect

_LUMA = (0.2126, 0.7152, 0.0722)  # type: tuple  # Rec. 709
_SEPIA = ((0.393, 0.769, 0.189), (0.349, 0.686, 0.168), (0.272, 0.534, 0.131))  # type: tuple
_RGB_TO_LMS = ((17.8824, 43.5161, 4.11935), (3.45565, 27.1554, 3.86714), (0.0299566, 0.184309, 1.46709))
_LMS_TO_RGB = ((0.0809444479, -0.130504409, 0.116721066), (-0.0102485335, 0.0540193266, -0.113614708),
               (-0.000365296938, -0.00412161469, 0.693511405))
_SIMULATE = {  # Viénot / Brettel dichromacy in LMS space (what each viewer sees; used to measure _CORRECTION)
    PROTAN: ((0.0, 2.02344, -2.52581), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    DEUTAN: ((1.0, 0.0, 0.0), (0.494207, 0.0, 1.24827), (0.0, 0.0, 1.0)),
    TRITAN: ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-0.395913, 0.801109, 0.0)),
}  # type: dict
_CORRECTION = {  # colour-blindness help: one 3 x 3 matrix each (rows = output R, G, B; each row sums to 1)
    PROTAN: ((-0.021395, 1.013657, 0.007738), (-0.076196, 1.046547, 0.029649), (-0.047976, 0.006427, 1.041549)),
    DEUTAN: ((-0.054579, 1.031042, 0.023537), (-0.079481, 1.050765, 0.028716), (-0.080570, 0.059028, 1.021542)),
    TRITAN: ((0.650883, 0.525070, -0.175952), (0.361911, 0.811148, -0.173059), (0.360183, -0.029230, 0.669047)),
}  # type: dict
# How the matrices were made: each one minimises, for 600 random colours, the pairs that typical vision sees as
# different (CIE76 delta E >= 20) but the simulated viewer (_SIMULATE) cannot tell apart - the sum of
# max(0, min(20, typical distance) - viewer distance) squared - plus a penalty for colours pushed outside 0 .. 255
# (which would posterise the picture). Each row sums to 1, so whites, greys and blacks never change. On 600 other
# random colours they cut the pairs the viewer confuses (delta E < 10) by 20 % (red-weak), 38 % (green-weak) and
# 67 % (blue-weak); the classic Fidaner daltonisation increases them. Red / green differences become lightness
# differences, which red- and green-weak viewers see. The Strength slider blends the correction with the original.
_THERMAL_STOPS = ((0, (0, 0, 0)), (40, (40, 10, 110)), (95, (150, 20, 140)), (150, (225, 60, 50)),
                  (200, (250, 160, 20)), (240, (255, 240, 90)), (255, (255, 255, 255)))  # type: tuple
_THERMAL = []  # type: list  # lazily built 256 x 3 palette


def isAvailable():
    """
    :return: (bool) NumPy is installed (every effect needs it).
    """
    return numpy


def _luma(a):
    """
    :param a: (ndarray) (H, W, 3) float32.
    :return: (ndarray) (H, W) float32.
    """
    return a[..., 0] * _LUMA[0] + a[..., 1] * _LUMA[1] + a[..., 2] * _LUMA[2]


def _matrix(a, m):
    """
    :param a: (ndarray) (H, W, 3) float32.
    :param m: 3 x 3 matrix (rows = output channels).
    :return: ndarray
    """
    return dot(a, array(m, float32).T)


def _thermalPalette():
    """
    :return: (ndarray) 256 x 3 float32 palette, black -> purple -> red -> orange -> yellow -> white.
    """
    if not _THERMAL:
        xs = [s[0] for s in _THERMAL_STOPS]  # type: list
        lut = empty((256, 3), float32)
        for c in range(3):
            lut[:, c] = interp(linspace(0, 255, 256), xs, [s[1][c] for s in _THERMAL_STOPS])
        _THERMAL.append(lut)
    return _THERMAL[0]


def adjust(a, brightness=0, contrast=0, saturation=0):
    """
    :param a: (ndarray) (H, W, 3) float32 0 .. 255.
    :param brightness: (int) -100 .. 100.
    :param contrast: (int) -100 .. 100.
    :param saturation: (int) -100 .. 100 (-100 = gray).
    :return: (ndarray) float32.
    """
    if brightness:
        a += float(brightness) * 1.28
    if contrast:
        c = float(contrast) * 2.55  # type: float
        factor = (259.0 * (c + 255.0)) / (255.0 * (259.0 - c))  # type: float
        a = (a - 128.0) * factor + 128.0
    if saturation:
        gray = _luma(a)[..., None]
        a = gray + (a - gray) * (1.0 + float(saturation) / 100.0)
    return a


def effect(a, kind):
    """
    :param a: (ndarray) (H, W, 3) float32 0 .. 255 (already adjusted).
    :param kind: (int) Effect number.
    :return: (ndarray) float32.
    """
    if kind == GRAYSCALE:
        return repeat(_luma(a)[..., None], 3, axis=2)
    if kind == SEPIA:
        return _matrix(a, _SEPIA)
    if kind == INVERT:
        return 255.0 - a
    if kind == HIGH_CONTRAST:
        y = _luma(a)
        lo, hi = percentile(y, 2), percentile(y, 98)
        span = max(1.0, float(hi - lo))  # type: float
        b = (a - lo) * (255.0 / span)  # auto levels, then a steep S-curve
        b = clip(b, 0, 255) / 255.0
        return (b * b * (3.0 - 2.0 * b)) * 255.0
    if kind == WARM:
        return a * array((1.0, 0.86, 0.62), float32)
    if kind == NIGHT_VISION:  # lift the shadows (gamma), keep the highlights apart, green phosphor
        y = 255.0 * (clip(_luma(a), 0, 255) / 255.0) ** 0.55
        return stack([y * 0.28, y, y * 0.26], axis=2)
    if kind == THERMAL:
        return _thermalPalette()[clip(_luma(a), 0, 255).astype(uint8)]
    if kind == OUTLINE:
        y = _luma(a)
        gx = zeros_like(y)
        gy = zeros_like(y)
        gx[:, 1:-1] = y[:, 2:] - y[:, :-2]
        gy[1:-1, :] = y[2:, :] - y[:-2, :]
        edges = clip(sqrt(gx * gx + gy * gy) * 1.6, 0, 255)[..., None]
        return a * 0.35 + edges
    if kind in _CORRECTION:
        return _matrix(a, _CORRECTION[kind])
    return a


def applyFilters(arr, kind=NONE, brightness=0, contrast=0, saturation=0, strength=100):
    """
    :param arr: (ndarray) (H, W, 3) uint8 RGB.
    :param kind: (int) Effect number (see EFFECT_NAMES).
    :param brightness: (int) -100 .. 100.
    :param contrast: (int) -100 .. 100.
    :param saturation: (int) -100 .. 100.
    :param strength: (int) 0 .. 100: how much of the effect (100 = all of it).
    :return: (ndarray) Filtered (H, W, 3) uint8 copy.
    """
    a = arr.astype(float32)
    a = adjust(a, brightness, contrast, saturation)
    if kind != NONE and strength > 0:
        e = effect(clip(a, 0, 255), int(kind))
        k = min(1.0, max(0.0, float(strength) / 100.0))  # type: float
        a = e if k >= 1.0 else a + (e - a) * k
    return clip(a + 0.5, 0, 255).astype(uint8)


def isIdentity(kind=NONE, brightness=0, contrast=0, saturation=0, strength=100):
    """
    :return: (bool) These settings leave every image unchanged (skip the work).
    """
    return (kind == NONE or strength <= 0) and not brightness and not contrast and not saturation
