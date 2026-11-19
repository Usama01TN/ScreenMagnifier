# -*- coding: utf-8 -*-
"""
FacePointer: the mouse pointer - or a game's view - goes to the faces on the screen (films, offline games).
Films and games that show the pointer (MOTION_POINTER): a few times per second the screen of the pointer is scanned
for faces (on a background thread); the pointer glides to the largest face, or the one nearest it, and stays with a
face while it moves. Moving the mouse yourself pauses it. FOLLOW_ZOOMER moves only the zoomer's target.
Games that capture the mouse (MOTION_VIEW; first-person, 3D): such a game hides the pointer, turns its view with the
raw mouse movements and puts the pointer back in the middle, so moving the pointer does nothing there. In real time
(~30 times per second) the area around the crosshair (the screen center) is captured at full resolution; mouse
movements are sent, like a real mouse, until the face is at the crosshair.
    - How far the view turns per mouse count (the game's sensitivity, per axis, inverted axes included) is measured
      from the picture itself: the scene shift between two captures (phase correlation) divided by the movement
      sent between them. Until it is known, only small test movements are sent.
    - A face that stays still while the scene turns is a portrait of the game's interface: ignored for a while.
    - Movements sent while the scene never turns: the game does not receive them (e.g. it runs as administrator).
    - HOLD_RIGHT_BUTTON assists only while the right mouse button (aim) is held.
MOTION_AUTO moves the pointer, and centres the face on the screen (turns the view) while a game captures the mouse:
the system says the pointer is confined (Windows) or hidden - and it stays hidden while it is moved (a video player
shows it again) - or the game puts it back on the same spot after each move. When the pointer comes back (a menu),
the pointer is moved again.
Capture: on Windows the optional dxcam package (DXGI desktop duplication) is used when installed, else the screen
grab, else the game window itself (PrintWindow); a black capture is reported (exclusive full-screen games).
"""
from ManyQt.QtCore import QObject, QTimer, QPoint, QRect, QElapsedTimer, Qt, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtGui import QCursor
from threading import Thread, Lock
from sys import path, platform
from math import exp, hypot
from os.path import dirname

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .screengrabber.screengrabber import ScreenGrabber, screenAtPoint, winWindowAt, winGrabWindowRect, isBlankImage
    from .mousemove import sendRelativeMove, canSendRelative, ButtonWatcher, mouseCapture
    from .facedetector.facedetector import qimageToArray, appDataDir
    from .facedetector.core import FaceEngine
except:
    from screengrabber.screengrabber import ScreenGrabber, screenAtPoint, winWindowAt, winGrabWindowRect, isBlankImage
    from mousemove import sendRelativeMove, canSendRelative, ButtonWatcher, mouseCapture
    from facedetector.facedetector import qimageToArray, appDataDir
    from facedetector.core import FaceEngine
try:
    from cv2 import createHanningWindow, CV_32F, resize, INTER_AREA, cvtColor, COLOR_RGB2GRAY
    from numpy import float32, fft, conj, real, abs, unravel_index, argmax, clip, mgrid

    cv2exists = True  # type: bool
except:
    cv2exists = False  # type: bool

FOLLOW_POINTER, FOLLOW_ZOOMER = 0, 1  # type: int, int
CHOOSE_LARGEST, CHOOSE_NEAREST = 0, 1  # type: int, int
MOTION_POINTER, MOTION_VIEW, MOTION_AUTO = 0, 1, 2  # type: int, int, int
HOLD_ALWAYS, HOLD_RIGHT_BUTTON = 0, 1  # type: int, int
SCAN_WIDTH = 960  # type: int  # Whole screens are scanned at most this wide: faces from ~48 px on a 1080p screen.
VIEW_FRAME_MS = 33  # type: int  # Games: the area around the crosshair, ~30 times per second.
LOST_MS = 1200  # type: int  # A followed face may vanish this long (cut, profile view) before another is chosen.
LOST_VIEW_MS = 500  # type: int  # (in a game).
USER_MOVE_PX = 3  # type: int  # The pointer moved more than this by itself: the user took the mouse.
MAX_STEP = 120  # type: int  # Mouse counts sent at most per move (~60 per second): never a violent spin.
PROBE = 40  # type: int  # First test movement per axis until the game's sensitivity is known (doubled while the.
PROBE_MAX = 640  # type: int  # View does not visibly turn: very low sensitivities are found too).
CORRELATION = 256  # type: int  # Side of the small gray captures compared for the scene's motion.
RETRY_MS = 1500  # type: int  # The game did not react: test again this often (never a drift).
LEAD_S = 0.06  # type: float  # Moving enemies: lead by the time since the capture + this (the movement's landing).
ACQUIRE_SIDE = 640  # type: int  # The whole assist area is searched at most this wide (speed).
FULL_EVERY = 8  # type: int  # While following, every 8th scan searches the whole assist area again.
STATIC_MS = 6000  # type: int  # A face that does not move with the view is ignored this long.
NO_REACTION_SCANS = 8  # type: int  # Movements sent, scene never turned: the game does not receive them.
BLANK_SCANS = 8  # type: int  # Black captures in a row: the screen cannot be captured.
_DXCAM = []  # type: list  # [camera | None] (Windows, optional)


def clamp(x, a, b):
    """
    :param x: float | int
    :param a: float | int
    :param b: float | int
    :return: float | int
    """
    return a if x < a else b if x > b else x


def sceneShift(previous, current, sent, k, known):
    """
    How far the scene moved between two small gray captures - robust to what does not move with a game's view (the
    weapon, the interface): the phase-correlation surface is searched for several peaks; a peak at zero shift is the
    static layer, a clear non-zero peak is the turning world; with a known sensitivity, the expected shift only
    breaks near-ties between strong peaks (repeating textures), never overriding a clearly stronger peak.
    :param previous: (ndarray) N x N float32.
    :param current: (ndarray) N x N float32.
    :param sent: (tuple[int, int]) Mouse counts sent between the two captures.
    :param k: (tuple[float, float]) Screen px per count (in these images' pixels).
    :param known: (tuple[bool, bool]) The sensitivity is measured on that axis.
    :return: (tuple[float, float] | None) Shift of the scene in these images' pixels, None if unclear.
    """
    n = previous.shape[0]  # type: int
    window = createHanningWindow((n, n), CV_32F)
    a, b = fft.fft2(previous * window), fft.fft2(current * window)
    cross = b * conj(a)
    surface = fft.fftshift(real(fft.ifft2(cross / (abs(cross) + 1e-9))))
    peaks = []  # type: list  # (value, dx, dy)
    work = surface.copy()
    for _ in range(6):
        y, x = unravel_index(int(argmax(work)), work.shape)
        value = float(work[y, x])  # type: float
        if value <= 0:
            break
        y0, y1, x0, x1 = max(0, y - 1), min(n, y + 2), max(0, x - 1), min(n, x + 2)
        patch = clip(surface[y0:y1, x0:x1], 0, None)
        total = float(patch.sum()) or 1.0  # type: float  # sub-pixel: centroid of the 3 x 3 peak
        ys, xs = mgrid[y0:y1, x0:x1]
        peaks.append((value, float((patch * xs).sum() / total) - n // 2, float((patch * ys).sum() / total) - n // 2))
        work[max(0, y - 3):y + 4, max(0, x - 3):x + 4] = -1.0
    if not peaks:
        return None
    best = peaks[0][0]  # type: float
    if max(abs(sent[0]), abs(sent[1])) < 8:
        return peaks[0][1], peaks[0][2]
    moving = [p for p in peaks if hypot(p[1], p[2]) > 0.75 and p[0] >= 0.25 * best]  # type: list
    if not moving:
        return 0.0, 0.0  # only the static layer: the scene did not turn
    strongest = max(p[0] for p in moving)  # type: float
    if strongest < 0.03:
        return None  # no clear match (a cut, an explosion...): unclear, not "no motion"
    strong = [p for p in moving if p[0] >= 0.6 * strongest]  # type: list  # a clearly stronger peak always wins:
    if len(strong) > 1 and (known[0] or known[1]):  # the expectation only breaks near-ties (it must never
        expected = (-sent[0] * k[0], -sent[1] * k[1])  # type: tuple  # confirm a wrong estimate)
        return min(((p[1], p[2]) for p in strong), key=lambda q: hypot(q[0] - expected[0], q[1] - expected[1]))
    top = max(strong, key=lambda p: p[0])
    return top[1], top[2]


def _dxcam():
    """
    :return: dxcam camera of the primary output | None (not Windows, not installed, or failed once).
    """
    if not _DXCAM:
        camera = None
        if platform == 'win32':
            try:
                from dxcam import create
                camera = create(output_color='RGB')
            except:
                camera = None
        _DXCAM.append(camera)
    return _DXCAM[0]


class FacePointer(QObject):
    """
    FacePointer class.
    """
    statusChanged = pyqtSignal('QString')  # type: pyqtSignal  # off, searching, following, paused, waiting,
    enabledChanged = pyqtSignal(bool)  # type: pyqtSignal      # static, blocked, blank, noReaction, unavailable,
    _found = pyqtSignal(object)  # type: pyqtSignal            # error  (_found: worker thread -> GUI thread)

    def __init__(self, *args, **kwargs):
        """
        :param follow: (int) FOLLOW_POINTER (move the mouse pointer) or FOLLOW_ZOOMER (only the zoomer's target).
        :param choose: (int) CHOOSE_LARGEST or CHOOSE_NEAREST (nearest the pointer / the crosshair).
        :param motion: (int) MOTION_AUTO, MOTION_POINTER or MOTION_VIEW.
        :param hold: (int) HOLD_ALWAYS or HOLD_RIGHT_BUTTON (games: assist only while the right button is held).
        :param smoothness: (int) 0 .. 100: 0 jumps to the face, 100 glides slowly.
        :param pauseSeconds: (float | int) Control given back after you move the mouse yourself (films).
        :param scanRate: (int) Whole-screen scans per second (films); games run at ~30.
        :param assistArea: (int) 10 .. 100: radius around the crosshair, in % of half the screen height (games).
        :param strength: (int) 10 .. 100: share of the distance corrected per scan (games).
        :param detector: (FaceDetector | None) Its backend and confidence are used (the Detection tab settings).
        :param ignoreRects: (callable | None) f() -> list of global QRect never scanned (the lens, this window).
        :param moveZoomer: (callable | None) f(QPoint) puts the zoomer's target there (FOLLOW_ZOOMER).
        :param statusChanged: (callable | None)
        :param args: any
        :param kwargs: any
        """
        follow = kwargs.pop('follow', FOLLOW_POINTER)  # type: int
        choose = kwargs.pop('choose', CHOOSE_LARGEST)  # type: int
        motion = kwargs.pop('motion', MOTION_AUTO)  # type: int
        hold = kwargs.pop('hold', HOLD_ALWAYS)  # type: int
        smoothness = kwargs.pop('smoothness', 40)  # type: int
        pauseSeconds = kwargs.pop('pauseSeconds', 3.0)  # type: float
        scanRate = kwargs.pop('scanRate', 5)  # type: int
        assistArea = kwargs.pop('assistArea', 35)  # type: int
        strength = kwargs.pop('strength', 60)  # type: int
        detector = kwargs.pop('detector', None)
        ignoreRects = kwargs.pop('ignoreRects', None)  # type: callable | None
        moveZoomer = kwargs.pop('moveZoomer', None)  # type: callable | None
        statusChanged = kwargs.pop('statusChanged', None)  # type: callable | None
        super(FacePointer, self).__init__(*args, **kwargs)
        if callable(statusChanged):
            self.statusChanged.connect(statusChanged)
        self.__m_follow = FOLLOW_ZOOMER if int(follow) == FOLLOW_ZOOMER else FOLLOW_POINTER  # type: int
        self.__m_choose = CHOOSE_NEAREST if int(choose) == CHOOSE_NEAREST else CHOOSE_LARGEST  # type: int
        self.__m_motion = int(motion) if int(motion) in (MOTION_POINTER, MOTION_VIEW, MOTION_AUTO) else \
            MOTION_AUTO  # type: int
        self.__m_hold = HOLD_RIGHT_BUTTON if int(hold) == HOLD_RIGHT_BUTTON else HOLD_ALWAYS  # type: int
        self.__m_smoothness = int(clamp(int(smoothness), 0, 100))  # type: int
        self.__m_pauseSeconds = float(clamp(float(pauseSeconds), 0.5, 30.0))  # type: float
        self.__m_scanRate = int(clamp(int(scanRate), 1, 15))  # type: int
        self.__m_assistArea = int(clamp(int(assistArea), 10, 100))  # type: int
        self.__m_strength = int(clamp(int(strength), 10, 100))  # type: int
        self.__m_detector = detector
        self.__m_ignoreRects = ignoreRects if callable(ignoreRects) else None  # type: callable | None
        self.__m_moveZoomer = moveZoomer if callable(moveZoomer) else None  # type: callable | None
        # State.
        self.__m_engine = FaceEngine(
            dataDir=appDataDir(), maxInputSize=SCAN_WIDTH, haarMaxInput=SCAN_WIDTH)  # type: FaceEngine
        self.__m_enabled = False  # type: bool
        self.__m_busy = False  # type: bool  # a worker thread is detecting (one at a time: OpenCV objects are
        self.__m_lock = Lock()  # type: Lock  # not thread-safe)
        self.__m_generation = 0  # type: int  # results of an earlier on / off period are dropped
        self.__m_status = 'off'  # type: str
        self.__m_detail = {}  # type: dict
        self.__m_target = None  # type: QPoint | None  # followed face center (global, device independent)
        self.__m_targetSize = 0.0  # type: float
        self.__m_lastSeen = 0  # type: int
        self.__m_lastSet = None  # type: QPoint | None  # where we last put the pointer
        self.__m_zoomPos = None  # type: tuple | None  # smoothed zoomer target (float x, y)
        self.__m_pausedUntil = 0  # type: int
        self.__m_blocked = 0  # type: int  # consecutive pointer moves the system refused
        self.__m_blank = 0  # type: int  # consecutive black captures
        self.__m_lastTick = 0  # type: int
        self.__m_captured = False  # type: bool  # MOTION_AUTO: this game captures the mouse
        self.__m_snap = None  # type: tuple | None  # (QPoint, ms, count): where the pointer was put back
        self.__m_captureBy = ''  # type: str  # 'signal' (the system said so) or 'snap' (put back on one spot)
        self.__m_hiddenSince = None  # type: int | None
        self.__m_visibleSince = None  # type: int | None
        self.__m_lastCheck = 0  # type: int
        self.__m_lastMoveMs = -10000  # type: int  # last time the pointer was moved by us
        # Game (view) state.
        self.__m_watcher = ButtonWatcher()  # type: ButtonWatcher
        self.__m_k = [1.0, 1.0]  # type: list[float]  # screen px per mouse count, per axis (measured)
        self.__m_kKnown = [False, False]  # type: list[bool]
        self.__m_probe = [PROBE, PROBE]  # type: list[int]
        self.__m_nextProbe = 0  # type: int
        self.__m_history = []  # type: list
        self.__m_samples = [[], []]  # type: list
        self.__m_lastOffset = None  # type: tuple | None
        self.__m_velocity, self.__m_tracked, self.__m_prevGrabMs = (0.0, 0.0), 0, None
        self.__m_lead = True  # type: bool
        self.__m_scans = 0  # type: int
        self.__m_sent = [0, 0]  # type: list[int]  # mouse counts sent in total
        self.__m_pending = [0.0, 0.0]  # type: list[float]  # counts still to send
        self.__m_lastGrabSent = None  # type: tuple | None  # counts sent at the previous capture
        self.__m_previousFace = None  # type: tuple | None  # (x, y) of the followed face at the previous capture
        self.__m_prevGray = None  # worker thread only: the previous capture, small and gray
        self.__m_staticHits = 0  # type: int
        self.__m_noReaction = 0  # type: int
        self.__m_ignored = []  # type: list  # [(QPoint, until ms)] faces that do not move with the view
        self.__m_acquired = None  # type: tuple | None  # (distance px, counts sent) when the face was chosen
        self.__m_clock = QElapsedTimer()  # type: QElapsedTimer
        self.__m_clock.start()
        self.__m_scanTimer = QTimer(self)  # type: QTimer
        self.__m_scanTimer.timeout.connect(self._scan)
        self.__m_moveTimer = QTimer(self)  # type: QTimer
        self.__m_moveTimer.setInterval(16)  # ~60 moves per second: smooth
        self.__m_moveTimer.timeout.connect(self._move)
        self._found.connect(self._onFound, Qt.QueuedConnection)
        if detector is not None and hasattr(detector, 'downloadFinished'):
            detector.downloadFinished.connect(lambda *a: self.__m_engine.resetModel())

    # ---------- Helpers ----------
    @staticmethod
    def isAvailable():
        """
        :return: (bool) Face detection is possible (NumPy + OpenCV).
        """
        return FaceEngine.isAvailable()

    def _now(self):
        """
        :return: (int) ms
        """
        return int(self.__m_clock.elapsed())

    def _setStatus(self, status, **detail):
        """
        :param status: str | unicode | QString
        :param detail: (dict) faces, backend, timeMs, seconds, message...
        :return:
        """
        self.__m_detail = dict(detail)  # type: dict
        if status != self.__m_status or detail:
            self.__m_status = status  # type: str
            self.statusChanged.emit(status)

    def _isView(self):
        """
        :return: (bool) The game's view is turned (MOTION_VIEW, or MOTION_AUTO in a game that captures the mouse).
        """
        return self.__m_motion == MOTION_VIEW or (self.__m_motion == MOTION_AUTO and self.__m_captured)

    def _resetView(self):
        """
        Forget what was learned about a game (another game, or the face pointer switched on again).
        :return:
        """
        self.__m_k, self.__m_kKnown, self.__m_probe = [1.0, 1.0], [False, False], [PROBE, PROBE]
        self.__m_history = []  # type: list  # [(ms, counts sent, total scene shift)] for _learn()
        self.__m_samples = [[], []]  # type: list  # recent sensitivity readings per axis (their median is used)
        self.__m_lastOffset = None  # type: tuple | None  # the followed face's offset at the previous capture
        self.__m_velocity = (0.0, 0.0)  # type: tuple  # the followed enemy's own motion (px / s, on screen)
        self.__m_tracked = 0  # type: int  # velocity readings of the followed enemy
        self.__m_prevGrabMs = None  # type: int | None
        self.__m_lead = True  # type: bool  # lead moving enemies
        self.__m_pending, self.__m_lastGrabSent, self.__m_previousFace = [0.0, 0.0], None, None
        self.__m_staticHits, self.__m_noReaction, self.__m_acquired = 0, 0, None
        with self.__m_lock:
            self.__m_prevGray = None

    def _restartScans(self):
        """
        :return:
        """
        if self.__m_enabled:
            self.__m_scanTimer.start(VIEW_FRAME_MS if self._isView() else int(1000 / self.__m_scanRate))

    def _grab(self, area, width):
        """
        Capture a global rect (the black-out of the ignored windows included), with the fallbacks of Windows.
        :param area: QRect
        :param width: (int) At most this wide.
        :return: (tuple[ndarray, float, float] | None) RGB array and its scale (px per device-independent px).
        """
        arr, sx, sy = None, 1.0, 1.0
        camera = _dxcam() if platform == 'win32' else None
        screen = screenAtPoint(area.center())
        if camera is not None and screen is not None and screen.geometry().topLeft() == QPoint(0, 0):
            try:  # DXGI desktop duplication: also games that GDI sees black (primary screen only)
                dpr = float(screen.devicePixelRatio())  # type: float
                frame = camera.grab(region=(int(area.left() * dpr), int(area.top() * dpr),
                                            int((area.right() + 1) * dpr), int((area.bottom() + 1) * dpr)))
                if frame is not None:
                    arr, sx, sy = frame, dpr, dpr
            except Exception:
                _DXCAM[0] = None  # never again
        if arr is None:
            image, dpr = ScreenGrabber.grabRect(area)
            if platform == 'win32' and isBlankImage(image):  # exclusive full-screen, hardware overlays...
                hwnd = winWindowAt(area.center())
                if hwnd:
                    image, dpr = winGrabWindowRect(hwnd, area)
            if isBlankImage(image):
                self.__m_blank += 1
                if self.__m_blank >= BLANK_SCANS and self.__m_status != 'blank':
                    self._setStatus('blank')
                return None
            if image.width() > width:
                image = image.scaledToWidth(width, Qt.SmoothTransformation)
            arr = qimageToArray(image)
            sx, sy = image.width() / float(area.width()), image.height() / float(area.height())
        elif arr.shape[1] > width and cv2exists:
            f = width / float(arr.shape[1])  # type: float
            arr = resize(arr, (width, max(1, int(arr.shape[0] * f))), interpolation=INTER_AREA)
            sx, sy = sx * f, sy * f
        self.__m_blank = 0  # type: int
        if self.__m_status == 'blank':
            self._setStatus('searching')
        if self.__m_ignoreRects is not None:  # this application's windows: a magnified face is not a face
            arr = arr.copy()
            for r in self.__m_ignoreRects() or []:
                if r is not None and r.isValid() and r.intersects(area):
                    x0, y0 = max(0, int((r.x() - area.x()) * sx)), max(0, int((r.y() - area.y()) * sy))
                    arr[y0:int((r.bottom() + 1 - area.y()) * sy) + 1, x0:int((r.right() + 1 - area.x()) * sx) + 1] = 0
        return arr, sx, sy

    @pyqtSlot()
    def _scan(self):
        """
        GUI thread: capture (games: around the crosshair, full resolution; films: the whole screen), then detect on a
        worker thread.
        :return:
        """
        if not self.__m_enabled or self.__m_busy:
            return
        view = self._isView()  # type: bool
        screen = screenAtPoint(self.__m_target if self.__m_target is not None and not view else QCursor.pos())
        g = screen.geometry()  # type: QRect
        if view:
            radius = int(self.__m_assistArea / 100.0 * g.height() / 2.0 * 1.25)  # type: int  # (a margin)
            area = QRect(g.center().x() - radius, g.center().y() - radius, 2 * radius, 2 * radius).intersected(g)
        else:
            area = QRect(g)  # type: QRect
        grabbed = self._grab(area, SCAN_WIDTH)
        if grabbed is None:
            return
        arr, sx, sy = grabbed
        if self.__m_detector is not None:  # the Detection tab settings (no worker is running: not busy)
            self.__m_engine.backend = u'{}'.format(self.__m_detector.getBackend())  # type str
            self.__m_engine.scoreThreshold = float(self.__m_detector.getScoreThreshold())  # type float
        self.__m_busy = True  # type: bool
        crop = None  # games: once a face is followed, detect only around it, at full resolution (fast)
        self.__m_scans += 1
        if view and self.__m_target is not None and self.__m_scans % FULL_EVERY and \
                self._now() - self.__m_lastSeen < LOST_VIEW_MS:
            half = max(100.0, 1.75 * self.__m_targetSize)  # type: float
            t = self.__m_target  # type: QPoint
            x0, y0 = int(max(0, (t.x() - half - area.x()) * sx)), int(max(0, (t.y() - half - area.y()) * sy))
            x1 = int(min(arr.shape[1], (t.x() + half - area.x()) * sx))
            y1 = int(min(arr.shape[0], (t.y() + half - area.y()) * sy))
            if x1 - x0 >= 48 and y1 - y0 >= 48:
                crop = (x0, y0, x1, y1)
        job = {'arr': arr, 'area': QRect(area), 'sx': sx, 'sy': sy, 'aim': QPoint(g.center()), 'view': view,
               'grabMs': self._now(),
               'crop': crop,
               'k': tuple(self.__m_k), 'known': tuple(self.__m_kKnown),
               'radius': self.__m_assistArea / 100.0 * g.height() / 2.0,
               'generation': self.__m_generation, 'sentAtGrab': tuple(self.__m_sent)}  # type: dict
        worker = Thread(target=self._detect, args=(job,), name='FacePointer')
        worker.daemon = True
        worker.start()

    def _detect(self, job):
        """
        Worker thread: faces, and (games) how far the scene moved since the previous capture.
        :param job: dict
        :return:
        """
        with self.__m_lock:
            try:
                arr, engine = job['arr'], self.__m_engine
                crop = job.get('crop')
                if crop is not None:  # around the followed face, full resolution
                    engine.maxInputSize = engine.haarMaxInput = max(160, crop[2] - crop[0], crop[3] - crop[1])
                    result = engine.detect(arr[crop[1]:crop[3], crop[0]:crop[2]])
                    for face in result.get('faces', []):
                        face['rect'] = [face['rect'][0] + crop[0], face['rect'][1] + crop[1]] + list(face['rect'][2:])
                        face['landmarks'] = [[px + crop[0], py + crop[1]] for px, py in face.get('landmarks', [])]
                else:  # games: the whole assist area, at most ACQUIRE_SIDE wide; films: the screen
                    engine.maxInputSize = engine.haarMaxInput = ACQUIRE_SIDE if job['view'] else SCAN_WIDTH
                    result = engine.detect(arr)
                job['result'] = result
            except Exception as e:
                job['result'] = {'faces': [], 'error': u'{}'.format(e)}
            if not job['view']:
                job.pop('arr', None)
            job['shift'] = None
            if job['view'] and cv2 is not None:
                try:
                    arr = job.pop('arr')
                    small = resize(cvtColor(arr, COLOR_RGB2GRAY), (CORRELATION, CORRELATION),
                                       interpolation=INTER_AREA).astype(float32)
                    fill = float(small.mean())  # type: float  # people are blanked: the world alone is measured
                    c = float(CORRELATION)  # type: float  # (a walking enemy's body would pull the measurement)
                    for face in job['result'].get('faces', []):  # head + body: half a head above, ~4 heads below
                        x, y, w, h = face['rect'][:4]
                        x0, x1 = int((x - 1.0 * w) * c / arr.shape[1]), int((x + 2.0 * w) * c / arr.shape[1])
                        y0, y1 = int((y - 0.5 * h) * c / arr.shape[0]), int((y + 5.0 * h) * c / arr.shape[0])
                        small[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = fill
                    previous, self.__m_prevGray = self.__m_prevGray, (small, job['area'].size(), job['sentAtGrab'])
                    if previous is not None and previous[1] == job['area'].size():
                        fx = job['area'].width() / float(CORRELATION)  # type: float  # small px -> screen px
                        fy = job['area'].height() / float(CORRELATION)  # type: float
                        sent = (job['sentAtGrab'][0] - previous[2][0], job['sentAtGrab'][1] - previous[2][1])
                        shift = sceneShift(previous[0], small, sent, (job['k'][0] / fx, job['k'][1] / fy),
                                           job['known'])
                        if shift is not None:
                            job['shift'], job['response'] = (shift[0] * fx, shift[1] * fy), 1.0
                except Exception:
                    job['shift'] = None
            job.pop('arr', None)
        self._found.emit(job)

    @pyqtSlot(object)
    def _onFound(self, job):
        """
        GUI thread: choose the face, plan the movement.
        :param job: dict
        :return: None
        """
        self.__m_busy = False  # type: bool  # (only here: the worker has finished)
        if not self.__m_enabled or job['generation'] != self.__m_generation:
            return  # Switched off, or a result from before the last on / off.
        result, area, sx, sy = job['result'], job['area'], job['sx'], job['sy']
        faces = []  # type: list[tuple]  # Global center x, y, size, and the head's aim point x, y (between the eyes).
        for face in result.get('faces', []):
            x, y, w, h = face['rect'][:4]
            eyes = face.get('landmarks') or []  # type: list  # YuNet: right eye, left eye, nose, mouth corners
            ex, ey = ((eyes[0][0] + eyes[1][0]) / 2.0, (eyes[0][1] + eyes[1][1]) / 2.0) if len(eyes) >= 2 else \
                (x + w / 2.0, y + 0.40 * h)  # (Haar: eye level of the box)
            faces.append((area.x() + (x + w / 2.0) / sx, area.y() + (y + h / 2.0) / sy, max(w / sx, h / sy),
                          area.x() + ex / sx, area.y() + ey / sy))
        detail = {'faces': len(faces), 'backend': result.get('backend', ''),
                  'timeMs': float(result.get('timeMs', 0.0)), 'auto': self.__m_captured}  # type: dict
        if result.get('error'):
            self._setStatus('error', message=result['error'])
        elif job['view']:
            self._onFoundView(job, faces, detail)
        else:
            self._onFoundPointer(faces, detail)

    def _onFoundPointer(self, faces, detail):
        """
        Films: keep the followed face while it moves, else choose one.
        :param faces: list[tuple[float, float, float]]
        :param detail: dict
        :return:
        """
        now = self._now()  # type: int
        chosen = None
        if self.__m_target is not None and faces:
            tx, ty = self.__m_target.x(), self.__m_target.y()
            near = min(faces, key=lambda f: hypot(f[0] - tx, f[1] - ty))
            if hypot(near[0] - tx, near[1] - ty) <= max(60.0, 0.9 * max(self.__m_targetSize, near[2])):
                chosen = near
        if chosen is None and faces and (self.__m_target is None or now - self.__m_lastSeen > LOST_MS):
            if self.__m_choose == CHOOSE_NEAREST:
                c = self._position()  # type: QPoint
                chosen = min(faces, key=lambda f: hypot(f[0] - c.x(), f[1] - c.y()))
            else:
                chosen = max(faces, key=lambda f: f[2])
        if chosen is not None:
            self.__m_target = QPoint(int(round(chosen[0])), int(round(chosen[1])))  # type: QPoint
            self.__m_targetSize, self.__m_lastSeen = chosen[2], now
        elif self.__m_target is not None and now - self.__m_lastSeen > LOST_MS:
            self.__m_target = None
        if self.__m_status in ('paused', 'blocked', 'blank'):
            self.__m_detail.update(detail)
        else:
            self._setStatus('following' if self.__m_target is not None else 'searching', **detail)

    def _onFoundView(self, job, faces, detail):
        """
        Games: learn the game's sensitivity from the scene's motion, choose a face near the crosshair, plan the
        mouse movements that bring it there.
        :param job: dict
        :param faces: list[tuple[float, float, float]]
        :param detail: dict
        :return: None
        """
        now = self._now()  # type: int
        aim = job['aim']  # type: QPoint  # the crosshair
        grabSent = job['sentAtGrab']  # type: tuple[int, int]
        sent = (0, 0) if self.__m_lastGrabSent is None else \
            (grabSent[0] - self.__m_lastGrabSent[0], grabSent[1] - self.__m_lastGrabSent[1])
        self.__m_lastGrabSent = tuple(grabSent)  # type: tuple
        shift = job.get('shift') if job.get('response', 0.0) >= 0.03 else None  # scene motion between captures
        self._learn(now, grabSent, shift)
        radius = job['radius']  # type: float  # the assist area around the crosshair
        self.__m_ignored = [(p, until) for p, until in self.__m_ignored if until > now]  # type: list
        candidates = [f for f in faces if hypot(f[0] - aim.x(), f[1] - aim.y()) <= radius and
                      not any(hypot(f[0] - p.x(), f[1] - p.y()) < max(40.0, f[2]) for p, u in self.__m_ignored)]
        detail['faces'] = len(candidates)
        chosen = None
        previous = self.__m_previousFace  # type: tuple | None
        if self.__m_target is not None and previous is not None and candidates:
            sx, sy = shift if shift is not None else (-sent[0] * self.__m_k[0], -sent[1] * self.__m_k[1])
            px, py = previous[0] + sx, previous[1] + sy  # where the face should be after the turn
            near = min(candidates, key=lambda f: hypot(f[0] - px, f[1] - py))
            if hypot(near[0] - px, near[1] - py) <= max(60.0, 1.2 * max(self.__m_targetSize, near[2])):
                chosen = near
                if shift is not None and hypot(*shift) >= 8.0:  # the scene turned: did the face turn with it?
                    faceMove = hypot(near[0] - previous[0], near[1] - previous[1])  # type: float
                    if faceMove < 0.3 * hypot(*shift):
                        self.__m_staticHits += 1
                        if self.__m_staticHits >= 3:  # a portrait of the game's interface: ignore it for a while
                            self.__m_ignored.append((QPoint(int(near[0]), int(near[1])), now + STATIC_MS))
                            self.__m_target, self.__m_previousFace, self.__m_staticHits = None, None, 0
                            self.__m_pending = [0.0, 0.0]  # type: list[float]
                            self._setStatus('static', **detail)
                            return
                    else:
                        self.__m_staticHits = 0  # type: int
        if chosen is None and candidates and (self.__m_target is None or now - self.__m_lastSeen > LOST_VIEW_MS):
            chosen = min(candidates, key=lambda f: hypot(f[3] - aim.x(), f[4] - aim.y())) \
                if self.__m_choose == CHOOSE_NEAREST else max(candidates, key=lambda f: f[2])
            self.__m_staticHits, self.__m_lastOffset, previous = 0, None, None  # (a new enemy: no velocity yet)
            self.__m_acquired = (hypot(chosen[3] - aim.x(), chosen[4] - aim.y()), tuple(grabSent))  # type: tuple
        elif chosen is not None and self.__m_acquired is not None and \
                hypot(chosen[3] - aim.x(), chosen[4] - aim.y()) <= max(20.0, 0.5 * chosen[2]):
            self.__m_acquired = None  # on the head: the approach is over (tracking may turn on and on)
        elif chosen is not None and self.__m_acquired is not None and self.__m_noReaction < NO_REACTION_SCANS:
            start, counts = self.__m_acquired  # never a runaway, whatever was measured: far more sent than should
            spent = (grabSent[0] - counts[0], grabSent[1] - counts[1])  # have centred it, and no closer
            turned = hypot(spent[0] * self.__m_k[0] if self.__m_kKnown[0] else 0.0,  # (measured axes only)
                           spent[1] * self.__m_k[1] if self.__m_kKnown[1] else 0.0)  # type: float
            closer = hypot(chosen[3] - aim.x(), chosen[4] - aim.y()) <= 0.6 * start  # type: bool
            if not closer and (turned > 2.5 * max(start, 40.0) or abs(spent[0]) + abs(spent[1]) > 4000):
                self.__m_ignored.append((QPoint(int(chosen[0]), int(chosen[1])), now + STATIC_MS))
                self.__m_target, self.__m_previousFace, self.__m_acquired = None, None, None
                self._resetView()  # what was learned towards it is not trusted
                self._setStatus('static', **detail)
                return
        if chosen is None:
            if self.__m_target is not None and now - self.__m_lastSeen > LOST_VIEW_MS:
                self.__m_target, self.__m_previousFace = None, None
                self.__m_pending = [0.0, 0.0]  # type: list[float]
            if self.__m_status not in ('blocked', 'waiting', 'blank'):
                quiet = 'static' if self.__m_ignored else 'searching'  # type: str
                self._setStatus('following' if self.__m_target is not None else quiet, **detail)
            return
        grabMs = job.get('grabMs', now)  # type: int
        if previous is not None and shift is not None and self.__m_prevGrabMs is not None and \
                grabMs > self.__m_prevGrabMs:  # the enemy's own motion: on screen, minus the view's turn
            dt = (grabMs - self.__m_prevGrabMs) / 1000.0  # type: float
            own = ((chosen[0] - previous[0] - shift[0]) / dt, (chosen[1] - previous[1] - shift[1]) / dt)
            v = self.__m_velocity  # type: tuple
            self.__m_velocity = (0.5 * v[0] + 0.5 * own[0], 0.5 * v[1] + 0.5 * own[1])  # type: tuple
            self.__m_tracked += 1
        elif previous is None:
            self.__m_velocity, self.__m_tracked = (0.0, 0.0), 0
        self.__m_prevGrabMs = grabMs  # type: int
        self.__m_target = QPoint(int(round(chosen[0])), int(round(chosen[1])))  # type: QPoint
        self.__m_targetSize, self.__m_lastSeen, self.__m_previousFace = chosen[2], now, (chosen[0], chosen[1])
        share = self.__m_strength / 100.0  # type: float
        offset = (chosen[3] - aim.x(), chosen[4] - aim.y())  # type: tuple[float, float]  # the head, not the face
        if self.__m_lead and self.__m_tracked >= 2:  # lead a moving enemy: where the head will be when we land
            lead = (now - grabMs) / 1000.0 + LEAD_S  # type: float
            dx, dy = self.__m_velocity[0] * lead, self.__m_velocity[1] * lead
            limit = 1.5 * chosen[2]  # type: float  # never far from what is seen (noise)
            length = hypot(dx, dy)  # type: float
            if length > limit:
                dx, dy = dx * limit / length, dy * limit / length
            offset = (offset[0] + dx, offset[1] + dy)
        last = self.__m_lastOffset  # type: tuple | None
        still = hypot(*self.__m_velocity) < 40.0 or self.__m_tracked < 2  # type: bool  # (a walking enemy crosses
        for i in (0, 1):  # the crosshair by itself) crossed it: the sensitivity was too low (it would overshoot again)
            if still and last is not None and self.__m_kKnown[i] and abs(offset[i]) > max(8.0, 0.5 * abs(last[i])) \
                    and (offset[i] > 0) != (last[i] > 0):
                self.__m_k[i] *= 1.6
                self.__m_samples[i] = (self.__m_samples[i] + [self.__m_k[i]])[-7:]
                self.__m_pending[i] = 0.0
        self.__m_lastOffset = offset  # type: tuple
        plan = [0.0, 0.0]  # type: list[float]
        for i in (0, 1):  # what is still to correct, minus what was sent since this capture
            inFlight = (self.__m_sent[i] - grabSent[i]) * self.__m_k[i]  # type: float  # px
            counts = (offset[i] - inFlight) * share / self.__m_k[i]  # type: float
            if len(self.__m_samples[i]) < 3:  # still learning: a cautious share
                counts *= 0.6
            plan[i] = counts if self.__m_kKnown[i] else clamp(counts, -self.__m_probe[i], self.__m_probe[i])
        if self.__m_noReaction >= NO_REACTION_SCANS:
            if now < self.__m_nextProbe:
                plan = [0.0, 0.0]  # type: list[float]
            else:
                self.__m_nextProbe = now + RETRY_MS  # type: int  # one test movement, then wait
                plan = [clamp(p, -PROBE, PROBE) for p in plan]  # type: list[float]
        self.__m_pending = plan  # type: list[float]
        if self.__m_noReaction >= NO_REACTION_SCANS:
            self._setStatus('noReaction', **detail)
        elif self.__m_status not in ('blocked', 'waiting', 'blank'):
            self._setStatus('following', **detail)

    def _learn(self, now, grabSent, shift):
        """
        The game's sensitivity, measured over a window of ~0.4 - 0.9 s: the scene's total shift divided by the
        mouse counts sent - a game shows a movement one or more frames later, so comparing two captures alone would
        pair the wrong movement with the wrong shift.
        :param now: int
        :param grabSent: (tuple[int, int]) Counts sent when this capture was taken.
        :param shift: (tuple[float, float] | None) Scene shift since the previous capture (px).
        :return: None
        """
        if shift is None:
            self.__m_history = []  # type: list  # the chain is broken: start again
            return
        total = self.__m_history[-1][2] if self.__m_history else (0.0, 0.0)
        total = (total[0] + shift[0], total[1] + shift[1])  # type: tuple
        self.__m_history.append((now, tuple(grabSent), total))
        self.__m_history = [h for h in self.__m_history if now - h[0] <= 900]  # type: list
        old = next((h for h in self.__m_history if now - h[0] >= 400), None)  # (long: latency is a small share)
        if old is None:
            return
        sent = (grabSent[0] - old[1][0], grabSent[1] - old[1][1])  # type: tuple
        moved = (total[0] - old[2][0], total[1] - old[2][1])  # type: tuple
        if max(abs(sent[0]), abs(sent[1])) < 20:
            return
        visible = False  # type: bool
        chasing = self.__m_tracked >= 2 and hypot(*self.__m_velocity) >= 40.0  # type: bool  # a walking enemy
        for axis in (0, 1):
            if abs(sent[axis]) < 20:
                continue
            if chasing and len(self.__m_samples[axis]) >= 3:  # The least reliable moments - and a game's.
                visible = True  # type: bool  # Sensitivity does not change while playing: keep what was learned.
                continue
            if abs(moved[axis]) < 1.5:  # No visible turn on this axis: a bigger test movement next time.
                if not self.__m_kKnown[axis]:
                    self.__m_probe[axis] = min(PROBE_MAX, self.__m_probe[axis] * 2)
                continue
            visible = True  # type: bool
            measured = -moved[axis] / float(sent[axis])  # type: float  # Turning right moves the scene left
            sign = 1.0 if measured > 0 else -1.0  # type: float  # (an inverted axis is negative)
            samples = (self.__m_samples[axis] + [sign * clamp(abs(measured), 0.005, 50.0)])[-7:]  # type: list
            self.__m_samples[axis] = samples
            self.__m_k[axis] = sorted(samples)[len(samples) // 2]  # The median: one wrong reading changes nothing.
            self.__m_kKnown[axis] = True
            self.__m_probe[axis] = PROBE  # type: int
        self.__m_noReaction = 0 if visible else self.__m_noReaction + 1  # type: int
        if self.__m_noReaction >= NO_REACTION_SCANS:  # Test again now and then: it recovers when the game reacts
            self.__m_kKnown = [False, False]  # type: list[bool]  # and never drifts meanwhile
            if self.__m_noReaction == NO_REACTION_SCANS:
                self.__m_nextProbe = now + RETRY_MS  # type: int

    def _position(self):
        """
        :return: (QPoint) What follows the face: the pointer, or the zoomer's target.
        """
        if self.__m_follow == FOLLOW_ZOOMER and self.__m_zoomPos is not None:
            return QPoint(int(round(self.__m_zoomPos[0])), int(round(self.__m_zoomPos[1])))
        return QCursor.pos()

    @pyqtSlot()
    def _move(self):
        """
        ~60 times per second: glide towards the face (films) or send part of the planned movement (games).
        :return: None
        """
        now = self._now()  # type: int
        dt = max(1, now - self.__m_lastTick) / 1000.0  # type: float
        self.__m_lastTick = now  # type: int
        if not self.__m_enabled:
            return None
        if self.__m_motion == MOTION_AUTO and now - self.__m_lastCheck >= 200:
            self.__m_lastCheck = now  # type: int
            self._watchCapture(now)
        if self._isView():
            return self._moveView(dt)
        if self.__m_follow == FOLLOW_POINTER:
            current = QCursor.pos()  # type: QPoint
            last = self.__m_lastSet  # type: QPoint | None
            testing = False  # type: bool  # MOTION_AUTO: a tiny test step tells a game from a hand
            if last is not None and (current - last).manhattanLength() > USER_MOVE_PX:
                testing = self.__m_motion == MOTION_AUTO and self._putBack(current, now)
                if self._isView():
                    return None
                if not testing:  # The user moved it.
                    self._pause(now)
                    return None
            elif self.__m_snap is not None:  # After the test step: hold still and watch.
                if now - self.__m_snap[1] > 120:
                    self._pause(now)  # It stayed where it was put: it was the user.
                return None
            if now < self.__m_pausedUntil:
                self.__m_lastSet = None
                return None
            if self.__m_status == 'paused':
                self._setStatus('following' if self.__m_target is not None else 'searching')
        else:
            testing = False  # type: bool
        if self.__m_target is None:
            return None
        tau = 0.6 * self.__m_smoothness / 100.0  # type: float  # Seconds to cover ~63 % of the way.
        k = 1.0 if tau <= 0.0 else 1.0 - exp(-dt / tau)  # type: float
        if self.__m_follow == FOLLOW_ZOOMER:
            x, y = self.__m_zoomPos if self.__m_zoomPos is not None else (self.__m_target.x(), self.__m_target.y())
            x += (self.__m_target.x() - x) * k
            y += (self.__m_target.y() - y) * k
            self.__m_zoomPos = (x, y)  # type: tuple
            if self.__m_moveZoomer is not None:
                self.__m_moveZoomer(QPoint(int(round(x)), int(round(y))))
            return None
        d = self.__m_target - current  # type: QPoint
        if d.manhattanLength() <= 1:
            self.__m_lastSet = current  # type: QPoint
            return None
        step = QPoint(int(round(d.x() * k)), int(round(d.y() * k)))  # type: QPoint
        if testing:  # only a few pixels: if it was the user, the pointer stays (almost) where they left it
            length = max(1.0, hypot(d.x(), d.y()))  # type: float
            step = QPoint(int(round(3 * d.x() / length)), int(round(3 * d.y() / length)))
        if step.isNull():  # always progress at least one pixel
            step = QPoint((d.x() > 0) - (d.x() < 0), (d.y() > 0) - (d.y() < 0))
        wanted = current + step  # type: QPoint
        QCursor.setPos(wanted)
        self.__m_lastMoveMs = self._now()  # type: int
        actual = QCursor.pos()  # type: QPoint
        if (actual - wanted).manhattanLength() > 2:  # the system refused (Wayland, macOS permission)
            self.__m_blocked += 1
            if self.__m_blocked >= 15 and self.__m_status != 'blocked':
                self._setStatus('blocked')
        else:
            self.__m_blocked = 0  # type: int
        self.__m_lastSet = actual  # type: QPoint  # (a refused move is not the user's).
        return None

    def _pause(self, now):
        """
        The user took the mouse: give it back for a while.
        :param now: int
        :return:
        """
        self.__m_pausedUntil = now + int(self.__m_pauseSeconds * 1000)  # type: int
        self.__m_lastSet, self.__m_snap = None, None
        self._setStatus('paused', seconds=self.__m_pauseSeconds)

    def _putBack(self, current, now):
        """
        MOTION_AUTO: the pointer moved by itself. The first time, a tiny test step follows; put back on the same
        spot again, it is a game that captures the mouse (a hand never lands on the same pixel twice): its view is
        turned from now on.
        :param current: QPoint
        :param now: int
        :return: (bool) Testing (no pause yet).
        """
        snap = self.__m_snap  # type: tuple | None
        if snap is not None and (current - snap[0]).manhattanLength() <= 2 and now - snap[1] < 1500:
            self._setCaptured(True, 'snap')
            return False
        if snap is None:
            self.__m_snap = (QPoint(current), now)  # type: tuple
            self.__m_lastSet = current  # type: QPoint
            return True
        return False  # moved again, elsewhere: the user

    def _setCaptured(self, captured, by=''):
        """
        MOTION_AUTO: a game captures the mouse (center the face on the screen) - or no longer (move the pointer).
        :param captured: bool
        :param by: (str | unicode | QString) 'signal' or 'snap'.
        :return:
        """
        self.__m_captured, self.__m_captureBy = bool(captured), by if captured else ''
        self.__m_snap, self.__m_lastSet, self.__m_pausedUntil = None, None, 0
        self.__m_target, self.__m_zoomPos, self.__m_hiddenSince, self.__m_visibleSince = None, None, None, None
        self._resetView()
        self._restartScans()
        self._setStatus('searching', auto=bool(captured))

    def _watchCapture(self, now):
        """
        MOTION_AUTO, every 200 ms: does a game capture the mouse? Confined (Windows): yes. Hidden: yes if it stays
        hidden while it is moved (a resting video player shows it again). Visible again for 1 s: a menu - the pointer
        is moved again (only when the system's signal decided, not the 'put back' test).
        :param now: int
        :return:
        """
        state = mouseCapture()  # type: str
        if not self.__m_captured:
            moving = now - self.__m_lastMoveMs < 400  # type: bool  # we are moving it: a video player would show it
            if state == 'clipped' or (state == 'hidden' and moving and self.__m_hiddenSince is not None and
                                      now - self.__m_hiddenSince >= 1000):
                self._setCaptured(True, 'signal')
            elif state == 'hidden' and moving:
                self.__m_hiddenSince = self.__m_hiddenSince if self.__m_hiddenSince is not None else now
            elif state != 'hidden':
                self.__m_hiddenSince = None
        elif self.__m_captureBy == 'signal':
            if state == '':
                self.__m_visibleSince = self.__m_visibleSince if self.__m_visibleSince is not None else now
                if now - self.__m_visibleSince >= 1000:
                    self._setCaptured(False)
            else:
                self.__m_visibleSince = None

    def _moveView(self, dt):
        """
        Games, ~60 times per second: send part of the planned mouse movement (smoothly, capped).
        :param dt: (float | int) s since the last move.
        :return: None
        """
        if self.__m_hold == HOLD_RIGHT_BUTTON and not self.__m_watcher.isHeld():
            self.__m_pending = [0.0, 0.0]  # type: list[float]
            if self.__m_status != 'waiting':
                self._setStatus('waiting')
            return
        if self.__m_status == 'waiting':
            self._setStatus('following' if self.__m_target is not None else 'searching')
        tau = max(0.016, 0.15 * self.__m_smoothness / 100.0)  # type: float
        k = 1.0 - exp(-dt / tau)  # type: float
        step = [int(round(clamp(p * k, -MAX_STEP, MAX_STEP))) for p in self.__m_pending]  # type: list[int]
        for i in (0, 1):
            if step[i] == 0 and abs(self.__m_pending[i]) >= 1.0:  # always progress
                step[i] = 1 if self.__m_pending[i] > 0 else -1
        if not step[0] and not step[1]:
            return
        if not sendRelativeMove(step[0], step[1]):
            if self.__m_status != 'blocked':
                self._setStatus('blocked')
            return
        for i in (0, 1):
            self.__m_sent[i] += step[i]
            self.__m_pending[i] -= step[i]

    def _syncWatcher(self):
        """
        Watch the right mouse button only while it matters.
        :return:
        """
        if self.__m_enabled and self.__m_motion != MOTION_POINTER and self.__m_hold == HOLD_RIGHT_BUTTON:
            self.__m_watcher.start()
        else:
            self.__m_watcher.stop()

    # ---------- Public API ----------
    def isEnabled(self):
        """
        :return: bool
        """
        return self.__m_enabled

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setEnabled(self, enabled):
        """
        :param enabled: bool
        :return: None
        """
        enabled = bool(enabled) and FacePointer.isAvailable()  # type: bool
        if enabled == self.__m_enabled:
            if not FacePointer.isAvailable():
                self._setStatus('unavailable')
            return
        self.__m_enabled = enabled  # type: bool
        self.__m_target, self.__m_lastSet, self.__m_zoomPos, self.__m_snap = None, None, None, None
        self.__m_pausedUntil, self.__m_blocked, self.__m_blank = 0, 0, 0
        self.__m_captured, self.__m_captureBy = False, ''  # MOTION_AUTO finds out again (another game, perhaps).
        self.__m_hiddenSince, self.__m_visibleSince = None, None
        self.__m_generation += 1  # a running worker's result will be dropped (it keeps 'busy' until it ends).
        self._resetView()
        self._syncWatcher()
        if enabled:
            self._restartScans()
            self.__m_moveTimer.start()
            self._setStatus('searching')
            self._scan()
        else:
            self.__m_scanTimer.stop()
            self.__m_moveTimer.stop()
            self._setStatus('off')
        self.enabledChanged.emit(enabled)

    @pyqtSlot()
    def toggle(self):
        """
        :return:
        """
        self.setEnabled(not self.__m_enabled)

    def getStatus(self):
        """
        :return: (str | unicode | QString)
            off, searching, following, paused, waiting, static, blocked, blank, noReaction,
            unavailable or error.
        """
        return self.__m_status if FacePointer.isAvailable() else 'unavailable'

    def getStatusDetail(self):
        """
        :return: (dict) faces, backend, timeMs, auto, seconds, message (when known).
        """
        return dict(self.__m_detail)

    def isTurningView(self):
        """
        :return: (bool) The game's view is being turned (MOTION_VIEW, or MOTION_AUTO found a game).
        """
        return self._isView()

    def getTarget(self):
        """
        :return: (QPoint | None) The followed face (global center).
        """
        return QPoint(self.__m_target) if self.__m_target is not None else None

    def getSensitivity(self):
        """
        :return: (tuple[float, float]) Measured screen pixels per mouse count (x, y; negative = inverted axis).
        """
        return tuple(self.__m_k)

    @staticmethod
    def canTurnView():
        """
        :return: (bool) This system lets the application send mouse movements (not Wayland).
        """
        return canSendRelative()

    def getFollow(self):
        """
        :return: int
        """
        return self.__m_follow

    @pyqtSlot(int)
    def setFollow(self, follow):
        """
        :param follow: (int) FOLLOW_POINTER or FOLLOW_ZOOMER.
        :return:
        """
        self.__m_follow = FOLLOW_ZOOMER if int(follow) == FOLLOW_ZOOMER else FOLLOW_POINTER  # type: int
        self.__m_lastSet, self.__m_zoomPos, self.__m_pausedUntil, self.__m_blocked = None, None, 0, 0
        if self.__m_status in ('paused', 'blocked'):
            self._setStatus('following' if self.__m_target is not None else 'searching')

    def getChoose(self):
        """
        :return: int
        """
        return self.__m_choose

    @pyqtSlot(int)
    def setChoose(self, choose):
        """
        :param choose: (int) CHOOSE_LARGEST or CHOOSE_NEAREST.
        :return:
        """
        self.__m_choose = CHOOSE_NEAREST if int(choose) == CHOOSE_NEAREST else CHOOSE_LARGEST  # type: int

    def getMotion(self):
        """
        :return: int
        """
        return self.__m_motion

    @pyqtSlot(int)
    def setMotion(self, motion):
        """
        :param motion: (int) MOTION_AUTO, MOTION_POINTER or MOTION_VIEW.
        :return:
        """
        motion = int(motion) if int(motion) in (MOTION_POINTER, MOTION_VIEW, MOTION_AUTO) else MOTION_AUTO
        if motion != self.__m_motion:
            self.__m_motion = motion  # type: int
            self.__m_captured, self.__m_snap = False, None
            self.__m_target, self.__m_lastSet, self.__m_pausedUntil = None, None, 0
            self._resetView()
            self._syncWatcher()
            self._restartScans()
            if self.__m_status in ('paused', 'blocked', 'waiting', 'static', 'noReaction'):
                self._setStatus('searching' if self.__m_enabled else 'off')

    def getHold(self):
        """
        :return: int
        """
        return self.__m_hold

    @pyqtSlot(int)
    def setHold(self, hold):
        """
        :param hold: (int) HOLD_ALWAYS or HOLD_RIGHT_BUTTON.
        :return:
        """
        self.__m_hold = HOLD_RIGHT_BUTTON if int(hold) == HOLD_RIGHT_BUTTON else HOLD_ALWAYS  # type: int
        self._syncWatcher()

    def getSmoothness(self):
        """
        :return: int
        """
        return self.__m_smoothness

    @pyqtSlot(int)
    def setSmoothness(self, smoothness):
        """
        :param smoothness: (int) 0 .. 100.
        :return:
        """
        self.__m_smoothness = int(clamp(int(smoothness), 0, 100))  # type: int

    def getPauseSeconds(self):
        """
        :return: float | int
        """
        return self.__m_pauseSeconds

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setPauseSeconds(self, pauseSeconds):
        """
        :param pauseSeconds: float | int
        :return:
        """
        self.__m_pauseSeconds = float(clamp(float(pauseSeconds), 0.5, 30.0))  # type: float

    def getScanRate(self):
        """
        :return: int
        """
        return self.__m_scanRate

    @pyqtSlot(int)
    def setScanRate(self, scanRate):
        """
        :param scanRate: (int) Whole-screen scans per second, 1 .. 15 (films; games run at ~30).
        :return:
        """
        self.__m_scanRate = int(clamp(int(scanRate), 1, 15))  # type: int
        if self.__m_scanTimer.isActive():
            self._restartScans()

    def getAssistArea(self):
        """
        :return: int
        """
        return self.__m_assistArea

    @pyqtSlot(int)
    def setAssistArea(self, assistArea):
        """
        :param assistArea: (int) 10 .. 100 (% of half the screen height).
        :return:
        """
        self.__m_assistArea = int(clamp(int(assistArea), 10, 100))  # type: int
        with self.__m_lock:
            self.__m_prevGray = None  # (another capture size)

    def getStrength(self):
        """
        :return: int
        """
        return self.__m_strength

    @pyqtSlot(int)
    def setStrength(self, strength):
        """
        :param strength: (int) 10 .. 100 (%).
        :return:
        """
        self.__m_strength = int(clamp(int(strength), 10, 100))  # type: int

    # ---------- Properties ----------
    enabled = pyqtProperty(bool, fget=isEnabled, fset=setEnabled, notify=enabledChanged)  # type: pyqtProperty
    follow = pyqtProperty(int, fget=getFollow, fset=setFollow)  # type: pyqtProperty
    choose = pyqtProperty(int, fget=getChoose, fset=setChoose)  # type: pyqtProperty
    motion = pyqtProperty(int, fget=getMotion, fset=setMotion)  # type: pyqtProperty
    hold = pyqtProperty(int, fget=getHold, fset=setHold)  # type: pyqtProperty
    smoothness = pyqtProperty(int, fget=getSmoothness, fset=setSmoothness)  # type: pyqtProperty
    pauseSeconds = pyqtProperty(float, fget=getPauseSeconds, fset=setPauseSeconds)  # type: pyqtProperty
    scanRate = pyqtProperty(int, fget=getScanRate, fset=setScanRate)  # type: pyqtProperty
    assistArea = pyqtProperty(int, fget=getAssistArea, fset=setAssistArea)  # type: pyqtProperty
    strength = pyqtProperty(int, fget=getStrength, fset=setStrength)  # type: pyqtProperty
