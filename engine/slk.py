# Reads SLK tables.
import os
import struct
import sys



_NAT = [None]


def _native_sound():
    if os.environ.get('JASS_NATIVE') == '0' or sys.platform == 'emscripten' or sys.byteorder != 'little':
        return None
    if _NAT[0] is None:
        _NAT[0] = False
        try:
            import ctypes
            jn = sys.modules.get('jass_native')
            if jn is None:
                source = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jass_native.py')
                if os.path.isfile(source):
                    import importlib.util
                    spec = importlib.util.spec_from_file_location('_slk_jass_native', source)
                    jn = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(jn)
                else:
                    import jass_native as jn
            dll = jn._dll()
            if dll and hasattr(dll, 'slk_parse'):
                f = dll.slk_parse
                f.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p),
                              ctypes.POINTER(ctypes.c_size_t)]
                f.restype = ctypes.c_int
                _NAT[0] = (f, dll.jass_free)
        except Exception:
            _NAT[0] = False
    return _NAT[0] or None


def _call(op, raw):
    nat = _native_sound()
    if not nat:
        return None
    import ctypes
    f, free = nat
    if not isinstance(raw, bytes):
        try:
            raw = bytes(raw)
        except TypeError:
            return None
    p, n = ctypes.c_void_p(), ctypes.c_size_t()
    if f(op, raw, len(raw), ctypes.byref(p), ctypes.byref(n)) != 0:
        return None
    try:
        buf = ctypes.string_at(p.value, n.value) if n.value else b''
    finally:
        free(p, n.value)
    k = struct.unpack_from('<I', buf, 0)[0]
    return memoryview(buf)[4:4 + 4 * k].cast('I'), buf[4 + 4 * k:].decode('utf-8', 'surrogateescape').split('\n')


def _slk_native(raw):
    r = _call(1, raw)
    if r is None:
        return None
    iv, s = r
    if not iv[0]:
        return [], {}
    nh, nn, nr = iv[1], iv[2], iv[3]
    hdr = s[:nh]
    fname = s[nh:nh + nn].__getitem__
    rows = {}
    p, q = nh + nn, 4
    for _ in range(nr):
        c = iv[q]
        q += 1
        rows[s[p]] = dict(zip(map(fname, iv[q:q + c]), s[p + 1:p + 1 + c]))
        p += 1 + c
        q += c
    return hdr, rows


def native_ini(raw, quoted=True, lowercase_names=False):
    r = _call(2 if quoted else 3, raw)
    if r is None:
        return None
    iv, s = r
    out = {}
    p = 0
    for i in range(iv[0]):
        c = iv[1 + i]
        keys = s[p + 1:p + 1 + c]
        out[s[p]] = dict(zip(map(str.lower, keys) if lowercase_names else keys, s[p + 1 + c:p + 1 + 2 * c]))
        p += 1 + 2 * c
    return out


def parse_slk_bytes(raw, native=True):
    if native:
        r = _slk_native(raw)
        if r is not None:
            return r
    txt = raw.decode('utf-8', 'surrogateescape')
    header = {}
    rows = {}
    cur_y = 0
    cells = {}
    for line in txt.split('\n'):
        line = line.rstrip('\r')
        if not line.startswith('C;') and not line.startswith('F;'):
            continue
        if line.startswith('F;'):
            continue
        x = None
        y = None
        k = None
        parts = line[2:].split(';')
        rebuilt = []
        buf = None
        for p in parts:
            if buf is not None:
                buf += ';' + p
                if buf.count('"') % 2 == 0:
                    rebuilt.append(buf)
                    buf = None
                continue
            if p.startswith('K"') and p.count('"') % 2 == 1:
                buf = p
                continue
            rebuilt.append(p)
        if buf is not None:
            rebuilt.append(buf)
        for p in rebuilt:
            if p.startswith('X'):
                x = int(p[1:])
            elif p.startswith('Y'):
                y = int(p[1:])
            elif p.startswith('K'):
                k = p[1:]
                if len(k) >= 2 and k[0] == '"' and k[-1] == '"':
                    k = k[1:-1]
        if y is not None:
            cur_y = y
        if x is None or k is None:
            continue
        cells.setdefault(cur_y, {})[x] = k
    if 1 not in cells:
        return [], {}
    header = cells[1]
    maxx = max(header)
    hdr = [header.get(i, '') for i in range(1, maxx + 1)]
    for y in sorted(cells):
        if y == 1:
            continue
        row = cells[y]
        rid = row.get(1)
        if rid is None:
            continue
        d = {}
        for x, v in row.items():
            name = header.get(x)
            if name:
                d[name] = v
        rows[rid] = d
    return hdr, rows

