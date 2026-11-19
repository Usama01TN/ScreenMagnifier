# -*- coding: utf-8 -*-
"""
AnalysisController: runs color detection and (optional AI) face detection on the magnified frames and turns the
results into annotations (boxes, labels, landmarks, privacy blur, color mask) for the view and the lens.
- Several sources ('view', 'lens'), each rate limited (rateHz) with "latest frame wins".
- Local analysis runs on a worker thread, so zooming / panning stay smooth.
- With a connected RemoteClient and useRemote, the analysis runs on the server instead (automatic local fallback
  whenever the server is unavailable).
- A generation counter drops results computed with outdated settings.
- colorAppeared(source, name) fires when a target color becomes visible (alerts).
"""
from ManyQt.QtCore import QObject, QTimer, QSize, Qt, pyqtSignal, pyqtSlot, pyqtProperty
from ManyQt.QtGui import QImage
from threading import Thread, Condition
from os.path import dirname
from zlib import adler32
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .colordetector import ColorDetector, maskToOverlay
    from .facedetector import FaceDetector
except:
    from colordetector import ColorDetector, maskToOverlay
    from facedetector import FaceDetector

FACE_COLOR = '#00E5FF'  # type: str
REMOTE_MAX_SIDE = 1280  # type: int  # Larger frames are downscaled for remote analysis (smaller would blur thin text).


def frameKey(image):
    """
    :param image: QImage
    :return: (int) Cheap content fingerprint (unchanged screens are not analysed again).
    """
    ptr = image.constBits()
    n = image.sizeInBytes() if hasattr(image, 'sizeInBytes') else image.byteCount()  # type: int
    if hasattr(ptr, 'setsize'):
        ptr.setsize(n)
    return adler32(bytes(ptr)) ^ (image.width() << 16) ^ image.height()


class AnalysisController(QObject):
    """
    AnalysisController class.
    """
    annotationsReady = pyqtSignal('QString', object, object, object, object)  # type: pyqtSignal  # source, list,
    #                                                                 QSize, QImage, origin [x, y, dpr] | None
    resultsReady = pyqtSignal('QString', object)  # type: pyqtSignal  # source, {'colors': {...}, 'faces': {...}}
    colorAppeared = pyqtSignal('QString', 'QString')  # type: pyqtSignal  # source, color name
    settingsChanged = pyqtSignal()  # type: pyqtSignal
    _workerDone = pyqtSignal('QString', object, object, int)  # type: pyqtSignal  # worker -> GUI thread

    def __init__(self, *args, **kwargs):
        """
        :param colorDetector: (ColorDetector | None) None = create one.
        :param faceDetector: (FaceDetector | None) None = create one.
        :param client: (RemoteClient | None) Server connection used when useRemote is on.
        :param rateHz: (float | int) Analyses per second and per source.
        :param colorEnabled: bool
        :param faceEnabled: bool
        :param useRemote: (bool) Analyse on the server when it is connected.
        :param showBoxes: (bool) Boxes around detected color regions.
        :param showMask: (bool) Color highlight mask.
        :param maskMode: (str | unicode | QString) 'isolate' or 'tint'.
        :param maskAlpha: (float | int) 0 .. 1
        :param faceMode: (str | unicode | QString) 'box', 'landmarks' or 'blur' (privacy).
        :param annotationsReady: callable | None
        :param resultsReady: callable | None
        :param colorAppeared: callable | None
        :param args: any
        :param kwargs: any
        """
        colorDetector = kwargs.pop('colorDetector', None)  # type: ColorDetector | None
        faceDetector = kwargs.pop('faceDetector', None)  # type: FaceDetector | None
        client = kwargs.pop('client', None)
        rateHz = kwargs.pop('rateHz', 8)  # type: float
        colorEnabled = kwargs.pop('colorEnabled', False)  # type: bool
        faceEnabled = kwargs.pop('faceEnabled', False)  # type: bool
        useRemote = kwargs.pop('useRemote', False)  # type: bool
        showBoxes = kwargs.pop('showBoxes', True)  # type: bool
        showMask = kwargs.pop('showMask', True)  # type: bool
        maskMode = kwargs.pop('maskMode', 'isolate')  # type: str
        maskAlpha = kwargs.pop('maskAlpha', 0.6)  # type: float
        faceMode = kwargs.pop('faceMode', 'box')  # type: str
        annotationsReady = kwargs.pop('annotationsReady', None)  # type: callable | None
        resultsReady = kwargs.pop('resultsReady', None)  # type: callable | None
        colorAppeared = kwargs.pop('colorAppeared', None)  # type: callable | None
        super(AnalysisController, self).__init__(*args, **kwargs)
        for signal, slot in ((self.annotationsReady, annotationsReady), (self.resultsReady, resultsReady),
                             (self.colorAppeared, colorAppeared)):
            if callable(slot):
                signal.connect(slot)
        self.__m_colors = colorDetector if colorDetector is not None else ColorDetector(parent=self)
        self.__m_faces = faceDetector if faceDetector is not None else FaceDetector(parent=self)
        self.__m_client = client
        self.__m_rateHz = max(0.5, min(60.0, float(rateHz)))  # type: float
        self.__m_colorEnabled = bool(colorEnabled)  # type: bool
        self.__m_faceEnabled = bool(faceEnabled)  # type: bool
        self.__m_useRemote = bool(useRemote)  # type: bool
        self.__m_showBoxes = bool(showBoxes)  # type: bool
        self.__m_showMask = bool(showMask)  # type: bool
        self.__m_maskMode = 'tint' if u'{}'.format(maskMode) == 'tint' else 'isolate'  # type: str
        self.__m_maskAlpha = max(0.0, min(1.0, float(maskAlpha)))  # type: float
        self.__m_faceMode = u'{}'.format(faceMode) if u'{}'.format(faceMode) in ('box', 'landmarks', 'blur') else 'box'  # type: str
        # State.
        self.__m_frames = {}  # type: dict  # source -> newest QImage
        self.__m_origins = {}  # type: dict  # source -> [x, y, dpr] screen position of that frame (or None)
        self.__m_dirty = set()  # type: set
        self.__m_present = {}  # type: dict  # source -> set of visible target names (alerts)
        self.__m_generation = 0  # type: int
        self.__m_last = {}  # type: dict  # source -> last published result
        self.__m_analysed = {}  # type: dict  # source -> (frame fingerprint, generation) last dispatched
        # Worker thread.
        self.__m_cond = Condition()  # type: Condition
        self.__m_jobs = {}  # type: dict  # source -> (QImage, generation)
        self.__m_running = True  # type: bool
        self.__m_thread = Thread(target=self._work, name='AnalysisWorker')  # type: Thread
        self.__m_thread.daemon = True
        self.__m_thread.start()
        self._workerDone.connect(self._onLocalDone, Qt.QueuedConnection)
        # Any detector setting change invalidates in-flight work and re-analyses the last frames.
        self.__m_colors.targetsChanged.connect(self.reanalyse)
        self.__m_colors.settingsChanged.connect(self.reanalyse)
        self.__m_faces.backendChanged.connect(self.reanalyse)
        if client is not None:
            client.analysisReady.connect(self._onRemoteDone)
        self.__m_timer = QTimer(self)  # type: QTimer
        self.__m_timer.timeout.connect(self._tick)
        self._updateTimer()

    # ---------- Helpers ----------
    def _active(self):
        """
        :return: bool
        """
        return self.__m_colorEnabled or self.__m_faceEnabled

    def _remote(self):
        """
        :return: (bool) Analyse on the server right now.
        """
        return self.__m_useRemote and self.__m_client is not None and self.__m_client.isReady()

    def _updateTimer(self):
        """
        :return:
        """
        if self._active():
            self.__m_timer.start(int(round(1000.0 / self.__m_rateHz)))
        else:
            self.__m_timer.stop()

    def _changed(self, reanalyse=True):
        """
        A setting changed: drop in-flight results, re-analyse the last frames, clear when disabled.
        :param reanalyse: bool
        :return:
        """
        self.__m_generation += 1
        self._updateTimer()
        if not self._active():
            for source in list(self.__m_frames):
                self.annotationsReady.emit(source, [], QSize(), QImage(), None)
            self.__m_present = {}  # type: dict
        elif reanalyse:
            self.__m_dirty.update(self.__m_frames.keys())
        self.settingsChanged.emit()

    def _work(self):
        """
        Worker thread: always analyse the newest job of each source.
        :return:
        """
        while True:
            with self.__m_cond:
                while self.__m_running and not self.__m_jobs:
                    self.__m_cond.wait()
                if not self.__m_running:
                    return
                source = next(iter(self.__m_jobs))  # type: str
                image, generation, origin = self.__m_jobs.pop(source)
            try:
                result, mask = self._analyseLocal(image)
            except Exception as e:
                result, mask = {'error': u'{}'.format(e)}, QImage()
            result['origin'] = origin
            self._workerDone.emit(source, result, mask, generation)

    def _analyseLocal(self, image):
        """
        :param image: QImage
        :return: (tuple[dict, QImage]) Result and label mask.
        """
        result, mask = {}, QImage()  # type: dict, QImage
        if self.__m_colorEnabled:
            colors = self.__m_colors.analyze(image)  # type: dict
            label = colors.pop('labelMask', None)
            mask = label if label is not None else QImage()  # type: QImage
            result['colors'] = colors
        if self.__m_faceEnabled:
            result['faces'] = self.__m_faces.detect(image)
        return result, mask

    def _params(self):
        """
        :return: (dict) Analysis settings in the AnalysisServer protocol format.
        """
        cd = self.__m_colors  # type: ColorDetector
        fd = self.__m_faces  # type: FaceDetector
        return {'colors': {'enabled': self.__m_colorEnabled,
                           'targets': [u'{}'.format(c.name()) for c in cd.getTargetColors()],
                           'tolerance': cd.getTolerance(), 'minArea': cd.getMinArea(),
                           'palette': cd.getPaletteSize(), 'mask': self.__m_showMask,
                           'matchMode': int(cd.getMatchMode()), 'groupDistance': cd.getGroupDistance()},
                'faces': {'enabled': self.__m_faceEnabled, 'backend': fd.getBackend(),
                          'score': fd.getScoreThreshold(), 'minSize': fd.getMinFaceSize()},
                'generation': self.__m_generation}

    @pyqtSlot()
    def _tick(self):
        """
        Rate limiter: dispatch the newest frame of every source that changed.
        :return:
        """
        for source in list(self.__m_dirty):
            image = self.__m_frames.get(source)  # type: QImage
            self.__m_dirty.discard(source)
            if image is None or image.isNull():
                continue
            stamp = (frameKey(image), self.__m_generation, self._remote())  # type: tuple
            if self.__m_analysed.get(source) == stamp:
                continue  # Same pixels, same settings: the published result is still valid.
            self.__m_analysed[source] = stamp
            if self._remote():
                scale = min(1.0, REMOTE_MAX_SIDE / float(max(image.width(), image.height())))  # type: float
                img = image if scale >= 1.0 else image.scaled(int(image.width() * scale), int(image.height() * scale),
                                                              Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                params = self._params()  # type: dict
                origin = self.__m_origins.get(source)  # type: list | None
                params['origin'] = [origin[0], origin[1], origin[2] * min(1.0, scale)] if origin else None
                self.__m_client.requestAnalysis(source, img, params)
            else:
                with self.__m_cond:
                    self.__m_jobs[source] = (image.copy(), self.__m_generation, self.__m_origins.get(source))
                    self.__m_cond.notify()

    def _onLocalDone(self, source, result, mask, generation):
        """
        :param source: str | unicode | QString
        :param result: dict
        :param mask: QImage
        :param generation: int
        :return:
        """
        if generation == self.__m_generation and self._active():
            self._publish(u'{}'.format(source), result, mask)

    def _onRemoteDone(self, source, result, mask):
        """
        :param source: str | unicode | QString
        :param result: dict
        :param mask: QImage
        :return:
        """
        if self._active() and self.__m_useRemote:
            self._publish(u'{}'.format(source), result, mask)

    def _publish(self, source, result, mask):
        """
        :param source: str | unicode | QString
        :param result: dict
        :param mask: QImage
        :return:
        """
        colors = result.get('colors') or {}  # type: dict
        faces = result.get('faces') or {}  # type: dict
        w = colors.get('width') or faces.get('width') or 0  # type: int
        h = colors.get('height') or faces.get('height') or 0  # type: int
        annotations = []  # type: list
        if self.__m_colorEnabled and self.__m_showBoxes:
            for d in colors.get('detections', []):
                annotations.append({'rect': d['rect'], 'color': d['color'], 'label': d['name']})
        if self.__m_faceEnabled:
            for f in faces.get('faces', []):
                if self.__m_faceMode == 'blur':
                    annotations.append({'rect': f['rect'], 'style': 'blur', 'blocks': 10})
                else:
                    annotations.append({'rect': f['rect'], 'color': FACE_COLOR,
                                        'label': 'face {:.0f}%'.format(100.0 * float(f.get('score', 1.0))),
                                        'points': f.get('landmarks', []) if self.__m_faceMode == 'landmarks' else []})
        overlay = QImage()  # type: QImage
        if self.__m_colorEnabled and self.__m_showMask and mask is not None and not mask.isNull():
            overlay = maskToOverlay(mask, self.__m_colors.getTargetColors(), self.__m_maskAlpha, self.__m_maskMode)
        self.__m_last[source] = result
        self.annotationsReady.emit(source, annotations, QSize(int(w), int(h)), overlay, result.get('origin'))
        self.resultsReady.emit(source, result)
        names = set(d['name'] for d in colors.get('detections', []))  # type: set
        for name in sorted(names - self.__m_present.get(source, set())):
            self.colorAppeared.emit(source, name)
        self.__m_present[source] = names

    # ---------- Public API ----------
    def submit(self, source, image, origin=None, dpr=1.0):
        """
        Offer a new frame; it is analysed at the configured rate (newest frame wins).
        :param source: (str | unicode | QString) 'view', 'lens', ...
        :param image: QImage
        :param origin: (QPoint | None) Screen position of the frame (top-left): results carry it so annotations
            can follow moving content.
        :param dpr: (float | int) Frame pixels per screen point.
        :return:
        """
        if self._active() and image is not None and not image.isNull():
            self.__m_frames[u'{}'.format(source)] = image
            self.__m_origins[u'{}'.format(source)] = [origin.x(), origin.y(), float(dpr)] if origin is not None else None
            self.__m_dirty.add(u'{}'.format(source))

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def forget(self, source):
        """
        Stop analyzing a source (e.g. the lens was hidden) and clear its annotations.
        :param source: str | unicode | QString
        :return:
        """
        self.__m_frames.pop(u'{}'.format(source), None)
        self.__m_analysed.pop(u'{}'.format(source), None)
        self.__m_dirty.discard(u'{}'.format(source))
        self.__m_present.pop(u'{}'.format(source), None)
        self.annotationsReady.emit(u'{}'.format(source), [], QSize(), QImage(), None)

    @pyqtSlot()
    def reanalyse(self):
        """
        Settings of the detectors changed: analyse the last frames again.
        :return:
        """
        self._changed()

    @pyqtSlot()
    def shutdown(self):
        """
        Stop the worker thread (call before quitting).
        :return:
        """
        self.__m_timer.stop()
        with self.__m_cond:
            self.__m_running = False  # type: bool
            self.__m_cond.notify()
        self.__m_thread.join(1.0)

    def getLastResult(self, source):
        """
        :param source: str | unicode | QString
        :return: (dict) Last published result for a source ({} if none).
        """
        return dict(self.__m_last.get(u'{}'.format(source), {}))

    def getColorDetector(self):
        """
        :return: ColorDetector
        """
        return self.__m_colors

    def getFaceDetector(self):
        """
        :return: FaceDetector
        """
        return self.__m_faces

    def isRemoteActive(self):
        """
        :return: (bool) Analyses are currently sent to the server.
        """
        return self._remote()

    def getRateHz(self):
        """
        :return: float | int
        """
        return self.__m_rateHz

    @pyqtSlot(float)
    @pyqtSlot(int)
    def setRateHz(self, rateHz):
        """
        :param rateHz: (float | int) 0.5 .. 60
        :return:
        """
        self.__m_rateHz = max(0.5, min(60.0, float(rateHz)))  # type: float
        self._updateTimer()

    def isColorEnabled(self):
        """
        :return: bool
        """
        return self.__m_colorEnabled

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setColorEnabled(self, colorEnabled):
        """
        :param colorEnabled: bool
        :return:
        """
        self.__m_colorEnabled = bool(colorEnabled)  # type: bool
        self._changed()

    def isFaceEnabled(self):
        """
        :return: bool
        """
        return self.__m_faceEnabled

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setFaceEnabled(self, faceEnabled):
        """
        :param faceEnabled: bool
        :return:
        """
        self.__m_faceEnabled = bool(faceEnabled)  # type: bool
        self._changed()

    def isUseRemote(self):
        """
        :return: bool
        """
        return self.__m_useRemote

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setUseRemote(self, useRemote):
        """
        :param useRemote: bool
        :return:
        """
        self.__m_useRemote = bool(useRemote)  # type: bool
        self._changed()

    def isShowBoxes(self):
        """
        :return: bool
        """
        return self.__m_showBoxes

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setShowBoxes(self, showBoxes):
        """
        :param showBoxes: bool
        :return:
        """
        self.__m_showBoxes = bool(showBoxes)  # type: bool
        self._changed()

    def isShowMask(self):
        """
        :return: bool
        """
        return self.__m_showMask

    @pyqtSlot(bool)
    @pyqtSlot(int)
    def setShowMask(self, showMask):
        """
        :param showMask: bool
        :return:
        """
        self.__m_showMask = bool(showMask)  # type: bool
        self.__m_colors.setReturnMask(self.__m_showMask)
        self._changed()

    def getMaskMode(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_maskMode

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setMaskMode(self, maskMode):
        """
        :param maskMode: (str | unicode | QString) 'isolate' or 'tint'.
        :return:
        """
        self.__m_maskMode = 'tint' if u'{}'.format(maskMode) == 'tint' else 'isolate'  # type: str
        self._changed()

    def getMaskAlpha(self):
        """
        :return: float | int
        """
        return self.__m_maskAlpha

    @pyqtSlot(float)
    def setMaskAlpha(self, maskAlpha):
        """
        :param maskAlpha: (float | int) 0 .. 1
        :return:
        """
        self.__m_maskAlpha = max(0.0, min(1.0, float(maskAlpha)))  # type: float
        self._changed()

    def getFaceMode(self):
        """
        :return: str | unicode | QString
        """
        return self.__m_faceMode

    @pyqtSlot('QString')
    @pyqtSlot(str)
    def setFaceMode(self, faceMode):
        """
        :param faceMode: (str | unicode | QString) 'box', 'landmarks' or 'blur'.
        :return:
        """
        self.__m_faceMode = u'{}'.format(faceMode) if u'{}'.format(faceMode) in ('box', 'landmarks', 'blur') else 'box'  # type: str
        self._changed()

    # ---------- Properties ----------
    rateHz = pyqtProperty(float, fget=getRateHz, fset=setRateHz)  # type: pyqtProperty
    colorEnabled = pyqtProperty(bool, fget=isColorEnabled, fset=setColorEnabled)  # type: pyqtProperty
    faceEnabled = pyqtProperty(bool, fget=isFaceEnabled, fset=setFaceEnabled)  # type: pyqtProperty
    useRemote = pyqtProperty(bool, fget=isUseRemote, fset=setUseRemote)  # type: pyqtProperty
    showBoxes = pyqtProperty(bool, fget=isShowBoxes, fset=setShowBoxes)  # type: pyqtProperty
    showMask = pyqtProperty(bool, fget=isShowMask, fset=setShowMask)  # type: pyqtProperty
    maskMode = pyqtProperty('QString', fget=getMaskMode, fset=setMaskMode)  # type: pyqtProperty
    maskAlpha = pyqtProperty(float, fget=getMaskAlpha, fset=setMaskAlpha)  # type: pyqtProperty
    faceMode = pyqtProperty('QString', fget=getFaceMode, fset=setFaceMode)  # type: pyqtProperty
