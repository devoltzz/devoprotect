# The sector codec in native code (zopfli and zlib-ng): the same bytes the program writes on Windows.
import ctypes
import os
import sys
from array import array


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT = os.path.normpath(os.path.join(HERE, '..', 'cache', 'sector512_native'))
DLL = 'setor512.so' if sys.platform.startswith('linux') else 'setor512.dll'
VERSION = 'zopfli=1.0.3|zlib-ng=2.2.4'
MODES = {'zopfli': 0, 'zlib9': 1}
_NAT = [None]


def _paths():
    out = [os.environ.get('SECTOR512_NATIVE') or '', os.path.join(HERE, DLL), os.path.join(DEFAULT_OUTPUT, DLL)]
    if getattr(sys, '_MEIPASS', None):
        out.append(os.path.join(sys._MEIPASS, DLL))
    return [p for p in out if p and p != '0']


def _through_js():
    try:
        import js
        from pyodide.ffi import to_js
    except ImportError:
        return None
    f = getattr(js, 's512Fatia', None)
    if f is None:
        return None

    def sector_slice(data_bytes, sector_bytes, margem, method):
        n = (len(data_bytes) + sector_bytes - 1) // sector_bytes
        if not n:
            return []
        r = f(to_js(bytes(data_bytes)), sector_bytes, margem, MODES[method])
        if r is None:
            return None
        b = r.to_bytes()
        lens = array('I')
        lens.frombytes(b[:4 * n])
        if sys.byteorder != 'little':
            lens.byteswap()
        out, pos = [], 4 * n
        for k in lens:
            out.append(b[pos:pos + k])
            pos += k
        return out
    return sector_slice


def _by_dll():
    if not (os.name == 'nt' or sys.platform.startswith('linux')):
        return None
    for p in _paths():
        if not os.path.isfile(p):
            continue
        try:
            dll = ctypes.CDLL(p)
            f = dll.s512_fatia
        except (OSError, AttributeError):
            continue
        f.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                      ctypes.c_void_p]
        f.restype = ctypes.c_long

        def sector_slice(data_bytes, sector_bytes, margem, method, _f=f):
            data_bytes = bytes(data_bytes)
            n = (len(data_bytes) + sector_bytes - 1) // sector_bytes
            if not n:
                return []
            out = ctypes.create_string_buffer(len(data_bytes))
            lens = array('I', bytes(4 * n))
            k = _f(data_bytes, len(data_bytes), sector_bytes, margem, MODES[method], out, lens.buffer_info()[0])
            if k != n:
                return None
            raw, pieces, pos = out.raw, [], 0
            for t in lens:
                pieces.append(raw[pos:pos + t])
                pos += t
            return pieces
        return sector_slice
    return None


def load_data():
    if os.environ.get('SECTOR512_NATIVE') == '0':
        return None
    if sys.platform == 'emscripten':
        return _through_js()
    if _NAT[0] is None:
        _NAT[0] = _by_dll() or False
    return _NAT[0] or None

