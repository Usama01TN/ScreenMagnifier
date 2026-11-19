# -*- coding: utf-8 -*-
"""
Face pointer decisions (which face, keeping a followed face, stale results) and the restart environment.
"""
from pytest import fixture, skip, mark
from types import ModuleType
from sys import modules
from os import environ

try:
    from ManyQt import QtWidgets  # noqa: F401

    needsQt = mark.skipif(False, reason=u'')
except:
    needsQt = mark.skip(reason=u'No Qt binding')

APP = []  # The QApplication must outlive every test (a collected one deletes the Qt objects).


@fixture
def pointer():
    environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from ManyQt.QtWidgets import QApplication
    if not APP:
        APP.append(QApplication.instance() or QApplication([]))
    from ScreenMagnifier.facepointer import FacePointer
    if not FacePointer.isAvailable():
        skip(u'No OpenCV')
    fp = FacePointer()
    fp._FacePointer__m_enabled = True  # decisions only: no timers, no screen grabs
    return fp


def found(fp, rects, generation=None, sentAtGrab=(0, 0), view=False, shift=None):
    from ManyQt.QtCore import QRect, QPoint
    job = {'result': {'faces': [{'rect': r} for r in rects], 'backend': 'haar', 'timeMs': 5.0},
           'area': QRect(0, 0, 1000, 800), 'sx': 1.0, 'sy': 1.0, 'aim': QPoint(499, 399), 'view': view,
           'radius': 400.0, 'generation': fp._FacePointer__m_generation if generation is None else generation,
           'sentAtGrab': tuple(sentAtGrab)}
    if shift is not None:
        job['shift'], job['response'] = shift, 1.0
    fp._onFound(job)


def face(cx, cy, size=80):
    return [cx - size / 2.0, cy - size / 2.0, size, size]


@needsQt
def test_largest_or_nearest_face(pointer):
    from ScreenMagnifier.facepointer import CHOOSE_NEAREST
    from ManyQt.QtGui import QCursor
    found(pointer, [[100, 100, 40, 40], [600, 400, 120, 120]])
    assert (pointer.getTarget().x(), pointer.getTarget().y()) == (660, 460)  # the largest
    other = type(pointer)()
    other._FacePointer__m_enabled = True
    other.setChoose(CHOOSE_NEAREST)
    cursor = QCursor.pos()
    found(other, [[cursor.x() - 20, cursor.y() - 20, 40, 40], [cursor.x() + 400, cursor.y() + 300, 120, 120]])
    assert abs(other.getTarget().x() - cursor.x()) <= 1 and abs(other.getTarget().y() - cursor.y()) <= 1


@needsQt
def test_a_followed_face_is_kept_and_stale_results_are_dropped(pointer):
    found(pointer, [[600, 400, 120, 120]])
    found(pointer, [[630, 410, 120, 120], [100, 100, 300, 300]])  # Moved a little; a bigger face appears.
    assert (pointer.getTarget().x(), pointer.getTarget().y()) == (690, 470)  # Still the followed face.
    found(pointer, [[100, 100, 40, 40]], generation=pointer._FacePointer__m_generation - 1)
    assert (pointer.getTarget().x(), pointer.getTarget().y()) == (690, 470)  # an old result changes nothing


@needsQt
def test_game_sensitivity_is_measured_from_the_scene_inverted_axis_included(pointer):
    pointer._learn(0, (0, 0), (0.0, 0.0))
    pointer._learn(500, (100, 50),
                   (-100.0, 50.0))  # right + down sent; the scene moved left (normal x), down (inverted y)
    kx, ky = pointer.getSensitivity()
    assert abs(kx - 1.0) < 0.01 and abs(ky + 1.0) < 0.01, (kx, ky)


@needsQt
def test_game_no_reaction_is_detected(pointer):
    from ScreenMagnifier.facepointer import NO_REACTION_SCANS
    for n in range(NO_REACTION_SCANS + 6):
        pointer._learn(n * 100, (n * 60, 0), (0.0, 0.0))  # movements sent, the scene never turns
    assert pointer._FacePointer__m_noReaction >= NO_REACTION_SCANS


@needsQt
def test_game_interface_portrait_and_assist_area(pointer):
    from ScreenMagnifier.facepointer import MOTION_VIEW
    pointer.setMotion(MOTION_VIEW)
    found(pointer, [face(700, 500)], view=True)
    found(pointer, [face(700, 500)], view=True, sentAtGrab=(30, 0), shift=(-30.0, 0.0))  # the scene turned, not it
    found(pointer, [face(700, 500)], view=True, sentAtGrab=(60, 0), shift=(-30.0, 0.0))
    found(pointer, [face(700, 500)], view=True, sentAtGrab=(90, 0), shift=(-30.0, 0.0))  # (3 readings: enemies move)
    assert pointer.getStatus() == 'static' and pointer.getTarget() is None
    other = type(pointer)()
    other._FacePointer__m_enabled = True
    other.setMotion(MOTION_VIEW)
    from ManyQt.QtCore import QRect, QPoint
    other._onFound({'result': {'faces': [{'rect': face(900, 700)}]}, 'area': QRect(0, 0, 1000, 800), 'sx': 1.0,
                    'sy': 1.0, 'aim': QPoint(499, 399), 'view': True, 'radius': 40.0,
                    'generation': other._FacePointer__m_generation, 'sentAtGrab': (0, 0)})
    assert other.getTarget() is None  # outside the assist area


@needsQt
def test_automatic_mode_recognises_a_game_that_captures_the_mouse(pointer):
    from ManyQt.QtCore import QPoint
    from ScreenMagnifier.facepointer import MOTION_AUTO, MOTION_POINTER
    pointer.setMotion(MOTION_AUTO)
    assert not pointer.isTurningView()
    assert pointer._putBack(QPoint(960, 540), 100)  # moved by itself: a tiny test step follows
    pointer._putBack(QPoint(960, 541), 400)  # put back on the same spot again: a game
    assert pointer.isTurningView()
    pointer.setMotion(MOTION_POINTER)
    pointer.setMotion(MOTION_AUTO)
    assert pointer._putBack(QPoint(300, 300), 100)
    assert not pointer._putBack(QPoint(420, 380), 200)  # moved again, elsewhere: the user
    assert not pointer.isTurningView()


@needsQt
def test_automatic_mode_follows_the_system_capture_signals(pointer, monkeypatch):
    import ScreenMagnifier.facepointer as module
    from ScreenMagnifier.facepointer import MOTION_AUTO
    pointer.setMotion(MOTION_AUTO)
    signal = ['clipped']
    monkeypatch.setattr(module, 'mouseCapture', lambda: signal[0])
    pointer._watchCapture(1000)  # confined (Windows ClipCursor): a game at once
    assert pointer.isTurningView()
    signal[0] = ''
    pointer._watchCapture(1200)
    pointer._watchCapture(2300)  # Visible again for 1 s: a menu, the pointer is moved again.
    assert not pointer.isTurningView()
    signal[0] = 'hidden'  # Hidden while resting (a video player): nothing changes.
    pointer._watchCapture(5000)
    pointer._watchCapture(7000)
    assert not pointer.isTurningView()
    pointer._FacePointer__m_lastMoveMs = 7900  # Hidden while we move it, for 1 s: a game
    pointer._watchCapture(8000)
    pointer._FacePointer__m_lastMoveMs = 9000
    pointer._watchCapture(9100)
    assert pointer.isTurningView()


def test_restart_environment_drops_what_opencv_added(monkeypatch):
    from ScreenMagnifier.support import cleanEnvironment
    fake = ModuleType('cv2')
    fake.__file__ = '/somewhere/site-packages/cv2/__init__.py'
    monkeypatch.setitem(modules, 'cv2', fake)
    package = modules['ScreenMagnifier']
    monkeypatch.setattr(package, 'STARTUP_ENVIRONMENT', {'LD_LIBRARY_PATH': '/opt/mine'}, raising=False)
    env = cleanEnvironment({'QT_QPA_PLATFORM_PLUGIN_PATH': '/somewhere/site-packages/cv2/qt/plugins',
                            'QT_QPA_FONTDIR': '/somewhere/site-packages/cv2/qt/fonts',
                            'LD_LIBRARY_PATH': '/somewhere/site-packages/cv2/../../lib64:/opt/mine',
                            'HOME': '/home/me'})
    assert env == {'LD_LIBRARY_PATH': '/opt/mine', 'HOME': '/home/me'}
