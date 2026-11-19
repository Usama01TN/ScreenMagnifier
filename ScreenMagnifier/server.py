# coding=utf-8
"""
Screen Magnifier analysis server - pure Python, no Qt: runs on a desktop or on a phone (Android: Termux, Pydroid).
Needs NumPy; OpenCV adds the Bicubic / Lanczos / AI upscalers, face detection and JPEG / PNG (Pillow also gives
JPEG / PNG). Usage:
    ScreenMagnifierServer [--host 0.0.0.0] [--port 8765] [--token SECRET] [--max-clients 4]
    python -m ScreenMagnifier.server ...   or   python server.py ...
    --download-face-model   fetch the YuNet face model (verified) into the user data folder, then exit
    --selftest              start on a free port, run a real session over TCP, exit (0 = ok)
"""
from sys import path, exit, stdout
from os.path import dirname, join
from datetime import datetime
from os import environ
import socket

if not __package__ and dirname(__file__) not in path:
    path.append(dirname(__file__))

try:
    from .netprotocol.wire import DEFAULT_PORT, packMessage, MessageParser, encodeArray, decodeArray
    from .facedetector.core import downloadModel, userDataDir, YUNET_FILE
    from .analysisserver import AnalysisServer
except:
    from netprotocol.wire import DEFAULT_PORT, packMessage, MessageParser, encodeArray, decodeArray
    from facedetector.core import downloadModel, userDataDir, YUNET_FILE
    from analysisserver import AnalysisServer


def log(text):
    """
    :param text: str | unicode | QString
    :return:
    """
    stdout.write('[{}] {}\n'.format(datetime.now().strftime('%H:%M:%S'), text))
    stdout.flush()


def parseArguments(argv):
    """
    :param argv: list[str | unicode | QString]
    :return: argparse.Namespace
    """
    from argparse import ArgumentParser
    parser = ArgumentParser(
        description=u'Screen Magnifier real-time upscaling / analysis server.')  # type: ArgumentParser
    parser.add_argument('--host', default='127.0.0.1',
                        help=u'Interface to listen on: 127.0.0.1 (this computer) or 0.0.0.0 (network)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=u'TCP port (default %(default)s)')
    parser.add_argument('--token', default=environ.get('SCREENMAGNIFIER_TOKEN', ''),
                        help=u'Shared secret required from clients (or env SCREENMAGNIFIER_TOKEN)')
    parser.add_argument('--max-clients', type=int, default=4, help=u'Simultaneous clients (default %(default)s)')
    parser.add_argument('--selftest', action='store_true',
                        help=u'Start on a free port, upscale one image through a real connection, exit (0 = ok)')
    parser.add_argument('--download-face-model', action='store_true',
                        help=u'Download the YuNet face detection model (232 KB) before starting')
    return parser.parse_args(argv)


def request(sock, parser, header, payload=b''):
    """
    Self-test client: send one message and wait for the reply.
    :param sock: socket.socket
    :param parser: MessageParser
    :param header: dict
    :param payload: bytes
    :return: (tuple[dict, bytes]) Reply.
    """
    sock.sendall(packMessage(header, payload))
    while True:
        data = sock.recv(1 << 16)
        if not data:
            return {'type': 'closed'}, b''
        messages = parser.feed(data)
        if messages:
            return messages[0]


def selfTest():
    """
    A real session over TCP: wrong token refused, upscale, color analysis.
    :return: (bool) Everything worked.
    """
    from numpy import zeros, uint8
    server = AnalysisServer(host='127.0.0.1', port=0, token='secret', logMessage=lambda t: None)  # type: AnalysisServer
    server.start()
    checks = []  # type: list
    try:
        intruder = socket.create_connection(('127.0.0.1', server.getPort()), 10)
        reply = request(intruder, MessageParser(), {'type': 'hello', 'token': 'wrong'})[0]
        checks.append((u'Wrong token refused', reply.get('code') == 'auth'))
        intruder.close()
        sock = socket.create_connection(('127.0.0.1', server.getPort()), 10)
        parser = MessageParser()  # type: MessageParser
        welcome = request(sock, parser, {'type': 'hello', 'token': 'secret', 'client': 'selftest'})[0]
        checks.append(('welcome', welcome.get('type') == 'welcome'))
        img = zeros((24, 32, 3), uint8)
        img[:, :] = (46, 74, 46)
        img[6:16, 8:20] = (224, 16, 32)
        reply, data = request(sock, parser, {'type': 'upscale', 'id': 1, 'width': 128, 'height': 96, 'method': 0,
                                             'format': 'PNG'}, encodeArray(img, 'RAWZ')[0])
        up = decodeArray(data)
        checks.append((u'Upscale 32x24 -> 128x96', up is not None and up.shape[:2] == (96, 128)))
        reply = request(sock, parser, {'type': 'analyze', 'id': 2, 'colors': {
            'enabled': True, 'targets': ['#E01020'], 'minArea': 4, 'mask': True}}, encodeArray(img, 'RAWZ')[0])[0]
        found = (reply.get('result') or {}).get('colors', {}).get('detections', [])  # type: list
        checks.append((u'Colour analysis', len(found) == 1 and found[0]['rect'] == [8, 6, 12, 10]))
        sock.close()
    finally:
        server.stop()
    print(u'SELFTEST server (pure Python, no Qt): ' + ', '.join('{} {}'.format(n, 'ok' if v else 'FAILED')
                                                                for n, v in checks))
    return all(v for n, v in checks)


def run():
    """
    Server entry point: the ScreenMagnifierServer command, python -m ScreenMagnifier.server or python server.py.
    :return:
    """
    from sys import argv
    args = parseArguments(argv[1:])
    if args.selftest:
        exit(0 if selfTest() else 1)
    if args.download_face_model:
        target = join(userDataDir(), 'models', YUNET_FILE)  # type: str  # searched by the face engine
        log(u'Downloading the YuNet face model to {} ...'.format(target))
        downloadModel(target, lambda p: stdout.write('\r{:3d} %'.format(p)))
        stdout.write('\n')
        log(u'YuNet face model installed (SHA-256 verified)')
        exit(0)
    server = AnalysisServer(host=args.host, port=args.port, token=args.token, maxClients=args.max_clients,
                            logMessage=log)  # type: AnalysisServer
    try:
        server.start()
    except OSError as e:
        log(u'Cannot listen on {}:{}: {}'.format(args.host, args.port, e))
        exit(1)
    engine = server.getUpscaleEngine()
    log(u'Listening on {}:{} ({}), upscale methods: {}'.format(
        args.host, server.getPort(), 'token required' if args.token else 'NO token',
        ', '.join(n for m, n in engine.availableMethods())))
    if not args.token and args.host not in ('127.0.0.1', 'localhost', '::1'):
        log(u'WARNING: listening on the network without a token - use --token SECRET')
    server.serveForever()
    log(u'Stopped')


if __name__ == '__main__':
    run()
