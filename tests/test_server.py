# -*- coding: utf-8 -*-
"""
The analysis server is pure Python (no Qt): it must run where no Qt binding exists (e.g. Android).
"""
from os.path import dirname, abspath
from subprocess import run, PIPE
from pytest import importorskip
from sys import executable
from zlib import compress
from struct import pack

ROOT = dirname(dirname(abspath(__file__)))  # type: str
BLOCK_QT = '''
from importlib.abc import MetaPathFinder
from numpy import run_module
import sys

class BlockQt(MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in ('ManyQt', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'PyQt4', 'PySide'):
            raise ImportError('the server imported ' + name)

sys.meta_path.insert(0, BlockQt())
sys.argv = ['server', '--selftest']
run_module('ScreenMagnifier.server', run_name='__main__')
'''
numpy = importorskip('numpy')


def test_server_runs_with_every_qt_binding_blocked():
    result = run([executable, '-c', BLOCK_QT], cwd=ROOT, stdout=PIPE, stderr=PIPE, universal_newlines=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'SELFTEST' in result.stdout and 'FAILED' not in result.stdout


def test_raw_images_round_trip_and_are_bounded():
    from ScreenMagnifier.netprotocol.wire import encodeArray, decodeArray, unpackRaw, RAWZ_MAGIC
    rgb = numpy.arange(24 * 32 * 3, dtype=numpy.uint8).reshape(24, 32, 3)
    gray = numpy.arange(24 * 32, dtype=numpy.uint8).reshape(24, 32)
    assert (decodeArray(encodeArray(rgb, 'RAWZ')[0]) == rgb).all()
    assert (decodeArray(encodeArray(gray, 'RAWZ')[0]) == gray).all()  # RAWG
    huge = RAWZ_MAGIC + pack('>II', 100000, 100000) + compress(b'\0' * 1000)
    assert unpackRaw(huge) is None  # declared size over the limit
    bomb = RAWZ_MAGIC + pack('>II', 10, 10) + compress(b'\0' * (50 << 20))
    assert unpackRaw(bomb) is None  # inflates far beyond 10 x 10: stopped, not expanded


def test_upscale_engine_works_with_numpy_only_methods():
    from ScreenMagnifier.upscaler.core import UpscaleEngine, NEAREST, BILINEAR, PIXEL_ART, bilinearResize
    img = numpy.zeros((10, 16, 3), numpy.uint8)
    img[:, 8:] = 200
    engine = UpscaleEngine()
    for method in (NEAREST, BILINEAR, PIXEL_ART):
        assert engine.upscale(img, 64, 40, method).shape == (40, 64, 3)
    out = bilinearResize(img, 64, 40)
    assert out[20, 5].tolist() == [0, 0, 0] and out[20, 60].tolist() == [200, 200, 200]
