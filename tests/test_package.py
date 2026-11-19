# coding=utf-8
"""
Tests of the installed ScreenMagnifier package. Run them after `pip install -e .[all]` (or installing the wheel):
    pytest tests
Tests needing Qt are skipped when no Qt binding is installed.
"""
from ScreenMagnifier.support import qtBindingProblem, DONATION_LINKS
import ScreenMagnifier
from subprocess import run, PIPE, STDOUT
from sys import path, executable
from pytest import mark
from os import environ

needsQt = mark.skipif(bool(qtBindingProblem()), reason=u'No Qt binding installed')


def test_version_matches_the_installed_metadata():
    from importlib.metadata import version
    assert version('ScreenMagnifier') == ScreenMagnifier.__version__


def test_donation_links_are_in_the_metadata():
    from importlib.metadata import metadata
    urls = [value.split(', ', 1)[1] for value in (metadata('ScreenMagnifier').get_all('Project-URL') or [])]
    assert sorted(urls) == sorted(url for name, url in DONATION_LINKS)


def test_icon_resources_are_installed():
    from os.path import dirname, isfile, join
    folder = join(dirname(ScreenMagnifier.__file__), 'resources')
    for name in ['icon-{}.png'.format(s) for s in (16, 24, 32, 48, 64, 128, 256, 512)] + ['icon.ico', 'icon.icns']:
        assert isfile(join(folder, name)), name


def test_importing_the_package_never_changes_sys_path():
    before = list(path)
    import ScreenMagnifier.shortcuts, ScreenMagnifier.features, ScreenMagnifier.support  # noqa: F401
    if not qtBindingProblem():
        assert ScreenMagnifier.MainWindow is not None  # Imports every component.
    assert path == before


@needsQt
def test_every_export_resolves():
    for name in ScreenMagnifier.__all__:
        assert getattr(ScreenMagnifier, name) is not None, name


def selftest(*args):
    proc = run([executable] + list(args) + ['--selftest'], stdout=PIPE, stderr=STDOUT, timeout=240,
               env=dict(environ, QT_QPA_PLATFORM='offscreen'))
    return proc.returncode, proc.stdout.decode('utf-8', 'replace')


@needsQt
def test_application_selftest():
    code, out = selftest('-m', 'ScreenMagnifier')
    assert code == 0 and 'SELFTEST' in out, out[-2000:]


@needsQt
def test_server_selftest():
    code, out = selftest('-m', 'ScreenMagnifier.server')
    assert code == 0 and 'ok' in out, out[-2000:]


@needsQt
def test_every_check_box_keeps_an_accessible_name():
    """
    Long check box texts wrap in a label beside the box: screen readers must still announce each box.
    """
    environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from ManyQt.QtWidgets import QApplication, QCheckBox
    app = QApplication.instance() or QApplication([])  # type: QApplication
    from ScreenMagnifier.mainwindow import MainWindow
    window = MainWindow()
    try:
        boxes = window.findChildren(QCheckBox)
        assert boxes
        assert [b for b in boxes if not b.text() and not b.accessibleName()] == []
    finally:
        window.quitApp()


@needsQt
def test_zoomer_custom_area_and_full_screen_geometry():
    environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from ManyQt.QtWidgets import QApplication
    from ManyQt.QtCore import QRect, QPoint
    app = QApplication.instance() or QApplication([])
    from ScreenMagnifier.zoomoverlay import ZoomOverlay
    lens = ZoomOverlay(zoom=2.0, target=ZoomOverlay.Point, targetPoint=QPoint(100, 100),
                       placement=ZoomOverlay.Custom, customRect=QRect(400, 200, 300, 150))
    assert lens.lensGeometry() == QRect(400, 200, 300, 150)
    assert lens.sourceRect().size().width() == 150 and lens.sourceRect().size().height() == 75  # lens aspect
    lens.setPlacement(ZoomOverlay.FullScreen)
    assert lens.lensGeometry() == app.primaryScreen().geometry()


@needsQt
def test_zoomer_corner_radius_shapes_the_lens():
    environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from ManyQt.QtWidgets import QApplication
    from ManyQt.QtCore import QRectF, QPointF
    app = QApplication.instance() or QApplication([])
    from ScreenMagnifier.zoomoverlay import ZoomOverlay
    lens = ZoomOverlay(shape=ZoomOverlay.RoundedRect, cornerRadius=0, lensSize=__import__(
        'ManyQt.QtCore', fromlist=['QSize']).QSize(300, 200))
    square = lens._lensPath(QRectF(0, 0, 300, 200))
    assert square.contains(QPointF(1, 1))  # radius 0: square corners
    lens.setCornerRadius(60)
    assert lens.getCornerRadius() == 60 and not lens._lensPath(QRectF(0, 0, 300, 200)).contains(QPointF(5, 5))
    lens.setCornerRadius(1000)  # capped at half the short side: a pill
    assert lens._radiusFor(QRectF(0, 0, 300, 200)) == 100
