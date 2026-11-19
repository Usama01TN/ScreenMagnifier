# -*- coding: utf-8 -*-
"""
AnalysisServer: real-time upscaling and analysis service for Screen Magnifier clients - pure Python (asyncio),
NumPy, OpenCV optional, NO Qt: it runs on a desktop or on a phone (Android: Termux, Pydroid).
Clients send the zoomed frames and receive the upscaled image and / or the analysis (colors, faces).
Messages (wire.py framing, JSON header + binary payload):
    client -> server -> client
    hello   {token, client, version}                         welcome {version, server, methods, colors, faces, formats}
    upscale {id, channel, width, height, method, sharpness,  upscaled {id, channel, timeMs, method, format} + image
             format, quality} + image
    analyze {id, source, colors {...}, faces {...}} + image  analysis {id, source, result, hasMask} + mask
    ping    {t}                                              pong {t}
    (any error)                                              error {id, code, message}
'formats' lists the image formats this server decodes: RAWZ always (lossless, zlib only), PNG / JPG with OpenCV
or Pillow - clients upload RAWZ when JPG is not listed. A token (shared secret) can be required; unauthenticated
peers may only send 'hello'. Upscaling and analysis run on two worker threads: the network loop stays responsive.
"""
from asyncio import get_event_loop, ensure_future, new_event_loop, set_event_loop, start_server
from concurrent.futures import ThreadPoolExecutor
from threading import Thread, Event
from hmac import compare_digest
from socket import gethostname
from os.path import dirname
from time import time
from sys import path

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .netprotocol.wire import packMessage, MessageParser, encodeArray, decodeArray, availableFormats, DEFAULT_PORT
    from .facedetector.core import FaceEngine, userDataDir
    from .colordetector.core import ColorAnalyzer, np
    from .upscaler.core import UpscaleEngine
except:
    from netprotocol.wire import packMessage, MessageParser, encodeArray, decodeArray, availableFormats, DEFAULT_PORT
    from facedetector.core import FaceEngine, userDataDir
    from colordetector.core import ColorAnalyzer, np
    from upscaler.core import UpscaleEngine

PROTOCOL_VERSION = 1  # type: int
MAX_TARGET_SIDE = 4096  # type: int  # Largest upscaled image a client may request.
MAX_PENDING = 8  # type: int  # Analyses queued per client before 'busy' errors.


class _Client(object):
    """
    _Client class: one connection.
    """

    def __init__(self, writer, peer):
        """
        :param writer: StreamWriter
        :param peer: str | unicode | QString
        """
        self.writer = writer
        self.peer = peer  # type: str
        self.authed = False  # type: bool
        self.pending = 0  # type: int
        self.open = True  # type: bool


class AnalysisServer(object):
    """
    AnalysisServer class.
    """

    def __init__(self, *args, **kwargs):
        """
        :param host: (str | unicode | QString)
                    Interface to listen on ('127.0.0.1' = this computer only, '0.0.0.0' = the network).
        :param port: (int) TCP port, 0 = any free port (see getPort()).
        :param token: (str | unicode | QString) Shared secret clients must send in 'hello' ('' = none).
        :param maxClients: (int) Simultaneous connections.
        :param logMessage: (callable | None) f(text) for the server log.
        :param args: any
        :param kwargs: any
        """
        self.__m_host = u'{}'.format(kwargs.pop('host', '127.0.0.1'))  # type: str
        self.__m_port = int(kwargs.pop('port', DEFAULT_PORT))  # type: int
        self.__m_token = u'{}'.format(kwargs.pop('token', '') or '')  # type: str
        self.__m_maxClients = max(1, int(kwargs.pop('maxClients', 8)))  # type: int
        self.__m_logMessage = kwargs.pop('logMessage', None)
        super(AnalysisServer, self).__init__(*args, **kwargs)
        self.__m_upscaler = UpscaleEngine(onError=self._log)  # type: UpscaleEngine
        self.__m_colors = ColorAnalyzer()  # type: ColorAnalyzer
        self.__m_faces = FaceEngine(dataDir=userDataDir(), onError=self._log)  # type: FaceEngine
        self.__m_upscalePool = ThreadPoolExecutor(max_workers=1)  # type: ThreadPoolExecutor
        self.__m_analysisPool = ThreadPoolExecutor(max_workers=1)  # type: ThreadPoolExecutor
        self.__m_clients = set()  # type: set
        self.__m_stats = {'upscaled': 0, 'analyzed': 0, 'upscaleMs': 0.0, 'analyzeMs': 0.0}  # type: dict
        self.__m_loop = None
        self.__m_server = None
        self.__m_thread = None  # type: Thread | None
        self.__m_ready = Event()  # type: Event
        self.__m_error = None  # type: Exception | None

    # ---------- Helpers ----------
    def _log(self, text):
        """
        :param text: str | unicode | QString
        :return:
        """
        if callable(self.__m_logMessage):
            self.__m_logMessage(u'{}'.format(text))

    def _send(self, client, header, payload=b''):
        """
        Send from the event-loop thread.
        :param client: _Client
        :param header: dict
        :param payload: bytes
        :return:
        """
        if client.open:
            try:
                client.writer.write(packMessage(header, payload))
            except Exception as e:
                self._log('Send to {} failed: {}'.format(client.peer, e))
                client.open = False

    def _error(self, client, header, code, message):
        """
        :param client: _Client
        :param header: dict
        :param code: str | unicode | QString
        :param message: str | Exception
        :return:
        """
        self._send(client, {'type': 'error', 'id': header.get('id'), 'code': code, 'message': u'{}'.format(message)})

    def _capabilities(self):
        """
        :return: dict
        """
        return {'type': 'welcome', 'version': PROTOCOL_VERSION, 'server': gethostname(),
                'methods': [[int(m), n] for m, n in self.__m_upscaler.availableMethods()],
                'colors': bool(np), 'formats': availableFormats(),
                'faces': {'available': FaceEngine.isAvailable(), 'yunet': self.__m_faces.isModelReady()}}

    def _decode(self, payload):
        """
        :param payload: bytes
        :return: numpy.ndarray
        :raise ValueError: undecodable image (e.g. JPEG without OpenCV / Pillow).
        """
        arr = decodeArray(payload)
        if arr is None or arr.ndim != 3:
            raise ValueError(u'Cannot decode the image here (supported: {}); send RAWZ'.format(
                ', '.join(availableFormats())))
        return arr

    def _upscale(self, header, payload):
        """
        Worker thread.
        :param header: dict
        :param payload: bytes
        :return: (tuple[dict, bytes]) Reply header and image.
        """
        arr = self._decode(payload)
        w = int(min(MAX_TARGET_SIDE, max(1, int(header.get('width', arr.shape[1])))))  # type: int
        h = int(min(MAX_TARGET_SIDE, max(1, int(header.get('height', arr.shape[0])))))  # type: int
        method = self.__m_upscaler.resolve(int(header.get('method', 1)))  # type: int
        started = time()  # type: float
        out = self.__m_upscaler.upscale(arr, w, h, method, float(header.get('sharpness', 0.0)))
        fmt = 'PNG' if u'{}'.format(header.get('format', 'JPG')).upper() == 'PNG' else 'JPG'  # type: str
        data, used = encodeArray(out, fmt, int(header.get('quality', 90)))
        ms = (time() - started) * 1000.0  # type: float
        self.__m_stats['upscaled'] += 1
        self.__m_stats['upscaleMs'] = ms
        return {'type': 'upscaled', 'id': header.get('id'), 'channel': header.get('channel', ''),
                'timeMs': round(ms, 2), 'method': int(method), 'format': used}, data

    def _analyze(self, header, payload):
        """
        Worker thread.
        :param header: dict
        :param payload: bytes
        :return: (tuple[dict, bytes]) Reply header and label mask (PNG when available, else RAWG).
        """
        arr = self._decode(payload)
        started = time()  # type: float
        result, mask = {}, b''  # type: dict, bytes
        colors = header.get('colors') or {}  # type: dict
        if colors.get('enabled'):
            options = {'targets': [u'{}'.format(c) for c in colors.get('targets', [])][:64]}  # type: dict
            for key, option in (('tolerance', 'tolerance'), ('minArea', 'minArea'), ('palette', 'paletteSize'),
                                ('mask', 'returnMask'), ('matchMode', 'matchMode'), ('groupDistance', 'groupDistance')):
                if key in colors:
                    options[option] = colors[key]
            self.__m_colors.configure(**options)
            res = self.__m_colors.analyze(arr)  # type: dict
            label = res.pop('labelMask', None)
            if label is not None:
                mask = encodeArray(label, 'PNG')[0]  # type: bytes  # RAWG without a PNG codec
            result['colors'] = res
        faces = header.get('faces') or {}  # type: dict
        if faces.get('enabled'):
            fe = self.__m_faces  # type: FaceEngine
            fe.backend = u'{}'.format(faces.get('backend', 'auto'))  # type str
            fe.scoreThreshold = min(0.99, max(0.1, float(faces.get('score', fe.scoreThreshold))))  # type float
            fe.minFaceSize = max(8, int(faces.get('minSize', fe.minFaceSize)))  # type int
            result['faces'] = fe.detect(arr)
        ms = (time() - started) * 1000.0  # type: float
        self.__m_stats['analyzed'] += 1
        self.__m_stats['analyzeMs'] = ms
        return ({'type': 'analysis', 'id': header.get('id'), 'source': header.get('source', ''), 'result': result,
                 'origin': header.get('origin'), 'hasMask': bool(mask), 'timeMs': round(ms, 2)}, mask)

    async def _work(self, client, pool, job, header, payload, analysis=False):
        """
        Run a job on its worker thread and send the reply (dropped if the client has left meanwhile).
        :param client: _Client
        :param pool: ThreadPoolExecutor
        :param job: callable
        :param header: dict
        :param payload: bytes
        :param analysis: bool
        :return:
        """
        try:
            reply, data = await get_event_loop().run_in_executor(pool, job, header, payload)
            self._send(client, reply, data)
        except Exception as e:
            self._error(client, header, 'failed', e)
        finally:
            if analysis:
                client.pending -= 1

    async def _dispatch(self, client, header, payload):
        """
        :param client: _Client
        :param header: dict
        :param payload: bytes
        :return: (bool) Keep the connection.
        """
        kind = u'{}'.format(header.get('type', ''))  # type: str
        if kind == 'hello':
            if self.__m_token and not compare_digest(u'{}'.format(header.get('token', '')).encode('utf-8'),
                                                     self.__m_token.encode('utf-8')):
                self._log(u'Rejected {}: wrong token'.format(client.peer))
                self._error(client, header, 'auth', u'Wrong or missing token')
                return False
            client.authed = True
            self._send(client, self._capabilities())
            return True
        if not client.authed:
            self._error(client, header, 'auth', u'Send hello first')
            return False
        if kind == 'ping':
            self._send(client, {'type': 'pong', 't': header.get('t')})
        elif kind == 'upscale':
            ensure_future(self._work(client, self.__m_upscalePool, self._upscale, header, payload))
        elif kind == 'analyze':
            if client.pending >= MAX_PENDING:
                self._error(client, header, 'busy', u'Too many pending analyses')
            else:
                client.pending += 1
                ensure_future(self._work(client, self.__m_analysisPool, self._analyze, header, payload, True))
        else:
            self._error(client, header, 'unknown', u'Unknown message type {!r}'.format(kind))
        return True

    async def _serve(self, reader, writer):
        """
        :param reader: StreamReader
        :param writer: StreamWriter
        :return:
        """
        address = writer.get_extra_info('peername')
        client = _Client(writer, '{}:{}'.format(*address[:2]) if address else '?')  # type: _Client
        if len(self.__m_clients) >= self.__m_maxClients:
            self._error(client, {}, 'busy', u'Too many clients')
            writer.close()
            return
        self.__m_clients.add(client)
        self._log('Client {} connected ({} connected)'.format(client.peer, len(self.__m_clients)))
        parser = MessageParser()  # type: MessageParser
        try:
            while client.open:
                data = await reader.read(1 << 16)
                if not data:
                    break
                try:
                    messages = parser.feed(data)  # type: list
                except ValueError as e:
                    self._log(u'Closing {}: {}'.format(client.peer, e))
                    break
                for header, payload in messages:
                    if not await self._dispatch(client, header, payload):
                        client.open = False
                        break
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            client.open = False
            self.__m_clients.discard(client)
            try:
                writer.close()
            except:
                pass
            self._log(u'Client {} left ({} connected)'.format(client.peer, len(self.__m_clients)))

    def _run(self):
        """
        Server thread: its own event loop.
        :return: None
        """
        loop = new_event_loop()
        set_event_loop(loop)
        self.__m_loop = loop
        try:
            self.__m_server = loop.run_until_complete(start_server(self._serve, self.__m_host, self.__m_port))
            self.__m_port = int(self.__m_server.sockets[0].getsockname()[1])  # type: int
        except Exception as e:
            self.__m_error = e
            self.__m_ready.set()
            return
        self.__m_ready.set()
        try:
            loop.run_forever()
        finally:
            self.__m_server.close()
            loop.run_until_complete(self.__m_server.wait_closed())
            loop.close()

    # ---------- Public API ----------
    def start(self):
        """
        Listen in a background thread.
        :return: None
        :raise OSError: the address cannot be used (e.g. port taken).
        """
        if self.isRunning():
            return
        self.__m_ready.clear()
        self.__m_error = None
        self.__m_thread = Thread(target=self._run, name='AnalysisServer')
        self.__m_thread.daemon = True
        self.__m_thread.start()
        self.__m_ready.wait(10.0)
        if self.__m_error is not None:
            error, self.__m_error = self.__m_error, None
            raise error

    def stop(self):
        """
        :return:
        """
        if self.__m_loop is not None and self.__m_thread is not None:
            self.__m_loop.call_soon_threadsafe(self.__m_loop.stop)
            self.__m_thread.join(5.0)
        self.__m_thread, self.__m_loop = None, None

    def serveForever(self):
        """
        Start and block until stop() or Ctrl+C.
        :return:
        """
        self.start()
        try:
            while self.isRunning():
                self.__m_thread.join(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def isRunning(self):
        """
        :return: bool
        """
        return self.__m_thread is not None and self.__m_thread.is_alive()

    def getPort(self):
        """
        :return: int
        """
        return self.__m_port

    def getClientCount(self):
        """
        :return: int
        """
        return len(self.__m_clients)

    def getStats(self):
        """
        :return: dict
        """
        return dict(self.__m_stats)

    def getFaceEngine(self):
        """
        :return: FaceEngine
        """
        return self.__m_faces

    def getUpscaleEngine(self):
        """
        :return: UpscaleEngine
        """
        return self.__m_upscaler
