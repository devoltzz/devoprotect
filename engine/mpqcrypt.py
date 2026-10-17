# The MPQ hot loops in native code (mpqcrypt.c: a DLL in the exe, WebAssembly on the site): the decryption, the key search of nameless files, the sound sectors.
import ctypes
import os
import sys
from array import array


HERE = os.path.dirname(os.path.abspath(__file__))
DLL = 'mpqcrypt.so' if sys.platform.startswith('linux') else 'mpqcrypt.dll'
_LOADED_DLL = [None]


def _paths():
    out = [os.environ.get('MPQCRYPT') or '', os.path.join(HERE, DLL),
           os.path.normpath(os.path.join(HERE, '..', 'cache', 'mpqcrypt', DLL))]
    if getattr(sys, '_MEIPASS', None):
        out.append(os.path.join(sys._MEIPASS, DLL))
    return [p for p in out if p]


def _disabled():
    return os.environ.get('MPQCRYPT') == '0'


def _js():
    if sys.platform != 'emscripten':
        return None
    try:
        import js
        from pyodide.ffi import to_js
    except ImportError:
        return None
    return js, to_js


def _through_js():
    j = _js()
    f = getattr(j[0], 'mpqDecrypt', None) if j else None
    if f is None:
        return None
    to_js = j[1]

    def decrypt(data_bytes, hash_key):
        return f(to_js(bytes(data_bytes)), hash_key & 0xFFFFFFFF).to_bytes()
    return decrypt


def _dll():
    if _LOADED_DLL[0] is None:
        _LOADED_DLL[0] = False
        if os.name == 'nt' or sys.platform.startswith('linux'):
            for p in _paths():
                if not os.path.isfile(p):
                    continue
                try:
                    dll = ctypes.CDLL(p)
                    dll.mpq_decrypt.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
                    dll.mpq_decrypt.restype = None
                except (OSError, AttributeError):
                    continue
                _LOADED_DLL[0] = dll
                break
    return _LOADED_DLL[0]


def load_data():
    if _disabled():
        return None
    if sys.platform == 'emscripten':
        return _through_js()
    dll = _dll()
    if not dll:
        return None

    def decrypt(data_bytes, hash_key, _f=dll.mpq_decrypt):
        buf = bytearray(data_bytes)
        n = len(buf)
        if n:
            _f(ctypes.addressof((ctypes.c_char * n).from_buffer(buf)), n, hash_key & 0xFFFFFFFF)
        return bytes(buf)
    return decrypt


def _cipher_through_js():
    j = _js()
    f = getattr(j[0], 'mpqEncrypt', None) if j else None
    if f is None:
        return None
    to_js = j[1]

    def cipher(data_bytes, hash_key):
        return f(to_js(bytes(data_bytes)), hash_key & 0xFFFFFFFF).to_bytes()
    return cipher


def load_cipher():
    if _disabled():
        return None
    if sys.platform == 'emscripten':
        return _cipher_through_js()
    dll = _dll()
    if not dll:
        return None
    try:
        f = dll.mpq_encrypt
    except AttributeError:
        return None
    f.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
    f.restype = None

    def cipher(data_bytes, hash_key, _f=f):
        buf = bytearray(data_bytes)
        n = len(buf)
        if n:
            _f(ctypes.addressof((ctypes.c_char * n).from_buffer(buf)), n, hash_key & 0xFFFFFFFF)
        return bytes(buf)
    return cipher


def load_hash():
    if _disabled() or sys.platform == 'emscripten':
        return None
    dll = _dll()
    if not dll:
        return None
    try:
        f1, fn = dll.mpq_hash, dll.mpq_hash_many
    except AttributeError:
        return None
    f1.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint32]
    f1.restype = ctypes.c_uint32
    fn.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_void_p]
    fn.restype = None

    def singular(fname, type_name, _f=f1):
        return _f(fname, len(fname), type_name)

    def batch(name_list, type_name, _f=fn):
        import itertools
        offs = array('I', itertools.accumulate(map(len, name_list), initial=0))
        out = array('I', bytes(4 * len(name_list)))
        if name_list:
            _f(b''.join(name_list), offs.buffer_info()[0], len(name_list), type_name, out.buffer_info()[0])
        return out
    return singular, batch


def _keys_through_js():
    j = _js()
    f = getattr(j[0], 'mpqKeys', None) if j else None
    if f is None:
        return None

    def key_candidates(enc0, enc1, d0):
        v = array('I')
        v.frombytes(f(enc0, enc1, d0).to_bytes())
        return list(zip(v[0::2], v[1::2]))
    return key_candidates


def load_keys():
    if _disabled():
        return None
    if sys.platform == 'emscripten':
        return _keys_through_js()
    dll = _dll()
    if not dll:
        return None
    try:
        f = dll.mpq_key_candidates
    except AttributeError:
        return None
    f.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    f.restype = ctypes.c_int
    pair = ctypes.c_uint32 * 512

    def key_candidates(enc0, enc1, d0):
        out = pair()
        n = f(enc0, enc1, d0, out)
        return list(zip(out[0:2 * n:2], out[1:2 * n:2]))
    return key_candidates


def _sound_through_js():
    j = _js()
    fh, fa = (getattr(j[0], 'mpqHuffman', None), getattr(j[0], 'mpqAdpcm', None)) if j else (None, None)
    if fh is None or fa is None:
        return None
    to_js = j[1]

    def huffman(data_bytes, ceiling):
        r = fh(to_js(bytes(data_bytes)), ceiling)
        return None if r is None else r.to_bytes()

    def adpcm(data_bytes, channels, ceiling):
        r = fa(to_js(bytes(data_bytes)), channels, ceiling)
        return None if r is None else r.to_bytes()
    return huffman, adpcm


def load_sound():
    if _disabled():
        return None
    if sys.platform == 'emscripten':
        return _sound_through_js()
    dll = _dll()
    if not dll:
        return None
    try:
        fh, fa = dll.mpq_huffman, dll.mpq_adpcm
    except AttributeError:
        return None
    fh.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
    fa.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t]
    fh.restype = fa.restype = ctypes.c_int

    def huffman(data_bytes, ceiling):
        data_bytes = bytes(data_bytes)
        out = ctypes.create_string_buffer(ceiling)
        r = fh(data_bytes, len(data_bytes), out, ceiling)
        return None if r < 0 else out.raw[:r]

    def adpcm(data_bytes, channels, ceiling):
        data_bytes = bytes(data_bytes)
        out = ctypes.create_string_buffer(ceiling)
        r = fa(data_bytes, len(data_bytes), channels, out, ceiling)
        return None if r < 0 else out.raw[:r]
    return huffman, adpcm


def _explode_through_js():
    j = _js()
    fx = getattr(j[0], 'mpqExplode', None) if j else None
    if fx is None:
        return None
    to_js = j[1]

    def explode(data_bytes, expected_len):
        r = fx(to_js(bytes(data_bytes)), expected_len)
        return None if r is None else r.to_bytes()
    return explode


def load_explode():
    if _disabled():
        return None
    if sys.platform == 'emscripten':
        return _explode_through_js()
    dll = _dll()
    if not dll:
        return None
    try:
        fx = dll.mpq_explode
    except AttributeError:
        return None
    fx.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
    fx.restype = ctypes.c_int

    def explode(data_bytes, expected_len):
        data_bytes = bytes(data_bytes)
        out = ctypes.create_string_buffer(max(expected_len, 1))
        r = fx(data_bytes, len(data_bytes), out, expected_len)
        return None if r < 0 else out.raw[:r]
    return explode


def _jpeg_through_js():
    j = _js()
    fs, fw = (getattr(j[0], 'jpegScan', None), getattr(j[0], 'jpegWrite', None)) if j else (None, None)
    if fs is None or fw is None:
        return None
    to_js = j[1]

    def scan(d, ent, nmcu, dri, spec, tabs, cap):
        r = fs(to_js(d), ent, nmcu, dri, to_js(spec), to_js(tabs), cap)
        if r is None:
            return None
        out = array('I')
        out.frombytes(r.to_bytes())
        return out

    def write(recs, codes, action_match, ntab, cap):
        r = fw(to_js(recs.tobytes()), to_js(codes.tobytes()), to_js(bytes(action_match)), ntab, cap)
        return None if r is None else r.to_bytes()
    return scan, write


def load_jpeg():
    if _disabled():
        return None
    if sys.platform == 'emscripten':
        return _jpeg_through_js()
    dll = _dll()
    if not dll:
        return None
    try:
        fs, fw = dll.jpeg_huff_scan, dll.jpeg_huff_write
    except AttributeError:
        return None
    vp, sz = ctypes.c_void_p, ctypes.c_size_t
    fs.argtypes = [ctypes.c_char_p, sz, sz, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_char_p, sz, ctypes.c_char_p, sz,
                   vp, sz]
    fw.argtypes = [vp, sz, vp, ctypes.c_char_p, sz, vp, sz]
    fs.restype = fw.restype = ctypes.c_int

    def scan(d, ent, nmcu, dri, spec, tabs, cap, _f=fs):
        out = array('I', bytes(4 * cap))
        r = _f(d, len(d), ent, nmcu, dri, spec, len(spec), tabs, len(tabs), out.buffer_info()[0], cap)
        return None if r < 0 else out

    def write(recs, codes, action_match, ntab, cap, _f=fw):
        if not cap:
            return None
        out = bytearray(cap)
        r = _f(recs.buffer_info()[0], len(recs), codes.buffer_info()[0], bytes(action_match), ntab,
               ctypes.addressof((ctypes.c_char * cap).from_buffer(out)), cap)
        if r < 0:
            return None
        del out[r:]
        return bytes(out)
    return scan, write

