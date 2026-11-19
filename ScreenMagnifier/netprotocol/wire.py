# -*- coding: utf-8 -*-
"""
Wire format of ScreenMagnifier messages - pure Python (no Qt): shared by the Qt client (netprotocol.FrameChannel)
and the headless server, which also runs where Qt is not available (e.g. Android: Termux, Pydroid).
One message:
    b'SMG1' | uint32 header length | uint32 payload length | header (UTF-8 JSON object) | payload (bytes)
(integers big-endian). Images travel in the payload as:
    RAWZ  b'RAWZ' | uint32 w | uint32 h | zlib(RGB888 rows)   lossless color, only needs zlib
    RAWG  b'RAWG' | uint32 w | uint32 h | zlib(gray8 rows)    lossless grayscale (label masks)
    PNG / JPEG                                                 when OpenCV or Pillow is installed
Limits protect against hostile peers: header / payload sizes, image sizes, and the zlib expansion of raw images
(a small payload cannot inflate into gigabytes).
"""
from zlib import compress, decompressobj
from struct import pack, unpack
from json import dumps, loads

MAGIC = b'SMG1'  # type: bytes
PREFIX_SIZE = 12  # type: int
MAX_HEADER = 1 << 20  # type: int  # 1 MB of JSON.
MAX_PAYLOAD = 64 << 20  # type: int  # 64 MB image.
RAWZ_MAGIC = b'RAWZ'  # type: bytes
RAWG_MAGIC = b'RAWG'  # type: bytes
MAX_RAW_PIXELS = 4096 * 4096  # type: int  # The largest raw image accepted.
DEFAULT_PORT = 8765  # type: int

try:
    from numpy import ascontiguousarray, frombuffer, uint8, asarray

    numpyExists = True  # type: bool
except:
    numpyExists = None  # type: bool
try:
    from cv2 import IMWRITE_JPEG_QUALITY, imencode, imdecode, IMREAD_COLOR

    cv2exists = True  # type: bool
except:
    cv2exists = False  # type: bool
try:
    from PIL.Image import fromarray, open

    PILImageExists = True  # type: bool
except:
    PILImageExists = False  # type: bool


def packMessage(header, payload=b''):
    """
    :param header: (dict) JSON-serialisable message header (must contain 'type').
    :param payload: (bytes) Binary payload.
    :return: bytes
    """
    head = dumps(header, separators=(',', ':')).encode('utf-8')  # type: bytes
    payload = bytes(payload or b'')  # type: bytes
    if len(head) > MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise ValueError(u'Message too large ({} + {} bytes)'.format(len(head), len(payload)))
    return MAGIC + pack('>II', len(head), len(payload)) + head + payload


class MessageParser(object):
    """
    MessageParser class: incremental decoder for a TCP byte stream.
    """

    def __init__(self):
        """
        """
        self.__m_buffer = bytearray()  # type: bytearray

    def feed(self, data):
        """
        :param data: (bytes) Newly received bytes.
        :return: (list[tuple[dict, bytes]]) Complete messages.
        :raise ValueError: on a protocol violation (the connection should be closed).
        """
        self.__m_buffer.extend(data)
        out = []  # type: list
        while len(self.__m_buffer) >= PREFIX_SIZE:
            if bytes(self.__m_buffer[:4]) != MAGIC:
                raise ValueError(u'Bad magic: not a ScreenMagnifier peer')
            headLen, payloadLen = unpack('>II', bytes(self.__m_buffer[4:PREFIX_SIZE]))
            if headLen > MAX_HEADER or payloadLen > MAX_PAYLOAD:
                raise ValueError(u'Message too large ({} + {} bytes)'.format(headLen, payloadLen))
            total = PREFIX_SIZE + headLen + payloadLen  # type: int
            if len(self.__m_buffer) < total:
                break
            head = bytes(self.__m_buffer[PREFIX_SIZE:PREFIX_SIZE + headLen])  # type: bytes
            payload = bytes(self.__m_buffer[PREFIX_SIZE + headLen:total])  # type: bytes
            del self.__m_buffer[:total]
            header = loads(head.decode('utf-8'))  # type: dict
            if not isinstance(header, dict):
                raise ValueError(u'Header is not a JSON object')
            out.append((header, payload))
        return out

    def pending(self):
        """
        :return: (int) Buffered bytes of an incomplete message.
        """
        return len(self.__m_buffer)


def packRaw(width, height, rows, gray=False):
    """
    :param width: int
    :param height: int
    :param rows: (bytes) Tightly packed RGB888 (or gray8) rows.
    :param gray: bool
    :return: (bytes) RAWZ / RAWG image.
    """
    return (RAWG_MAGIC if gray else RAWZ_MAGIC) + pack('>II', int(width), int(height)) + compress(bytes(rows), 1)


def unpackRaw(data):
    """
    :param data: bytes
    :return: (tuple[int, int, int, bytes] | None) width, height, channels (3 or 1), rows - None if not a valid
        raw image (wrong magic, size limits, corrupt or over-long zlib data).
    """
    if not data or len(data) < 12 or bytes(data[:4]) not in (RAWZ_MAGIC, RAWG_MAGIC):
        return None
    channels = 1 if bytes(data[:4]) == RAWG_MAGIC else 3  # type: int
    w, h = unpack('>II', bytes(data[4:12]))
    if not (0 < w <= 16384 and 0 < h <= 16384 and w * h <= MAX_RAW_PIXELS):
        return None
    expected = w * h * channels  # type: int
    try:
        z = decompressobj()
        rows = z.decompress(bytes(data[12:]), expected + 1)  # type: bytes  # bounded: no zlib bomb
    except:
        return None
    return (w, h, channels, rows) if len(rows) == expected else None


def availableFormats():
    """
    :return: (list[str | unicode | QString]) Image formats this process can decode and encode ('RAWZ' always).
    """
    return ['RAWZ', 'PNG', 'JPG'] if (cv2exists or PILImageExists) and numpyExists else ['RAWZ']


def encodeArray(arr, fmt='RAWZ', quality=90):
    """
    :param arr: (ndarray) (H, W, 3) RGB or (H, W) gray uint8.
    :param fmt: (str | unicode | QString)
                'RAWZ' (gray arrays: RAWG), 'PNG' or 'JPG' - falls back to RAWZ when no codec is installed.
    :param quality: (int) JPEG quality.
    :return: (tuple[bytes, str]) Encoded image and the format actually used.
    """
    arr = ascontiguousarray(arr)
    gray = arr.ndim == 2  # type: bool
    fmt = u'{}'.format(fmt).upper()  # type: str
    if fmt in ('PNG', 'JPG', 'JPEG') and cv2exists:
        ext = '.png' if fmt == 'PNG' else '.jpg'  # type: str
        params = [int(IMWRITE_JPEG_QUALITY), int(quality)] if ext == '.jpg' else []  # type: list
        ok, buf = imencode(ext, arr if gray else arr[..., ::-1], params)
        if ok:
            return buf.tobytes(), 'PNG' if ext == '.png' else 'JPG'
    if fmt in ('PNG', 'JPG', 'JPEG') and PILImageExists:
        from io import BytesIO
        out = BytesIO()
        fromarray(arr).save(out, 'PNG' if fmt == 'PNG' else 'JPEG', quality=int(quality))
        return out.getvalue(), 'PNG' if fmt == 'PNG' else 'JPG'
    h, w = arr.shape[:2]
    return packRaw(w, h, arr.tobytes(), gray), 'RAWZ'


def decodeArray(data):
    """
    :param data: (bytes) RAWZ / RAWG, or PNG / JPEG (with OpenCV or Pillow).
    :return: (ndarray | None) (H, W, 3) RGB or (H, W) gray uint8, None on failure.
    """
    raw = unpackRaw(data)
    if raw is not None:
        w, h, channels, rows = raw
        arr = frombuffer(rows, uint8)
        return (arr.reshape(h, w) if channels == 1 else arr.reshape(h, w, 3)).copy()
    if not data or bytes(data[:4]) in (RAWZ_MAGIC, RAWG_MAGIC):
        return None
    if cv2exists:
        img = imdecode(frombuffer(bytes(data), uint8), IMREAD_COLOR)
        return None if img is None else ascontiguousarray(img[..., ::-1])
    if PILImageExists:
        from io import BytesIO
        try:
            return asarray(open(BytesIO(bytes(data))).convert('RGB')).copy()
        except:
            return None
    return None
