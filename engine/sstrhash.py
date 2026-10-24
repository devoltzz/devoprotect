# The StringHash of the game (lookup2), computed outside the game.
M32 = 0xFFFFFFFF


def _norm(b):
    if 0x61 <= b <= 0x7A:
        return b - 0x20
    if b == 0x2F:
        return 0x5C
    return b


def sstrhash2(body_text):
    return sstrhash2_bytes(body_text.encode('utf-8', 'surrogateescape'))


MEASURED_IN_GAME = (('掉落总数', -1970465554), ('JN_DATA_1', 1234034213), ('1', 1132341824),
                    ('devoltz#11953', 461077761), ('test', -310027398))


def hybrid_stringhash(body_text, dobra=True):
    return hybrid_stringhash_bytes(body_text.encode('utf-8', 'surrogateescape'), dobra)


def hybrid_stringhash_bytes(data_bytes, dobra=True):
    out = bytearray()
    i, n = 0, len(data_bytes)
    while i < n:
        c = data_bytes[i]
        if c < 0x80:
            out.append(_norm(c) if dobra else c)
            i += 1
            continue
        cp, sz = None, 1
        tally = lambda k: i + k < n and 0x80 <= data_bytes[i + k] <= 0xBF
        if 0xC2 <= c <= 0xDF and tally(1):
            cp, sz = ((c & 0x1F) << 6) | (data_bytes[i + 1] & 0x3F), 2
        elif 0xE0 <= c <= 0xEF and tally(1) and tally(2):
            cp, sz = ((c & 0x0F) << 12) | ((data_bytes[i + 1] & 0x3F) << 6) | (data_bytes[i + 2] & 0x3F), 3
        elif 0xF0 <= c <= 0xF4 and tally(1) and tally(2) and tally(3):
            cp, sz = (((c & 0x07) << 18) | ((data_bytes[i + 1] & 0x3F) << 12) | ((data_bytes[i + 2] & 0x3F) << 6)
                      | (data_bytes[i + 3] & 0x3F)), 4
        if cp is None:
            cp = 0xFFFD
        if cp >= 0x10000:
            v = cp - 0x10000
            for u in (0xD800 + (v >> 10), 0xDC00 + (v & 0x3FF)):
                out += bytes((u & 0xFF, (u >> 8) & 0xFF))
        else:
            out += bytes((cp & 0xFF, cp >> 8))
        i += sz
    return _lookup2(bytes(out))


def sstrhash2_bytes(data_bytes):
    return _lookup2(bytes(_norm(b) for b in data_bytes))


def _lookup2(k):
    n = len(k)
    a = b = 0x9E3779B9
    c = 0
    i = 0

    def mix(a, b, c):
        a = (a - b) & M32
        a = (a - c) & M32
        a ^= (c >> 13)
        b = (b - c) & M32
        b = (b - a) & M32
        b ^= ((a << 8) & M32)
        c = (c - a) & M32
        c = (c - b) & M32
        c ^= (b >> 13)
        a = (a - b) & M32
        a = (a - c) & M32
        a ^= (c >> 12)
        b = (b - c) & M32
        b = (b - a) & M32
        b ^= ((a << 16) & M32)
        c = (c - a) & M32
        c = (c - b) & M32
        c ^= (b >> 5)
        a = (a - b) & M32
        a = (a - c) & M32
        a ^= (c >> 3)
        b = (b - c) & M32
        b = (b - a) & M32
        b ^= ((a << 10) & M32)
        c = (c - a) & M32
        c = (c - b) & M32
        c ^= (b >> 15)
        return a, b, c

    while n - i >= 12:
        a = (a + (k[i] | (k[i + 1] << 8) | (k[i + 2] << 16) | (k[i + 3] << 24))) & M32
        b = (b + (k[i + 4] | (k[i + 5] << 8) | (k[i + 6] << 16) | (k[i + 7] << 24))) & M32
        c = (c + (k[i + 8] | (k[i + 9] << 8) | (k[i + 10] << 16) | (k[i + 11] << 24))) & M32
        a, b, c = mix(a, b, c)
        i += 12

    c = (c + len(k)) & M32
    rest = k[i:]
    shift = [0, 8, 16, 24, 0, 8, 16, 24, 8, 16, 24]
    for j, sh in enumerate(shift):
        if j < len(rest):
            if j < 4:
                a = (a + (rest[j] << sh)) & M32
            elif j < 8:
                b = (b + (rest[j] << sh)) & M32
            else:
                c = (c + (rest[j] << sh)) & M32
    a, b, c = mix(a, b, c)
    return c - 0x100000000 if c >= 0x80000000 else c


def signed(v):
    return v - 0x100000000 if v >= 0x80000000 else v


for _t, _v in MEASURED_IN_GAME:
    assert hybrid_stringhash(_t) == _v, (_t, _v)
    assert (hybrid_stringhash(_t, dobra=False) == _v) == (_t.upper() == _t), (_t, _v)
