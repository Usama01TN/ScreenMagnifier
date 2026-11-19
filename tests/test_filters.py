# -*- coding: utf-8 -*-
"""
Zoomer filters (imagefilters/core.py, NumPy): every effect works, and the color-blindness help really helps.
"""
from pytest import mark, importorskip
from itertools import combinations

numpy = importorskip('numpy')
from ScreenMagnifier.imagefilters import core  # noqa: E402


def test_no_filter_changes_nothing_and_effects_do_what_they_say():
    rgb = numpy.array([[[200, 60, 40], [10, 220, 90]]], numpy.uint8)
    assert (core.applyFilters(rgb) == rgb).all() and core.isIdentity()
    gray = core.applyFilters(rgb, core.GRAYSCALE)
    assert (gray[..., 0] == gray[..., 1]).all() and (gray[..., 1] == gray[..., 2]).all()
    assert (core.applyFilters(rgb, core.INVERT) == 255 - rgb).all()
    assert (core.applyFilters(rgb, brightness=40) >= rgb).all()
    half = core.applyFilters(rgb, core.INVERT, strength=50)[0, 0]
    assert all(abs(int(v) - 128) <= 1 for v in half)


@mark.parametrize('effect', range(len(core.EFFECT_NAMES)))
def test_every_effect_returns_an_image(effect):
    arr = numpy.random.default_rng(effect).integers(0, 256, (24, 32, 3)).astype(numpy.uint8)
    out = core.applyFilters(arr, effect, 20, -20, 30, 80)
    assert out.shape == arr.shape and out.dtype == numpy.uint8


def test_colour_blind_help_keeps_greys_and_reduces_confusion():
    from ScreenMagnifier.colordetector.core import labArray
    lab = lambda a: labArray(numpy.clip(a, 0, 255).astype(numpy.uint8).reshape(-1, 1, 3)).reshape(-1, 3)
    colours = numpy.random.default_rng(2024).uniform(0, 255, (160, 3)).astype(numpy.float32)
    pairs = numpy.array(list(combinations(range(len(colours)), 2)))
    typical = numpy.linalg.norm(lab(colours)[pairs[:, 0]] - lab(colours)[pairs[:, 1]], axis=1)
    for kind in (core.PROTAN, core.DEUTAN, core.TRITAN):
        matrix = numpy.array(core._CORRECTION[kind])
        assert numpy.allclose(matrix.sum(axis=1), 1.0, atol=1e-5)  # whites, grays, blacks unchanged
        seen = numpy.array(core._LMS_TO_RGB) @ numpy.array(core._SIMULATE[kind]) @ numpy.array(core._RGB_TO_LMS)

        def confused(rgb):
            v = lab(numpy.clip(rgb, 0, 255) @ seen.T)
            d = numpy.linalg.norm(v[pairs[:, 0]] - v[pairs[:, 1]], axis=1)
            return int(numpy.sum((typical >= 20) & (d < 10)))

        corrected = core.applyFilters(colours.astype(numpy.uint8).reshape(-1, 1, 3), kind).reshape(-1, 3)
        assert confused(corrected.astype(numpy.float32)) < confused(colours), core.EFFECT_NAMES[kind]
